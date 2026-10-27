# Superaudio

Generador local de audiolibros en español usando **Supertonic TTS**. Convierte libros en formato **TXT, DOCX o EPUB** en archivos **M4B con capítulos internos**, **un MP3 por capítulo** o **MP3 planos**, con portada, metadatos y reanudación automática.

No sube libros a ningún servicio: la síntesis y el ensamblado se ejecutan en tu equipo.

## Características

- Lectura de **TXT** (UTF-8/UTF-16), **DOCX** y **EPUB**.
- Detección de capítulos por:
  - estilos de Word (`Heading 1` / `Heading 2`, sin confundir `Title`),
  - marcadores de texto (`Capítulo 1`, `Cap. 1`, `Chapter 1`, `Prólogo`…),
  - spine y TOC del EPUB, con Calibre opcional.
- Limpieza de texto para TTS: escenas (`***`, `---`, `…`), diálogo con raya, apertura de `¿`/`¡`, párrafos y símbolos decorativos.
- Salidas:
  - **M4B** con chapter atoms reales (títulos y saltos internos).
  - **MP3 por capítulo**.
  - **MP3 plano** de un libro o de un volumen.
- Portadas JPG/PNG/WebP/GIF convertidas a JPEG para que sean compatibles con MP3 y M4B.
- Reanudación mediante `progress.json` con huella de configuración. Si cambias voz, velocidad, modo o el libro, el progreso se invalida solo.
- Escrituras atómicas (`.part`) y validación estricta: un capítulo incompleto **no** se publica como si estuviera terminado.
- Informe `revisar.txt` con bloques problemáticos y capítulos incompletos.
- GUI de escritorio con Flet y CLI.

## Requisitos

- Windows 10/11 (el proyecto también contiene rutas de ejemplo de Windows; el código evita depender de ellas).
- Python 3.11 de 64 bits.
- **ffmpeg** y **ffprobe** disponibles en el `PATH`.
- Un entorno con **Supertonic** instalado. Por defecto el proyecto busca:

  ```text
  C:\supertonic\venv\Scripts\python.exe
  ```

  Puedes cambiar esa ruta con `config.py` o con la variable de entorno `SUPERTONIC_PY`.

- Para la GUI: `flet` y `tkinter` (tkinter viene con el instalador oficial de Python en Windows).

## Instalación

```powershell
git clone https://github.com/darknappy/superaudio.git
cd superaudio

# Opción A: usar el venv que ya tengas para Supertonic
C:\supertonic\venv\Scripts\python.exe -m pip install -r requirements.txt

# Opción B: crear un venv nuevo
py -3.11 -m venv C:\supertonic\venv
C:\supertonic\venv\Scripts\python.exe -m pip install -r requirements.txt
```

La primera síntesis descarga el modelo de Supertonic si no está en caché. Necesitas conexión a Internet para esa primera descarga y espacio en disco para el modelo.

### ffmpeg

Comprueba que esté disponible:

```powershell
ffmpeg -version
ffprobe -version
```

