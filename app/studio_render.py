"""Safe, isolated finishing preview/export workers. No expensive AI analysis.

Exports are never written to the source job's /output and never modify its
plan, completion status or registered output files.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import logging
import threading
import traceback
import uuid
import time
import re
import shutil
import hashlib
from pathlib import Path

from app import config
from app.json_store import atomic_json, read_json
from app.media import inspect_media, render_part, choose_encoder
from app.clean_parts import prepare_clean_part, CLEAN_VERSION
from app.music import list_tracks, pick_track_for_part, music_library_identity
from app.content_identity import digest

_RENDER_SEMAPHORE = threading.Semaphore(1)
# A restarted process cannot have any of the old threads. Persisted queued /
# running exports must become interrupted, not remain spinning forever.
_TASKS_LOCK = threading.Lock()
_ACTIVE_TASKS: set[str] = set()
_ACTIVE_THREADS = {}
_ACTIVE_CANCEL = {}
_ACTIVE_OWNERS = {}
# One FFmpeg worker is allowed to render at a time. Keep no more than two
# additional waiting requests; unlimited daemon threads exhaust local memory.
MAX_PENDING_FINISHING_TASKS = 3


@contextmanager
def _render_slot(cancelled):
    while True:
        if cancelled():
            raise InterruptedError("Экспорт прерван при закрытии приложения")
        if _RENDER_SEMAPHORE.acquire(timeout=0.2):
            break
    try:
        yield
    finally:
        _RENDER_SEMAPHORE.release()


def stop_finishing_tasks(manager, timeout=12.0):
    """Cancel own queued/running renders; never join under manager.mutex."""
    import time
    with _TASKS_LOCK:
        targets = [(thread, _ACTIVE_CANCEL[key]) for key, thread in list(_ACTIVE_THREADS.items())
                   if _ACTIVE_OWNERS.get(key) is manager]
    for _, flag in targets:
        flag.set()
    deadline = time.monotonic() + max(0.0, timeout)
    for thread, _ in targets:
        if thread is not threading.current_thread():
            thread.join(timeout=max(0, deadline - time.monotonic()))
    return all(not thread.is_alive() for thread, _ in targets)


def slice_part(part: dict, start: float, duration: float) -> dict:
    """Convert source-clock cuts to a bounded output-clock preview."""
    requested_end = start + duration
    offset = 0.0
    cuts = []
    for original in part["cuts"]:
        length = float(original["end"]) - float(original["start"])
        a = max(start, offset)
        b = min(requested_end, offset + length)
        if b > a + 0.00001:
            cut = copy.deepcopy(original)
            cut["start"] = round(float(original["start"]) + (a - offset), 6)
            cut["end"] = round(float(original["start"]) + (b - offset), 6)
            # Focus coordinates use source time. Remove outdated anchors, while
            # preserving the last known composition at the new cut entrance.
            focus = original.get("focus", [])
            prior = [f for f in focus if f.get("time", 0) <= cut["start"]]
            inside = [f for f in focus if cut["start"] < f.get("time", 0) < cut["end"]]
            cut["focus"] = ([
                {**prior[-1], "time": cut["start"]}] if prior else []
            ) + inside
            cuts.append(cut)
        offset += length
    if not cuts:
        raise ValueError("Нет исходных кадров в выбранном интервале")
    result = copy.deepcopy(part)
    result["cuts"] = cuts
    result["duration"] = round(sum(c["end"] - c["start"] for c in cuts), 6)
    result["subtitles"] = [
        {"start": round(max(0, c["start"] - start), 6),
         "end": round(min(result["duration"], c["end"] - start), 6),
         "text": c["text"]}
        for c in part.get("subtitles", [])
        if c["start"] < requested_end and c["end"] > start
    ]
    return result


def _source(request_manager, job_id: str) -> Path:
    info = read_json(request_manager.job_dir(job_id) / "source.json", {}) or {}
    path = Path(info.get("path", "")).resolve()
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError("Исходная серия недоступна")
    if not path.is_relative_to(request_manager.root.resolve()):
        raise ValueError("Исходная серия должна находиться внутри рабочего каталога")
    return path


def _probe(source: Path, work: Path) -> dict:
    raw = inspect_media(source, work)
    video = next((v for v in raw.get("streams", []) if v.get("codec_type") == "video"), None)
    audios = [a for a in raw.get("streams", []) if a.get("codec_type") == "audio"]
    if video is None or not audios:
        raise ValueError("У исходной серии нет видео или аудио")
    # The initial ASR/montage selects the Russian-labelled audio stream.
    # Re-export MUST use the same stream; otherwise subtitles and original
    # dialogue can end up in different languages.
    ordinal = 0
    if len(audios) > 1:
        russian = [i for i, audio in enumerate(audios)
                   if str(audio.get("tags", {}).get("language", "")).lower() in ("ru", "rus")
                   or any(marker in str(audio.get("tags", {}).get("title", "")).lower()
                          for marker in ("рус", "russian"))]
        if not russian:
            raise ValueError("Несколько аудиодорожек без обозначения русской")
        ordinal = russian[0]
    return {"width": int(video["width"]), "height": int(video["height"]),
            "audio_stream": ordinal}


def _effective_part(manager, job_id: str, part: dict, profile: dict) -> dict:
    result = copy.deepcopy(part)
    index = result["index"]
    stored = read_json(manager.job_dir(job_id) / "finishing" / ("captions_%03d.json" % index))
    # Speech belongs to this *job*. Episode-wide legacy part_overrides.cues
    # are not attributable to any particular completed montage and must never
    # overwrite the text or timing of a different attempt.
    if stored is not None:
        result["subtitles"] = stored.get("cues", result.get("subtitles", []))
    result["layout"] = profile["video"]["layout"]
    return result


def _music(profile: dict, index: int, total: int, part: dict) -> dict | None:
    audio = profile["audio"]
    if not audio["enabled"]:
        return None
    # A missing explicitly selected track must not silently turn into an
    # unrelated random soundtrack. Explicit "none" still means no music.
    chosen = (audio.get("part_tracks", {}).get(str(index))
              if audio.get("mode") == "per_part" else audio.get("track")
              if audio.get("mode") == "single" else None)
    if chosen and chosen not in {"none", "__none__", "off", "без музыки",
                                 "random", "__random__", "случайный"}:
        if not any(path.name == chosen for path in list_tracks(config.MUSIC)):
            raise FileNotFoundError("Выбранный музыкальный трек больше недоступен")
    track = pick_track_for_part(config.MUSIC, audio, index, total)
    if not track:
        return None
    return {
        "path": track, "volume": audio["volume"],
        "fade_in": audio["fade_in"] > 0, "fade_out": audio["fade_out"] > 0,
        "fade_in_seconds": audio["fade_in"], "fade_out_seconds": audio["fade_out"],
        "duck_intervals": [(c["start"], c["end"]) for c in part.get("subtitles", [])]
        if audio.get("ducking") else [],
        "volume_music_duck": min(audio["volume"], 0.02),
    }


def render_finishing_part(manager, job_id: str, original: dict, profile: dict,
                          output: Path, work: Path, preview: tuple[float, float] | None = None,
                          cancelled=lambda: False, *, resolved: bool = False,
                          encoder=None, on_progress=None) -> Path:
    source = _source(manager, job_id)
    part = copy.deepcopy(original) if resolved else _effective_part(manager, job_id, original, profile)
    visual_style = dict(profile["subtitles"])
    override = profile.get("part_overrides", {}).get(str(original["index"]), {})
    visual_style.update(override.get("style") or {})
    total = 100
    work.mkdir(parents=True, exist_ok=True)
    if cancelled():
        raise InterruptedError("Экспорт прерван при закрытии приложения")
    probed = _probe(source, work)
    if on_progress:
        on_progress('preparing_clean', 0)
    source, part, probed, _ = prepare_clean_part(source, part, probed, manager.job_dir(job_id),
        cancelled, create=preview is None,
        on_progress=(lambda fraction: on_progress('preparing_clean', fraction)) if on_progress else None)
    if preview:
        part = slice_part(part, *preview)
    music = _music(profile, part['index'], total, part)
    from .finishing_avatar import resolve_avatar
    avatar = resolve_avatar(manager.root, profile['video'])
    encoder = encoder or choose_encoder(work, cancelled)
    if on_progress:
        on_progress('rendering', 0)
    return render_part(source, part, probed, output, work, encoder,
                       cancelled=cancelled, background_music=music,
                       finishing={"subtitles": visual_style, "video": profile["video"], 'avatar_path': avatar},
                       on_progress=(lambda fraction: on_progress('rendering', fraction)) if on_progress else None)


def presentation_digest(source, part, profile, music_identity):
    """Per-part visual/audio identity; other parts and editor revisions do not count."""
    style = {**profile['subtitles'], **(profile.get('part_overrides', {}).get(str(part['index']), {}).get('style') or {})}
    style.pop('safe_guides', None)
    stat = source.stat()
    music = _music(profile, part['index'], 100, part)
    if music:
        music = {**music, 'path': next((m for m in music_identity if m['name'] == music['path'].name), None)}
    return digest({'version': 1, 'clean_version': CLEAN_VERSION, 'source': str(source.resolve()),
        'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'part': part,
        'video': profile['video'], 'subtitles': style, 'music': music})


def _file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _presentation_intact(ready, signature):
    if (not ready or ready.get('render_digest') != signature
            or not ready.get('subtitle_url') or not ready.get('video_sha256') or not ready.get('srt_sha256')):
        return False
    try:
        return (_file_digest(ready['_path']) == ready['video_sha256']
                and _file_digest(ready['_path'].with_suffix('.srt')) == ready['srt_sha256'])
    except OSError:
        return False


def _save_render_error(target: Path):
    """Keep detailed FFmpeg/IO failure context *locally*, never in API output.

    Existing HTTP errors are deliberately generic to avoid leaking absolute
    paths or secrets. The local log is not part of the public status payload.
    """
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / "render-error.log").write_text(
            traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass


def run_export(manager, job_id: str, part_indices: list[int], profile: dict, target: Path,
               status_file: Path, preview: tuple[int, float, float] | None = None,
               cancelled=lambda: False, *, plan_snapshot: dict | None = None):
    def update(**values):
        with _TASKS_LOCK:
            state = read_json(status_file, {}) or {}
            state.update(values)
            atomic_json(status_file, state)
    try:
        with _render_slot(cancelled):
            update(status="running", progress=0.01)
            logging.getLogger("app.studio_render").info(
                "Finishing started", extra={"job_id": job_id, "action": "finishing_start",
                                         "status": "running"})
            plan = plan_snapshot if plan_snapshot is not None else read_json(manager.job_dir(job_id) / "plan.json")
            if not isinstance(plan, dict):
                raise ValueError("Монтажный план недоступен")
            parts = {p["index"]: p for p in plan.get("parts", [])}
            if any(i not in parts for i in part_indices):
                raise ValueError("Некорректные номера частей")
            files = []
            latest = {} if preview else ready_outputs(manager, job_id)
            music_identity = music_library_identity(config.MUSIC) if profile['audio']['enabled'] else []
            source = _source(manager, job_id)
            encoder = None
            for k, index in enumerate(part_indices):
                if cancelled():
                    raise InterruptedError("Экспорт прерван при закрытии приложения")
                part = parts[index] if plan_snapshot is not None else _effective_part(manager, job_id, parts[index], profile)
                span = (preview[1], preview[2]) if preview else None
                signature = presentation_digest(source, part, profile, music_identity)
                ready = latest.get(f'part_{index:03}.mp4')
                if _presentation_intact(ready, signature):
                    output = target / 'output'
                    output.mkdir(parents=True, exist_ok=True)
                    for suffix in ('.mp4', '.srt', '.ass'):
                        old = ready['_path'].with_suffix(suffix)
                        if old.is_file():
                            shutil.copy2(old, output / old.name)
                    files.append({'part_index': index, 'name': ready['name'], 'duration': part['duration'],
                                  'render_digest': signature, 'video_sha256': ready['video_sha256'],
                                  'srt_sha256': ready['srt_sha256'], 'reused': True})
                    update(progress=round((k + 1) / len(part_indices), 4), completed_parts=k + 1,
                           phase='reusing', part_index=index)
                    continue
                if encoder is None:
                    encoder = choose_encoder(target / 'encoder', cancelled)
                last_update = 0
                def progress(phase, fraction):
                    nonlocal last_update
                    now = time.monotonic()
                    if fraction and now - last_update < .5:
                        return
                    last_update = now
                    update(phase=phase, part_index=index, completed_parts=k, total_parts=len(part_indices),
                           progress=round(min(.999, (k + (.15 * fraction if phase == 'preparing_clean'
                                      else .15 + .85 * fraction)) / len(part_indices)), 4))
                rendered = render_finishing_part(manager, job_id, part, profile,
                                                 target / "output", target / f"work_{index}", span,
                                                 cancelled=cancelled, resolved=plan_snapshot is not None,
                                                 encoder=encoder, on_progress=progress)
                files.append({"part_index": index, "name": rendered.name,
                              "duration": float(span[1] if span else part["duration"]),
                              'render_digest': signature, 'reused': False,
                              'video_sha256': _file_digest(rendered),
                              'srt_sha256': _file_digest(rendered.with_suffix('.srt'))
                                  if rendered.with_suffix('.srt').is_file() else None})
                update(progress=round((k + 1) / len(part_indices), 4), completed_parts=k + 1)
                logging.getLogger("app.studio_render").info(
                    "Finishing part rendered: %s", index,
                    extra={"job_id": job_id, "stage": "finishing", "action": "finishing_part",
                           "progress": round((k + 1) / len(part_indices), 4)})
            if cancelled():
                raise InterruptedError("Экспорт прерван при закрытии приложения")
            update(status="completed", progress=1.0, files=files,
                   phase='completed', completed_parts=len(part_indices), total_parts=len(part_indices),
                   message="Части пересобраны" if not preview else "Предпросмотр готов")
    except InterruptedError:
        logging.getLogger("app.studio_render").warning("Finishing interrupted",
            extra={"job_id": job_id, "action": "finishing_interrupted", "status": "interrupted"})
        update(status="interrupted", error="Экспорт прерван при закрытии приложения")
    except FileNotFoundError:
        logging.getLogger("app.studio_render").exception("Finishing music file missing",
            extra={"job_id": job_id, "action": "finishing_failed", "status": "failed"})
        _save_render_error(target)
        update(status="failed", progress=0.0,
               error="Выбранный музыкальный файл не найден. Выберите другой трек.")
    except Exception:
        logging.getLogger("app.studio_render").exception(
            "Finishing render failed",
            extra={"job_id": job_id, "action": "finishing_failed", "status": "failed",
                   "detail_log": str(target.relative_to(config.ROOT)) if target.is_relative_to(config.ROOT) else "job/finishing"})
        _save_render_error(target)
        # Do not expose FFmpeg stderr containing absolute private filesystem paths.
        update(status="failed", progress=0.0, error="Не удалось создать видео. Подробности в локальном render-error.log.")


def _registered_export(identifier: str, manager, job_id: str, part_indices: list[int],
                       profile: dict, target: Path, status_file: Path,
                       preview: tuple[int, float, float] | None,
                       stop_flag: threading.Event, plan_snapshot: dict):
    try:
        run_export(manager, job_id, part_indices, profile, target, status_file, preview,
                   cancelled=stop_flag.is_set, plan_snapshot=plan_snapshot)
    finally:
        # The job's source, plan and output must not be removed while a
        # preview/export is still using them.
        with manager.mutex:
            remaining = manager.finishing_tasks.get(job_id, 0) - 1
            if remaining > 0:
                manager.finishing_tasks[job_id] = remaining
            else:
                manager.finishing_tasks.pop(job_id, None)
        with _TASKS_LOCK:
            _ACTIVE_TASKS.discard(identifier)
            _ACTIVE_THREADS.pop(identifier, None)
            _ACTIVE_CANCEL.pop(identifier, None)
            _ACTIVE_OWNERS.pop(identifier, None)


def submit_render(manager, job_id: str, part_indices: list[int], profile: dict,
                  *, preview: tuple[int, float, float] | None = None) -> dict:
    # All submissions to the current manager are serialized. The global task
    # lock ensures even two managers in one process respect the same queue cap.
    # Keep lock ordering consistent with _registered_export: manager, then tasks.
    with manager.mutex:
        if manager.closed or manager.shutdown_requested:
            raise RuntimeError("Приложение завершает работу")
        if manager.busy():
            raise RuntimeError("Нельзя запускать повторный экспорт во время обработки серии")
        with _TASKS_LOCK:
            if len(_ACTIVE_TASKS) >= MAX_PENDING_FINISHING_TASKS:
                raise RuntimeError("Очередь экспорта заполнена. Дождитесь завершения текущих задач")
            plan = read_json(manager.job_dir(job_id) / 'plan.json')
            if not isinstance(plan, dict):
                raise ValueError('Монтажный план недоступен')
            profile = copy.deepcopy(profile)
            part_indices = list(part_indices)
            wanted = set(part_indices)
            selected = [p for p in plan.get('parts', []) if p['index'] in wanted]
            if len(selected) != len(wanted):
                raise ValueError('Некорректные номера частей')
            # Caption writes share this mutex. Capture text before queuing.
            snapshot = copy.deepcopy(plan)
            snapshot['parts'] = [_effective_part(manager, job_id, part, profile) for part in selected]
            revisions = {str(part['index']): (read_json(manager.job_dir(job_id) / 'finishing' /
                f"captions_{part['index']:03d}.json", {}) or {}).get('revision', 0) for part in selected}
            identifier = ("pv_" if preview else "ex_") + uuid.uuid4().hex
            base = (manager.job_dir(job_id) / "finishing" /
                    ("previews" if preview else "exports") / identifier)
            status_file = base / "status.json"
            status = {
                ("preview_id" if preview else "export_id"): identifier,
                "source_job_id": job_id, "status": "queued", "progress": 0.0,
                "error": None, "files": [],
                'phase': 'queued', 'completed_parts': 0, 'total_parts': len(part_indices),
                'created_at_ns': time.time_ns(), 'source_plan_digest': plan_digest(plan),
                'caption_revisions': revisions,
                'profile': copy.deepcopy(profile),
            }
            registry = (None if preview else
                        manager.root / "finishing" / "exports-index" / (identifier + ".json"))
            # Do not register or create any files when the queue is full.
            try:
                atomic_json(status_file, status)
                if registry is not None:
                    atomic_json(registry, {"source_job_id": job_id})
            except Exception:
                if registry is not None:
                    registry.unlink(missing_ok=True)
                status_file.unlink(missing_ok=True)
                raise
            stop_flag = threading.Event()
            worker = threading.Thread(target=_registered_export,
                                      args=(identifier, manager, job_id, part_indices, profile,
                                            base, status_file, preview, stop_flag, snapshot),
                                      daemon=True, name="finishing-" + identifier)
            manager.finishing_tasks[job_id] = manager.finishing_tasks.get(job_id, 0) + 1
            _ACTIVE_TASKS.add(identifier)
            _ACTIVE_THREADS[identifier] = worker
            _ACTIVE_CANCEL[identifier] = stop_flag
            _ACTIVE_OWNERS[identifier] = manager
            try:
                worker.start()
            except BaseException:
                remaining = manager.finishing_tasks[job_id] - 1
                if remaining:
                    manager.finishing_tasks[job_id] = remaining
                else:
                    manager.finishing_tasks.pop(job_id, None)
                _ACTIVE_TASKS.discard(identifier)
                _ACTIVE_THREADS.pop(identifier, None)
                _ACTIVE_CANCEL.pop(identifier, None)
                _ACTIVE_OWNERS.pop(identifier, None)
                atomic_json(status_file, {**status, "status": "failed",
                                          "error": "Не удалось запустить поток экспорта"})
                raise
            return status


def _locate_task(manager, identifier: str, job_id: str | None = None):
    if identifier.startswith("pv_"):
        if not job_id:
            raise ValueError("Для предпросмотра нужен ID задания")
        base = manager.job_dir(job_id) / "finishing" / "previews" / identifier
    else:
        record = read_json(manager.root / "finishing" / "exports-index" / (identifier + ".json"))
        if not record:
            raise KeyError(identifier)
        job_id = record["source_job_id"]
        base = manager.job_dir(job_id) / "finishing" / "exports" / identifier
    return job_id, base


def plan_digest(plan):
    return digest({'source': plan.get('source'), 'parts': [
        {k: part.get(k) for k in ('index', 'duration', 'cuts', 'subtitles')}
        for part in plan.get('parts', [])]})


def ready_outputs(manager, job_id: str, plan: dict | None = None) -> dict:
    """Latest completed owned finishing file per part; base exports stay intact."""
    folder = (manager.job_dir(job_id) / 'finishing' / 'exports').resolve()
    if not folder.is_relative_to(manager.job_dir(job_id).resolve()) or not folder.is_dir():
        return {}
    plan = plan if plan is not None else read_json(manager.job_dir(job_id) / 'plan.json', {})
    signature = plan_digest(plan)
    parts = {p['index']: p for p in plan.get('parts', [])}
    results, ranks = {}, {}
    for status_path in folder.glob('ex_*/status.json'):
        identifier = status_path.parent.name
        if not re.fullmatch(r'ex_[0-9a-f]{32}', identifier):
            continue
        try:
            if not status_path.resolve().is_relative_to(folder):
                continue
            registry_path = manager.root / 'finishing' / 'exports-index' / (identifier + '.json')
            if not registry_path.resolve().is_relative_to(manager.root.resolve()):
                continue
            registry = read_json(registry_path, {})
            state = read_json(status_path, {})
            if not isinstance(registry, dict) or not isinstance(state, dict):
                raise ValueError('Invalid finishing record')
            if (registry.get('source_job_id') != job_id or state.get('status') != 'completed'
                    or state.get('source_job_id') != job_id or state.get('source_plan_digest') != signature):
                continue
            rank = state.get('created_at_ns', status_path.stat().st_mtime_ns)
            if type(rank) is not int or rank < 0 or not isinstance(state.get('files'), list):
                raise ValueError('Invalid finishing file list or rank')
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).warning('Skipping invalid finishing export %s', identifier,
                extra={'job_id': job_id, 'action': 'invalid_finishing_record'})
            continue
        for item in state.get('files', []):
            if not isinstance(item, dict):
                continue
            index = item.get('part_index')
            if type(index) is not int or index not in parts or item.get('name') != f'part_{index:03}.mp4':
                continue
            name = item['name']
            output = (status_path.parent / 'output').resolve()
            path = (output / name).resolve()
            try:
                if (not path.is_relative_to(output) or not output.is_relative_to(folder)
                        or not path.is_file() or path.stat().st_size == 0 or rank <= ranks.get(name, -1)):
                    continue
                subtitle = path.with_suffix('.srt')
                has_subtitle = subtitle.resolve().is_relative_to(output) and subtitle.is_file()
            except OSError:
                continue
            ranks[name] = rank
            results[name] = {**item, 'export_id': identifier,
                'url': f'/api/exports/{identifier}/files/{name}',
                'subtitle_url': f'/api/exports/{identifier}/files/{Path(name).stem}.srt'
                    if has_subtitle else None,
                '_path': path}
    return results


def task_status(manager, identifier: str, job_id: str | None = None) -> dict:
    job_id, base = _locate_task(manager, identifier, job_id)
    with _TASKS_LOCK:
        status = read_json(base / "status.json")
    if not status:
        raise KeyError(identifier)
    if status.get("status") in {"queued", "running"}:
        with _TASKS_LOCK:
            alive = identifier in _ACTIVE_TASKS
            if not alive:
                # A worker can finish and leave _ACTIVE_TASKS between our
                # initial read and this lock. Re-read before declaring a
                # completed preview/export to be interrupted.
                latest = read_json(base / "status.json") or status
                if latest.get("status") in {"queued", "running"}:
                    latest = {**latest, "status": "interrupted",
                              "error": "Монтажёр был перезапущен во время экспорта. Запустите новый экспорт."}
                    atomic_json(base / "status.json", latest)
                status = latest
    files = [
        {"part_index": item["part_index"], "name": item["name"],
         "duration": item["duration"],
         "url": (f"/api/jobs/{job_id}/previews/{identifier}.mp4" if identifier.startswith("pv_")
                 else f"/api/exports/{identifier}/files/{item['name']}"),
         "subtitle_url": None if identifier.startswith("pv_")
                 else f"/api/exports/{identifier}/files/{Path(item['name']).stem}.srt"}
        for item in status.get("files", [])
    ]
    return {**status, "files": files,
            "url": files[0]["url"] if files and identifier.startswith("pv_") else None}
