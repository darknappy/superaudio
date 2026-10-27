"""
pipeline.py — Orquesta la síntesis y el ensamblado de audio.

Modos de salida:
  MODE_BOOK   (default) → 1 M4B con capítulos internos
  MODE_SPLIT  --chapters → 1 MP3 por capítulo
  MODE_VOLUME -N         → 1 M4B por cada N capítulos
"""
import multiprocessing
import os
import shutil
import time
from pathlib import Path

from tqdm import tqdm

from . import config as C
from . import progress as P
from .audio      import build_chapter_wav, build_m4b, build_mp3, build_plain_mp3, normalize_wav
from .metadata   import book_tags, find_cover, extract_epub_metadata, sanitize_filename
from .readers    import load_book
from .synthesis  import init_worker, synthesize_job
from .text       import build_blocks

# ----------------------------------------------------------
# Constantes de modo
# ----------------------------------------------------------
MODE_BOOK   = "book"
MODE_SPLIT  = "split"
MODE_VOLUME = "volume"

_MIN_AUDIO_BYTES = 1000


# ----------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------

def _file_ok(path: str) -> bool:
    try:
        return bool(path) and os.path.exists(path) and os.path.getsize(path) > _MIN_AUDIO_BYTES
    except OSError:
        return False


def _make_groups(n_chapters: int, chapters_per_volume: int) -> list[list[int]]:
    if chapters_per_volume > 0:
        return [list(range(i, min(i + chapters_per_volume, n_chapters)))
                for i in range(0, n_chapters, chapters_per_volume)]
    return [list(range(n_chapters))]


def _clean_generated_outputs(out_dir: str):
    """Borra solo lo que genera Superaudio dentro de la carpeta del libro."""
    for entry in os.listdir(out_dir):
        path = os.path.join(out_dir, entry)
        lower = entry.lower()
        if entry in ("capitulos", "_tmp") and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif entry in ("progress.json", "progress.json.tmp", "revisar.txt",
                       "preview.mp3") or lower.startswith("_cover."):
            try:
                os.remove(path)
            except OSError:
                pass
        elif lower.endswith((".m4b", ".mp3", ".part.m4b", ".part.mp3")):
            try:
                os.remove(path)
            except OSError:
                pass


