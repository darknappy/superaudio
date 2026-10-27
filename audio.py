"""
audio.py — Ensamblado de audio: silencios, capítulos WAV,
           MP3 individuales y M4B con capítulos internos.
"""
import array
import json
import math
import os
import re
import subprocess
import sys
import wave
from collections import deque
from pathlib import Path

from tqdm import tqdm

from . import config as C
from .metadata import escape_ffmetadata

_MIN_AUDIO_BYTES = 1000

# ----------------------------------------------------------
# ffmpeg con barra de progreso real (parsea -progress)
# ----------------------------------------------------------
_TIME_RE = re.compile(r"(\d+):(\d+):(\d+\.\d+)")


def _ffmpeg_error(stderr: str) -> str:
    lines = [ln for ln in (stderr or "").strip().splitlines() if ln.strip()]
    return "\n".join(lines[-10:]) or "(sin detalle de ffmpeg)"


def _run_ffmpeg(cmd: list):
    """Ejecuta ffmpeg capturando stderr para poder mostrar el error real."""
    full_cmd = [cmd[0], "-hide_banner", "-loglevel", "error", *cmd[1:]]
    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo y agrégalo al PATH."
        ) from e

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}):\n{_ffmpeg_error(proc.stderr)}"
        )
    return proc


def _run_ffmpeg_with_progress(cmd: list, total_ms: int, desc: str = "Encoding"):
    """Corre ffmpeg mostrando una barra de progreso real en vez de
    bloquear en silencio hasta terminar. Requiere que `cmd` sea una
    lista ffmpeg completa (el archivo de salida es el último elemento).

    stderr se fusiona con stdout para no bloquear el pipe y para poder
    mostrar el error real si ffmpeg falla.
    """
    base = [cmd[0], "-hide_banner", "-loglevel", "warning", *cmd[1:]]
    cmd_with_progress = base[:-1] + ["-progress", "pipe:1", "-nostats", base[-1]]

    try:
        proc = subprocess.Popen(
            cmd_with_progress,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo y agrégalo al PATH."
        ) from e

    bar = tqdm(total=max(total_ms, 1), desc=desc, unit="ms")
    last = 0
    tail = deque(maxlen=20)

    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("out_time="):
                m = _TIME_RE.search(line)
                if m:
                    h, mi, s = m.groups()
                    ms = int((int(h) * 3600 + int(mi) * 60 + float(s)) * 1000)
                    if ms > last:
                        bar.update(ms - last)
                        last = ms
            elif line.startswith("progress="):
                continue
            elif line.strip():
                tail.append(line)
        proc.wait()
    finally:
        if total_ms > 0 and last < total_ms:
            bar.update(total_ms - last)
        bar.close()

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}) al generar "
            f"'{os.path.basename(cmd[-1])}':\n"
            f"{_ffmpeg_error(chr(10).join(tail))}"
        )


def _temp_path(path: str) -> str:
    """Nombre temporal en la misma carpeta y con la misma extensión."""
    suffix = Path(path).suffix
    return path + ".part" + suffix


def _commit_temp(tmp: str, out: str):
    if not (os.path.exists(tmp) and os.path.getsize(tmp) > _MIN_AUDIO_BYTES):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(
            f"La salida '{os.path.basename(out)}' quedó vacía o incompleta."
        )
    os.replace(tmp, out)


def _concat_line(path: str) -> str:
    """Línea de lista concat segura, incluso con apóstrofos en la ruta.

    ffmpeg usa comillas simples y el escape dentro de ellas es '\\''
    (cerrar comilla, apóstrofo escapado, abrir comilla).
    """
    escaped = str(path).replace("'", r"'\''")
    return f"file '{escaped}'\n"


# ----------------------------------------------------------
# Silencio auxiliar
# ----------------------------------------------------------

def make_silence(path: str, duration_ms: int):
    """Genera un WAV de silencio de `duration_ms` ms.
    No hace nada si el archivo ya existe y es válido."""
    if os.path.exists(path) and os.path.getsize(path) > 44:
        return

    tmp = _temp_path(path)
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{duration_ms / 1000.0:.3f}",
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
            tmp,
        ])
        if not (os.path.exists(tmp) and os.path.getsize(tmp) > 44):
            raise RuntimeError("ffmpeg generó un silencio vacío.")
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------
# Duración de un WAV (usado para timestamps y barras de progreso)
# ----------------------------------------------------------

