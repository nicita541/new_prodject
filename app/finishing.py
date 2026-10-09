"""Studio Edition finishing state: versioned profiles and non-destructive caption overrides.

All paths are rooted in the JobManager workspace so tests and second worktrees
cannot mutate the user's primary app. Never edit original plan.json/exports.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import config
from app.jobs import atomic_json, read_json, validate_id

COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class VideoFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: Literal["portrait", "cinema"] = "portrait"
    zoom: int = Field(100, ge=90, le=160)
    blur: int = Field(24, ge=0, le=45)
    brightness: int = Field(100, ge=60, le=140)
    vignette: int = Field(15, ge=0, le=60)


class SubtitleFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    text: str = Field("", max_length=180)
    x: float = Field(50, ge=0, le=100)
    y: float = Field(74, ge=0, le=100)
    font_size: int = Field(32, ge=18, le=54)
    color: str = Field("#f6d779", pattern=COLOR_PATTERN)
    outline: int = Field(3, ge=0, le=6)
    background: bool = False
    align: Literal["left", "center", "right"] = "center"
    uppercase: bool = True
    safe_guides: bool = True


class AudioFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    volume: float = Field(0.15, ge=0, le=1)
    track: str | None = Field(None, max_length=255)
    mode: Literal["single", "random_per_part", "per_part"] = "random_per_part"
    fade_in: float = Field(0.8, ge=0, le=5)
    fade_out: float = Field(1.3, ge=0, le=5)
    ducking: bool = False
    part_tracks: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("track")
    @classmethod
    def valid_track(cls, value: str | None):
        if value is not None and ("/" in value or "\\" in value or "\x00" in value or value in {".", ".."}):
            raise ValueError("Недопустимое имя музыкального файла")
        return value

    @field_validator("part_tracks")
    @classmethod
    def valid_part_tracks(cls, value: dict[str, str | None]):
        if len(value) > 100 or any(not k.isdigit() or int(k) < 1 or int(k) > 100 for k in value):
            raise ValueError("Недопустимые номера частей")
        for track in value.values():
            cls.valid_track(track)
        return value


class Cue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(max_length=180)

    @model_validator(mode="after")
    def valid_span(self):
        if self.start >= self.end:
            raise ValueError("Конец реплики должен быть позже начала")
        return self


class PartOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: SubtitleFinish | None = None
    cues: list[Cue] | None = Field(None, max_length=150)


class FinishProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    video: VideoFinish = Field(default_factory=VideoFinish)
    subtitles: SubtitleFinish = Field(default_factory=SubtitleFinish)
    audio: AudioFinish = Field(default_factory=AudioFinish)
    part_overrides: dict[str, PartOverride] = Field(default_factory=dict)

    @field_validator("part_overrides")
    @classmethod
    def valid_overrides(cls, value: dict[str, PartOverride]):
        if len(value) > 100 or any(not k.isdigit() or not 1 <= int(k) <= 100 for k in value):
            raise ValueError("Недопустимый номер части")
        return value


class FinishProfileUpdate(FinishProfile):
    # Optimistic concurrency. Kept optional for older clients until their
    # explicit revision-less saves are migrated.
    revision: int | None = Field(None, ge=0)


class CaptionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_index: int = Field(ge=1, le=100)
    cues: list[Cue] = Field(max_length=150)
    revision: int | None = Field(None, ge=0)



class FinishingSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: FinishProfileUpdate
    captions: list[CaptionsUpdate] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_parts(self):
        indices = [item.part_index for item in self.captions]
        if len(indices) != len(set(indices)):
            raise ValueError("Одна часть не может быть передана дважды")
        return self


class PreviewSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    part_index: int = Field(ge=1, le=100)
    from_seconds: float = Field(0, ge=0, alias="from", allow_inf_nan=False)
    duration: float = Field(5, gt=0, le=10, allow_inf_nan=False)
    settings: FinishProfile | None = None


class ExportSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_indices: list[int] = Field(min_length=1, max_length=50)
    settings: FinishProfile | None = None

    @field_validator("part_indices")
    @classmethod
    def valid_indices(cls, values):
        if len(set(values)) != len(values) or any(not 1 <= v <= 100 for v in values):
            raise ValueError("Выберите уникальные номера частей от 1 до 100")
        return values


def _checked_render_job(request: Request, job_id: str):
    job, plan = _job_plan(request, job_id)
    # Older jobs are linked by Library._migrate() without rewriting job.json.
    # A completed legacy montage is still a valid editing target.
    library = request.app.state.library
    episode_id = job.get("episode_id") or library.data.get("legacy_jobs", {}).get(job_id)
    if not episode_id:
        raise HTTPException(400, "Для этого монтажа не найдена серия с настройками оформления")
    _episode(request, episode_id)
    return job, plan, episode_id


def _manager(request: Request):
    return request.app.state.manager


def _episode(request: Request, identifier: str):
    validate_id(identifier)
    with _manager(request).mutex:
        episode = request.app.state.library._episode(identifier)
        return dict(episode)


def _job_plan(request: Request, job_id: str, *, require_completed: bool = True):
    current = _manager(request)
    job = current.get(job_id)
    if require_completed and job["status"] != "completed":
        raise HTTPException(409, "Дождитесь окончания монтажа")
    plan = read_json(current.job_dir(job_id) / "plan.json")
    if not isinstance(plan, dict) or not isinstance(plan.get("parts"), list):
        raise HTTPException(404, "Монтажный план не найден")
    return job, plan


def _part(plan: dict, index: int):
    part = next((p for p in plan["parts"] if p.get("index") == index), None)
    if not part:
        raise HTTPException(404, "Часть не найдена")
    return part


def _profile_file(request: Request, identifier: str) -> Path:
    return _manager(request).root / "finishing" / "episodes" / (identifier + ".json")


def _caption_file(request: Request, job_id: str, part_index: int) -> Path:
    return _manager(request).job_dir(job_id) / "finishing" / ("captions_%03d.json" % part_index)


def _validate_cues(cues: list[Cue], duration: float) -> None:
    previous_end = 0.0
    for cue in cues:
        if cue.end > duration + 0.001 or cue.start < previous_end - 0.001:
            raise HTTPException(422, "Реплики пересекаются или выходят за пределы части")
        previous_end = cue.end


def _stored_profile(request: Request, identifier: str) -> dict:
    saved = read_json(_profile_file(request, identifier))
    if saved is None:
        saved = FinishProfile().model_dump()
        # Base layout matches the episode, not the standalone demo default.
        saved["video"]["layout"] = _episode(request, identifier)["settings"].get("layout", "portrait")
    return FinishProfile.model_validate({k: v for k, v in saved.items() if k in FinishProfile.model_fields}).model_dump()


def _save_shared_profile(request: Request, episode_id: str,
                         profile: FinishProfileUpdate, previous: dict) -> dict:
    """Write common *styling* only; keep any unowned legacy cues in backups."""
    previous_revision = int(previous.get("revision", 0))
    if profile.revision is not None and profile.revision != previous_revision:
        raise HTTPException(409, "Оформление изменено в другом окне, обновите страницу")
    path = _profile_file(request, episode_id)
    shared = profile.model_dump(exclude={"revision"})
    old_overrides = previous.get("part_overrides", {})
    old_had_cues = isinstance(old_overrides, dict) and any(
        isinstance(value, dict) and value.get("cues") is not None
        for value in old_overrides.values())
    incoming_had_cues = any(value.get("cues") is not None
                            for value in shared["part_overrides"].values())
    if old_had_cues or incoming_had_cues:
        backup = (path.parent / "legacy-caption-backups" /
                  f"{episode_id}-r{previous_revision:06d}.json")
        if not backup.exists():
            atomic_json(backup, previous if old_had_cues else {
                "episode_id": episode_id, **shared, "revision": previous_revision})
    for override in shared["part_overrides"].values():
        override.pop("cues", None)
    stored = {"episode_id": episode_id, **shared, "revision": previous_revision + 1}
    atomic_json(path, stored)
    return stored


def create_finishing_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/episodes/{episode_id}/finishing")
    def get_finishing(request: Request, episode_id: str):
        _episode(request, episode_id)
        saved = _stored_profile(request, episode_id)
        record = read_json(_profile_file(request, episode_id), {}) or {}
        return {"episode_id": episode_id, **saved, "revision": record.get("revision", 0)}

    @router.put("/api/episodes/{episode_id}/finishing")
    def put_finishing(request: Request, episode_id: str, profile: FinishProfileUpdate):
        _episode(request, episode_id)
        with _manager(request).mutex:
            path = _profile_file(request, episode_id)
            return _save_shared_profile(request, episode_id, profile,
                                        read_json(path, {}) or {})

    @router.put("/api/jobs/{job_id}/finishing/state")
    def save_finishing_state(request: Request, job_id: str, body: FinishingSave):
        """Preflight all revisions/cues before applying one editor save.

        Disk errors roll back changes in-process. Multi-file writes cannot be
        guaranteed crash-atomic, so they are not described as such.
        """
        _, plan, episode_id = _checked_render_job(request, job_id)
        manager = _manager(request)
        with manager.mutex:
            profile_path = _profile_file(request, episode_id)
            profile_exists = profile_path.is_file()
            previous = read_json(profile_path, {}) or {}
            expected_profile_rev = int(previous.get("revision", 0))
            if (body.profile.revision is not None
                    and body.profile.revision != expected_profile_rev):
                raise HTTPException(409, "Оформление изменено в другом окне, обновите страницу")
            updates = []
            for item in body.captions:
                part = _part(plan, item.part_index)
                _validate_cues(item.cues, float(part["duration"]))
                path = _caption_file(request, job_id, item.part_index)
                existed = path.is_file()
                prev = read_json(path, {}) or {}
                revision = int(prev.get("revision", 0))
                if item.revision is not None and item.revision != revision:
                    raise HTTPException(409, "Реплики изменены в другом окне, обновите страницу")
                value = {"job_id": job_id, "part_index": item.part_index,
                         "revision": revision + 1,
                         "cues": [cue.model_dump() for cue in item.cues]}
                updates.append((path, existed, prev, value))
            changed = []
            try:
                for path, existed, prev, value in updates:
                    atomic_json(path, value)
                    changed.append((path, existed, prev))
                profile = _save_shared_profile(request, episode_id, body.profile, previous)
            except Exception:
                for path, existed, prev in reversed(changed):
                    if existed:
                        atomic_json(path, prev)
                    else:
                        path.unlink(missing_ok=True)
                if profile_exists and read_json(profile_path, {}) != previous:
                    atomic_json(profile_path, previous)
                elif not profile_exists:
                    profile_path.unlink(missing_ok=True)
                raise
            return {"profile": profile,
                    "captions": [value for _, _, _, value in updates]}

    @router.get("/api/jobs/{job_id}/parts/{part_index}/captions")
    def get_captions(request: Request, job_id: str, part_index: int):
        _, plan = _job_plan(request, job_id)
        part = _part(plan, part_index)
        record = read_json(_caption_file(request, job_id, part_index))
        if record:
            return record
        cues = part.get("subtitles", []) or []
        return {"job_id": job_id, "part_index": part_index, "revision": 0, "cues": cues}

    @router.put("/api/jobs/{job_id}/parts/{part_index}/captions")
    def put_captions(request: Request, job_id: str, part_index: int, body: CaptionsUpdate):
        if body.part_index != part_index:
            raise HTTPException(422, "Номер части в запросе не совпадает")
        _, plan = _job_plan(request, job_id)
        part = _part(plan, part_index)
        duration = float(part["duration"])
        _validate_cues(body.cues, duration)
        path = _caption_file(request, job_id, part_index)
        with _manager(request).mutex:
            prev = read_json(path, {}) or {}
            previous_revision = int(prev.get("revision", 0))
            if body.revision is not None and previous_revision != body.revision:
                raise HTTPException(409, "Реплики изменены в другом окне, обновите страницу")
            stored = {"job_id": job_id, "part_index": part_index, "revision": previous_revision + 1,
                      "cues": [c.model_dump() for c in body.cues]}
            atomic_json(path, stored)
        return stored



    @router.post("/api/jobs/{job_id}/previews", status_code=202)
    def create_preview(request: Request, job_id: str, body: PreviewSubmission):
        from .studio_render import submit_render
        _, plan, episode_id = _checked_render_job(request, job_id)
        part = _part(plan, body.part_index)
        if body.from_seconds >= float(part["duration"]):
            raise HTTPException(422, "Выбранное время за пределами части")
        duration = min(body.duration, float(part["duration"]) - body.from_seconds)
        profile = body.settings.model_dump() if body.settings else _stored_profile(request, episode_id)
        try:
            state = submit_render(_manager(request), job_id, [body.part_index], profile,
                                  preview=(body.part_index, body.from_seconds, duration))
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return {"preview_id": state["preview_id"], "job_id": job_id,
                "part_index": body.part_index, "status": state["status"], "progress": 0,
                "url": None, "error": None}

    @router.api_route("/api/jobs/{job_id}/previews/{preview_file}.mp4", methods=["GET", "HEAD"])
    def stream_preview(request: Request, job_id: str, preview_file: str):
        from .studio_render import task_status, _locate_task
        from .server import ranged_file
        identifier = preview_file
        if not re.fullmatch(r"pv_[0-9a-f]{32}", identifier):
            raise HTTPException(404, "Предпросмотр не найден")
        state = task_status(_manager(request), identifier, job_id)
        if state["status"] != "completed" or not state["files"]:
            raise HTTPException(404, "Предпросмотр ещё не готов")
        _, directory = _locate_task(_manager(request), identifier, job_id)
        source = (directory / "output" / state["files"][0]["name"]).resolve()
        if not source.is_relative_to((directory / "output").resolve()) or not source.is_file():
            raise HTTPException(404, "Файл предпросмотра не найден")
        return ranged_file(source, request)

    @router.get("/api/jobs/{job_id}/previews/{preview_id}")
    def get_preview(request: Request, job_id: str, preview_id: str):
        from .studio_render import task_status
        _manager(request).get(job_id)
        if not re.fullmatch(r"pv_[0-9a-f]{32}", preview_id):
            raise HTTPException(404, "Предпросмотр не найден")
        return task_status(_manager(request), preview_id, job_id)

    @router.post("/api/jobs/{job_id}/exports", status_code=202)
    def create_export(request: Request, job_id: str, body: ExportSubmission):
        from .studio_render import submit_render
        _, plan, episode_id = _checked_render_job(request, job_id)
        for index in body.part_indices:
            _part(plan, index)
        profile = body.settings.model_dump() if body.settings else _stored_profile(request, episode_id)
        try:
            return submit_render(_manager(request), job_id, body.part_indices, profile)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/api/exports/{export_id}")
    def get_export(request: Request, export_id: str):
        from .studio_render import task_status
        if not re.fullmatch(r"ex_[0-9a-f]{32}", export_id):
            raise HTTPException(404, "Экспорт не найден")
        return task_status(_manager(request), export_id)

    @router.api_route("/api/exports/{export_id}/files/{filename}", methods=["GET", "HEAD"])
    def stream_export(request: Request, export_id: str, filename: str):
        from .studio_render import task_status, _locate_task
        from .server import ranged_file
        if not re.fullmatch(r"ex_[0-9a-f]{32}", export_id):
            raise HTTPException(404, "Экспорт не найден")
        state = task_status(_manager(request), export_id)
        allowed = {item["name"] for item in state["files"]}
        allowed |= {Path(name).with_suffix(".srt").name for name in allowed}
        if state["status"] != "completed" or filename not in allowed:
            raise HTTPException(404, "Файл экспорта не найден")
        _, directory = _locate_task(_manager(request), export_id)
        output_dir = (directory / "output").resolve()
        source = (output_dir / filename).resolve()
        if not source.is_relative_to(output_dir) or not source.is_file():
            raise HTTPException(404, "Файл экспорта не найден")
        return ranged_file(source, request, as_attachment=bool(request.query_params.get("download")))

    @router.api_route("/api/music/tracks/{filename}/stream", methods=["GET", "HEAD"])
    def stream_music(request: Request, filename: str):
        from .server import ranged_file
        # Restrict to the exact list presented by the existing /api/music API.
        from .music import list_tracks
        found = next((p for p in list_tracks(config.MUSIC) if p.name == filename), None)
        if not found or not found.is_file():
            raise HTTPException(404, "Музыкальный файл не найден")
        return ranged_file(found, request)

    @router.post("/api/music/import", status_code=201)
    async def import_music(request: Request, file: UploadFile = File(...)):
        from .music import SUPPORTED_SUFFIXES
        from .media import run_command
        name = file.filename or ""
        if (not name or len(name) > 255
                or any(ord(ch) < 32 or ch in '/\\:<>"|?*' for ch in name)
                or name.endswith(('.', ' '))
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name)
                or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES):
            raise HTTPException(422, "Поддерживаются аудиофайлы MP3, WAV, M4A, AAC, FLAC и OGG")
        if not config.FFPROBE.is_file():
            raise HTTPException(503, "FFprobe не установлен")
        config.MUSIC.mkdir(parents=True, exist_ok=True)
        if (config.MUSIC / name).exists():
            raise HTTPException(409, "Трек с таким названием уже существует")
        partial = config.MUSIC / ("." + uuid.uuid4().hex + ".upload")
        total = 0
        try:
            with partial.open("wb") as sink:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 35 * 1024 * 1024:
                        raise HTTPException(413, "Музыкальный файл больше 35 МБ")
                    sink.write(chunk)
            # Accept only a decodable audio stream; uploaded metadata is untrusted.
            try:
                probe = subprocess.run(
                    [str(config.FFPROBE), "-v", "error", "-show_streams", "-show_format",
                     "-of", "json", str(partial)], capture_output=True, timeout=30, check=True)
                parsed = json.loads(probe.stdout)
                if not any(t.get("codec_type") == "audio" for t in parsed.get("streams", [])):
                    raise ValueError("No audio stream")
                duration = float(parsed.get("format", {}).get("duration", 0))
                if not 0 < duration < 24 * 3600:
                    raise ValueError("Invalid duration")
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise HTTPException(422, "Аудиофайл не удалось декодировать") from error
            destination = config.MUSIC / name
            # Renaming is atomic on the same filesystem and cannot overwrite an
            # existing Windows file; explicit duplicate validation above is UX.
            if destination.exists():
                raise HTTPException(409, "Трек с таким названием уже существует")
            os.rename(partial, destination)
            return {"track_id": "mt_" + uuid.uuid4().hex[:8], "name": name, "size": total,
                    "content_type": file.content_type or "application/octet-stream",
                    "duration_seconds": duration,
                    "playback_url": f"/api/music/tracks/{name}/stream", "stored": True}
        finally:
            await file.close()
            partial.unlink(missing_ok=True)

    return router
