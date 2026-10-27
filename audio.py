"""
audio.py — Ensamblado de audio: silencios, capítulos WAV,
           MP3 individuales y M4B con capítulos internos.
"""
import os
import re
import subprocess
import wave
from collections import deque
from pathlib import Path

from tqdm import tqdm

from . import config as C
from .metadata import escape_ffmetadata

_MIN_AUDIO_BYTES = 1000

# ----------------------------------------------------------
# ffmpeg con barra de progreso real (parsea -progress)
# ----------------------------------------------------------
_TIME_RE = re.compile(r"(\d+):(\d+):(\d+\.\d+)")


def _ffmpeg_error(stderr: str) -> str:
    lines = [ln for ln in (stderr or "").strip().splitlines() if ln.strip()]
    return "\n".join(lines[-10:]) or "(sin detalle de ffmpeg)"


def _run_ffmpeg(cmd: list):
    """Ejecuta ffmpeg capturando stderr para poder mostrar el error real."""
    full_cmd = [cmd[0], "-hide_banner", "-loglevel", "error", *cmd[1:]]
    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo y agrégalo al PATH."
        ) from e

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}):\n{_ffmpeg_error(proc.stderr)}"
        )
    return proc


def _run_ffmpeg_with_progress(cmd: list, total_ms: int, desc: str = "Encoding"):
    """Corre ffmpeg mostrando una barra de progreso real en vez de
    bloquear en silencio hasta terminar. Requiere que `cmd` sea una
    lista ffmpeg completa (el archivo de salida es el último elemento).

    stderr se fusiona con stdout para no bloquear el pipe y para poder
    mostrar el error real si ffmpeg falla.
    """
    base = [cmd[0], "-hide_banner", "-loglevel", "warning", *cmd[1:]]
    cmd_with_progress = base[:-1] + ["-progress", "pipe:1", "-nostats", base[-1]]

    try:
        proc = subprocess.Popen(
            cmd_with_progress,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo y agrégalo al PATH."
        ) from e

    bar = tqdm(total=max(total_ms, 1), desc=desc, unit="ms")
    last = 0
    tail = deque(maxlen=20)

    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("out_time="):
                m = _TIME_RE.search(line)
                if m:
                    h, mi, s = m.groups()
                    ms = int((int(h) * 3600 + int(mi) * 60 + float(s)) * 1000)
                    if ms > last:
                        bar.update(ms - last)
                        last = ms
            elif line.startswith("progress="):
                continue
            elif line.strip():
                tail.append(line)
        proc.wait()
    finally:
        if total_ms > 0 and last < total_ms:
            bar.update(total_ms - last)
        bar.close()

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}) al generar "
            f"'{os.path.basename(cmd[-1])}':\n"
            f"{_ffmpeg_error(chr(10).join(tail))}"
        )


def _temp_path(path: str) -> str:
    """Nombre temporal en la misma carpeta y con la misma extensión."""
    suffix = Path(path).suffix
    return path + ".part" + suffix


def _commit_temp(tmp: str, out: str):
    if not (os.path.exists(tmp) and os.path.getsize(tmp) > _MIN_AUDIO_BYTES):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(
            f"La salida '{os.path.basename(out)}' quedó vacía o incompleta."
        )
    os.replace(tmp, out)


def _concat_line(path: str) -> str:
    """Línea de lista concat segura, incluso con apóstrofos en la ruta.

    ffmpeg usa comillas simples y el escape dentro de ellas es '\\''
    (cerrar comilla, apóstrofo escapado, abrir comilla).
    """
    escaped = str(path).replace("'", r"'\''")
    return f"file '{escaped}'\n"


# ----------------------------------------------------------
# Silencio auxiliar
# ----------------------------------------------------------

def make_silence(path: str, duration_ms: int):
    """Genera un WAV de silencio de `duration_ms` ms.
    No hace nada si el archivo ya existe y es válido."""
    if os.path.exists(path) and os.path.getsize(path) > 44:
        return

    tmp = _temp_path(path)
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{duration_ms / 1000.0:.3f}",
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
            tmp,
        ])
        if not (os.path.exists(tmp) and os.path.getsize(tmp) > 44):
            raise RuntimeError("ffmpeg generó un silencio vacío.")
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------
# Duración de un WAV (usado para timestamps y barras de progreso)
# ----------------------------------------------------------

def _wav_duration_ms(wav_path: str) -> int:
    """Devuelve la duración de un WAV en milisegundos."""
    try:
        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            if rate > 0:
                return int(frames * 1000 / rate)
    except Exception:
        pass

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             wav_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if probe.returncode == 0:
            return int(float(probe.stdout.strip()) * 1000)
    except Exception:
        pass
    return 0


# ----------------------------------------------------------
# Normalización
# ----------------------------------------------------------

