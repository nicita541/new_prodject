"""Safe, isolated finishing preview/export workers. No expensive AI analysis.

Exports are never written to the source job's /output and never modify its
plan, completion status or registered output files.
"""
from __future__ import annotations

import copy
import json
import math
import threading
import uuid
from pathlib import Path

from app import config
from app.jobs import atomic_json, read_json
from app.media import inspect_media, render_part
from app.music import pick_track_for_part

_RENDER_SEMAPHORE = threading.Semaphore(1)
# A restarted process cannot have any of the old threads. Persisted queued /
# running exports must become interrupted, not remain spinning forever.
_TASKS_LOCK = threading.Lock()
_ACTIVE_TASKS: set[str] = set()



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
    overrides = profile.get("part_overrides", {}).get(str(index), {})
    cues = overrides.get("cues")
    if cues is None and stored is not None:
        cues = stored.get("cues")
    if cues is not None:
        result["subtitles"] = cues
    result["layout"] = profile["video"]["layout"]
    return result


def _music(profile: dict, index: int, total: int, part: dict) -> dict | None:
    audio = profile["audio"]
    if not audio["enabled"]:
        return None
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
                          output: Path, work: Path, preview: tuple[float, float] | None = None) -> Path:
    source = _source(manager, job_id)
    part = _effective_part(manager, job_id, original, profile)
    if preview:
        part = slice_part(part, *preview)
    visual_style = dict(profile["subtitles"])
    override = profile.get("part_overrides", {}).get(str(original["index"]), {})
    visual_style.update(override.get("style") or {})
    total = 100
    music = _music(profile, part["index"], total, part)
    work.mkdir(parents=True, exist_ok=True)
    probed = _probe(source, work)
    return render_part(source, part, probed, output, work, "libx264",
                       background_music=music,
                       finishing={"subtitles": visual_style, "video": profile["video"]})


def run_export(manager, job_id: str, part_indices: list[int], profile: dict, target: Path,
               status_file: Path, preview: tuple[int, float, float] | None = None):
    def update(**values):
        state = read_json(status_file, {}) or {}
        state.update(values)
        atomic_json(status_file, state)
    try:
        with _RENDER_SEMAPHORE:
            update(status="running", progress=0.01)
            plan = read_json(manager.job_dir(job_id) / "plan.json")
            if not isinstance(plan, dict):
                raise ValueError("Монтажный план недоступен")
            parts = {p["index"]: p for p in plan.get("parts", [])}
            if any(i not in parts for i in part_indices):
                raise ValueError("Некорректные номера частей")
            files = []
            for k, index in enumerate(part_indices):
                part = parts[index]
                span = (preview[1], preview[2]) if preview else None
                rendered = render_finishing_part(manager, job_id, part, profile,
                                                 target / "output", target / f"work_{index}", span)
                files.append({"part_index": index, "name": rendered.name,
                              "duration": float(span[1] if span else part["duration"])})
                update(progress=round((k + 1) / len(part_indices), 4))
            update(status="completed", progress=1.0, files=files,
                   message="Части пересобраны" if not preview else "Предпросмотр готов")
    except Exception:
        # Do not expose FFmpeg stderr containing absolute private filesystem paths.
        update(status="failed", progress=0.0, error="Не удалось создать видео. Проверьте локальный журнал рендера.")


def _registered_export(identifier: str, manager, job_id: str, part_indices: list[int],
                       profile: dict, target: Path, status_file: Path,
                       preview: tuple[int, float, float] | None):
    try:
        run_export(manager, job_id, part_indices, profile, target, status_file, preview)
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


def submit_render(manager, job_id: str, part_indices: list[int], profile: dict,
                  *, preview: tuple[int, float, float] | None = None) -> dict:
    if manager.busy():
        raise RuntimeError("Нельзя запускать повторный экспорт во время обработки серии")
    if preview:
        identifier = "pv_" + uuid.uuid4().hex
        base = manager.job_dir(job_id) / "finishing" / "previews" / identifier
    else:
        identifier = "ex_" + uuid.uuid4().hex
        base = manager.job_dir(job_id) / "finishing" / "exports" / identifier
        registry = manager.root / "finishing" / "exports-index" / (identifier + ".json")
        atomic_json(registry, {"source_job_id": job_id})
    status_file = base / "status.json"
    status = {
        ("preview_id" if preview else "export_id"): identifier,
        "source_job_id": job_id, "status": "queued", "progress": 0.0,
        "error": None, "files": [],
    }
    atomic_json(status_file, status)
    worker = threading.Thread(target=_registered_export,
                              args=(identifier, manager, job_id, part_indices, profile,
                                    base, status_file, preview),
                              daemon=True, name="finishing-" + identifier)
    with manager.mutex:
        manager.finishing_tasks[job_id] = manager.finishing_tasks.get(job_id, 0) + 1
        with _TASKS_LOCK:
            _ACTIVE_TASKS.add(identifier)
        try:
            worker.start()
        except BaseException:
            remaining = manager.finishing_tasks[job_id] - 1
            if remaining:
                manager.finishing_tasks[job_id] = remaining
            else:
                manager.finishing_tasks.pop(job_id, None)
            with _TASKS_LOCK:
                _ACTIVE_TASKS.discard(identifier)
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


def task_status(manager, identifier: str, job_id: str | None = None) -> dict:
    job_id, base = _locate_task(manager, identifier, job_id)
    status = read_json(base / "status.json")
    if not status:
        raise KeyError(identifier)
    if status.get("status") in {"queued", "running"}:
        with _TASKS_LOCK:
            alive = identifier in _ACTIVE_TASKS
        if not alive:
            status = {**status, "status": "interrupted",
                      "error": "Монтажёр был перезапущен во время экспорта. Запустите новый экспорт."}
            atomic_json(base / "status.json", status)
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
