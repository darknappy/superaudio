"""
synthesis.py — Worker de Supertonic, control de calidad de audio
               y detección de arrastre/repetición de sílabas.
"""
import os

import numpy as np
from . import config as C
from .audio import polish_wav

# ----------------------------------------------------------
# Variables de proceso (inicializadas en _init_worker).
# Todo lo que la síntesis necesita se pasa EXPLICITO aquí, nunca se
# lee de C.* directamente dentro de synthesize_block: en Windows cada
# proceso worker re-importa config.py desde el archivo al arrancar
# (spawn), así que un override en memoria del proceso principal
# (ej. --steps, --chunk-chars por CLI) no llegaría a los workers si
# dependiéramos de leer la config global ahí.
# ----------------------------------------------------------
_tts              = None
_voice_style      = None
_total_steps      = None
_max_chunk_length = None
_lang             = None


def _init_worker(intra_threads: int, inter_threads: int,
                  voice: str = None,
                  total_steps: int = None,
                  max_chunk_length: int = None,
                  lang: str = None,
                  model: str = None):
    """Carga el modelo Supertonic UNA sola vez por proceso worker."""
    global _tts, _voice_style, _total_steps, _max_chunk_length, _lang
    from supertonic import TTS
    _tts = TTS(
        model=model or C.TTS_MODEL,
        auto_download=True,
        intra_op_num_threads=intra_threads,
        inter_op_num_threads=inter_threads,
    )
    _voice_style      = _tts.get_voice_style(voice or C.VOICE)
    _total_steps      = total_steps if total_steps is not None else C.TOTAL_STEPS
    _max_chunk_length = max_chunk_length if max_chunk_length is not None else C.MAX_CHUNK_LENGTH
    _lang             = lang or C.LANG


# ----------------------------------------------------------
# Control de calidad
# ----------------------------------------------------------

def _duration_anomalous(text: str, duration_s: float) -> bool:
    """True si la duración está fuera del rango esperado de
    caracteres/segundo para español narrado (8–22 cps)."""
    if duration_s <= 0:
        return True
    cps = len(text) / duration_s
    return not (8.0 <= cps <= 22.0)


def _detect_stutter(wav, sample_rate: int = 44100) -> bool:
    """Heurística de autocorrelación para detectar sílabas repetidas
    o arrastradas. No es transcripción, pero atrapa bastantes casos."""
    try:
        samples = np.asarray(wav).squeeze().astype(np.float32)
    except Exception:
        return False

    win  = int(0.18 * sample_rate)
    hop  = int(0.06 * sample_rate)
    if samples.size < win * 2:
        return False

    prev, streak = None, 0
    for i in range((samples.size - win) // hop):
        seg = samples[i * hop: i * hop + win]
        rms = float(np.sqrt(np.mean(seg ** 2)))
        if rms < 0.01:
            prev, streak = None, 0
            continue
        if prev is not None:
            denom = np.linalg.norm(seg) * np.linalg.norm(prev)
            if denom > 1e-6 and float(np.dot(seg, prev) / denom) > 0.93:
                streak += 1
                if streak >= 3:
                    return True
            else:
                streak = 0
        prev = seg
    return False


# ----------------------------------------------------------
# Síntesis de un bloque con reintentos
# ----------------------------------------------------------

def synthesize_block(text: str, out_file: str,
                     speed: float = None,
                     silence_duration: float = None,
                     retries: int = 3) -> tuple[bool, str | None]:
    """Sintetiza `text` y guarda el resultado en `out_file`.
    Devuelve (ok, motivo_de_fallo_o_None).

    La escritura es atómica: se genera en `.part` y solo se renombra
    al nombre final si el WAV existe y tiene tamaño razonable. Así un
    fallo o un corte no deja un archivo "válido" a medias que luego
    se salte en la reanudación.
    """
    if not text or not text.strip():
        return False, "texto vacío"

    speed    = C.SPEED                     if speed is None else speed
    silence  = C.SILENCE_BETWEEN_SENTENCES if silence_duration is None else silence_duration
    attempt_text = text
    last_reason  = None

    out_dir = os.path.dirname(out_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # El sufijo .wav es importante: soundfile/libsndfile infieren el
    # formato por la extensión y no reconocen ".part".
    tmp_file = out_file + ".part.wav"
    try:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
    except OSError:
        pass

    for attempt in range(retries):
        reason = None
        try:
            wav, duration = _tts.synthesize(
                text            = attempt_text,
                lang            = _lang,
                voice_style     = _voice_style,
                total_steps     = _total_steps,
                speed           = speed,
                max_chunk_length= _max_chunk_length,
                silence_duration= silence,
            )
            dur = float(duration[0]) if hasattr(duration, "__len__") else float(duration)

            if _duration_anomalous(attempt_text, dur):
                reason = f"duración sospechosa ({dur:.1f}s / {len(attempt_text)} chars)"
                if attempt < retries - 1:
                    continue

            elif _detect_stutter(wav):
                reason = "posible arrastre/repetición detectado"
                if attempt < retries - 1:
                    continue

            _tts.save_audio(wav, tmp_file)
            if not (os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 1000):
                last_reason = "el WAV generado está vacío o es demasiado pequeño"
                continue
            # Recorte suave de bordes y micro-fade antes de publicar el
            # bloque. Si falla, el WAV original sigue siendo válido.
            try:
                polish_wav(tmp_file)
            except Exception:
                pass
            os.replace(tmp_file, out_file)
            return True, reason

        except Exception as e:
            last_reason = f"error: {e}"
            # Limpieza de emergencia suave: preserva acentos y ñ
            attempt_text = "".join(
                c for c in attempt_text if c.isprintable() or c in " \n\t"
            )

    try:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
    except OSError:
        pass
    return False, last_reason


# ----------------------------------------------------------
# Función de job (llamada desde multiprocessing.Pool)
# ----------------------------------------------------------

def synthesize_job(job: dict) -> tuple[int, bool, str | None]:
    """job debe tener: id, wav_path, text, speed, silence."""
    wav_path = job["wav_path"]
    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
        return job["id"], True, None

    # Restos de una ejecución interrumpida.
    try:
        if os.path.exists(wav_path + ".part.wav"):
            os.remove(wav_path + ".part.wav")
    except OSError:
        pass

    ok, reason = synthesize_block(
        text             = job["text"],
        out_file         = wav_path,
        speed            = job["speed"],
        silence_duration = job["silence"],
    )
    return job["id"], ok, reason


# ----------------------------------------------------------
# Inicializador exportado para multiprocessing.Pool
# ----------------------------------------------------------

def init_worker(intra_threads: int, inter_threads: int,
                 voice: str = None,
                 total_steps: int = None,
                 max_chunk_length: int = None,
                 lang: str = None,
                 model: str = None):
    _init_worker(intra_threads, inter_threads, voice,
                 total_steps, max_chunk_length, lang, model)
