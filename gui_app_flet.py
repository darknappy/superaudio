"""
gui_app_flet.py — Interfaz Flet (app de escritorio) para superaudio.

Instalar (una sola vez):
    pip install flet

Correr:
    flet run gui_app_flet.py
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import flet as ft

if getattr(sys, "frozen", False):
    # Empaquetado con PyInstaller/flet pack: __file__ apunta a una
    # carpeta temporal de extracción, no a donde vive el .exe real.
    HERE = Path(sys.executable).resolve().parent
else:
    HERE = Path(__file__).resolve().parent

# run.py puede estar junto al .exe, dentro del paquete superaudio/ o
# empaquetado por PyInstaller en sys._MEIPASS.
_run_py_candidates = []
if hasattr(sys, "_MEIPASS"):
    _run_py_candidates.append(Path(sys._MEIPASS) / "run.py")
_run_py_candidates += [HERE / "run.py", HERE / "superaudio" / "run.py"]
RUN_PY = next((p for p in _run_py_candidates if p.exists()), _run_py_candidates[0])

VALID_VOICES = [f"{g}{n}" for g in ("F", "M") for n in range(1, 6)]

# ---------------- Paleta ----------------
BG_MATTE      = "#0a0a0c"
PANEL_BG      = "#131317"
PANEL_BORDER  = "#232329"
PURPLE        = "#9B5CFF"
PURPLE_DIM    = "#6B3FB5"
PURPLE_GLOW   = "#9B5CFF3D"
TEXT_DIM      = ft.Colors.WHITE_60
TEXT_DIMMER   = ft.Colors.WHITE_38

# --- Borde compatible con Flet v0.20+ ---
_border_side = ft.BorderSide(1, PANEL_BORDER)
PANEL_BORDER_STYLE = ft.Border(
    top=_border_side,
    bottom=_border_side,
    left=_border_side,
    right=_border_side,
)
# ----------------------------------------

# ---------------- Defaults desde config.py ----------------
# Si HERE es la carpeta del paquete (contiene __init__.py), la raíz
# que hay que poner en sys.path es HERE.parent. Si es la carpeta del
# .exe, la raíz puede ser HERE o HERE.parent según cómo se distribuyó.
_ROOT = HERE.parent if (HERE / "__init__.py").exists() else HERE
for _p in (str(_ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

C = None
_CONFIG_ERROR = None

_defaults = dict(
    voice="F2",
    output=str(_ROOT / "output"),
    speed=1.0, steps=10, silence=0.35,
    chunk_chars=300, block_chars=1200, workers=1,
)
try:
    from superaudio import config as C
    if C.VOICE in VALID_VOICES:
        _defaults["voice"] = C.VOICE
    _defaults["output"]      = C.OUTPUT_DIR
    _defaults["speed"]       = C.SPEED
    _defaults["steps"]       = C.TOTAL_STEPS
    _defaults["silence"]     = C.SILENCE_BETWEEN_SENTENCES
    _defaults["chunk_chars"] = C.MAX_CHUNK_LENGTH
    _defaults["block_chars"] = C.BLOCK_MAX_CHARS
    _defaults["workers"]     = C.PARALLEL_WORKERS
except Exception as e:
    _CONFIG_ERROR = str(e)

# Python del venv dedicado de Supertonic (numpy/onnxruntime/supertonic
# viven ahí, NO en el entorno de la GUI ni dentro del .exe empaquetado).
VENV_PY = Path(C.SUPERTONIC_PY) if C else Path(
    os.environ.get("SUPERTONIC_PY", r"C:\supertonic\venv\Scripts\python.exe")
)



def _iter_process_lines(process):
    buf = ""
    while True:
        chunk = process.stdout.read(256)
        if not chunk:
            break
        buf += chunk
        while True:
            idxs = [i for i in (buf.find("\n"), buf.find("\r")) if i != -1]
            if not idxs:
                break
            idx = min(idxs)
            line, buf = buf[:idx], buf[idx + 1:]
            if line.strip():
                yield line
    if buf.strip():
        yield buf


def _terminate_process(process):
    """Mata el proceso y, en Windows, también sus workers hijos."""
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.terminate()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


_FRAC_RE = re.compile(r"\|\s*(\d+)/(\d+)\s*\[")
_PCT_RE  = re.compile(r"(\d+)%\|")


def gradient_button(text: str, on_click=None, disabled: bool = False,
                     height: int = 44, width: int = 240) -> ft.Container:
    """Botón 'con textura' centrado y de tamaño controlado."""
    inner = ft.Text(text, color=ft.Colors.WHITE, weight=ft.FontWeight.W_600, size=14)
    container = ft.Container(
        content=ft.Row([inner], alignment=ft.MainAxisAlignment.CENTER),
        height=height,
        width=width,
        border_radius=12,
        alignment=ft.Alignment(0, 0),
        ink=True,
        on_click=None if disabled else on_click,
        opacity=0.45 if disabled else 1,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=[PURPLE, PURPLE_DIM],
        ),
        shadow=None if disabled else ft.BoxShadow(
            blur_radius=18, spread_radius=0.5,
            color=PURPLE_GLOW, offset=ft.Offset(0, 4),
        ),
        animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
    )
    return container


def main(page: ft.Page):
    page.title = "Superaudio"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=PURPLE)
    page.bgcolor = BG_MATTE
    page.padding = 0
    page.window.width = 820
    page.window.height = 780
    page.window.min_width = 680
    page.window.min_height = 680
    page.window.resizable = True
    page.window.bgcolor = BG_MATTE
    page.scroll = None

    state = {
        "book_path": None,
        "out_dir": "",
        "current_chapter": "",
        "process": None,
        "stopping": False,
    }

    # =====================================================
    # Encabezado
    # =====================================================
    header = ft.Row(
        [
            ft.Container(
                content=ft.Text("🎧", size=22),
                bgcolor="#1c1420", border_radius=10, padding=8,
                shadow=ft.BoxShadow(blur_radius=14, color=PURPLE_GLOW,
                                     offset=ft.Offset(0, 0)),
            ),
            ft.Column(
                [
                    ft.Text("Superaudio", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Audiolibros en español · Supertonic TTS",
                            size=11, color=TEXT_DIM),
                ],
                spacing=0,
            ),
        ],
        spacing=12,
    )

    # =====================================================
    # Selección de archivo (vía Tkinter nativo)
    # =====================================================
    file_label = ft.Text("Ningún archivo seleccionado", color=TEXT_DIM, size=12)

    def on_pick_click(e):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Seleccionar libro",
            filetypes=[
                ("Archivos compatibles", "*.epub *.docx *.txt"),
                ("EPUB", "*.epub"),
                ("Word", "*.docx"),
                ("Texto", "*.txt"),
                ("Todos los archivos", "*.*")
            ]
        )
        root.destroy()

        if file_path:
            state["book_path"] = file_path
            file_label.value = Path(file_path).name
            file_label.color = ft.Colors.WHITE
            file_label.update()
            generate_btn.opacity = 1
            generate_btn.on_click = on_generate
            generate_btn.update()

    pick_btn = ft.OutlinedButton(
        "📂  Elegir libro",
        on_click=on_pick_click,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1, PANEL_BORDER),
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    # =====================================================
    # Opciones esenciales
    # =====================================================
    voice_dd = ft.Dropdown(
        label="Voz", value=_defaults["voice"], width=130, dense=True,
        options=[ft.dropdown.Option(v) for v in VALID_VOICES],
    )

    mode_dd = ft.Dropdown(
        label="Salida", value="M4B (capítulos internos)", width=240, dense=True,
        options=[
            ft.dropdown.Option("M4B (capítulos internos)"),
            ft.dropdown.Option("MP3 plano"),
            ft.dropdown.Option("MP3 por capítulo"),
        ],
    )

    # ---------------- Estado / Progreso Circular y Visual ----------------
    status_text = ft.Text("Esperando archivo…", size=11, color=TEXT_DIM)
    progress_ring = ft.ProgressRing(value=0, width=28, height=28, stroke_width=3, color=PURPLE, bgcolor="#1c1c22")

    log_view = ft.ListView(spacing=3, auto_scroll=True, expand=True)
    
    log_container = ft.Container(
        content=log_view,
        bgcolor=PANEL_BG,
        border=PANEL_BORDER_STYLE,
        border_radius=10,
        padding=10,
        height=170,
    )

    def on_open_folder(_):
        target = state.get("out_dir") or _defaults["output"]
        if not target or not os.path.exists(target):
            status_text.value = f"⚠ La carpeta aún no existe: {target}"
            status_text.color = ft.Colors.RED_300
            status_text.update()
            return
        try:
            if os.name == "nt":
                os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            status_text.value = f"❌ No se pudo abrir la carpeta: {e}"
            status_text.color = ft.Colors.RED_300
            status_text.update()

    open_folder_btn = ft.TextButton(
        "📁  Abrir carpeta de salida", visible=False,
        on_click=on_open_folder,
        style=ft.ButtonStyle(color=PURPLE),
    )

    # Botón centrado con ancho controlado
    generate_btn = gradient_button("🚀  Generar audiolibro", disabled=True, height=44, width=240)

    stop_btn = ft.OutlinedButton(
        "⏹  Detener",
        visible=False,
        on_click=lambda e: on_stop(e),
        style=ft.ButtonStyle(
            color=ft.Colors.RED_300,
            side=ft.BorderSide(1, ft.Colors.RED_300),
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    # =====================================================
    # Tarjeta de Audio Decorativa (aprovecha el espacio vacío)
    # =====================================================
    audio_badge_card = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [ft.Text("🎶", size=20), ft.Text("🎧", size=24), ft.Text("🔊", size=20)],
                    alignment=ft.MainAxisAlignment.SPACE_AROUND,
                ),
                ft.Divider(height=1, color=PANEL_BORDER),
                ft.Row(
                    [
                        progress_ring,
                        ft.Column([
                            ft.Text("Estado del Motor", size=10, color=TEXT_DIMMER),
                            status_text
                        ], spacing=0, expand=True)
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
            spacing=8,
        ),
        bgcolor=PANEL_BG,
        border=PANEL_BORDER_STYLE,
        border_radius=12,
        padding=12,
        width=260,
    )

    # =====================================================
    # Opciones avanzadas
    # =====================================================
    def _adv_field(label, value, hint=None, width=170):
        return ft.TextField(
            label=label, value=str(value), width=width, dense=True,
            keyboard_type=ft.KeyboardType.NUMBER, hint_text=hint,
        )

    chapters_field = _adv_field("Capítulos por archivo", 0, "0 = todo en 1 archivo")
    preview_field  = _adv_field("Preview: solo N bloques", 0, "0 = libro completo")
    speed_field    = _adv_field("Velocidad", _defaults["speed"], "0.7 – 2.0")
    steps_field    = _adv_field("Steps (calidad)", _defaults["steps"], "5 – 12")
    silence_field  = _adv_field("Silencio entre oraciones (s)", _defaults["silence"])
    chunk_field    = _adv_field("Chunk chars (Supertonic)", _defaults["chunk_chars"])
    block_field    = _adv_field("Block chars (propio)", _defaults["block_chars"])
    workers_field  = _adv_field("Workers en paralelo", _defaults["workers"])
    force_checkbox = ft.Checkbox(label="Forzar regeneración (--force)", value=False)

    def adv_section(title, controls):
        return ft.Column(
            [
                ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=TEXT_DIM),
                ft.Row(controls, spacing=14, wrap=True),
            ],
            spacing=8,
        )

    # =====================================================
    # Vistas de contenido con la nueva distribución equilibrada
    # =====================================================
    essential_tab_content = ft.Container(
        padding=ft.Padding(left=0, top=16, right=0, bottom=0),
        content=ft.Column(
            [
                # Fila 1: Selector de archivo
                ft.Row([pick_btn, file_label], spacing=12),
                
                # Fila 2: Dos columnas simétricas (Controles/Botón centrado vs Tarjeta de Audio)
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Row([voice_dd, mode_dd], spacing=12),
                                ft.Container(height=8),
                                # Botones centrados en su espacio
                                ft.Row([generate_btn, stop_btn],
                                       alignment=ft.MainAxisAlignment.CENTER,
                                       spacing=12),
                            ],
                            spacing=0,
                            expand=True,
                        ),
                        audio_badge_card,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),

                ft.Divider(height=1, color=PANEL_BORDER),
                
                # Fila 3: Consola de logs y botón de salida
                log_container,
                open_folder_btn,
            ],
            spacing=14,
        ),
    )

    advanced_tab_content = ft.Container(
        padding=ft.Padding(left=4, top=20, right=4, bottom=0),
        content=ft.Column(
            [
                adv_section("Lotes / pruebas", [chapters_field, preview_field, force_checkbox]),
                ft.Divider(height=1, color=PANEL_BORDER),
                adv_section("Síntesis", [speed_field, steps_field, silence_field]),
                ft.Divider(height=1, color=PANEL_BORDER),
                adv_section("Troceo de texto", [chunk_field, block_field]),
                ft.Divider(height=1, color=PANEL_BORDER),
                adv_section("Rendimiento", [workers_field]),
                ft.Container(height=10),
                ft.Text("Estos valores solo aplican a esta corrida; no modifican config.py.",
                        size=11, color=TEXT_DIMMER, italic=True),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    # =====================================================
    # Sistema de pestañas personalizado
    # =====================================================
    tab_body = ft.Container(content=essential_tab_content, expand=True)

    def switch_tab(e, index):
        if index == 0:
            tab_inicio.border = ft.Border(bottom=ft.BorderSide(2, PURPLE))
            tab_inicio.content.color = PURPLE
            tab_avanzada.border = ft.Border(bottom=ft.BorderSide(2, ft.Colors.TRANSPARENT))
            tab_avanzada.content.color = TEXT_DIM
            tab_body.content = essential_tab_content
        else:
            tab_inicio.border = ft.Border(bottom=ft.BorderSide(2, ft.Colors.TRANSPARENT))
            tab_inicio.content.color = TEXT_DIM
            tab_avanzada.border = ft.Border(bottom=ft.BorderSide(2, PURPLE))
            tab_avanzada.content.color = PURPLE
            tab_body.content = advanced_tab_content
        
        tab_inicio.update()
        tab_avanzada.update()
        tab_body.update()

    tab_inicio = ft.Container(
        content=ft.Text("Inicio", color=PURPLE, weight=ft.FontWeight.BOLD),
        padding=ft.Padding(left=12, top=10, right=12, bottom=10),
        border=ft.Border(bottom=ft.BorderSide(2, PURPLE)),
        on_click=lambda e: switch_tab(e, 0),
        ink=True,
    )
    
    tab_avanzada = ft.Container(
        content=ft.Text("Configuración avanzada", color=TEXT_DIM, weight=ft.FontWeight.BOLD),
        padding=ft.Padding(left=12, top=10, right=12, bottom=10),
        border=ft.Border(bottom=ft.BorderSide(2, ft.Colors.TRANSPARENT)),
        on_click=lambda e: switch_tab(e, 1),
        ink=True,
    )

    custom_tabs_header = ft.Row([tab_inicio, tab_avanzada], spacing=10)

    # =====================================================
    # Lectura del subproceso con actualización del Ring
    # =====================================================
    def run_pipeline(cmd, env):
        log_view.controls.clear()
        status_text.value = "Iniciando…"
        status_text.color = TEXT_DIM
        progress_ring.value = 0
        generate_btn.on_click = None
        generate_btn.opacity = 0.45
        stop_btn.visible = True
        stop_btn.disabled = False
        open_folder_btn.visible = False
        state["stopping"] = False
        page.update()

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = None
        last_push = 0.0
        MIN_INTERVAL = 0.1

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                creationflags=creationflags, env=env,
            )
            state["process"] = process

            for line in _iter_process_lines(process):
                stripped = line.strip()
                if not stripped:
                    continue

                is_progress_line = stripped.startswith(("🎙", "🔊"))

                if is_progress_line:
                    pct_m = _PCT_RE.search(stripped)
                    if pct_m:
                        progress_ring.value = min(int(pct_m.group(1)), 100) / 100

                    frac_m = _FRAC_RE.search(stripped)
                    if stripped.startswith("🎙") and frac_m:
                        status_text.value = f"Bloque {frac_m.group(1)}/{frac_m.group(2)}"
                    elif stripped.startswith("🔊"):
                        pct = pct_m.group(1) if pct_m else "…"
                        label = stripped.split(":")[0]
                        status_text.value = f"{label}: {pct}%"

                    now = time.time()
                    if now - last_push >= MIN_INTERVAL:
                        status_text.update()
                        progress_ring.update()
                        last_push = now
                else:
                    log_view.controls.append(
                        ft.Text(stripped, size=11, font_family="Consolas", color=TEXT_DIM)
                    )
                    if len(log_view.controls) > 150:
                        log_view.controls.pop(0)
                    status_text.value = stripped
                    status_text.color = ft.Colors.WHITE
                    log_view.update()
                    status_text.update()
                    last_push = time.time()

            process.wait()

        except Exception as e:
            log_view.controls.append(
                ft.Text(f"❌ {e}", size=11, font_family="Consolas", color=ft.Colors.RED_300)
            )
            status_text.value = f"❌ Error al lanzar el proceso: {e}"
            status_text.color = ft.Colors.RED_300
        finally:
            state["process"] = None
            out_dir = state.get("out_dir") or ""

            if state.get("stopping"):
                progress_ring.value = 0
                status_text.value = "⏹ Detenido. Puedes reanudar cuando quieras."
                status_text.color = ft.Colors.ORANGE_300
            elif process is not None and process.returncode == 0:
                progress_ring.value = 1
                status_text.value = "¡Completado con éxito!"
                status_text.color = ft.Colors.GREEN_300
            elif process is not None:
                status_text.value = f"Error (cód. {process.returncode}). Revisa el log."
                status_text.color = ft.Colors.RED_300
            else:
                status_text.value = "❌ No se pudo iniciar el proceso."
                status_text.color = ft.Colors.RED_300

            open_folder_btn.visible = bool(out_dir) and os.path.exists(out_dir)
            stop_btn.visible = False
            stop_btn.disabled = False
            generate_btn.on_click = on_generate
            generate_btn.opacity = 1
            page.update()

    def on_stop(_e):
        process = state.get("process")
        if not process or process.poll() is not None:
            return
        state["stopping"] = True
        status_text.value = "⏹ Deteniendo… (esperando a que terminen los workers)"
        status_text.color = ft.Colors.ORANGE_300
        status_text.update()
        stop_btn.disabled = True
        stop_btn.update()
        _terminate_process(process)

    def _int_or(field, fallback):
        try:
            return int(float(field.value))
        except (TypeError, ValueError):
            return fallback

    def _float_or(field, fallback):
        try:
            return float(field.value)
        except (TypeError, ValueError):
            return fallback

    def on_generate(e):
        if not state["book_path"]:
            return
        if state.get("process") is not None:
            return

        if not VENV_PY.exists():
            status_text.value = f"❌ No se encontró el venv de Supertonic: {VENV_PY}"
            status_text.color = ft.Colors.RED_300
            status_text.update()
            return

        if not RUN_PY.exists():
            status_text.value = f"❌ No se encontró run.py junto al programa: {RUN_PY}"
            status_text.color = ft.Colors.RED_300
            status_text.update()
            return

        cmd = [str(VENV_PY), str(RUN_PY), state["book_path"],
               "--voice", voice_dd.value]

        if mode_dd.value == "MP3 plano":
            cmd.append("--mp3")
        elif mode_dd.value == "MP3 por capítulo":
            cmd.append("--chapters")

        cpf = _int_or(chapters_field, 0)
        if cpf > 0:
            cmd += ["--chapters-per-file", str(cpf)]

        prev = _int_or(preview_field, 0)
        if prev > 0:
            cmd += ["--preview", str(prev)]

        cmd += ["--speed", str(_float_or(speed_field, _defaults["speed"]))]
        cmd += ["--steps", str(_int_or(steps_field, _defaults["steps"]))]
        cmd += ["--silence", str(_float_or(silence_field, _defaults["silence"]))]
        cmd += ["--chunk-chars", str(_int_or(chunk_field, _defaults["chunk_chars"]))]
        cmd += ["--block-chars", str(_int_or(block_field, _defaults["block_chars"]))]
        cmd += ["--workers", str(_int_or(workers_field, _defaults["workers"]))]

        if force_checkbox.value:
            cmd.append("--force")

        state["out_dir"] = str(Path(_defaults["output"]) / Path(state["book_path"]).stem)

        # La raíz que contiene el paquete superaudio/ (para run.py).
        env = os.environ.copy()
        if (HERE / "superaudio" / "__init__.py").exists():
            env["SUPERAUDIO_ROOT"] = str(HERE)
        elif (HERE / "__init__.py").exists():
            env["SUPERAUDIO_ROOT"] = str(HERE.parent)

        # Deshabilitar ya, para que un doble clic no lance dos procesos.
        generate_btn.on_click = None
        generate_btn.opacity = 0.45
        stop_btn.visible = True
        stop_btn.disabled = False
        generate_btn.update()
        stop_btn.update()

        page.run_thread(run_pipeline, cmd, env)

    # =====================================================
    # Layout General
    # =====================================================
    card = ft.Container(
        content=ft.Column(
            [
                header,
                custom_tabs_header,
                ft.Divider(height=1, color=PANEL_BORDER),
                tab_body
            ], 
            spacing=4, expand=True
        ),
        bgcolor=PANEL_BG,
        border=PANEL_BORDER_STYLE,
        border_radius=18,
        padding=22,
        expand=True,
        shadow=ft.BoxShadow(blur_radius=40, spread_radius=-4,
                             color="#00000080", offset=ft.Offset(0, 12)),
    )

    page.add(
        ft.Container(
            content=card,
            padding=16,
            expand=True,
            bgcolor=BG_MATTE,
        )
    )

    # Si se cierra la ventana mientras se sintetiza, matar también los
    # workers hijos para no dejar procesos huérfanos.
    def on_page_close(_e):
        _terminate_process(state.get("process"))
    page.on_close = on_page_close

    if _CONFIG_ERROR:
        msg = (f"⚠ No se pudo cargar config.py ({_CONFIG_ERROR}). "
               f"Se usan valores por defecto.")
        status_text.value = msg
        status_text.color = ft.Colors.ORANGE_300
        log_view.controls.append(
            ft.Text(msg, size=11, font_family="Consolas", color=ft.Colors.ORANGE_300)
        )
        page.update()

if __name__ == "__main__":
    ft.run(main)