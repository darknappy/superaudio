"""
progress.py — Registro de progreso en JSON para poder reanudar el
              proceso sin depender de que existan archivos WAV
              temporales en disco (que ahora se borran agresivamente
              por lote para no ocupar espacio).
"""
import hashlib
import json
import os


def load(out_dir: str) -> dict:
    path = os.path.join(out_dir, "progress.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("done_chapters", [])
                    return data
        except Exception:
            pass
    return {"done_chapters": []}


def save(out_dir: str, data: dict):
    """Escritura atómica (tmp + rename) para no corromper el JSON
    si el proceso se interrumpe justo mientras escribe."""
    path = os.path.join(out_dir, "progress.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def fingerprint(book_path: str, params: dict) -> str:
    """Huella de la fuente + configuración que afecta al audio.

    Si cambia el libro, la voz, la velocidad, el modo de salida, etc.,
    el progreso anterior ya no es válido y debe reiniciarse.
    """
    h = hashlib.sha256()
    try:
        st = os.stat(book_path)
        h.update(os.path.abspath(book_path).encode("utf-8", "replace"))
        h.update(str(st.st_size).encode("ascii"))
        h.update(str(int(st.st_mtime)).encode("ascii"))
    except OSError:
        h.update(os.path.abspath(book_path).encode("utf-8", "replace"))

    for key in sorted(params):
        h.update(f"{key}={params[key]!r}".encode("utf-8", "replace"))
    return h.hexdigest()


def is_chapter_done(data: dict, c_idx: int) -> bool:
    return c_idx in set(data.get("done_chapters", []))


def mark_chapters_done(out_dir: str, data: dict, indices) -> None:
    """Marca varios capítulos como listos y guarda una sola vez
    (se llama al cerrar cada lote/grupo, no por cada capítulo)."""
    done = set(data.get("done_chapters", []))
    done.update(indices)
    data["done_chapters"] = sorted(done)
    save(out_dir, data)
