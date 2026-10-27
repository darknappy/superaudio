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
- **Modelo fijado a `supertonic-3`** para que una actualización del motor no cambie la voz sin avisar.
- **Normalización española**: abreviaturas (`Dr.`, `Sra.`, `etc.`), números, fechas, horas, porcentajes, moneda y unidades. Se puede desactivar.
- **Prosodia por bloques**: los turnos de diálogo y los pensamientos se sintetizan por separado; la narración se agrupa y las frases largas se parten sin perder puntuación.
- **Pausas por estilo** (narración, diálogo, pensamiento) y micro-fades para evitar clics en las uniones.
- **Tags de expresión** de Supertonic 3: `[ríe]`, `[suspira]` y `[respira]` se convierten en `<laugh>`, `<sigh>` y `<breath>`. Solo se permiten esos tags.
- **Calidad de audio**: loudness a **-18 LUFS** con `loudnorm` en dos pasadas, recorte suave de silencios y fades de 8 ms por bloque.
- **Audición comparativa de voces** con el mismo texto (`--audition`), con WAV por voz, índice y MP3 combinado.
- **Banco de pruebas de prosodia** (`--benchmark`) con narración, diálogo, preguntas, exclamaciones, abreviaturas, números y frase larga.
- **Diccionario de pronunciación por libro** mediante un JSON junto al archivo del libro.
- Salidas:
  - **M4B** con chapter atoms reales (títulos y saltos internos).
  - **MP3 por capítulo**.
  - **MP3 plano** de un libro o de un volumen.
- Portadas JPG/PNG/WebP/GIF convertidas a JPEG para que sean compatibles con MP3 y M4B.
- Reanudación mediante `progress.json` con huella de configuración. Si cambias voz, modelo, velocidad, prosodia, normalización, audio o el libro, el progreso se invalida solo.
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
- La normalización de números usa `num2words` (incluido en `requirements.txt`). Si no está instalado, los números se dejan tal cual.

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

TTS_MODEL = "supertonic-3"   # modelo fijado
VOICE = "M1"                 # F1-F5, M1-M5
SPEED = 1.05                 # velocidad base
TOTAL_STEPS = 10             # 5 = rápido, 12 = máxima calidad oficial
MAX_CHUNK_LENGTH = 300

# Normalización y expresividad
ENABLE_SPANISH_ABBREVIATIONS = True
ENABLE_NUMBER_NORMALIZATION = True
ENABLE_EXPRESSION_CUES = True

# Prosodia
BLOCK_MAX_CHARS = 1200
SENTENCE_MAX_CHARS = 220
SPLIT_DIALOGUE_BLOCKS = True
SPLIT_THOUGHT_BLOCKS = True
STYLE_PAUSES_MS = {
    "narracion": 500,
    "dialogo": 400,
    "pensamiento": 650,
}

# Audio final
LOUDNORM_TARGET_I = -18.0    # LUFS
LOUDNORM_TARGET_TP = -3.0    # dBTP
LOUDNORM_TWO_PASS = True
EDGE_FADE_MS = 8
TRIM_TTS_EDGES = True