def normalize_wav(in_wav: str, out_wav: str):
    """Normaliza el loudness de UN WAV individual (capítulo: minutos,
    no horas). Se usa para evitar aplicar loudnorm sobre el audio del
    libro completo de una sola pasada, que es lento (loudnorm corre
    cerca de tiempo real en ffmpeg)."""
    tmp = _temp_path(out_wav)
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-i", in_wav,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
            tmp,
        ])
        _commit_temp(tmp, out_wav)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------
# WAV de capítulo (concatenación sin codificar)
# ----------------------------------------------------------

def build_chapter_wav(blocks: list, tmp_dir: str,
                      out_wav: str, silence_dir: str) -> bool:
    """Une los WAV de bloques de un capítulo en un único WAV crudo.

    Devuelve False si falta CUALQUIER bloque: es preferible fallar y
    reintentar que publicar un capítulo truncado silenciosamente.
    """
    if not blocks:
        return False

    entries = []
    for i, block in enumerate(blocks):
        wav = os.path.join(tmp_dir, f"{i:05d}.wav")
        if not (os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False
        entries.append(wav)
        pause_ms = int(block.get("pause_after_ms") or 0)
        if pause_ms > 0:
            sil = os.path.join(silence_dir, f"silence_{pause_ms}.wav")
            make_silence(sil, pause_ms)
            entries.append(sil)

    if not entries:
        return False

    list_file = os.path.join(tmp_dir, "list_raw.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(_concat_line(e))

    out_tmp = _temp_path(out_wav)
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", "-f", "wav", out_tmp,
        ])
        _commit_temp(out_tmp, out_wav)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


# ----------------------------------------------------------
# MP3 individual (modo --chapters)
# ----------------------------------------------------------

def _add_cover_args(cmd: list, cover_path: str | None, cover_index: int = 1):
    """Añade la portada convirtiéndola siempre a JPEG.

    Copiar el stream tal cual falla con WebP/GIF dentro de M4B/MP3
    («codec not currently supported in container»). MJPEG sí está
    soportado por ambos contenedores y por los reproductores habituales.

    `cover_index` es el índice de la entrada de la imagen (en M4B la
    entrada 1 es el FFMETADATA y la portada es la 2).
    """
    if cover_path and os.path.exists(cover_path):
        cmd += [
            "-i", cover_path,
            "-map", "0:a", "-map", f"{cover_index}:v",
            "-c:v", "mjpeg", "-q:v", "2", "-pix_fmt", "yuvj420p",
            "-frames:v", "1",
            "-disposition:v", "attached_pic",
        ]
    else:
        cmd += ["-map", "0:a"]


def build_mp3(in_wav: str, out_mp3: str,
              cover_path: str | None = None,
              tags: dict | None = None,
              normalize: bool = True) -> bool:
    """Convierte un WAV de capítulo a MP3 estéreo, con cover art
    incrustado y tags ID3. Muestra barra de progreso."""
    if not (os.path.exists(in_wav) and os.path.getsize(in_wav) > _MIN_AUDIO_BYTES):
        return False

    cmd = ["ffmpeg", "-y", "-i", in_wav]
    _add_cover_args(cmd, cover_path)

    if normalize:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += [
        "-acodec", "libmp3lame",
        "-b:a", getattr(C, "MP3_BITRATE", "192k"),
        "-ac", "2",
        "-id3v2_version", "3",
    ]

    for k, v in (tags or {}).items():
        if v:
            cmd += ["-metadata", f"{k}={v}"]

    out_tmp = _temp_path(out_mp3)
    cmd += ["-f", "mp3", out_tmp]

    total_ms = _wav_duration_ms(in_wav)
    try:
        _run_ffmpeg_with_progress(cmd, total_ms, desc=f"🔊 {os.path.basename(out_mp3)}")
        _commit_temp(out_tmp, out_mp3)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


