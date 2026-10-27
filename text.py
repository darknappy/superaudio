"""
text.py — Limpieza de texto, clasificación de párrafos y
          construcción de bloques de síntesis.
"""
import re
from . import config as C

# ----------------------------------------------------------
# Tokens internos (no deben llegar al motor TTS)
# ----------------------------------------------------------
# El token debe ser imprimible: `clean()` elimina los caracteres no
# imprimibles y un token con \uE000 desaparecía antes de llegar a
# `build_blocks()`.
SCENE_BREAK_TOKEN = "<<<SCENE_BREAK>>>"
_ELLIPSIS_TOKEN   = "\uE001ELLIPSIS\uE001"

# Línea formada SOLO por tres o más separadores, con espacios entre
# ellos: "***", "* * *", "---", "- - -", "~~~", "###", "· · ·"…
_SCENE_BREAK_RE = re.compile(
    r"(?m)^[ \t]*(?:[*#\-=~_·•◆◇○●▬━—.][ \t]*){3,}$"
)

# Caracteres que se usan como decoración y no deben leerse.
DECORATIVE_SYMBOLS = [
    "◆","◇","■","□","●","○","※","★","☆","✦","✧",
    "►","▼","▲","▬","━","·","•","~",
]

CJK_PUNCT_MAP = {
    "。":".", "、":",", "！":"!", "？":"?",
    "：":":", "；":";", "…":"...", "⋯":"...",
    "「":'"', "」":'"', "『":'"', "』":'"',
    "【":"",  "】":"",  "〈":"",  "〉":"",
    "\u201c":'"', "\u201d":'"', "\u201e":'"',
    "\u200b":"",  "\ufeff":"",
}

_OPENING_QUOTES = ('"', "\u201c", "\u00ab")
_CLOSING_QUOTES = ('"', "\u201d", "\u00bb")


# ----------------------------------------------------------
# Normalización
# ----------------------------------------------------------

def _normalize_cjk(text: str) -> str:
    for old, new in CJK_PUNCT_MAP.items():
        text = text.replace(old, new)
    return text

def _mark_scene_breaks(text: str) -> str:
    return _SCENE_BREAK_RE.sub(f"\n{SCENE_BREAK_TOKEN}\n", text)

def _protect_ellipsis(text: str) -> str:
    return re.sub(r"\.{3,}", _ELLIPSIS_TOKEN, text)

def _restore_ellipsis(text: str) -> str:
    return text.replace(_ELLIPSIS_TOKEN, "...")

def _opening_position(sentence: str, punctuation_index: int) -> int:
    """Devuelve dónde insertar ¿/¡ dentro de una oración.

    Orden de preferencia:
      1. Después de la última comilla de apertura que siga abierta
         (ej. 'Dijo: "Vienes?"' → 'Dijo: "¿Vienes?"').
      2. Después de la raya de diálogo inicial.
      3. Al principio de la oración.
    """
    # 1) Comilla de apertura sin cerrar antes del signo final.
    for pos in range(punctuation_index - 1, -1, -1):
        if sentence[pos] not in _OPENING_QUOTES:
            continue
        # La comilla recta es ambigua: solo es de apertura si hay un
        # número par de comillas rectas antes de ella.
        if sentence[pos] == '"' and sentence[:pos].count('"') % 2 == 1:
            continue
        between = sentence[pos + 1:punctuation_index]
        if not any(q in between for q in _CLOSING_QUOTES):
            return pos + 1

    # 2) Raya de diálogo al inicio (con posibles espacios).
    m = re.match(r"^\s*[—–-]+\s*", sentence)
    if m and m.end() < len(sentence):
        return m.end()

    # 3) Principio.
    return 0


