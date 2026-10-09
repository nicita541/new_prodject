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


class CaptionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_index: int = Field(ge=1, le=100)
    cues: list[Cue] = Field(max_length=150)
    revision: int | None = Field(None, ge=0)


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


def create_finishing_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/episodes/{episode_id}/finishing")
    def get_finishing(request: Request, episode_id: str):
        _episode(request, episode_id)
        saved = _stored_profile(request, episode_id)
        record = read_json(_profile_file(request, episode_id), {}) or {}
        return {"episode_id": episode_id, **saved, "revision": record.get("revision", 0)}

    @router.put("/api/episodes/{episode_id}/finishing")
    def put_finishing(request: Request, episode_id: str, profile: FinishProfile):
        _episode(request, episode_id)
        path = _profile_file(request, episode_id)
        with _manager(request).mutex:
            previous = read_json(path, {}) or {}
            revision = int(previous.get("revision", 0)) + 1
            stored = {"episode_id": episode_id, **profile.model_dump(), "revision": revision}
            atomic_json(path, stored)
        return stored

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
        if (not name or len(name) > 255 or any(ch in name for ch in ('/', '\\', '\x00', ':'))
                or name in {'.', '..'} or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES):
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
