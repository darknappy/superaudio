"""
quality.py — Banco de pruebas de prosodia y métricas objetivas.

No sustituye a escuchar: sirve para detectar frases omitidas, bloques
demasiado rápidos, clipping y silencios excesivos. El banco incluye
narración, diálogo, preguntas, exclamaciones, abreviaturas, números y
una frase larga.
"""
import array
import math
import os
import sys
import wave

from tqdm import tqdm

from . import config as C
from .audio import build_plain_mp3, polish_wav
from .text import clean

BENCHMARK_CASES = {
    "01_narracion": (
        "La casa estaba en silencio cuando el viento golpeó la ventana. "
        "Nadie se movió durante unos segundos."
    ),
    "02_dialogo": (
        "—No era eso lo que esperaba —dijo Ana, con voz tranquila—. "
        "Pero podemos intentarlo otra vez.\n\n"
        "—No sé si queda tiempo —respondió Luis."
    ),
    "03_pregunta": (
        "¿De verdad crees que todo esto servirá de algo cuando lleguemos?"
    ),
    "04_exclamacion": (
        "¡No puedo creerlo! ¡Lo conseguimos después de tanto tiempo!"
    ),
    "05_pausas": (
        "Abrió la puerta… y entonces lo vio. No dijo nada; no hacía falta."
    ),
    "06_abreviaturas": (
        "El Dr. Ruiz y la Sra. Gómez llegaron con el Sr. Pérez. "
        "Trajeron mapas, brújulas, etc., por si acaso."
    ),
    "07_numeros": (
        "En 1984, el 25% de los habitantes tenía menos de 30 años. "
        "El viaje costaba 12,50 € y duraba 2 h."
    ),
    "08_frase_larga": (
        "Cuando llegó al pueblo, después de caminar durante horas bajo la "
        "lluvia, comprendió que nada volvería a ser como antes, y aunque "
        "intentó sonreír, solo pudo mirar el horizonte en silencio, "
        "esperando que el ruido de sus pasos dejara de resonar en la calle."
    ),
}