def build_plain_mp3(chapter_wavs: list[str],
                    out_mp3: str,
                    tmp_dir: str,
                    cover_path: str | None = None,
                    tags: dict | None = None,
                    silence_between_ms: int = None) -> bool:
    """Concatena los WAV de varios capítulos en un único MP3 plano
    'a la antigua' (sin capítulos internos). Más simple y rápido que
    build_m4b: no calcula timestamps ni genera FFMETADATA."""
    if silence_between_ms is None:
        silence_between_ms = C.SILENCE_BETWEEN_CHAPTERS_MS

    if not chapter_wavs:
        return False
    for wav in chapter_wavs:
        if not (wav and os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False

    sil_path = None
    if silence_between_ms > 0:
        sil_path = os.path.join(tmp_dir, f"sil_chap_{silence_between_ms}.wav")
        make_silence(sil_path, silence_between_ms)

    list_file = os.path.join(tmp_dir, "plain_mp3_list.txt")
    total_ms = 0
    with open(list_file, "w", encoding="utf-8") as f:
        for i, wav in enumerate(chapter_wavs):
            total_ms += _wav_duration_ms(wav)
            f.write(_concat_line(wav))
            if sil_path and i < len(chapter_wavs) - 1:
                f.write(_concat_line(sil_path))
                total_ms += silence_between_ms

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file]
    _add_cover_args(cmd, cover_path)
    cmd += [
        "-acodec", "libmp3lame",
        "-b:a", getattr(C, "MP3_BITRATE", "192k"),
        "-ac", "2",
        "-id3v2_version", "3",
    ]

    for k, v in (tags or {}).items():
        if v:
            cmd += ["-metadata", f"{k}={v}"]

    out_tmp = _temp_path(out_mp3)
    cmd += ["-f", "mp3", out_tmp]

    try:
        _run_ffmpeg_with_progress(cmd, total_ms, desc=f"🔊 {os.path.basename(out_mp3)}")
        _commit_temp(out_tmp, out_mp3)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True


# ----------------------------------------------------------
# M4B con capítulos internos (modo book / volume)
# ----------------------------------------------------------

def build_m4b(chapter_wavs: list[str],
              chapter_titles: list[str],
              out_m4b: str,
              tmp_dir: str,
              cover_path: str | None = None,
              tags: dict | None = None,
              silence_between_ms: int = None) -> bool:
    """Ensambla un M4B con chapter atoms internos a partir de una
    lista de WAVs (uno por capítulo). Muestra barra de progreso real
    durante la codificación final (la parte que tarda).

    Flujo:
      1. Calcula los timestamps de cada capítulo midiendo los WAVs.
      2. Genera el archivo FFMETADATA con los [CHAPTER] atoms.
      3. Codifica todo en AAC estéreo con loudnorm ya aplicado por
         capítulo, mostrando progreso en tiempo real.
    """
    if silence_between_ms is None:
        silence_between_ms = C.SILENCE_BETWEEN_CHAPTERS_MS

    if not chapter_wavs or len(chapter_wavs) != len(chapter_titles):
        return False
    for wav in chapter_wavs:
        if not (wav and os.path.exists(wav) and os.path.getsize(wav) > _MIN_AUDIO_BYTES):
            return False

    sil_path = None
    if silence_between_ms > 0:
        sil_path = os.path.join(tmp_dir, f"sil_chap_{silence_between_ms}.wav")
        make_silence(sil_path, silence_between_ms)

    # Calcular timestamps
    chapter_starts: list[int] = []
    current_ms = 0
    list_file  = os.path.join(tmp_dir, "m4b_list.txt")

    with open(list_file, "w", encoding="utf-8") as f:
        for i, wav in enumerate(chapter_wavs):
            dur = _wav_duration_ms(wav)
            if dur <= 0:
                raise RuntimeError(f"No se pudo medir la duración de: {wav}")
            chapter_starts.append(current_ms)
            current_ms += dur
            f.write(_concat_line(wav))
            if sil_path and i < len(chapter_wavs) - 1:
                f.write(_concat_line(sil_path))
                current_ms += silence_between_ms

    # FFMETADATA con chapter atoms
    meta_file = os.path.join(tmp_dir, "m4b_meta.txt")
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(";FFMETADATA1\n")
        for k, v in (tags or {}).items():
            if v:
                f.write(f"{k}={escape_ffmetadata(v)}\n")
        f.write("\n")
        for i, (start_ms, title) in enumerate(zip(chapter_starts, chapter_titles)):
            end_ms = chapter_starts[i + 1] if i + 1 < len(chapter_starts) else current_ms
            f.write("[CHAPTER]\nTIMEBASE=1/1000\n")
            f.write(f"START={start_ms}\nEND={end_ms}\n")
            f.write(f"title={escape_ffmetadata(title)}\n\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-i", meta_file,
    ]
    _add_cover_args(cmd, cover_path, cover_index=2)
    cmd += ["-map_metadata", "1"]

    cmd += [
        "-c:a", "aac",
        "-b:a", getattr(C, "AAC_BITRATE", "192k"),
        "-ac", "2",
        "-movflags", "+faststart",
    ]

    out_tmp = _temp_path(out_m4b)
    cmd += ["-f", "ipod", out_tmp]

    try:
        _run_ffmpeg_with_progress(
            cmd, current_ms,
            desc=f"🔊 Codificando {os.path.basename(out_m4b)}",
        )
        _commit_temp(out_tmp, out_m4b)
    except Exception:
        try:
            if os.path.exists(out_tmp):
                os.remove(out_tmp)
        except OSError:
            pass
        raise
    return True
