"""
text.py — Limpieza, normalización y segmentación de texto para TTS.

Incluye:
  - limpieza de restos de EPUB/DOCX y signos decorativos;
  - expansión de abreviaturas españolas;
  - normalización opcional de números, fechas y unidades;
  - tags de expresión de Supertonic 3 con lista blanca;
  - división de frases largas y separación de turnos de diálogo.
"""
import json
import os
import re

from . import config as C

try:
    from num2words import num2words as _num2words
except ImportError:  # La normalización de números es opcional.
    _num2words = None

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
# Pronunciación por libro
# ----------------------------------------------------------
_BOOK_PRONUNCIATION: dict = {}


def _pronunciation_path(book_path: str) -> str | None:
    """Busca un diccionario JSON junto al libro."""
    if not book_path:
        return None
    base = os.path.splitext(book_path)[0]
    for suffix in getattr(C, "PRONUNCIATION_FILE_SUFFIXES", ()):
        candidate = base + suffix
        if os.path.exists(candidate):
            return candidate
    return None


def configure_book_pronunciation(book_path: str) -> dict:
    """Carga «libro.pronunciation.json» si existe.

    Formato:
        {"Shirayuki": "Shira-yuki", "Nyx": "Nics"}
    """
    global _BOOK_PRONUNCIATION
    _BOOK_PRONUNCIATION = {}
    path = _pronunciation_path(book_path)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _BOOK_PRONUNCIATION = {
                str(k): str(v) for k, v in data.items() if str(k).strip()
            }
    except Exception:
        _BOOK_PRONUNCIATION = {}
    return dict(_BOOK_PRONUNCIATION)


def clear_book_pronunciation():
    global _BOOK_PRONUNCIATION
    _BOOK_PRONUNCIATION = {}


def pronunciation_signature(book_path: str) -> str:
    """Huella sencilla para invalidar el progreso si cambia el JSON."""
    path = _pronunciation_path(book_path)
    if not path:
        return ""
    try:
        st = os.stat(path)
        return f"{os.path.abspath(path)}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return os.path.abspath(path)


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


