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
# Fijar el modelo evita que una actualización de Supertonic cambie la
# voz o el resultado sin que nos demos cuenta.
TTS_MODEL = os.environ.get("SUPERTONIC_MODEL", "supertonic-3")

VOICE = "M1"    # F2, F4, M1, M2 … (voces Supertonic)
LANG  = "es"
SPEED = 1.05    # Velocidad base narración. Rango útil: 0.7–2.0

# Calidad de síntesis: 5=rápida, 12=máxima oficial.
# Bajar esto es la palanca más directa para acelerar.
TOTAL_STEPS = 10

# Troceo interno de Supertonic (respeta límites de oración).
MAX_CHUNK_LENGTH = 300

# Pausa entre sub-fragmentos internos de Supertonic (segundos).
SILENCE_BETWEEN_SENTENCES = 0.35

# ----------------------------------------------------------
# NORMALIZACIÓN PARA TTS
# ----------------------------------------------------------
# Expande abreviaturas españolas, números, fechas y símbolos antes
# de enviar el texto al modelo. Se puede desactivar desde config.py
# o con --no-numbers en la CLI.
ENABLE_SPANISH_ABBREVIATIONS = True
ENABLE_NUMBER_NORMALIZATION = True
ENABLE_EXPRESSION_CUES = True
NUMBER_NORMALIZATION_MAX = 999_999_999

# Abreviaturas que Supertonic no conoce y que, si se dejan con punto,
# pueden provocar cortes de frase o lectura incorrecta.
SPANISH_ABBREVIATIONS = {
    "EE. UU.": "Estados Unidos",
    "p. ej.": "por ejemplo",
    "a. C.": "antes de Cristo",
    "d. C.": "después de Cristo",
    "Srta.": "Señorita",
    "Sra.": "Señora",
    "Sr.": "Señor",
    "Dr.": "Doctor",
    "Dra.": "Doctora",
    "Ud.": "usted",
    "Uds.": "ustedes",
    "etc.": "etcétera",
    "págs.": "páginas",
    "pág.": "página",
    "caps.": "capítulos",
    "cap.": "capítulo",
    "n.º": "número",
    "n.°": "número",
    "N.º": "número",
    "N.°": "número",
}

# Tags de expresión que Supertonic 3 entiende. Solo se permite esta
# lista: cualquier otro tag tipo HTML/SSML se elimina para que el
# modelo no lo lea como texto.
EXPRESSION_TAGS = ("laugh", "breath", "sigh")

# Indicaciones explícitas entre corchetes que se convierten en tags.
# No se convierten automáticamente verbos narrativos como «rió»:
# eso podría duplicar el efecto.
EXPRESSION_CUES = {
    "laugh":  ("ríe", "rie", "se ríe", "se rie", "risas", "carcajada"),
    "sigh":   ("suspira", "suspiró", "suspiro", "suspiraba"),
    "breath": ("respira", "respiró", "respiro", "jadea", "jadeó"),
}

# Diccionario de pronunciación opcional por libro. Se busca junto al
# archivo del libro, por ejemplo «mi_libro.pronunciation.json».
PRONUNCIATION_FILE_SUFFIXES = (".pronunciation.json", ".pron.json")

# ----------------------------------------------------------
# BLOQUES Y PROSODIA
# ----------------------------------------------------------
BLOCK_MAX_CHARS = 1200  # Máx. caracteres por llamada a synthesize()
MAX_PARAGRAPHS_PER_BLOCK = 2
SENTENCE_MAX_CHARS = 220  # Las frases más largas se parten para no perder prosodia

# Cada turno de diálogo y cada pensamiento se sintetiza por separado.
SPLIT_DIALOGUE_BLOCKS = True
SPLIT_THOUGHT_BLOCKS = True

# ----------------------------------------------------------
# ESTILOS DE NARRACIÓN
# Única palanca real con una sola voz: velocidad/pausa
# distintas para diálogo, pensamiento y narración.
# ----------------------------------------------------------
def _make_presets(speed, silence):
    return {
        "narracion":   {"speed": speed,                  "silence_duration": silence},
        "dialogo":     {"speed": round(speed * 1.03, 3), "silence_duration": round(silence * 0.80, 3)},
        "pensamiento": {"speed": round(speed * 0.92, 3), "silence_duration": round(silence * 1.20, 3)},
    }

STYLE_PRESETS = _make_presets(SPEED, SILENCE_BETWEEN_SENTENCES)

# ----------------------------------------------------------
# PAUSAS DE ENSAMBLADO (milisegundos)
# ----------------------------------------------------------
SILENCE_BETWEEN_BLOCKS_MS   = 450  # Respaldo si un estilo no tiene pausa
SENTENCE_GAP_MS             = 300  # Entre partes de una frase larga
STYLE_PAUSES_MS             = {
    "narracion":   500,
    "dialogo":     400,
    "pensamiento": 650,
}
SILENCE_SCENE_BREAK_MS      = 1200
SILENCE_BETWEEN_CHAPTERS_MS = 1500

# ----------------------------------------------------------
# AUDICIÓN DE VOCES Y EVALUACIÓN
# ----------------------------------------------------------
AUDITION_TEXT = (
    "La casa estaba en silencio cuando el Dr. Ruiz abrió la puerta. "
    "—No era eso lo que esperaba —dijo, con voz tranquila—, pero podemos intentarlo otra vez.\n\n"
    "En 1984, el 25% de los vecinos todavía recordaba aquella noche. "
    "¿Merecía la pena volver?"
)
AUDITION_SILENCE_MS = 700

# ----------------------------------------------------------
# CALIDAD DE AUDIO
# ----------------------------------------------------------
LOUDNORM_TARGET_I   = -18.0  # LUFS objetivo para audiolibro
LOUDNORM_TARGET_TP  = -3.0   # True peak (dB)
LOUDNORM_TARGET_LRA = 11.0
LOUDNORM_TWO_PASS   = True
EDGE_FADE_MS        = 8      # Evita clics al unir segmentos
TRIM_TTS_EDGES      = True   # Recorta silencio inicial/final de cada bloque
TRIM_SILENCE_DB     = -50.0
TRIM_KEEP_MS        = 20

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