def _wav_duration_ms(wav_path: str) -> int:
    """Devuelve la duración de un WAV en milisegundos."""
    try:
        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            if rate > 0:
                return int(frames * 1000 / rate)
    except Exception:
        pass

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             wav_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if probe.returncode == 0:
            return int(float(probe.stdout.strip()) * 1000)
    except Exception:
        pass
    return 0


# ----------------------------------------------------------
# Normalización y pulido de audio
# ----------------------------------------------------------

def _loudnorm_filter() -> str:
    """Filtro loudnorm con el objetivo configurado para audiolibro."""
    return (
        f"loudnorm=I={float(C.LOUDNORM_TARGET_I):g}:"
        f"TP={float(C.LOUDNORM_TARGET_TP):g}:"
        f"LRA={float(C.LOUDNORM_TARGET_LRA):g}"
    )


def _measure_loudness(in_wav: str) -> dict | None:
    """Primera pasada de loudnorm: mide loudness, LRA y true peak."""
    filter_spec = _loudnorm_filter() + ":print_format=json"
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info",
                "-i", in_wav, "-af", filter_spec, "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return None

    if proc.returncode != 0:
        return None
    raw = proc.stderr or ""
    start, end = raw.rfind("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        # Los valores no finitos no sirven para la segunda pasada.
        values = [
            float(data[key])
            for key in ("input_i", "input_tp", "input_lra",
                        "input_thresh", "target_offset")
        ]
        if not all(math.isfinite(value) for value in values):
            return None
        return data
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def normalize_wav(in_wav: str, out_wav: str):
    """Normaliza el loudness de UN WAV de capítulo.

    Por defecto hace dos pasadas: medir y aplicar. Así el nivel queda
    más estable entre capítulos y se evita que loudnorm «bombe» el
    volumen. Si la medición falla, cae a una única pasada.
    """
    tmp = _temp_path(out_wav)
    filter_spec = _loudnorm_filter()

    if getattr(C, "LOUDNORM_TWO_PASS", True):
        measured = _measure_loudness(in_wav)
        if measured:
            try:
                filter_spec = (
                    _loudnorm_filter()
                    + f":measured_I={measured['input_i']}"
                    + f":measured_LRA={measured['input_lra']}"
                    + f":measured_TP={measured['input_tp']}"
                    + f":measured_thresh={measured['input_thresh']}"
                    + f":offset={measured['target_offset']}"
                    + ":linear=true:print_format=summary"
                )
            except (KeyError, TypeError):
                filter_spec = _loudnorm_filter()

    def _run(filter_value: str):
        _run_ffmpeg([
            "ffmpeg", "-y", "-i", in_wav,
            "-af", filter_value,
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
            tmp,
        ])

    try:
        try:
            _run(filter_spec)
        except RuntimeError:
            # La segunda pasada puede fallar con audios muy cortos o
            # con un LRA incompatible; una pasada normal es suficiente.
            if filter_spec != _loudnorm_filter():
                _run(_loudnorm_filter())
            else:
                raise
        _commit_temp(tmp, out_wav)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def polish_wav(path: str, trim: bool = None, fade_ms: int = None) -> bool:
    """Recorta silencio inicial/final y aplica un micro-fade.

    Se hace sobre cada bloque TTS, no sobre el capítulo entero. El
    objetivo es quitar clics en las uniones sin tocar las pausas
    internas. Solo procesa WAV PCM de 16 bits.
    """
    if trim is None:
        trim = getattr(C, "TRIM_TTS_EDGES", True)
    if fade_ms is None:
        fade_ms = int(getattr(C, "EDGE_FADE_MS", 8))

    try:
        with wave.open(path, "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.getnframes()
            raw = wf.readframes(frames)
        if width != 2 or channels < 1 or frames <= 1:
            return False

        samples = array.array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return False

        total = len(samples)
        start, end = 0, total
        if trim:
            threshold = int(32767 * (10 ** (float(C.TRIM_SILENCE_DB) / 20.0)))
            first = next(
                (i for i, sample in enumerate(samples) if abs(sample) > threshold),
                None,
            )
            if first is not None:
                last = next(
                    (i for i in range(total - 1, -1, -1)
                     if abs(samples[i]) > threshold),
                    first,
                )
                margin = int(rate * float(C.TRIM_KEEP_MS) / 1000.0)
                start = max(0, first - margin)
                end = min(total, last + margin + 1)

        if end <= start:
            return False

        fade = max(0, int(rate * max(0, fade_ms) / 1000.0))
        if fade > 0:
            limit = min(fade, end - start)
            for i in range(limit):
                factor = i / fade
                samples[start + i] = int(samples[start + i] * factor)
                samples[end - 1 - i] = int(samples[end - 1 - i] * factor)

        trimmed = samples[start:end]
        if sys.byteorder != "little":
            trimmed.byteswap()

        tmp = path + ".polish.wav"
        try:
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(width)
                wf.setframerate(rate)
                wf.writeframes(trimmed.tobytes())
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        return True
    except (OSError, wave.Error, ValueError):
        return False


# ----------------------------------------------------------
# WAV de capítulo (concatenación sin codificar)
# ----------------------------------------------------------

def build_chapter_wav(blocks: list, tmp_dir: str,
                      out_wav: str, silence_dir: str) -> bool:
    """Une los WAV de bloques de un capítulo en un único WAV crudo.

    Devuelve False si falta CUALQUIER bloque: es preferible fallar y
    reintentar que publicar un capítulo truncado silenciosamente.
    """
    if not blocks:
        return False

    entries = []
    for i, block in enumerate(blocks):
        wav = os.path.join(tmp_dir, f"{i:05d}.wav")
        if not (os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False
        entries.append(wav)
        pause_ms = int(block.get("pause_after_ms") or 0)
        if pause_ms > 0:
            sil = os.path.join(silence_dir, f"silence_{pause_ms}.wav")
            make_silence(sil, pause_ms)
            entries.append(sil)

    if not entries:
        return False

    list_file = os.path.join(tmp_dir, "list_raw.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(_concat_line(e))

    out_tmp = _temp_path(out_wav)
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", "-f", "wav", out_tmp,
        ])
        _commit_temp(out_tmp, out_wav)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


# ----------------------------------------------------------
# MP3 individual (modo --chapters)
# ----------------------------------------------------------

def _add_cover_args(cmd: list, cover_path: str | None, cover_index: int = 1):
    """Añade la portada convirtiéndola siempre a JPEG.

    Copiar el stream tal cual falla con WebP/GIF dentro de M4B/MP3
    («codec not currently supported in container»). MJPEG sí está
    soportado por ambos contenedores y por los reproductores habituales.

    `cover_index` es el índice de la entrada de la imagen (en M4B la
    entrada 1 es el FFMETADATA y la portada es la 2).
    """
    if cover_path and os.path.exists(cover_path):
        cmd += [
            "-i", cover_path,
            "-map", "0:a", "-map", f"{cover_index}:v",
            "-c:v", "mjpeg", "-q:v", "2", "-pix_fmt", "yuvj420p",
            "-frames:v", "1",
            "-disposition:v", "attached_pic",
        ]
    else:
        cmd += ["-map", "0:a"]


def build_mp3(in_wav: str, out_mp3: str,
              cover_path: str | None = None,
              tags: dict | None = None,
              normalize: bool = True) -> bool:
    """Convierte un WAV de capítulo a MP3 estéreo, con cover art
    incrustado y tags ID3. Muestra barra de progreso."""
    if not (os.path.exists(in_wav) and os.path.getsize(in_wav) > _MIN_AUDIO_BYTES):
        return False

    cmd = ["ffmpeg", "-y", "-i", in_wav]
    _add_cover_args(cmd, cover_path)

    if normalize:
        cmd += ["-af", _loudnorm_filter()]
    cmd += [
        "-acodec", "libmp3lame",
        "-b:a", getattr(C, "MP3_BITRATE", "192k"),
        "-ac", "2",
        "-id3v2_version", "3",
    ]

    for k, v in (tags or {}).items():
        if v:
            cmd += ["-metadata", f"{k}={v}"]

    out_tmp = _temp_path(out_mp3)
    cmd += ["-f", "mp3", out_tmp]

    total_ms = _wav_duration_ms(in_wav)
    try:
        _run_ffmpeg_with_progress(cmd, total_ms, desc=f"🔊 {os.path.basename(out_mp3)}")
        _commit_temp(out_tmp, out_mp3)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


def build_plain_mp3(chapter_wavs: list[str],
                    out_mp3: str,
                    tmp_dir: str,
                    cover_path: str | None = None,
                    tags: dict | None = None,
                    silence_between_ms: int = None) -> bool:
    """Concatena los WAV de varios capítulos en un único MP3 plano
    'a la antigua' (sin capítulos internos). Más simple y rápido que
    build_m4b: no calcula timestamps ni genera FFMETADATA."""
    if silence_between_ms is None:
        silence_between_ms = C.SILENCE_BETWEEN_CHAPTERS_MS

    if not chapter_wavs:
        return False
    for wav in chapter_wavs:
        if not (wav and os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False

    sil_path = None
    if silence_between_ms > 0:
        sil_path = os.path.join(tmp_dir, f"sil_chap_{silence_between_ms}.wav")
        make_silence(sil_path, silence_between_ms)

    list_file = os.path.join(tmp_dir, "plain_mp3_list.txt")
    total_ms = 0
    with open(list_file, "w", encoding="utf-8") as f:
        for i, wav in enumerate(chapter_wavs):
            total_ms += _wav_duration_ms(wav)
            f.write(_concat_line(wav))
            if sil_path and i < len(chapter_wavs) - 1:
                f.write(_concat_line(sil_path))
                total_ms += silence_between_ms

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file]
    _add_cover_args(cmd, cover_path)
    cmd += [
        "-acodec", "libmp3lame",
        "-b:a", getattr(C, "MP3_BITRATE", "192k"),
        "-ac", "2",
        "-id3v2_version", "3",
    ]

    for k, v in (tags or {}).items():
        if v:
            cmd += ["-metadata", f"{k}={v}"]

    out_tmp = _temp_path(out_mp3)
    cmd += ["-f", "mp3", out_tmp]

    try:
        _run_ffmpeg_with_progress(cmd, total_ms, desc=f"🔊 {os.path.basename(out_mp3)}")
        _commit_temp(out_tmp, out_mp3)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


# ----------------------------------------------------------
# M4B con capítulos internos (modo book / volume)
# ----------------------------------------------------------

def build_m4b(chapter_wavs: list[str],
              chapter_titles: list[str],
              out_m4b: str,
              tmp_dir: str,
              cover_path: str | None = None,
              tags: dict | None = None,
              silence_between_ms: int = None) -> bool:
    """Ensambla un M4B con chapter atoms internos a partir de una
    lista de WAVs (uno por capítulo). Muestra barra de progreso real
    durante la codificación final (la parte que tarda).

    Flujo:
      1. Calcula los timestamps de cada capítulo midiendo los WAVs.
      2. Genera el archivo FFMETADATA con los [CHAPTER] atoms.
      3. Codifica todo en AAC estéreo con loudnorm ya aplicado por
         capítulo, mostrando progreso en tiempo real.
    """
    if silence_between_ms is None:
        silence_between_ms = C.SILENCE_BETWEEN_CHAPTERS_MS

    if not chapter_wavs or len(chapter_wavs) != len(chapter_titles):
        return False
    for wav in chapter_wavs:
        if not (wav and os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False

    sil_path = None
    if silence_between_ms > 0:
        sil_path = os.path.join(tmp_dir, f"sil_chap_{silence_between_ms}.wav")
        make_silence(sil_path, silence_between_ms)

    # Calcular timestamps
    chapter_starts: list[int] = []
    current_ms = 0
    list_file  = os.path.join(tmp_dir, "m4b_list.txt")

    with open(list_file, "w", encoding="utf-8") as f:
        for i, wav in enumerate(chapter_wavs):
            dur = _wav_duration_ms(wav)
            if dur <= 0:
                raise RuntimeError(f"No se pudo medir la duración de: {wav}")
            chapter_starts.append(current_ms)
            current_ms += dur
            f.write(_concat_line(wav))
            if sil_path and i < len(chapter_wavs) - 1:
                f.write(_concat_line(sil_path))
                current_ms += silence_between_ms

    # FFMETADATA con chapter atoms
    meta_file = os.path.join(tmp_dir, "m4b_meta.txt")
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(";FFMETADATA1\n")
        for k, v in (tags or {}).items():
            if v:
                f.write(f"{k}={escape_ffmetadata(v)}\n")
        f.write("\n")
        for i, (start_ms, title) in enumerate(zip(chapter_starts, chapter_titles)):
            end_ms = chapter_starts[i + 1] if i + 1 < len(chapter_starts) else current_ms
            f.write("[CHAPTER]\nTIMEBASE=1/1000\n")
            f.write(f"START={start_ms}\nEND={end_ms}\n")
            f.write(f"title={escape_ffmetadata(title)}\n\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-i", meta_file,
    ]
    _add_cover_args(cmd, cover_path, cover_index=2)
    cmd += ["-map_metadata", "1"]

    cmd += [
        "-c:a", "aac",
        "-b:a", getattr(C, "AAC_BITRATE", "192k"),
        "-ac", "2",
        "-movflags", "+faststart",
    ]

    out_tmp = _temp_path(out_m4b)
    cmd += ["-f", "ipod", out_tmp]

    try:
        _run_ffmpeg_with_progress(
            cmd, current_ms,
            desc=f"🔊 Codificando {os.path.basename(out_m4b)}",
        )
        _commit_temp(out_tmp, out_m4b)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True
