"""Workspace JSON persistence. Missing reads and encodings are explicit contracts."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default=None):
    try:
        return load_json(path)
    except FileNotFoundError:
        return default


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_json(path: Path, data, *, allow_nan=False, indent=2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=indent, allow_nan=allow_nan)
            stream.flush()
            os.fsync(stream.fileno())
        # A browser/read on Windows may briefly hold the old file handle.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


# Analysis historically permits non-finite values; validators reject them at domain boundaries.
analysis_json = partial(atomic_json, allow_nan=True)
compact_json = partial(atomic_json, indent=None)