def _write_review_log(path: str, book_name: str,
                      anomalies: dict, chapter_errors: dict,
                      jobs_by_id: dict, jobs_by_id_chap: dict,
                      titles: list):
    """Escribe un informe útil o elimina el informe viejo si no hay nada."""
    if not anomalies and not chapter_errors:
        try:
            os.remove(path)
        except OSError:
            pass
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write("Superaudio — revisión de audio\n")
        f.write(f"Libro: {book_name}\n")
        f.write(f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        if chapter_errors:
            f.write("CAPÍTULOS INCOMPLETOS\n")
            f.write("---------------------\n")
            for c, reason in sorted(chapter_errors.items()):
                title = titles[c] if 0 <= c < len(titles) else f"Capítulo {c + 1}"
                f.write(f"- Capítulo {c + 1}: {title}\n")
                f.write(f"  Motivo: {reason}\n")
            f.write("\n")

        if anomalies:
            f.write("BLOQUES CON AVISOS DE CALIDAD\n")
            f.write("-----------------------------\n")
            for jid, reason in sorted(anomalies.items()):
                job = jobs_by_id.get(jid)
                c = jobs_by_id_chap.get(jid)
                title = ""
                if c is not None and 0 <= c < len(titles):
                    title = titles[c]
                if job:
                    f.write(f"- Capítulo {c + 1 if c is not None else '?'}: {title}\n")
                    f.write(f"  Archivo: {job['wav_path']}\n")
                else:
                    f.write(f"- Job {jid}\n")
                f.write(f"  Motivo:  {reason}\n")
                if job:
                    f.write(f"  Texto:   {job['text'][:120]}...\n")
                f.write("\n")

        f.write("Para reintentar: ejecuta de nuevo el mismo comando. Los capítulos\n")
        f.write("completos se conservan y los incompletos se regeneran.\n")
        f.write("Para rehacer todo: usa --force.\n")


# ----------------------------------------------------------
# Pipeline principal
# ----------------------------------------------------------

def run(file_path: str,
        preview_blocks: int = 0,
        mode: str = MODE_BOOK,
        chapters_per_volume: int = 0,
        mp3_only: bool = False,
        force: bool = False) -> bool:
    """Genera el audiolibro. Devuelve True solo si TODAS las salidas
    esperadas existen y son válidas."""

    if not os.path.exists(file_path):
        print(f"❌ Archivo no encontrado: {file_path}")
        return False

    name    = Path(file_path).stem
    out_dir = os.path.join(C.OUTPUT_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    if force:
        print("🧹 --force: borrando resultados anteriores de este libro …")
        _clean_generated_outputs(out_dir)

    chapters_dir = os.path.join(out_dir, "capitulos")
    os.makedirs(chapters_dir, exist_ok=True)

    tmp_root = os.path.join(out_dir, "_tmp")
    os.makedirs(tmp_root, exist_ok=True)

    review_log = os.path.join(out_dir, "revisar.txt")

    print(f"\n📚 Libro: {name}")

    # --- Metadata y cover ---
    epub_meta  = extract_epub_metadata(file_path) if file_path.lower().endswith(".epub") else {}
    album      = epub_meta.get("title") or name
    cover_path = find_cover(file_path, out_dir)
    base_tags  = book_tags(album, epub_meta.get("artist", ""), epub_meta.get("date", ""))

    if cover_path:
        print(f"🖼  Cover: {Path(cover_path).name}")
    else:
        print("ℹ  Sin cover art (coloca una imagen .jpg/.png con el mismo nombre del archivo).")

    # --- Cargar libro ---
    try:
        chapters, chapter_titles = load_book(file_path)
    except Exception as e:
        print(f"❌ No se pudo leer el libro: {e}")
        return False

    if not chapters:
        print("❌ No se encontró texto.")
        return False

    n = len(chapters)
    print(f"📖 Capítulos: {n}")

    chapters_blocks = [build_blocks(paragraphs) for paragraphs in chapters]

    # ----------------------------------------------------------
    # MODO PREVIEW
    # ----------------------------------------------------------
    if preview_blocks > 0:
        print(f"🔍 Preview: generando los primeros {preview_blocks} bloques …")
        blocks = chapters_blocks[0][:preview_blocks]
        if not blocks:
            print("❌ El primer capítulo no tiene bloques para previsualizar.")
            return False

        tmp_prev = os.path.join(tmp_root, "preview")
        shutil.rmtree(tmp_prev, ignore_errors=True)
        os.makedirs(tmp_prev, exist_ok=True)

        try:
            init_worker(C.INTRA_OP_THREADS, C.INTER_OP_THREADS, C.VOICE,
                        C.TOTAL_STEPS, C.MAX_CHUNK_LENGTH, C.LANG)
            for i, block in enumerate(tqdm(blocks, desc="🎙 Chunks (preview)")):
                preset = C.STYLE_PRESETS.get(block["style"], C.STYLE_PRESETS["narracion"])
                _, ok, reason = synthesize_job({
                    "id": i,
                    "wav_path": os.path.join(tmp_prev, f"{i:05d}.wav"),
                    "text":    block["text"],
                    "speed":   preset["speed"],
                    "silence": preset["silence_duration"],
                })
                if not ok:
                    print(f"❌ Preview: falló el bloque {i + 1}: {reason or 'error desconocido'}")
                    return False

            prev_wav = os.path.join(tmp_prev, "preview.wav")
            if not build_chapter_wav(blocks, tmp_prev, prev_wav, tmp_root):
                print("❌ Preview: faltan bloques de audio.")
                return False

            out_prev = os.path.join(out_dir, "preview.mp3")
            build_mp3(prev_wav, out_prev, cover_path,
                      {**base_tags, "title": f"{name} – Preview"})
        except Exception as e:
            print(f"❌ Preview: {e}")
            return False

        if not _file_ok(out_prev):
            print("❌ Preview: no se generó el MP3.")
            return False
        print(f"✅ Preview: {out_prev}")
        return True

    # ----------------------------------------------------------
    # Agrupar capítulos en lotes.
    # En BOOK siempre es 1 solo grupo. En SPLIT cada capítulo se
    # finaliza de inmediato (no se acumulan WAVs de todo el libro).
    # ----------------------------------------------------------
    cpv = chapters_per_volume or C.CHAPTERS_PER_VOLUME

    if mode == MODE_SPLIT:
        groups         = [[c] for c in range(n)]
        effective_cpv  = 0
    else:
        effective_cpv  = cpv if mode == MODE_VOLUME else 0
        groups         = _make_groups(n, effective_cpv)

    chapter_to_grp = {c: g for g, grp in enumerate(groups) for c in grp}

    # ----------------------------------------------------------
    # Progreso persistente (JSON). La huella incluye TODO lo que
    # cambia el audio; si cambia, el progreso viejo se descarta.
    # ----------------------------------------------------------
    fp_params = {
        "version":      2,
        "voice":        C.VOICE,
        "lang":         C.LANG,
        "speed":        C.SPEED,
        "steps":        C.TOTAL_STEPS,
        "chunk":        C.MAX_CHUNK_LENGTH,
        "sentence_sil": C.SILENCE_BETWEEN_SENTENCES,
        "block":        C.BLOCK_MAX_CHARS,
        "mode":         mode,
        "cpv":          effective_cpv,
        "mp3_only":     mp3_only,
        "calibre":      C.USE_CALIBRE_FOR_EPUB,
        "regex":        repr(C.REGEX_FIXES),
        "pron":         repr(C.PRONUNCIATION_FIXES),
        "marker":       C.CHAPTER_MARKER_REGEX.pattern,
    }
    prog = P.load(out_dir)
    fp = P.fingerprint(file_path, fp_params)
    if prog.get("fingerprint") != fp:
        if prog.get("done_chapters"):
            print("⚠ La configuración o el libro cambió: se reinicia el progreso.")
        prog = {"done_chapters": [], "fingerprint": fp}
        P.save(out_dir, prog)

    # ----------------------------------------------------------
    # Nombres de salida
    # ----------------------------------------------------------
    def _split_output(c_idx: int) -> str:
        title = sanitize_filename(chapter_titles[c_idx])
        return os.path.join(out_dir, f"{c_idx + 1:04d} - {title}.mp3")

    def _split_tags(c_idx: int) -> dict:
        return {
            **base_tags,
            "title":      chapter_titles[c_idx],
            "track":      str(c_idx + 1),
            "tracktotal": str(n),
        }

    def _group_output(g_idx: int):
        grp = groups[g_idx]
        if mode == MODE_VOLUME:
            fname = sanitize_filename(
                f"Volumen {g_idx + 1:03d} (Cap.{grp[0] + 1:03d}-{grp[-1] + 1:03d})"
            )
            tags = {**base_tags, "title": f"{album} – Vol.{g_idx + 1}"}
        else:
            fname = sanitize_filename(name)
            tags = {**base_tags, "title": album}

        ext = "mp3" if mp3_only else "m4b"
        return os.path.join(out_dir, f"{fname}.{ext}"), tags

    # ----------------------------------------------------------
    # Validar que los capítulos marcados como hechos tengan salida.
    # Si alguien borró el M4B/MP3, hay que regenerarlo de verdad.
    # ----------------------------------------------------------
    done_before = set(prog.get("done_chapters", []))
    valid_done: set[int] = set()

    if mode == MODE_SPLIT:
        for c in done_before:
            if 0 <= c < n and _file_ok(_split_output(c)):
                valid_done.add(c)
    else:
        for g, grp in enumerate(groups):
            out_file, _ = _group_output(g)
            if _file_ok(out_file) and all(c in done_before for c in grp):
                valid_done.update(grp)

    if valid_done != done_before:
        lost = len(done_before - valid_done)
        if lost:
            print(f"⚠ {lost} capítulo(s) marcados como hechos no tienen una salida válida; se regenerarán.")
        prog["done_chapters"] = sorted(valid_done)
        P.save(out_dir, prog)

    # Grupos ya terminados y con salida válida.
    group_done = [False] * len(groups)
    if mode != MODE_SPLIT:
        for g, grp in enumerate(groups):
            out_file, _ = _group_output(g)
            if _file_ok(out_file) and all(P.is_chapter_done(prog, c) for c in grp):
                group_done[g] = True

    # ----------------------------------------------------------
    # Construir jobs (saltar capítulos ya generados)
    # ----------------------------------------------------------
    jobs             : list[dict] = []
    job_id           = 0
    chapter_tmp_dirs : dict[int, str] = {}
    jobs_by_id_chap  : dict[int, int] = {}   # job_id → c_idx
    jobs_by_chapter  : dict[int, list] = {}   # c_idx  → [job_ids]

    for c_idx, blocks in enumerate(chapters_blocks):
        if P.is_chapter_done(prog, c_idx):
            continue

        chap_wav = os.path.join(chapters_dir, f"{c_idx:04d}.wav")
        if _file_ok(chap_wav) or not blocks:
            continue

        tmp = os.path.join(tmp_root, f"cap_{c_idx:04d}")
        os.makedirs(tmp, exist_ok=True)
        chapter_tmp_dirs[c_idx] = tmp

        for b_idx, block in enumerate(blocks):
            preset = C.STYLE_PRESETS.get(block["style"], C.STYLE_PRESETS["narracion"])
            jobs.append({"id":       job_id,
                         "wav_path": os.path.join(tmp, f"{b_idx:05d}.wav"),
                         "text":     block["text"],
                         "speed":    preset["speed"],
                         "silence":  preset["silence_duration"]})
            jobs_by_id_chap[job_id] = c_idx
            jobs_by_chapter.setdefault(c_idx, []).append(job_id)
            job_id += 1

    print(f"⏳ Bloques a generar: {len(jobs)}  (workers: {C.PARALLEL_WORKERS})")

    # ----------------------------------------------------------
    # Contadores y callbacks de cierre incremental
    # ----------------------------------------------------------
    blocks_per_chap      = [len(b) for b in chapters_blocks]
    done_blocks_per_chap = [0] * n
    done_chaps_per_grp   = [0] * len(groups)
    anomalies            : dict[int, str] = {}
    chapter_errors       : dict[int, str] = {}
    failed_chapters      : set[int] = set()
    finalized_chapters   : set[int] = set()

    def _chap_wav(c_idx: int) -> str:
        return os.path.join(chapters_dir, f"{c_idx:04d}.wav")

    def _cleanup_chapter(c_idx: int, keep_wav: bool = False):
        if not keep_wav:
            try:
                os.remove(_chap_wav(c_idx))
            except OSError:
                pass
        tmp = chapter_tmp_dirs.pop(c_idx, None)
        if tmp and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)

    def _chapter_has_anomaly(c_idx: int) -> bool:
        return any(jid in anomalies for jid in jobs_by_chapter.get(c_idx, []))

    def _finalize_group(g_idx: int) -> bool:
        if group_done[g_idx]:
            return True

        grp = groups[g_idx]
        audio_chapters = [c for c in grp if chapters_blocks[c]]
        wavs   = [_chap_wav(c) for c in audio_chapters]
        titles = [chapter_titles[c] for c in audio_chapters]

        missing = [c for c, w in zip(audio_chapters, wavs) if not _file_ok(w)]
        if missing:
            for c in missing:
                failed_chapters.add(c)
                chapter_errors.setdefault(
                    c, "no se encontró el WAV del capítulo al ensamblar"
                )
            print(f"❌ No se puede cerrar el lote: faltan {len(missing)} WAV(s) de capítulo.")
            return False

        out_file, tags = _group_output(g_idx)

        if not audio_chapters:
            # Un grupo sin audio (caso muy raro): no hay archivo que crear.
            P.mark_chapters_done(out_dir, prog, grp)
            group_done[g_idx] = True
            print("ℹ  El lote no contiene audio; se marca como vacío.")
            return True

        try:
            if mp3_only:
                ok = build_plain_mp3(wavs, out_file, tmp_root, cover_path, tags)
            else:
                ok = build_m4b(wavs, titles, out_file, tmp_root, cover_path, tags)
            if not ok or not _file_ok(out_file):
                raise RuntimeError("no se generó el archivo final")
        except Exception as e:
            for c in audio_chapters:
                failed_chapters.add(c)
                chapter_errors.setdefault(c, f"falló el ensamblado final: {e}")
            print(f"❌ No se pudo generar {Path(out_file).name}: {e}")
            return False

        try:
            P.mark_chapters_done(out_dir, prog, grp)
        except Exception as e:
            print(f"⚠ No se pudo guardar progress.json: {e}")
            return False

        print(f"\n✅ {Path(out_file).name}")
        group_done[g_idx] = True
        finalized_chapters.update(grp)

        # Limpiar WAVs de capítulo del grupo, salvo los que tengan avisos.
        for c in grp:
            _cleanup_chapter(c, keep_wav=_chapter_has_anomaly(c))
        return True

    def _finalize_chapter(c_idx: int) -> bool:
        if c_idx in finalized_chapters:
            return True
        if c_idx in failed_chapters:
            return False

        chap_wav = _chap_wav(c_idx)
        blocks   = chapters_blocks[c_idx]

        if not _file_ok(chap_wav):
            if not blocks:
                # Capítulo vacío: no hay audio, pero no bloquea el grupo.
                finalized_chapters.add(c_idx)
                if mode == MODE_SPLIT:
                    P.mark_chapters_done(out_dir, prog, [c_idx])
                    return True
                g = chapter_to_grp[c_idx]
                done_chaps_per_grp[g] += 1
                if done_chaps_per_grp[g] >= len(groups[g]):
                    return _finalize_group(g)
                return True

            tmp = chapter_tmp_dirs.get(c_idx)
            if not tmp:
                tmp = os.path.join(tmp_root, f"cap_{c_idx:04d}")
                os.makedirs(tmp, exist_ok=True)
                chapter_tmp_dirs[c_idx] = tmp

            try:
                ok = build_chapter_wav(blocks, tmp, chap_wav, tmp_root)
                err = "" if ok else "faltan bloques de audio"
            except Exception as e:
                ok = False
                err = str(e)

            if not ok:
                failed_chapters.add(c_idx)
                chapter_errors[c_idx] = f"no se pudo unir el capítulo: {err}"
                print(f"❌ Capítulo {c_idx + 1} ({chapter_titles[c_idx]}): {chapter_errors[c_idx]}")
                return False

            # Normalizar por capítulo (no sobre el libro completo).
            try:
                norm_tmp = chap_wav + ".norm.wav"
                normalize_wav(chap_wav, norm_tmp)
                if os.path.exists(norm_tmp):
                    os.replace(norm_tmp, chap_wav)
            except Exception as e:
                print(f"⚠  No se pudo normalizar cap {c_idx + 1}: {e} (se usa sin normalizar)")

        # ---- SPLIT: un MP3 por capítulo, se cierra enseguida ----
        if mode == MODE_SPLIT:
            out_mp3 = _split_output(c_idx)
            try:
                if not _file_ok(out_mp3):
                    build_mp3(chap_wav, out_mp3, cover_path,
                              _split_tags(c_idx), normalize=False)
                if not _file_ok(out_mp3):
                    raise RuntimeError("no se generó el MP3")
            except Exception as e:
                failed_chapters.add(c_idx)
                chapter_errors[c_idx] = f"no se pudo generar el MP3: {e}"
                print(f"❌ Capítulo {c_idx + 1} ({chapter_titles[c_idx]}): {chapter_errors[c_idx]}")
                return False

            P.mark_chapters_done(out_dir, prog, [c_idx])
            print(f"  ✅ {Path(out_mp3).name}")
            finalized_chapters.add(c_idx)
            _cleanup_chapter(c_idx, keep_wav=_chapter_has_anomaly(c_idx))
            return True

        # ---- BOOK/VOLUME: esperar a que todo el grupo esté listo ----
        finalized_chapters.add(c_idx)
        g = chapter_to_grp[c_idx]
        done_chaps_per_grp[g] += 1
        if done_chaps_per_grp[g] >= len(groups[g]):
            return _finalize_group(g)
        return True

    # Capítulos sin bloques, ya sintetizados o con WAV existente.
    for c_idx in range(n):
        if c_idx in chapter_tmp_dirs:
            continue

        if mode == MODE_SPLIT:
            if P.is_chapter_done(prog, c_idx) and _file_ok(_split_output(c_idx)):
                continue
            _finalize_chapter(c_idx)
        else:
            g = chapter_to_grp[c_idx]
            if group_done[g]:
                continue
            if P.is_chapter_done(prog, c_idx):
                continue
            _finalize_chapter(c_idx)

    # ----------------------------------------------------------
    # Síntesis
    # ----------------------------------------------------------
    def _handle(result):
        jid, ok, reason = result
        c = jobs_by_id_chap[jid]
        done_blocks_per_chap[c] += 1

        if not ok:
            anomalies[jid] = reason or "fallo desconocido"
            failed_chapters.add(c)
        elif reason:
            anomalies[jid] = reason

        if done_blocks_per_chap[c] >= blocks_per_chap[c]:
            if c in failed_chapters:
                if c not in chapter_errors:
                    chapter_errors[c] = "falló al menos un bloque de síntesis"
                    print(f"❌ Capítulo {c + 1} ({chapter_titles[c]}): "
                          f"falló la síntesis; se reintentará en la próxima ejecución.")
            else:
                _finalize_chapter(c)

    synthesis_error = None
    try:
        if C.PARALLEL_WORKERS > 1 and len(jobs) > 1:
            tpw = max(1, C.INTRA_OP_THREADS // C.PARALLEL_WORKERS)
            with multiprocessing.Pool(
                processes  = C.PARALLEL_WORKERS,
                initializer= init_worker,
                initargs   = (tpw, C.INTER_OP_THREADS, C.VOICE,
                              C.TOTAL_STEPS, C.MAX_CHUNK_LENGTH, C.LANG),
            ) as pool:
                for res in tqdm(pool.imap_unordered(synthesize_job, jobs),
                                total=len(jobs), desc="🎙 Chunks"):
                    _handle(res)
        elif jobs:
            init_worker(C.INTRA_OP_THREADS, C.INTER_OP_THREADS, C.VOICE,
                        C.TOTAL_STEPS, C.MAX_CHUNK_LENGTH, C.LANG)
            for job in tqdm(jobs, desc="🎙 Chunks"):
                try:
                    res = synthesize_job(job)
                except Exception as e:
                    res = (job["id"], False, f"excepción en el worker: {e}")
                _handle(res)
    except Exception as e:
        synthesis_error = str(e)
        print(f"❌ La síntesis se interrumpió: {e}")

    # ----------------------------------------------------------
    # Log de anomalías
    # ----------------------------------------------------------
    jobs_by_id = {j["id"]: j for j in jobs}

    # Capítulos que quedaron sin terminar por un fallo o por una
    # interrupción del pool también deben aparecer en el informe.
    # Los que sí se ensamblaron pero esperan el cierre del grupo no
    # son "incompletos"; el problema está en el grupo.
    for c in range(n):
        if not P.is_chapter_done(prog, c) and c not in finalized_chapters:
            chapter_errors.setdefault(c, "el capítulo no se completó")
    for c in failed_chapters:
        chapter_errors.setdefault(c, "el capítulo no se completó")

    _write_review_log(review_log, name, anomalies, chapter_errors,
                      jobs_by_id, jobs_by_id_chap, chapter_titles)

    # ----------------------------------------------------------
    # Estado final: solo hay éxito si TODAS las salidas esperadas
    # existen. Un returncode 0 no basta.
    # ----------------------------------------------------------
    if mode == MODE_SPLIT:
        all_done = all(P.is_chapter_done(prog, c) for c in range(n))
        outputs_ok = all(
            (not chapters_blocks[c]) or _file_ok(_split_output(c))
            for c in range(n)
        )
        all_done = all_done and outputs_ok
        outputs = [_split_output(c) for c in range(n)
                   if chapters_blocks[c] and _file_ok(_split_output(c))]
    else:
        all_done = all(P.is_chapter_done(prog, c) for c in range(n))
        outputs_ok = all(
            group_done[g] and _file_ok(_group_output(g)[0])
            for g in range(len(groups))
        )
        all_done = all_done and outputs_ok
        outputs = [_group_output(g)[0] for g in range(len(groups))
                   if group_done[g] and _file_ok(_group_output(g)[0])]

    completed = sum(1 for c in range(n) if P.is_chapter_done(prog, c))

    if all_done and not failed_chapters and not synthesis_error:
        print("\n✅ Libro terminado.")
        for p in outputs:
            print(f"   {p}")
        if anomalies:
            print(f"⚠  Hay avisos de calidad; revisa: {review_log}")
        return True

    print(f"\n❌ Libro incompleto: {completed} de {n} capítulos listos.")
    if failed_chapters:
        failed_titles = ", ".join(
            f"{c + 1}" for c in sorted(failed_chapters)
        )
        print(f"   Capítulos con fallos: {failed_titles}")
    if os.path.exists(review_log):
        print(f"⚠  Revisar: {review_log}")
    return False
