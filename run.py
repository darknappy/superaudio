"""
run.py — lanzador de Superaudio para Windows.

Puede ejecutarse con el Python del sistema: si existe el venv de
Supertonic, se relanza automáticamente dentro de él antes de importar
numpy/supertonic. También es el archivo que usa la GUI.
"""
import os
import sys

# Forzar UTF-8 en stdout/stderr. Sin consola real detrás (como cuando
# el proceso lo lanza la GUI empaquetada), Python en Windows puede
# caer a cp1252, y CUALQUIER emoji impreso en el proyecto revienta con
# UnicodeEncodeError. Esto debe ir antes de cualquier otro print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# run.py vive DENTRO de la carpeta del paquete superaudio/, así que la
# raíz a insertar en sys.path es DOS niveles arriba: la carpeta que
# CONTIENE a superaudio/, no superaudio/ misma.
_root = os.environ.get("SUPERAUDIO_ROOT")
if not _root:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from superaudio.config import SUPERTONIC_PY as VENV_PY
except Exception:
    VENV_PY = os.environ.get(
        "SUPERTONIC_PY",
        r"C:\supertonic\venv\Scripts\python.exe",
    )

_cur  = os.path.abspath(sys.executable)
_venv = os.path.abspath(VENV_PY)

if os.path.exists(_venv) and _cur.lower() != _venv.lower():
    print("Reiniciando en el entorno de Supertonic ...", flush=True)
    os.environ["SUPERAUDIO_ROOT"] = _root
    os.execv(_venv, [_venv, os.path.abspath(__file__), *sys.argv[1:]])

try:
    from superaudio.__main__ import main
except ModuleNotFoundError as e:
    print(f"❌ No se pudo importar el paquete 'superaudio' desde: {_root}")
    print("   Verifica que la carpeta 'superaudio' esté junto a run.py.")
    print(f"   Detalle: {e}")
    raise SystemExit(1)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
