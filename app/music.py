"""Configurable background music for shorts rendering."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

from .config import MUSIC_CONFIG, MUSIC_SETTINGS

DEFAULT_CONFIG = {
    "enabled": True,
    "volume": 0.15,
    "fade_in": True,
    "fade_out": True,
    "track": None,
}

SUPPORTED_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def validate_config(value) -> dict:
    """Return a normalized music config, ignoring unknown keys."""
    if not isinstance(value, dict):
        raise ValueError("Некорректная конфигурация музыки")
    config = dict(DEFAULT_CONFIG)
    config.update({key: value[key] for key in DEFAULT_CONFIG if key in value})
    if not isinstance(config["enabled"], bool):
        raise ValueError("music.enabled должно быть true/false")
    volume = config["volume"]
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        raise ValueError("music.volume должно быть числом от 0 до 1")
    volume = float(volume)
    if not 0.0 <= volume <= 1.0:
        raise ValueError("music.volume должно быть от 0 до 1")
    config["volume"] = volume
    for key in ("fade_in", "fade_out"):
        if not isinstance(config[key], bool):
            raise ValueError(f"music.{key} должно быть true/false")
    track = config["track"]
    if track is not None:
        if not isinstance(track, str):
            raise ValueError("music.track должно быть именем файла или null")
        config["track"] = track.strip() or None
    return config


def load_config(path: Path = MUSIC_CONFIG) -> dict:
    """Load music settings from a JSON file; a missing file means defaults."""
    if not path.is_file():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Не удалось прочитать конфигурацию музыки") from error
    if not isinstance(data, dict):
        raise ValueError("Конфигурация музыки должна быть объектом")
    section = data.get("music", data)
    return validate_config(section)


def load_settings() -> dict:
    """Effective music settings: UI runtime file first, then shipped defaults."""
    if MUSIC_SETTINGS.is_file():
        return load_config(MUSIC_SETTINGS)
    return load_config(MUSIC_CONFIG)


def save_settings(config: dict) -> dict:
    """Persist normalized music settings to the ignored runtime file."""
    normalized = validate_config(config)
    MUSIC_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temporary = MUSIC_SETTINGS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"music": normalized}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    os.replace(temporary, MUSIC_SETTINGS)
    return normalized


def list_tracks(music_dir: Path) -> list[Path]:
    """Audio files in the music folder, sorted by name for stable ordering."""
    if not music_dir.is_dir():
        return []
    return sorted(
        path for path in music_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def pick_track(music_dir: Path, config: dict, rng: random.Random | None = None) -> Path | None:
    """Choose the configured track, a random one, or None when disabled/empty."""
    if not config.get("enabled"):
        return None
    tracks = list_tracks(music_dir)
    if not tracks:
        return None
    requested = config.get("track")
    if requested:
        match = next((path for path in tracks if path.name == requested), None)
        if match:
            return match
    return (rng or random).choice(tracks)
