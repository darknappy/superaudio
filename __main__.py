"""
__main__.py — Entry point de superaudio.
Permite ejecutarlo como:
    python -m superaudio libro.epub [opciones]
    superaudio libro.epub [opciones]        ← si tienes el alias/bat

Parsea los argumentos y llama a pipeline.run().
El relanzamiento en el venv de Supertonic ocurre AQUÍ, antes de que
Python intente importar numpy / supertonic / etc.
"""
import math
import os
import re
import sys


def _force_utf8_streams():
    """Evita UnicodeEncodeError con emojis en consolas cp1252.

    Cuando el proceso lo lanza la GUI empaquetada no hay consola real
    y Python puede caer a cp1252; cualquier print con 🎙/✅ reventaría.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _bootstrap():
    """Reconfigura UTF-8 y relanza dentro del venv de Supertonic."""
    _force_utf8_streams()

    # La raíz que CONTIENE el paquete superaudio/ (no la carpeta del
    # paquete) es la que debe estar en sys.path.
    root = os.environ.get("SUPERAUDIO_ROOT")
    if not root:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from superaudio.config import SUPERTONIC_PY
    except Exception:
        SUPERTONIC_PY = os.environ.get(
            "SUPERTONIC_PY",
            r"C:\supertonic\venv\Scripts\python.exe",
        )

    current = os.path.abspath(sys.executable)
    venv = os.path.abspath(SUPERTONIC_PY)

    if os.path.exists(venv) and current.lower() != venv.lower():
        print("🔄 Reiniciando en el entorno de Supertonic …", flush=True)
        env = os.environ.copy()
        old_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = root + (os.pathsep + old_pythonpath if old_pythonpath else "")
        os.execve(venv, [venv, "-m", "superaudio", *sys.argv[1:]], env)


if __name__ == "__main__":
    _bootstrap()

# ----------------------------------------------------------
# A partir de aquí ya estamos en el venv correcto
# ----------------------------------------------------------
from .pipeline import MODE_BOOK, MODE_SPLIT, MODE_VOLUME, run
from . import config as C

VALID_VOICES = [f"{g}{n}" for g in ("F", "M") for n in range(1, 6)]  # F1-F5, M1-M5

_HELP = """
Uso:
  superaudio libro.epub                        → M4B con capítulos internos (por defecto)
  superaudio libro.epub --chapters             → 1 MP3 por capítulo
  superaudio libro.epub -20                    → 1 M4B cada 20 capítulos
  superaudio libro.epub --chapters-per-file 20 → igual que -20
  superaudio libro.epub --chapters -20         → MP3 por capítulo (cada uno se cierra al terminar)
  superaudio libro.epub --preview 5            → genera solo los primeros 5 bloques (test rápido)
  superaudio libro.epub --voice M2             → usa la voz M2 sin preguntar (salta el prompt)
  superaudio libro.epub -10 --mp3              → MP3 plano cada 10 capítulos (sin capítulos internos)
  superaudio libro.epub --mp3                  → 1 solo MP3 plano de todo el libro (en vez de M4B)
  superaudio libro.epub --steps 6 --speed 1.1  → ajusta calidad/velocidad para esta corrida
  superaudio libro.epub --force                → borra las salidas de ESTE libro y regenera todo

Opciones:
  --chapters                 Genera 1 MP3 por capítulo en vez de 1 M4B.
  -N / --chapters-per-file N Cierra y limpia un archivo cada N capítulos (modo volumen).
  --mp3 / -mp3               Modo book/volumen sale en MP3 plano en vez de M4B.
  --preview N                Genera solo los primeros N bloques, para probar rápido.
  --voice VOZ                Usa la voz indicada (F1-F5, M1-M5) sin preguntar por consola.
  --speed X                  Velocidad de narración base (0.5-2.0). Default: config.py.
  --steps N                  Calidad de síntesis Supertonic (5=rápida, 12=máxima). Default: config.py.
  --silence X                Pausa entre oraciones en segundos. Default: config.py.
  --chunk-chars N            Límite interno de troceo de Supertonic. Default: config.py.
  --block-chars N            Tamaño máximo de bloque propio. Default: config.py.
  --workers N                Procesos de síntesis en paralelo. Default: config.py.
  --force                    Borra salidas/progreso de este libro y vuelve a generar.
  -h / --help                Muestra esta ayuda.