def _apply_spanish_abbreviations(text: str) -> str:
    if not getattr(C, "ENABLE_SPANISH_ABBREVIATIONS", True):
        return text
    # Primero las formas más largas: «p. ej.» antes que «p.».
    for abbr, full in sorted(
        C.SPANISH_ABBREVIATIONS.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        def _replace(match, expanded=full):
            original = match.group(0)
            replacement = expanded
            if original[:1].isupper() and replacement:
                replacement = replacement[0].upper() + replacement[1:]
            if original.isupper() and replacement:
                replacement = replacement.upper()
            return replacement

        text = re.sub(
            rf"(?<!\w){re.escape(abbr)}(?!\w)",
            _replace,
            text,
            flags=re.IGNORECASE,
        )
    return text


def _apply_expression_cues(text: str) -> str:
    """Convierte indicaciones explícitas [ríe], [suspira]… en tags."""
    if not getattr(C, "ENABLE_EXPRESSION_CUES", True):
        return text
    for tag, cues in C.EXPRESSION_CUES.items():
        if not cues:
            continue
        alternatives = "|".join(
            re.escape(c) for c in sorted(cues, key=len, reverse=True)
        )
        text = re.sub(
            rf"\[\s*(?:{alternatives})\s*\]",
            f" <{tag}> ",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _sanitize_expression_tags(text: str) -> str:
    """Conserva solo los tags que Supertonic 3 entiende.

    Cualquier otro tag tipo HTML/SSML se elimina para que el modelo no
    lo lea como si fuera parte de la narración.
    """
    allowed = {t.lower() for t in getattr(C, "EXPRESSION_TAGS", ())}
    # El marcador de escena usa «<...>» internamente; no debe pasar por
    # el filtro de tags.
    scene_sentinel = "\uE002SCENE_BREAK\uE002"
    text = text.replace(SCENE_BREAK_TOKEN, scene_sentinel)

    def _replace(match):
        raw = match.group(0)
        name = re.sub(r"[^A-Za-z]", "", raw).lower()
        if name in allowed:
            return f"<{name}>"
        return " "

    text = re.sub(r"</?[A-Za-z][^>]{0,40}>", _replace, text)
    # Separar los tags del texto evita que queden pegados a una palabra.
    for tag in allowed:
        text = re.sub(
            rf"\s*<{tag}>\s*", f" <{tag}> ", text, flags=re.IGNORECASE
        )
    return text.replace(scene_sentinel, SCENE_BREAK_TOKEN)


# ----------------------------------------------------------
# Números, fechas y unidades
# ----------------------------------------------------------
_NUM = r"\d+(?:[.,]\d+)*"
_DIGIT_WORDS = {
    "0": "cero", "1": "uno", "2": "dos", "3": "tres", "4": "cuatro",
    "5": "cinco", "6": "seis", "7": "siete", "8": "ocho", "9": "nueve",
}
_MONTHS = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
_UNITS = {
    "km/h": "kilómetros por hora",
    "km": "kilómetros",
    "kg": "kilogramos",
    "cm": "centímetros",
    "mm": "milímetros",
    "ml": "mililitros",
    "mg": "miligramos",
    "gb": "gigabytes",
    "mb": "megabytes",
    "kb": "kilobytes",
    "°c": "grados centígrados",
    "°f": "grados Fahrenheit",
    "m²": "metros cuadrados",
    "m2": "metros cuadrados",
    "l": "litros",
    "h": "horas",
    "min": "minutos",
    "s": "segundos",
    "m": "metros",
}
_ROMAN_CONTEXT_RE = re.compile(
    r"\b(siglo|capítulo|capitulo|tomo|libro|parte|acto|escena)\s+([IVXLCDM]+)\b",
    re.IGNORECASE,
)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_ORDINAL_RE = re.compile(r"\b(\d{1,3})\s*\.?\s*[ºª]\b", re.IGNORECASE)
_STANDALONE_NUM_RE = re.compile(rf"(?<![\w.,])[+-]?{_NUM}(?![\w])")


def _digits_words(digits: str) -> str:
    return " ".join(_DIGIT_WORDS[d] for d in digits if d.isdigit())


def _number_words(token: str) -> str | None:
    """Convierte un número español a palabras.

    Acepta 1.234,56 / 1234.56 / 1984 / 1,5. Devuelve None si no se
    puede interpretar con seguridad.
    """
    if _num2words is None:
        return None

    raw = token.strip().replace(" ", "")
    sign = ""
    if raw.startswith(("-", "+")):
        if raw[0] == "-":
            sign = "menos "
        raw = raw[1:]
    if not re.fullmatch(_NUM, raw):
        return None

    has_dot = "." in raw
    has_comma = "," in raw
    decimal_sep = None
    if has_dot and has_comma:
        decimal_sep = "." if raw.rfind(".") > raw.rfind(",") else ","
    elif has_dot:
        parts = raw.split(".")
        if len(parts) > 1 and len(parts[0]) <= 3 and all(
            len(p) == 3 for p in parts[1:]
        ):
            decimal_sep = None  # 1.234 / 12.345.678 = miles
        else:
            decimal_sep = "."
    elif has_comma:
        # En español la coma es decimal por defecto.
        decimal_sep = ","

    if decimal_sep:
        int_part, frac_part = raw.rsplit(decimal_sep, 1)
        int_part = int_part.replace(".", "").replace(",", "")
    else:
        int_part, frac_part = raw.replace(".", "").replace(",", ""), ""

    if not int_part.isdigit() or not int_part:
        return None
    if len(int_part) > 1 and int_part.startswith("0"):
        integer_words = _digits_words(int_part)
    else:
        try:
            value = int(int_part)
        except ValueError:
            return None
        if value > getattr(C, "NUMBER_NORMALIZATION_MAX", 999_999_999):
            return None
        integer_words = _num2words(value, lang="es")

    if frac_part:
        if len(frac_part) > 1 and frac_part.startswith("0"):
            fraction_words = _digits_words(frac_part)
        else:
            try:
                fraction_words = _num2words(int(frac_part), lang="es")
            except Exception:
                return None
        return f"{sign}{integer_words} coma {fraction_words}"
    return sign + integer_words


def _replace_number(match) -> str:
    words = _number_words(match.group(0))
    return words if words else match.group(0)


def _roman_to_int(value: str) -> int | None:
    value = value.upper()
    total = 0
    previous = 0
    for ch in reversed(value):
        number = _ROMAN_VALUES.get(ch)
        if number is None:
            return None
        if number < previous:
            total -= number
        else:
            total += number
            previous = number
    return total if total > 0 else None


def _date_words(match) -> str:
    day, month, year = (int(g) for g in match.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)
    if year < 100:
        year += 2000 if year < 70 else 1900
    day_words = _number_words(str(day))
    year_words = _number_words(str(year))
    if not day_words or not year_words:
        return match.group(0)
    return f"{day_words} de {_MONTHS[month]} de {year_words}"


def _time_words(match) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return match.group(0)
    hour_words = _number_words(str(hour))
    if minute == 0:
        return f"{hour_words} en punto"
    if minute == 30:
        return f"{hour_words} y media"
    minute_words = _number_words(str(minute))
    return f"{hour_words} y {minute_words}" if hour_words and minute_words else match.group(0)


def _apply_numbers(text: str) -> str:
    if not getattr(C, "ENABLE_NUMBER_NORMALIZATION", True) or _num2words is None:
        return text

    # Fechas y horas primero, para que sus componentes no se normalicen
    # por separado.
    text = _DATE_RE.sub(_date_words, text)
    text = _TIME_RE.sub(_time_words, text)

    def _ordinal_words(match):
        words = _number_words(match.group(1))
        if not words:
            return match.group(0)
        try:
            ordinal = _num2words(int(match.group(1)), lang="es", to="ordinal")
        except Exception:
            return match.group(0)
        # «primero»/«segunda» concuerdan mejor que el número cardinal.
        return ordinal

    text = _ORDINAL_RE.sub(_ordinal_words, text)

    def _roman_words(match):
        number = _roman_to_int(match.group(2))
        words = _number_words(str(number)) if number else None
        return f"{match.group(1)} {words}" if words else match.group(0)

    text = _ROMAN_CONTEXT_RE.sub(_roman_words, text)

    # Porcentajes y moneda.
    text = re.sub(
        rf"({_NUM})\s*%",
        lambda m: f"{_number_words(m.group(1)) or m.group(1)} por ciento",
        text,
    )
    text = re.sub(
        rf"({_NUM})\s*(€|\$|£)",
        lambda m: (
            f"{_number_words(m.group(1)) or m.group(1)} "
            f"{ {'€': 'euros', '$': 'dólares', '£': 'libras'}[m.group(2)] }"
        ),
        text,
    )
    text = re.sub(
        rf"(€|\$|£)\s*({_NUM})",
        lambda m: (
            f"{_number_words(m.group(2)) or m.group(2)} "
            f"{ {'€': 'euros', '$': 'dólares', '£': 'libras'}[m.group(1)] }"
        ),
        text,
    )

    # Unidades. Se ordenan de más largas a más cortas para que «km/h»
    # no se quede en «km».
    for unit, spoken in sorted(_UNITS.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = re.sub(
            rf"({_NUM})\s*{re.escape(unit)}\b",
            lambda m, u=spoken: (
                f"{_number_words(m.group(1)) or m.group(1)} {u}"
            ),
            text,
            flags=re.IGNORECASE,
        )

    return _STANDALONE_NUM_RE.sub(_replace_number, text)


# ----------------------------------------------------------
# Pronunciación
# ----------------------------------------------------------

def _apply_pronunciation(text: str) -> str:
    fixes = dict(C.PRONUNCIATION_FIXES)
    fixes.update(_BOOK_PRONUNCIATION)
    # Las claves más largas primero; «Shirayuki» antes que «Shira».
    for old, new in sorted(fixes.items(), key=lambda kv: len(kv[0]), reverse=True):
        if not old:
            continue
        if re.fullmatch(r"[\wÁÉÍÓÚÜÑáéíóúüñ]+", old):
            text = re.sub(
                rf"(?<!\w){re.escape(old)}(?!\w)", new, text
            )
        else:
            text = text.replace(old, new)
    return text


def _apply_regex(text: str) -> str:
    for pattern, replacement in C.REGEX_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def _opening_position(sentence: str, punctuation_index: int) -> int:
    """Devuelve dónde insertar ¿/¡ dentro de una oración.

    Orden de preferencia:
      1. Después de la última comilla de apertura que siga abierta.
      2. Después de la raya de diálogo inicial.
      3. Al principio de la oración.
    """
    # Si la oración empieza con una raya y/o un tag de expresión, el
    # signo de apertura debe ir después: «<laugh> ¡No puedo!».
    prefix = re.match(
        r"^\s*(?:(?:[—–-]+\s*)|(?:(?:<laugh>|<breath>|<sigh>)\s*))*",
        sentence,
        re.IGNORECASE,
    )
    if prefix and prefix.end() > 0 and prefix.end() <= punctuation_index:
        # Si después del tag/raya viene una comilla de apertura, la
        # comilla manda: «<laugh> "¿Hola?"», no «<laugh> ¿"Hola?"».
        remainder = sentence[prefix.end():punctuation_index].lstrip()
        if not remainder.startswith(_OPENING_QUOTES):
            return prefix.end()

    for pos in range(punctuation_index - 1, -1, -1):
        if sentence[pos] not in _OPENING_QUOTES:
            continue
        if sentence[pos] == '"' and sentence[:pos].count('"') % 2 == 1:
            continue
        between = sentence[pos + 1:punctuation_index]
        if not any(q in between for q in _CLOSING_QUOTES):
            return pos + 1

    m = re.match(r"^\s*[—–-]+\s*", sentence)
    if m and m.end() < len(sentence):
        return m.end()

    return 0


def _ensure_opening_marks(text: str) -> str:
    """Añade ¿/¡ de apertura donde solo existe el cierre ?/!."""
    out = []
    start = 0

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

        ws_start = end
        while ws_start < len(text) and text[ws_start].isspace():
            ws_start += 1
        out.append(text[end:ws_start])
        start = ws_start

    out.append(text[start:])
    return "".join(out)


# ----------------------------------------------------------
# Limpieza principal
# ----------------------------------------------------------

def clean(text: str) -> str:
    text = _apply_regex(text)
    text = _normalize_cjk(text)
    text = _mark_scene_breaks(text)
    text = _apply_spanish_abbreviations(text)
    text = _apply_expression_cues(text)
    text = _sanitize_expression_tags(text)
    # Los títulos «Capítulo 1» se conservan para metadatos; el número
    # se lee igual de bien y no queremos convertir el título en
    # «Capítulo uno» en el M4B.
    is_chapter_marker = bool(
        C.CHAPTER_MARKER_REGEX.match(text.strip())
    )
    if not is_chapter_marker:
        text = _apply_numbers(text)
    text = _apply_pronunciation(text)

    text = text.replace("\r", "\n")
    for sym in DECORATIVE_SYMBOLS:
        text = text.replace(sym, " ")

    text = _protect_ellipsis(text)
    text = re.sub(r"(?<=\w)\s*–\s*(?=\w)", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r",+", ",", text)
    # Conserva «!!» y «?!»; solo limita repeticiones largas del mismo
    # signo. Así no se pierde la intensidad expresiva del diálogo.
    text = re.sub(r"([!?])\1{2,}", r"\1\1", text)
    text = _restore_ellipsis(text)

    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    text = text.strip()

    if text and text != SCENE_BREAK_TOKEN:
        text = _ensure_opening_marks(text)

    return text


# ----------------------------------------------------------
# Oraciones y segmentos
# ----------------------------------------------------------

def _is_sentence_boundary(text: str, pos: int) -> bool:
    """True si el signo en `pos` cierra una oración.

    No corta tras abreviaturas conocidas ni tras iniciales tipo J. R.
    """
    ch = text[pos]
    if ch not in ".!?…":
        return False
    j = pos + 1
    while j < len(text) and text[j] in ".!?…":
        j += 1
    while j < len(text) and text[j] in "\"'”»)]}":
        j += 1
    if j < len(text) and not text[j].isspace():
        return False

    # Abreviatura: miramos la palabra que termina en este punto.
    word_start = pos
    while word_start > 0 and (text[word_start - 1].isalnum()
                              or text[word_start - 1] in ".-"):
        word_start -= 1
    token = text[word_start:pos + 1].lower()
    if token in {
        "sr.", "sra.", "srta.", "dr.", "dra.", "ud.", "uds.",
        "etc.", "pág.", "págs.", "cap.", "caps.", "n.º", "n.°",
        "p.", "a.", "d.", "ee.", "uu.",
    }:
        return False
    if re.fullmatch(r"[a-záéíóúüñ]\.", token):
        return False
    return True


def split_sentences(text: str) -> list[str]:
    """Divide en oraciones conservando la puntuación."""
    text = text.strip()
    if not text:
        return []

    parts, start = [], 0
    for pos, ch in enumerate(text):
        if pos < start:
            continue
        if _is_sentence_boundary(text, pos):
            end = pos + 1
            while end < len(text) and text[end] in ".!?…\"'”»)]}":
                end += 1
            piece = text[start:end].strip()
            if piece:
                parts.append(piece)
            start = end
            while start < len(text) and text[start].isspace():
                start += 1

    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _split_oversized_sentence(sentence: str, max_chars: int) -> list[str]:
    """Parte una frase sin puntuación interna suficiente."""
    out, rest = [], sentence.strip()
    while len(rest) > max_chars:
        window = rest[:max_chars]
        candidates = [
            m.end()
            for m in re.finditer(r"[;:,—–-]\s+", window)
            if m.end() >= max_chars * 0.45
        ]
        cut = max(candidates) if candidates else window.rfind(" ")
        if cut < max_chars * 0.45:
            cut = max_chars
        piece = rest[:cut].strip()
        if not piece:
            break
        out.append(piece)
        rest = rest[cut:].strip()
    if rest:
        out.append(rest)
    return out


def split_long_text(text: str, max_chars: int = None) -> list[str]:
    """Divide un párrafo en partes manejables respetando oraciones.

    Las frases que por sí solas superan `max_chars` se parten por
    comas, dos puntos, punto y coma o espacios cercanos al límite.
    """
    if max_chars is None:
        max_chars = getattr(C, "SENTENCE_MAX_CHARS", 220)
    max_chars = max(40, int(max_chars))

    text = text.strip()
    if not text or len(text) <= max_chars:
        return [text] if text else []

    units: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) <= max_chars:
            units.append(sentence)
        else:
            units.extend(_split_oversized_sentence(sentence, max_chars))

    # Agrupa oraciones cortas para no multiplicar llamadas al modelo.
    grouped: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= max_chars:
            current += " " + unit
        else:
            grouped.append(current)
            current = unit
    if current:
        grouped.append(current)
    return grouped


# ----------------------------------------------------------
# Clasificación de párrafo
# ----------------------------------------------------------

def classify_paragraph(p: str) -> str:
    """Devuelve 'dialogo', 'pensamiento' o 'narracion'."""
    s = p.strip()
    if not s:
        return "narracion"

    # Un tag de expresión al principio no cambia el tipo de párrafo:
    # «<laugh> —Hola» sigue siendo diálogo.
    s = re.sub(
        r"^(?:<(?:laugh|breath|sigh)>\s*)+", "", s, flags=re.IGNORECASE
    ).strip()
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

def _style_pause(style: str) -> int:
    return int(getattr(C, "STYLE_PAUSES_MS", {}).get(
        style, C.SILENCE_BETWEEN_BLOCKS_MS
    ))


def build_blocks(paragraphs: list, max_chars: int = None) -> list:
    """Agrupa párrafos en bloques de síntesis respetando la prosodia.

    - Los turnos de diálogo y los pensamientos se separan para que el
      modelo no los lea como una tirada continua.
    - La narración se agrupa como máximo `MAX_PARAGRAPHS_PER_BLOCK`
      párrafos o hasta `max_chars`.
    - Las frases/párrafos largos se parten con `split_long_text`.
    - Cada bloque lleva una pausa según su estilo.

    Devuelve lista de dicts:
        {"text": str, "pause_after_ms": int, "style": str}
    """
    if max_chars is None:
        max_chars = C.BLOCK_MAX_CHARS
    max_chars = max(80, int(max_chars))
    sentence_chars = min(
        max_chars, int(getattr(C, "SENTENCE_MAX_CHARS", max_chars))
    )

    blocks: list[dict] = []
    current: list[str] = []
    current_len = 0
    current_style = None
    current_paragraphs = 0

    def flush(pause_ms: int | None = None):
        nonlocal current, current_len, current_style, current_paragraphs
        if current:
            style = current_style or "narracion"
            blocks.append({
                "text":           "\n\n".join(current),
                "pause_after_ms": int(
                    _style_pause(style) if pause_ms is None else pause_ms
                ),
                "style":          style,
            })
        current = []
        current_len = 0
        current_style = None
        current_paragraphs = 0

    def emit(text: str, style: str, pause_ms: int):
        if text.strip():
            blocks.append({
                "text":           text.strip(),
                "pause_after_ms": int(pause_ms),
                "style":          style,
            })

    for p in paragraphs:
        if p.strip() == SCENE_BREAK_TOKEN:
            flush(C.SILENCE_SCENE_BREAK_MS)
            continue

        style = classify_paragraph(p)
        split_this = (
            (style == "dialogo" and getattr(C, "SPLIT_DIALOGUE_BLOCKS", True))
            or (style == "pensamiento" and getattr(C, "SPLIT_THOUGHT_BLOCKS", True))
            or len(p) > sentence_chars
        )
        parts = split_long_text(p, sentence_chars) if split_this else [p]

        if split_this:
            flush()
            for i, part in enumerate(parts):
                pause = (
                    C.SENTENCE_GAP_MS
                    if i < len(parts) - 1
                    else _style_pause(style)
                )
                emit(part, style, pause)
            continue

        # Narración corta: agrupar sin perder los límites de párrafo.
        if current and (
            style != current_style
            or current_len + len(p) + 2 > max_chars
            or current_paragraphs >= getattr(C, "MAX_PARAGRAPHS_PER_BLOCK", 2)
        ):
            flush()

        current.append(p)
        current_len += len(p) + 2
        current_style = style
        current_paragraphs += 1

    flush()
    return blocks