def write_benchmark_texts(out_dir: str) -> list[str]:
    """Escribe un TXT por caso para poder revisarlos o traducirlos."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, text in BENCHMARK_CASES.items():
        path = os.path.join(out_dir, f"{name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        paths.append(path)
    return paths


def _db(value: float, reference: float = 1.0) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(value / reference)


def analyze_wav(path: str, text: str | None = None) -> dict:
    """Métricas básicas de un WAV PCM de 16 bits."""
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.getnframes()
        raw = wf.readframes(frames)

    result = {
        "duration_s": frames / rate if rate else 0.0,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": width,
        "peak_dbfs": -120.0,
        "rms_dbfs": -120.0,
        "clipped_samples": 0,
        "silence_ratio": 0.0,
        "chars_per_second": None,
    }
    if text and result["duration_s"] > 0:
        result["chars_per_second"] = len(text) / result["duration_s"]

    if width != 2 or frames <= 0:
        return result

    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()

    peak = max((abs(s) for s in samples), default=0)
    rms = math.sqrt(sum(float(s) * float(s) for s in samples) / len(samples))
    threshold = 32767 * (10 ** (float(C.TRIM_SILENCE_DB) / 20.0))
    silent = sum(1 for s in samples if abs(s) <= threshold)
    result.update({
        "peak_dbfs": round(_db(peak / 32768.0), 2),
        "rms_dbfs": round(_db(rms / 32768.0), 2),
        "clipped_samples": sum(1 for s in samples if abs(s) >= 32767),
        "silence_ratio": round(silent / len(samples), 4),
    })
    return result


def _format_report(rows: list[dict]) -> str:
    lines = [
        "Superaudio — banco de pruebas de prosodia",
        "",
        "Escucha las muestras y valora: naturalidad, pronunciación, ritmo,",
        "pausas y fatiga. Las métricas solo detectan problemas objetivos.",
        "",
    ]
    for row in rows:
        lines.append(f"[{row['case']}]  {row['voice']}")
        lines.append(
            f"  duración={row['duration_s']:.2f}s  "
            f"cps={row['chars_per_second']:.2f}  "
            f"peak={row['peak_dbfs']:.1f} dBFS  "
            f"rms={row['rms_dbfs']:.1f} dBFS"
        )
        lines.append(
            f"  silencio={row['silence_ratio'] * 100:.1f}%  "
            f"clipping={row['clipped_samples']}"
        )
        if row.get("error"):
            lines.append(f"  ERROR: {row['error']}")
        lines.append("")
    return "\n".join(lines)


def run_benchmark(out_dir: str = None,
                  voice: str = None,
                  model: str = None,
                  speed: float = None,
                  steps: int = None,
                  lang: str = None,
                  max_chunk_length: int = None,
                  silence_duration: float = None,
                  make_mp3: bool = False) -> bool:
    """Genera el corpus de evaluación con la voz/configuración actual."""
    out_dir = os.path.abspath(
        out_dir or os.path.join(C.OUTPUT_DIR, "_benchmark")
    )
    os.makedirs(out_dir, exist_ok=True)
    write_benchmark_texts(out_dir)

    voice = voice or C.VOICE
    model = model or C.TTS_MODEL
    lang = lang or C.LANG
    speed = C.SPEED if speed is None else speed
    steps = C.TOTAL_STEPS if steps is None else steps
    max_chunk_length = (
        C.MAX_CHUNK_LENGTH if max_chunk_length is None else max_chunk_length
    )
    silence = (
        C.SILENCE_BETWEEN_SENTENCES if silence_duration is None
        else silence_duration
    )

    try:
        from supertonic import TTS
    except ImportError:
        print("❌ Supertonic no está instalado en este entorno.")
        return False

    try:
        tts = TTS(
            model=model,
            auto_download=True,
            intra_op_num_threads=C.INTRA_OP_THREADS,
            inter_op_num_threads=C.INTER_OP_THREADS,
        )
        style = tts.get_voice_style(voice)
    except Exception as e:
        print(f"❌ No se pudo cargar el modelo o la voz: {e}")
        return False

    rows, wavs = [], []
    print(f"🧪 Banco de pruebas: {voice} · {model}")
    print(f"📁 Salida: {out_dir}\n")

    for name, original in tqdm(BENCHMARK_CASES.items(), desc="🧪 Casos", unit="caso"):
        text = clean(original)
        path = os.path.join(out_dir, f"{name}_{voice}.wav")
        try:
            wav, duration = tts.synthesize(
                text=text,
                lang=lang,
                voice_style=style,
                total_steps=steps,
                speed=speed,
                max_chunk_length=max_chunk_length,
                silence_duration=silence,
            )
            tts.save_audio(wav, path)
            try:
                polish_wav(path)
            except Exception:
                pass
            metrics = analyze_wav(path, text)
            metrics.update({"case": name, "voice": voice})
            rows.append(metrics)
            wavs.append(path)
        except Exception as e:
            rows.append({
                "case": name, "voice": voice,
                "duration_s": 0.0, "sample_rate": 0,
                "channels": 0, "sample_width": 0,
                "peak_dbfs": -120.0, "rms_dbfs": -120.0,
                "clipped_samples": 0, "silence_ratio": 0.0,
                "chars_per_second": 0.0, "error": str(e),
            })
            tqdm.write(f"  ❌ {name}: {e}")

    report = _format_report(rows)
    report_path = os.path.join(out_dir, "informe.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    if make_mp3 and wavs:
        try:
            build_plain_mp3(
                wavs,
                os.path.join(out_dir, "banco_pruebas.mp3"),
                out_dir,
                tags={"album": "Superaudio — banco de pruebas",
                      "title": "Prosodia", "artist": "Supertonic"},
                silence_between_ms=700,
            )
        except Exception as e:
            print(f"⚠ No se pudo generar el MP3 del banco: {e}")

    print(report)
    print(f"✅ Informe: {report_path}")
    return bool(wavs)