Voces disponibles: """ + ", ".join(VALID_VOICES) + "\n"


def _ask_voice(default: str) -> str:
    """Pregunta por consola qué voz usar. Enter = usar la de config.py."""
    print(f"Voces disponibles: {', '.join(VALID_VOICES)}")
    while True:
        choice = input(f"Voz a usar [{default}]: ").strip().upper()
        if not choice:
            return default
        if choice in VALID_VOICES:
            return choice
        print(f"⚠  '{choice}' no es válida. Opciones: {', '.join(VALID_VOICES)}")


def _parse_positive_int(value: str):
    try:
        n = int(value)
    except ValueError:
        return None
    return n if n >= 0 else None


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help"):
        print(_HELP)
        return 0

    mode             = MODE_BOOK
    preview_n        = 0
    chapters_per_vol = 0
    force            = False

    # --force
    if "--force" in args:
        force = True
        args.remove("--force")

    # --preview N (si falta el número, usa 5 sin comerse el archivo)
    if "--preview" in args:
        i = args.index("--preview")
        if i + 1 < len(args) and re.fullmatch(r"\d+", args[i + 1]):
            preview_n = int(args[i + 1])
            args = args[:i] + args[i + 2:]
        else:
            preview_n = 5
            args = args[:i] + args[i + 1:]

    # --chapters
    if "--chapters" in args:
        mode = MODE_SPLIT
        args.remove("--chapters")

    # --chapters-per-file N  o  -N
    if "--chapters-per-file" in args:
        i = args.index("--chapters-per-file")
        if i + 1 >= len(args):
            print("❌ --chapters-per-file requiere un número entero.")
            return 2
        n = _parse_positive_int(args[i + 1])
        if n is None:
            print(f"❌ Valor inválido para --chapters-per-file: '{args[i + 1]}'.")
            return 2
        chapters_per_vol = n
        args = args[:i] + args[i + 2:]
        if chapters_per_vol > 0 and mode == MODE_BOOK:
            mode = MODE_VOLUME

    # Acepta también -N. Si se usó --chapters-per-file, ese valor manda,
    # pero se elimina el -N para que no acabe formando parte del nombre.
    for a in list(args):
        m = re.fullmatch(r"-(\d+)", a)
        if m:
            n = int(m.group(1))
            if chapters_per_vol == 0:
                chapters_per_vol = n
                if n > 0 and mode == MODE_BOOK:
                    mode = MODE_VOLUME
            args.remove(a)
            break

    # --mp3 / -mp3
    mp3_only = False
    for flag in ("--mp3", "-mp3"):
        if flag in args:
            mp3_only = True
            args.remove(flag)

    # --speed / --steps / --silence / --chunk-chars / --block-chars / --workers
    _numeric_flags = {
        "--speed":       ("SPEED", float),
        "--steps":       ("TOTAL_STEPS", int),
        "--silence":     ("SILENCE_BETWEEN_SENTENCES", float),
        "--chunk-chars": ("MAX_CHUNK_LENGTH", int),
        "--block-chars": ("BLOCK_MAX_CHARS", int),
        "--workers":     ("PARALLEL_WORKERS", int),
    }
    for flag, (attr, caster) in _numeric_flags.items():
        if flag not in args:
            continue
        i = args.index(flag)
        if i + 1 >= len(args):
            print(f"❌ {flag} requiere un valor.")
            return 2
        try:
            value = caster(args[i + 1])
        except ValueError:
            print(f"❌ Valor inválido para {flag}: '{args[i + 1]}'.")
            return 2
        setattr(C, attr, value)
        args = args[:i] + args[i + 2:]

    # Validación de rangos (evita valores que rompen el motor o el ensamblado)
    if not math.isfinite(C.SPEED) or not (0.5 <= C.SPEED <= 2.0):
        print("❌ --speed debe estar entre 0.5 y 2.0.")
        return 2
    if C.TOTAL_STEPS < 1:
        print("❌ --steps debe ser un entero positivo.")
        return 2
    if (not math.isfinite(C.SILENCE_BETWEEN_SENTENCES)
            or C.SILENCE_BETWEEN_SENTENCES < 0):
        print("❌ --silence no puede ser negativo.")
        return 2
    if C.MAX_CHUNK_LENGTH < 20:
        print("❌ --chunk-chars debe ser al menos 20.")
        return 2
    if C.BLOCK_MAX_CHARS < 100:
        print("❌ --block-chars debe ser al menos 100.")
        return 2
    if C.PARALLEL_WORKERS < 1:
        print("❌ --workers debe ser al menos 1.")
        return 2

    # SPEED/SILENCE pudieron cambiar: recalcular los presets de estilo.
    C.STYLE_PRESETS = C._make_presets(C.SPEED, C.SILENCE_BETWEEN_SENTENCES)

    # --voice VOZ
    voice_arg = None
    if "--voice" in args:
        i = args.index("--voice")
        if i + 1 >= len(args):
            print("❌ --voice requiere una voz (F1-F5, M1-M5).")
            return 2
        voice_arg = args[i + 1].strip().upper()
        args = args[:i] + args[i + 2:]

    # Archivo de entrada
    arg = " ".join(args).strip().strip('"')
    if not arg:
        print("❌ Falta el archivo de entrada.")
        print(_HELP)
        return 2

    file_path = arg if os.path.exists(arg) else os.path.join(C.BASE_INPUT, arg)
    if not os.path.exists(file_path):
        print(f"\n❌ Archivo no encontrado: {file_path}")
        return 1

    try:
        import supertonic  # noqa: F401
    except ImportError:
        print("❌ Supertonic no está instalado en este entorno.")
        print("   Ejecuta el proyecto con el venv de Supertonic o instala:")
        print("   pip install supertonic")
        return 1

    # Voz
    if voice_arg and voice_arg in VALID_VOICES:
        chosen = voice_arg
    else:
        if voice_arg:
            print(f"⚠  Voz '{voice_arg}' inválida, se preguntará por consola.")
        chosen = _ask_voice(C.VOICE)

    C.VOICE = chosen
    print(f"🎙  Voz seleccionada: {C.VOICE}\n")

    ok = run(
        file_path,
        preview_blocks      = preview_n,
        mode                = mode,
        chapters_per_volume = chapters_per_vol,
        mp3_only            = mp3_only,
        force               = force,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
