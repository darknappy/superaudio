"""
config.py — Toda la configuración editable en un solo lugar.
Este es el único archivo que deberías modificar habitualmente.
"""
import os
import re

# ----------------------------------------------------------
# RUTAS
# Las variables de entorno permiten usar el proyecto en otro equipo
# sin editar el código:
#   SUPERAUDIO_INPUT, SUPERAUDIO_OUTPUT, SUPERTONIC_PY
# ----------------------------------------------------------
def _env_path(name: str, default: str) -> str:
    """Ruta desde el entorno, expandiendo ~ y variables (%USERPROFILE%)."""
    value = os.environ.get(name, default)
    return os.path.abspath(os.path.expanduser(os.path.expandvars(value)))


BASE_INPUT    = _env_path("SUPERAUDIO_INPUT", r"C:\libros")
OUTPUT_DIR    = _env_path(
    "SUPERAUDIO_OUTPUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"),
)
SUPERTONIC_PY = _env_path(
    "SUPERTONIC_PY",
    r"C:\supertonic\venv\Scripts\python.exe",
)

# ----------------------------------------------------------
# VOZ Y SÍNTESIS
# ----------------------------------------------------------
VOICE = "M1"    # F2, F4, M1, M2 … (voces Supertonic)
LANG  = "es"
SPEED = 1.1     # Velocidad base narración. Rango útil: 0.7–2.0

# Calidad de síntesis: 5=rápida, 12=máxima oficial.
# Bajar esto es la palanca más directa para acelerar.
TOTAL_STEPS = 10

# Troceo interno de Supertonic (respeta límites de oración).
MAX_CHUNK_LENGTH = 300

# Pausa entre sub-fragmentos internos de Supertonic (segundos).
SILENCE_BETWEEN_SENTENCES = 0.35

# ----------------------------------------------------------
# BLOQUES DE TEXTO
# ----------------------------------------------------------
BLOCK_MAX_CHARS = 1200  # Máx. caracteres por llamada a synthesize()

# ----------------------------------------------------------
# ESTILOS DE NARRACIÓN
# Única palanca real con una sola voz: velocidad/pausa
# distintas para diálogo, pensamiento y narración.
# ----------------------------------------------------------
def _make_presets(speed, silence):
    return {
        "narracion":   {"speed": speed,                  "silence_duration": silence},
        "dialogo":     {"speed": round(speed * 1.06, 3), "silence_duration": round(silence * 0.75, 3)},
        "pensamiento": {"speed": round(speed * 0.93, 3), "silence_duration": round(silence * 1.20, 3)},
    }

STYLE_PRESETS = _make_presets(SPEED, SILENCE_BETWEEN_SENTENCES)

# ----------------------------------------------------------
# PAUSAS DE ENSAMBLADO (milisegundos)
# ----------------------------------------------------------
SILENCE_BETWEEN_BLOCKS_MS   = 450
SILENCE_SCENE_BREAK_MS      = 1200
SILENCE_BETWEEN_CHAPTERS_MS = 1500

# ----------------------------------------------------------
# CODIFICACIÓN DE SALIDA
# ----------------------------------------------------------
MP3_BITRATE = "192k"   # 128k–192k es un buen equilibrio para audiolibro
AAC_BITRATE = "192k"

# ----------------------------------------------------------
# PARALELISMO  (Ryzen 5 5600GT: 6 núcleos / 12 hilos)
# ----------------------------------------------------------
INTRA_OP_THREADS = 6   # hilos ONNX Runtime por proceso
INTER_OP_THREADS = 1
PARALLEL_WORKERS = 1   # procesos de síntesis simultáneos

# ----------------------------------------------------------
# VOLÚMENES  (activar por CLI: -20 o --chapters-per-file 20)
# ----------------------------------------------------------
CHAPTERS_PER_VOLUME = 0  # 0 = desactivado

# ----------------------------------------------------------
# CALIBRE — detección de capítulos en EPUB
# ----------------------------------------------------------
USE_CALIBRE_FOR_EPUB = True
CALIBRE_EBOOK_CONVERT_CANDIDATES = [
    r"C:\Program Files\Calibre2\ebook-convert.exe",
    r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
]

# ----------------------------------------------------------
# MARCADOR DE CAPÍTULO en TXT / DOCX sin estilos de Word
# ----------------------------------------------------------
CHAPTER_MARKER_REGEX = re.compile(
    r"^\s*(?:cap[ií]tulo|chapter|cap\.?)\s*\.?\s*(?:\d+|[ivxlcdm]+)\b"
    r"|^\s*(?:pr[oó]logo|ep[ií]logo|introducci[oó]n|prefacio|"
    r"dedicatoria|nota\s+del\s+autor)\s*:?\s*$",
    re.IGNORECASE,
)

# ----------------------------------------------------------
# CORRECCIONES DE PRONUNCIACIÓN
# Descomenta lo que aplique a tu novela tras escuchar el audio.
# ----------------------------------------------------------
PRONUNCIATION_FIXES: dict = {
    # Honoríficos japoneses (sin guion):
    # "bocchan": " bocchan",
    # "ojousama": " ojousama",
    # Términos coreanos:
    # "oppa": "opa", "unnie": "uni",
    # Términos chinos (xianxia):
    # "Shixiong": "Shi siong", "Shifu": "Shi fu",
    # Nombres propios de tu novela:
    # "Shirayuki": "Shira-yuki",
}

# IMPORTANTE: por defecto está vacío. Estas reglas se aplicaban a
# cualquier libro y podían destrozar texto normal (HP, INT, DEF…).
# Descomenta solo lo que corresponda a TU novela.
REGEX_FIXES: list = [
    # Honoríficos japoneses (guion → espacio)
    # (r"-san\b",           " san"),
    # (r"-sama\b",          " sama"),
    # (r"-dono\b",          " dono"),
    # (r"-kun\b",           " kun"),
    # (r"-chan\b",          " chan"),
    # (r"-tan\b",           " tan"),
    # (r"-senpai\b",        " sempai"),
    # (r"-sensei\b",        " sensei"),
    # (r"-nii(san|chan)\b", r" nii\1"),
    # (r"-nee(san|chan)\b", r" nee\1"),
    # (r"-bocchan\b",       " bocchan"),
    # Honoríficos coreanos
    # (r"-nim\b",           " nim"),
    # (r"-ssi\b",           " ssi"),
    # (r"-yang\b",          " yang"),
    # (r"-gun\b",           " gun"),
    # Stats LitRPG / webnovel
    # (r"\bLvl?\.?\s*(\d+)", r"Nivel \1"),
    # (r"\bHP\b",  "puntos de vida"),
    # (r"\bMP\b",  "puntos de mana"),
    # (r"\bSP\b",  "puntos de habilidad"),
    # (r"\bEXP\b", "experiencia"),
    # (r"\bATK\b", "ataque"),
    # (r"\bDEF\b", "defensa"),
    # (r"\bAGI\b", "agilidad"),
    # (r"\bINT\b", "inteligencia"),
    # (r"\bLUK\b", "suerte"),
    # (r"\bSTR\b", "fuerza"),
    # (r"\bVIT\b", "vitalidad"),
    # (r":\s*(\d+)\s*/\s*(\d+)", r": \1 de \2"),
]