Si no lo está, instálalo (por ejemplo con `winget install Gyan.FFmpeg` o desde <https://ffmpeg.org/download.html>) y abre una consola nueva para que se actualice el `PATH`.

## Configuración

Toda la configuración habitual está en `config.py`:

```python
BASE_INPUT    = r"C:\libros"
OUTPUT_DIR    = ...          # por defecto, <carpeta padre del repo>\output
SUPERTONIC_PY = r"C:\supertonic\venv\Scripts\python.exe"

VOICE = "M1"                 # F1-F5, M1-M5
SPEED = 1.1
TOTAL_STEPS = 10             # 5 = rápido, 12 = máxima calidad oficial
PARALLEL_WORKERS = 1
```

También puedes configurar las rutas sin editar el archivo:

```powershell
$env:SUPERAUDIO_INPUT  = "D:\MisLibros"
$env:SUPERAUDIO_OUTPUT = "D:\Audiolibros"
$env:SUPERTONIC_PY     = "D:\supertonic\venv\Scripts\python.exe"
```

`REGEX_FIXES` está **vacío por defecto**. Las reglas de pronunciación para honoríficos o términos LitRPG se aplicaban antes a cualquier libro y podían estropear texto normal (`HP`, `INT`, `DEF`…). Descomenta solo las que necesite tu novela.

## Uso por CLI

Desde la carpeta del proyecto:

```powershell
# Un M4B con capítulos internos
python run.py "C:\libros\mi_libro.epub" --voice M2

# Un MP3 por capítulo
python run.py "C:\libros\mi_libro.docx" --chapters --voice F2

# Un M4B por cada 20 capítulos
python run.py "C:\libros\mi_libro.txt" -20 --voice M1

# MP3 plano de todo el libro
python run.py "C:\libros\mi_libro.epub" --mp3

# Prueba rápida: solo los 5 primeros bloques
python run.py "C:\libros\mi_libro.epub" --preview 5

# Rehacer por completo este libro
python run.py "C:\libros\mi_libro.epub" --force
```

También se puede ejecutar como módulo desde la carpeta **padre** del repo:

```powershell
cd C:\superaudio
python -m superaudio "C:\libros\mi_libro.epub" --voice M2
```

`python run.py` detecta el venv de Supertonic y se relanza dentro de él automáticamente.

### Opciones principales

| Opción | Efecto |
| --- | --- |
| `--chapters` | Un MP3 por capítulo. Cada capítulo se cierra en cuanto termina. |
| `-N`, `--chapters-per-file N` | Cierra un M4B/MP3 cada N capítulos (modo volumen). |
| `--mp3` | En modo libro/volumen, genera MP3 plano en vez de M4B. |
| `--preview N` | Genera solo los primeros N bloques y `preview.mp3`. |
| `--voice F1..F5, M1..M5` | Evita el prompt de voz. |
| `--speed X` | Velocidad base, entre `0.5` y `2.0`. |
| `--steps N` | Calidad de síntesis (5 rápida, 12 máxima). |
| `--silence X` | Pausa entre oraciones, en segundos. |
| `--chunk-chars N` | Troceo interno de Supertonic. |
| `--block-chars N` | Tamaño máximo de bloque propio. |
| `--workers N` | Procesos de síntesis en paralelo. |
| `--force` | Borra salidas y progreso de **este** libro y regenera. |

`--help` muestra todas las opciones.

## GUI

```powershell
python gui_app_flet.py
```

La GUI permite elegir libro, voz, modo, calidad, workers, preview y `--force`. Usa el mismo `run.py` que la CLI, así que el comportamiento y la reanudación son idénticos.

- **Detener** mata también los workers hijos en Windows.
- Al cerrar la ventana se intenta detener el proceso de síntesis.
- Si `config.py` no se puede importar, la GUI avisa y usa valores por defecto.

## Salidas

Para un libro llamado `mi_libro`:

```text
output/
└── mi_libro/
    ├── mi_libro.m4b              # modo libro
    ├── 0001 - Capítulo 1.mp3     # modo --chapters
    ├── Volumen 001 (...).m4b     # modo -N
    ├── preview.mp3               # --preview
    ├── progress.json             # reanudación
    ├── revisar.txt               # solo si hay fallos/avisos
    ├── _cover.jpg                # portada extraída del EPUB
    ├── capitulos/                # WAV temporales de capítulo
    └── _tmp/                     # bloques y metadatos temporales
```

Los WAV de capítulo y los temporales se borran cuando el grupo se publica correctamente. Si hay un aviso de calidad, se conservan para que puedas revisarlos.

## Reanudación y fallos

- Vuelve a ejecutar el mismo comando: los capítulos completos se conservan y los incompletos se regeneran.
- Si borras el M4B/MP3 final, el progreso se invalida y se reconstruye de verdad.
- Si cambias voz, velocidad, `--steps`, modo, `--mp3`, la detección de capítulos, las correcciones o el archivo del libro, el progreso se reinicia automáticamente.
- `--force` solo borra lo generado dentro de la carpeta de ese libro.
- `revisar.txt` explica qué bloque o capítulo falló y dónde está el WAV para inspeccionarlo.
- La salida final se escribe primero como `.part` y solo se renombra cuando está completa.

## Detección de capítulos

Para **TXT/DOCX sin estilos**, usa líneas como:

```text
Capítulo 1
Cap. 2
Chapter 3
Prólogo
Epílogo
```

Para **DOCX**, el programa busca `Heading 1` y `Heading 2`. Elige el nivel con más encabezados y excluye el estilo `Title` (que suele ser el título del libro, no un capítulo). Si no hay encabezados, cae a los marcadores de texto.

Para **EPUB**, usa el orden del spine. Si Calibre está instalado, intenta primero la conversión a DOCX para aprovechar los estilos. Los títulos del TOC solo se aplican si el número de entradas coincide exactamente con los capítulos detectados; si no, se usan `Capítulo N` para evitar títulos corridos.

## Notas

- El proyecto está pensado para uso local y para audiolibros personales. Respeta los derechos de autor de los libros que conviertas.
- `SUPERTONIC_PY` y las rutas de `config.py` son específicas de cada equipo. No las publiques si no quieres revelar tu estructura de carpetas; usa las variables de entorno.
- El límite de tamaño de un M4B/MP3 depende del reproductor; para libros muy largos, el modo `-N` o `--chapters` es más cómodo.
- La detección de capítulos es heurística. Revisa `revisar.txt` y el nombre de los archivos antes de distribuir un audiolibro.

## Créditos

- [Supertonic](https://github.com/supertone-inc/supertonic) por el motor TTS.
- [Flet](https://flet.dev/) por la interfaz.
- [FFmpeg](https://ffmpeg.org/) por el ensamblado y la codificación.
- [python-docx](https://python-docx.readthedocs.io/), [EbookLib](https://github.com/aerkalov/ebooklib) y [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) por la lectura de formatos.
