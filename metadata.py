"""
metadata.py — Extracción de cover art y tags para MP3/M4B.
"""
import re
from pathlib import Path

from ebooklib import epub

# Nombres reservados por Windows (no se pueden usar como archivo).
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Devuelve un nombre seguro para Windows/macOS/Linux.

    - Quita los caracteres prohibidos y los de control.
    - Evita nombres reservados (CON, NUL, COM1…).
    - Recorta a `max_len` y elimina puntos/espacios finales.
    """
    name = _INVALID_FILENAME_CHARS.sub("", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "sin_titulo"

    if name.split(".")[0].strip().upper() in _RESERVED_NAMES:
        name = "_" + name

    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")

    return name or "sin_titulo"


def escape_ffmetadata(value: str) -> str:
    """Escapa un valor para el formato FFMETADATA1 de ffmpeg.

    En FFMETADATA1 los caracteres especiales son \\, =, ; y #, y
    los saltos de línea no están permitidos en un valor.
    """
    value = str(value).replace("\r", " ").replace("\n", " ")
    value = value.replace("\\", "\\\\")
    value = value.replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
    return value


def extract_epub_metadata(path: str) -> dict:
    """Devuelve dict con 'title', 'artist', 'date' (pueden ser None)."""
    meta = {"title": None, "artist": None, "date": None}
    try:
        book = epub.read_epub(path)
        if book.get_metadata("DC", "title"):
            meta["title"] = book.get_metadata("DC", "title")[0][0]
        if book.get_metadata("DC", "creator"):
            meta["artist"] = book.get_metadata("DC", "creator")[0][0]
        if book.get_metadata("DC", "date"):
            meta["date"] = book.get_metadata("DC", "date")[0][0][:4]
    except Exception:
        pass
    return meta


def extract_epub_cover(epub_path: str, out_dir: str) -> str | None:
    """Extrae la imagen de portada del EPUB.
    Devuelve la ruta del archivo extraído, o None si no se encuentra."""
    try:
        book = epub.read_epub(epub_path)

        # 1) item marcado explícitamente como cover-image en el manifest
        cover = None
        for item in book.get_items():
            props = getattr(item, "properties", "") or ""
            if "cover-image" in props:
                cover = item
                break

        # 2) fallback: nombre de archivo que contenga "cover" / "portada"
        if cover is None:
            for item in book.get_items():
                name_lower = (item.get_name() or "").lower()
                mtype = item.media_type or ""
                if any(k in name_lower for k in ("cover", "portada", "jacket")) \
                        and mtype.startswith("image/"):
                    cover = item
                    break

        if cover is None:
            return None

        ext_map = {
            "image/jpeg": ".jpg",
            "image/jpg":  ".jpg",
            "image/png":  ".png",
            "image/webp": ".webp",
            "image/gif":  ".gif",
            "image/bmp":  ".bmp",
        }
        ext = ext_map.get((cover.media_type or "").lower(), ".jpg")
        out_path = str(Path(out_dir) / f"_cover{ext}")
        with open(out_path, "wb") as f:
            f.write(cover.get_content())
        return out_path

    except Exception:
        return None


def find_cover(book_path: str, out_dir: str) -> str | None:
    """Busca cover art en orden:
    1. Dentro del EPUB (si aplica).
    2. Archivo de imagen con el mismo nombre del libro en la misma carpeta.
    """
    if book_path.lower().endswith(".epub"):
        cover = extract_epub_cover(book_path, out_dir)
        if cover:
            return cover

    stem   = Path(book_path).stem
    folder = Path(book_path).parent
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        candidate = folder / (stem + ext)
        if candidate.exists():
            return str(candidate)

    return None


def book_tags(album: str, artist: str = "", date: str = "") -> dict:
    """Devuelve el dict de tags base para todos los archivos de un libro."""
    return {
        "album":   album,
        "artist":  artist,
        "date":    date,
        "genre":   "Audiobook",
        "comment": "Generado por Superaudio",
    }