def _ensure_opening_marks(text: str) -> str:
    """Añade ¿/¡ de apertura donde solo existe el cierre ?/!.

    Se procesa por oraciones y se conservan los espacios/saltos de
    línea originales (no se reconstruye el texto con `join`).
    """
    out = []
    start = 0

    # Un signo de cierre, con posibles comillas de cierre detrás.
    for m in re.finditer(r"[.!?]+[\"'”»]*(?=\s|$)", text):
        end = m.end()
        sentence = text[start:end]
        stripped = sentence.rstrip()
        bare = stripped.rstrip("\"'”»")

        if bare.endswith("?") and "¿" not in sentence:
            pos = _opening_position(sentence, len(bare) - 1)
            sentence = sentence[:pos] + "¿" + sentence[pos:]
        elif bare.endswith("!") and "¡" not in sentence:
            pos = _opening_position(sentence, len(bare) - 1)
            sentence = sentence[:pos] + "¡" + sentence[pos:]

        out.append(sentence)

        # Conservar exactamente el espacio que separa esta oración
        # de la siguiente (incluidos los \n).
        ws_start = end
        while ws_start < len(text) and text[ws_start].isspace():
            ws_start += 1
        out.append(text[end:ws_start])
        start = ws_start

    out.append(text[start:])
    return "".join(out)

def _apply_pronunciation(text: str) -> str:
    for old, new in C.PRONUNCIATION_FIXES.items():
        text = text.replace(old, new)
    return text

def _apply_regex(text: str) -> str:
    for pattern, replacement in C.REGEX_FIXES:
        text = re.sub(pattern, replacement, text)
    return text

# ----------------------------------------------------------
# Limpieza principal
# ----------------------------------------------------------

def clean(text: str) -> str:
    text = _apply_regex(text)
    text = _normalize_cjk(text)
    text = _mark_scene_breaks(text)
    text = _apply_pronunciation(text)

    text = text.replace("\r", "\n")
    for sym in DECORATIVE_SYMBOLS:
        text = text.replace(sym, " ")

    text = _protect_ellipsis(text)
    text = re.sub(r"(?<=\w)\s*–\s*(?=\w)", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r",+", ",", text)
    text = re.sub(r"([!?]){2,}", r"\1", text)
    text = _restore_ellipsis(text)

    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    text = text.strip()

    if text and text != SCENE_BREAK_TOKEN:
        text = _ensure_opening_marks(text)

    return text

# ----------------------------------------------------------
# Clasificación de párrafo
# ----------------------------------------------------------

def classify_paragraph(p: str) -> str:
    """Devuelve 'dialogo', 'pensamiento' o 'narracion'."""
    s = p.strip()
    if not s:
        return "narracion"

    # Diálogo con raya (—), semiraya (–) o guion (-), y con comillas.
    if re.match(r"^[—–-]\s*\S", s):
        return "dialogo"
    if s.startswith(_OPENING_QUOTES):
        return "dialogo"

    st = s.rstrip(".,;:!?")
    if st.endswith(_CLOSING_QUOTES):
        return "dialogo"

    # Pensamientos: comillas simples o tipográficas.
    if s.startswith(("'", "\u2018")):
        return "pensamiento"
    if st.endswith(("'", "\u2019")):
        return "pensamiento"

    return "narracion"

# ----------------------------------------------------------
# Construcción de bloques de síntesis
# ----------------------------------------------------------

def build_blocks(paragraphs: list, max_chars: int = None) -> list:
    """Agrupa párrafos consecutivos del mismo tipo (narración /
    diálogo / pensamiento) en bloques, respetando cortes de escena.
    Devuelve lista de dicts:
        {"text": str, "pause_after_ms": int, "style": str}
    """
    if max_chars is None:
        max_chars = C.BLOCK_MAX_CHARS

    blocks = []
    current: list = []
    current_len = 0
    current_style = None

    def flush(pause_ms):
        nonlocal current, current_len, current_style
        if current:
            # \n\n preserva la señal de párrafo que Supertonic usa
            # para su propio troceo interno.
            blocks.append({
                "text":          "\n\n".join(current),
                "pause_after_ms": pause_ms,
                "style":         current_style or "narracion",
            })
        current = []
        current_len = 0
        current_style = None

    for p in paragraphs:
        if p.strip() == SCENE_BREAK_TOKEN:
            flush(C.SILENCE_SCENE_BREAK_MS)
            continue

        style = classify_paragraph(p)

        if current and (style != current_style or current_len + len(p) + 1 > max_chars):
            flush(C.SILENCE_BETWEEN_BLOCKS_MS)

        current.append(p)
        current_len += len(p) + 1
        current_style = style

    flush(C.SILENCE_BETWEEN_BLOCKS_MS)
    return blocks