PARALLEL_WORKERS = 1
```

También puedes configurar las rutas sin editar el archivo:

```powershell
$env:SUPERAUDIO_INPUT  = "D:\MisLibros"
$env:SUPERAUDIO_OUTPUT = "D:\Audiolibros"
$env:SUPERTONIC_PY     = "D:\supertonic\venv\Scripts\python.exe"
$env:SUPERTONIC_MODEL  = "supertonic-3"
```

`REGEX_FIXES` está **vacío por defecto**. Las reglas de pronunciación para honoríficos o términos LitRPG se aplicaban antes a cualquier libro y podían estropear texto normal (`HP`, `INT`, `DEF`…). Descomenta solo las que necesite tu novela.

### Pronunciación por libro

Si un libro tiene nombres propios o términos que Supertonic pronuncia mal, crea un JSON junto al libro:

```text
C:\libros\mi_libro.epub
C:\libros\mi_libro.pronunciation.json
```

```json
{
  "Nyx": "Nics",
  "Shirayuki": "Shira-yuki",
  "Aether": "Éter"
}
```

También se acepta el sufijo `.pron.json`. Las claves se sustituyen como palabras completas: `Nyx` no modifica `Nyxes`. El archivo entra en la huella de progreso, así que editarlo invalida la reanudación.

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

### Audición de voces

No hace falta un libro. Genera el mismo texto con las diez voces (o con las que indiques):

```powershell
python run.py --audition
python run.py --audition --audition-voices F1,F2,M1
python run.py --audition --audition-voices M1 --speed 1.0 --steps 12
python run.py --audition --audition-text "Texto breve para comparar."
```

La salida por defecto es `output/_audiciones`:

- `F1.wav`…`M5.wav`: una muestra por voz.
- `audicion_voces.mp3`: comparación seguida, con pausas.
- `audicion.txt`: texto, configuración y duración de cada muestra.

Escucha primero la misma frase en varias voces y elige la que menos te fatigue en una sesión larga. La velocidad y los `steps` deben compararse con el mismo texto.

### Banco de pruebas de prosodia

```powershell
python run.py --benchmark --voice M1
python run.py --benchmark --voice F2 --benchmark-out D:\pruebas
```

Genera ocho casos (narración, diálogo, pregunta, exclamación, pausas, abreviaturas, números y frase larga) y un `informe.txt` con duración, caracteres por segundo, peak, RMS, porcentaje de silencio y clipping. Las métricas detectan problemas objetivos; la naturalidad y la fatiga se valoran escuchando.

### Opciones principales

| Opción | Efecto |
| --- | --- |
| `--chapters` | Un MP3 por capítulo. Cada capítulo se cierra en cuanto termina. |
| `-N`, `--chapters-per-file N` | Cierra un M4B/MP3 cada N capítulos (modo volumen). |
| `--mp3` | En modo libro/volumen, genera MP3 plano en vez de M4B. |
| `--preview N` | Genera solo los primeros N bloques y `preview.mp3`. |
| `--voice F1..F5, M1..M5` | Evita el prompt de voz. |
| `--model NOMBRE` | Modelo Supertonic; por defecto `supertonic-3`. |
| `--speed X` | Velocidad base, entre `0.5` y `2.0`. |
| `--steps N` | Calidad de síntesis (1–12; 5 rápida, 12 máxima). |
| `--silence X` | Pausa interna entre oraciones, en segundos. |
| `--chunk-chars N` | Troceo interno de Supertonic. |
| `--block-chars N` | Tamaño máximo de bloque propio. |
| `--workers N` | Procesos de síntesis en paralelo. |
| `--no-numbers` | No convierte números/fechas/unidades a palabras. |
| `--no-expressions` | No convierte `[ríe]`, `[suspira]`… en tags. |
| `--audition` | Audición de voces; no requiere libro. |
| `--audition-voices F1,M1` | Voces concretas para la audición. |
| `--audition-out RUTA` | Carpeta de salida de la audición. |
| `--audition-text TEXTO` | Texto alternativo para la audición. |
| `--benchmark` | Banco de pruebas de prosodia; no requiere libro. |
| `--benchmark-out RUTA` | Carpeta del banco de pruebas. |
| `--force` | Borra salidas y progreso de **este** libro y regenera. |

`--help` muestra todas las opciones.

## GUI

```powershell
python gui_app_flet.py
```

La GUI permite elegir libro, voz, modo, calidad, workers, preview y `--force`. Usa el mismo `run.py` que la CLI, así que el comportamiento y la reanudación son idénticos.

- **Probar voces** ejecuta `--audition` y abre la carpeta de muestras.
- **Detener** mata también los workers hijos en Windows.
- Al cerrar la ventana se intenta detener el proceso de síntesis.
- Si `config.py` no se puede importar, la GUI avisa y usa valores por defecto.

## Salidas

Para un libro llamado `mi_libro`:

```text
output/
├── _audiciones/                  # --audition (WAV + MP3 + índice)
├── _benchmark/                   # --benchmark (casos + informe)
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

## Calidad de voz y prosodia

La mejora de naturalidad no depende de una sola palanca:

- **Modelo fijado**: `supertonic-3` evita cambios silenciosos de voz.
- **Velocidad**: `SPEED=1.05` es un punto de partida conservador. Para audiolibros largos suele funcionar mejor que `1.1`; si quieres más calma, prueba `1.0`.
- **Steps**: `TOTAL_STEPS=10` mantiene un buen equilibrio. Subir a `12` puede mejorar detalles, pero tarda más.
- **Diálogo y pensamientos**: se separan para que el modelo no lea un turno de diálogo como continuación de la narración. Las pausas se ajustan en `STYLE_PAUSES_MS`.
- **Frases largas**: se parten por puntuación antes de llegar al motor; así se evita que una oración enorme pierda la entonación final.
- **Tags de expresión**: usa `[ríe]`, `[suspira]` o `[respira]` con moderación. El texto entre corchetes que no sea una indicación conocida se conserva; los tags HTML/SSML desconocidos se eliminan.
- **Normalización**: `--no-numbers` es útil para libros con códigos, identificadores o cifras que deben leerse dígito a dígito. Los títulos de capítulo conservan su número para los metadatos.
- **Audio**: loudnorm en dos pasadas a `-18 LUFS`, true peak `-3 dBTP`, recorte de silencios y fades de 8 ms. Son valores pensados para audiolibro; si publicas en una plataforma con otra norma, ajusta `LOUDNORM_TARGET_I` y `LOUDNORM_TARGET_TP`.

## Pruebas

```powershell
C:\supertonic\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas cubren normalización, abreviaturas, tags, segmentación, pausas, pronunciación por libro, pulido de WAV, loudnorm, métricas y los comandos de audición/benchmark sin cargar el modelo real. Las pruebas de regresión del pipeline y lectores se pueden ejecutar por separado.

## Reanudación y fallos

- Vuelve a ejecutar el mismo comando: los capítulos completos se conservan y los incompletos se regeneran.
- Si borras el M4B/MP3 final, el progreso se invalida y se reconstruye de verdad.
- Si cambias voz, modelo, velocidad, `--steps`, modo, `--mp3`, prosodia, normalización, loudnorm, el diccionario de pronunciación, la detección de capítulos, las correcciones o el archivo del libro, el progreso se reinicia automáticamente.
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
- Los artefactos `Superaudio.exe`, `superaudio.rar`, `dist/`, `build/` y las salidas de audio están ignorados por `.gitignore`.

## Créditos

- [Supertonic](https://github.com/supertone-inc/supertonic) por el motor TTS.
- [Flet](https://flet.dev/) por la interfaz.
- [FFmpeg](https://ffmpeg.org/) por el ensamblado y la codificación.
- [python-docx](https://python-docx.readthedocs.io/), [EbookLib](https://github.com/aerkalov/ebooklib) y [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) por la lectura de formatos.
- [num2words](https://github.com/savoirfairelinux/num2words) por la conversión de números a palabras.
