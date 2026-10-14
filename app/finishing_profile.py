"""Shared visual profile validation and reads, without HTTP or inference."""
from pathlib import Path
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.finishing_avatar import AVATAR_PATTERN, resolve_avatar

from app.json_store import read_json


class VideoFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: Literal["portrait", "cinema"] = "portrait"
    frame_style: Literal["plain", "social"] = "plain"
    card_variant: Literal["compact", "post"] = "compact"
    channel_name: str = Field("", max_length=60)
    channel_handle: str = Field("", max_length=60)
    avatar_style: Literal['initials', 'star', 'play', 'chat', 'image'] = 'initials'
    avatar_id: str | None = Field(None, pattern='^' + AVATAR_PATTERN + '$')
    post_caption: str = Field("", max_length=180)
    zoom: int = Field(100, ge=90, le=160)
    blur: int = Field(24, ge=0, le=45)
    brightness: int = Field(100, ge=60, le=140)
    vignette: int = Field(15, ge=0, le=60)

    @model_validator(mode='after')
    def image_requires_asset(self):
        if self.avatar_style == 'image' and not self.avatar_id:
            raise ValueError('Загрузите изображение для иконки канала')
        return self

    @field_validator("channel_name", "channel_handle", "post_caption")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("Текст оформления содержит управляющие символы")
        return " ".join(value.split())


def profile_path(root: Path, episode_id: str) -> Path:
    if str(uuid.UUID(episode_id)) != episode_id:
        raise ValueError("Некорректный ID серии")
    path = (root / "finishing" / "episodes" / (episode_id + ".json")).resolve()
    path.relative_to(root.resolve())
    return path


def load_video_finish(root: Path, episode_id: str) -> dict:
    record = read_json(profile_path(root, episode_id), {}) or {}
    video = VideoFinish.model_validate(record.get("video", {})).model_dump()
    resolve_avatar(root, video, episode_id)
    return video
