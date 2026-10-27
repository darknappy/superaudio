"""
audition.py — Genera una audición comparativa de las voces de Supertonic.

Uso:
    python -m superaudio --audition
    python -m superaudio --audition --audition-voices F1,F2,M1
    python -m superaudio --audition --audition-out D:\\muestras

Produce un WAV por voz, un MP3 combinado y un índice para escuchar
todas las voces con el mismo texto antes de elegir la definitiva.
"""
import os
from pathlib import Path

from tqdm import tqdm

from . import config as C
from .audio import build_plain_mp3, polish_wav
from .text import clean

VALID_VOICES = [f"{g}{n}" for g in ("F", "M") for n in range(1, 6)]


def _default_out_dir() -> str:
    return os.path.join(C.OUTPUT_DIR, "_audiciones")


def run_audition(voices: list[str] | None = None,
                 out_dir: str | None = None,
                 text: str | None = None,
                 speed: float | None = None,
                 steps: int | None = None,
                 model: str | None = None,
                 lang: str | None = None,
                 max_chunk_length: int | None = None,
                 silence_duration: float | None = None,
                 make_mp3: bool = True) -> bool:
    """Sintetiza el mismo texto con varias voces.

    Devuelve True si se generó al menos una muestra.
    """
    if voices is None:
        voices = list(VALID_VOICES)
    voices = [v.strip().upper() for v in voices if v and v.strip()]
    invalid = [v for v in voices if v not in VALID_VOICES]
    if invalid:
        print(f"❌ Voces inválidas: {', '.join(invalid)}")
        print(f"   Opciones: {', '.join(VALID_VOICES)}")
        return False
    if not voices:
        print("❌ No hay voces para probar.")
        return False

    out_dir = os.path.abspath(out_dir or _default_out_dir())
    tmp_dir = os.path.join(out_dir, "_tmp")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    sample = clean(text or C.AUDITION_TEXT)
    if not sample:
        print("❌ El texto de audición quedó vacío.")
        return False

    try:
        from supertonic import TTS
    except ImportError:
        print("❌ Supertonic no está instalado en este entorno.")
        return False

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

    print(f"🎤 Modelo: {model}")
    print(f"📝 Texto de audición: {len(sample)} caracteres")
    print(f"📁 Salida: {out_dir}\n")

    try:
        tts = TTS(
            model=model,
            auto_download=True,
            intra_op_num_threads=C.INTRA_OP_THREADS,
            inter_op_num_threads=C.INTER_OP_THREADS,
        )
    except Exception as e:
        print(f"❌ No se pudo cargar el modelo: {e}")
        return False

    generated: list[tuple[str, str, float]] = []
    errors: list[tuple[str, str]] = []

    for voice in tqdm(voices, desc="🎙 Voces", unit="voz"):
        path = os.path.join(out_dir, f"{voice}.wav")
        try:
            style = tts.get_voice_style(voice)
            wav, duration = tts.synthesize(
                text=sample,
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
            seconds = (
                float(duration[0]) if hasattr(duration, "__len__")
                else float(duration)
            )
            generated.append((voice, path, seconds))
            tqdm.write(f"  ✅ {voice}: {seconds:.2f} s")
        except Exception as e:
            errors.append((voice, str(e)))
            tqdm.write(f"  ❌ {voice}: {e}")

    if not generated:
        print("❌ No se pudo generar ninguna muestra.")
        return False

    index_path = os.path.join(out_dir, "audicion.txt")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("Superaudio — audición de voces\n")
        f.write(f"Modelo: {model}\n")
        f.write(f"Idioma: {lang}\n")
        f.write(f"Velocidad: {speed}\n")
        f.write(f"Steps: {steps}\n")
        f.write(f"Chunk: {max_chunk_length}\n\n")
        f.write("Texto:\n")
        f.write(sample + "\n\n")
        f.write("Muestras:\n")
        for voice, path, seconds in generated:
            f.write(f"- {voice}: {Path(path).name} ({seconds:.2f} s)\n")
        if errors:
            f.write("\nErrores:\n")
            for voice, error in errors:
                f.write(f"- {voice}: {error}\n")

    if make_mp3 and generated:
        mp3_path = os.path.join(out_dir, "audicion_voces.mp3")
        try:
            ok = build_plain_mp3(
                [path for _, path, _ in generated],
                mp3_path,
                tmp_dir,
                cover_path=None,
                tags={
                    "album": "Superaudio — audición de voces",
                    "title": "Comparación de voces",
                    "artist": "Supertonic",
                },
                silence_between_ms=C.AUDITION_SILENCE_MS,
            )
            if ok:
                print(f"\n🔊 MP3 comparativo: {mp3_path}")
            else:
                print("\n⚠ No se pudo generar el MP3 comparativo.")
        except Exception as e:
            print(f"\n⚠ No se pudo generar el MP3 comparativo: {e}")

    print(f"\n✅ Audición terminada: {len(generated)} voz/voces")
    print(f"   Índice: {index_path}")
    if errors:
        print(f"   Voces con error: {', '.join(v for v, _ in errors)}")
    return True
