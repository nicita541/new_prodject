"""Named rendering presets, separate from expensive story decisions."""
from __future__ import annotations

import json
from pathlib import Path

LAYOUTS = {"portrait", "cinema"}
CAPTIONS = {"classic", "accent"}


def validate_options(layout="portrait", caption_style="classic") -> dict:
    if layout not in LAYOUTS or caption_style not in CAPTIONS:
        raise ValueError("Неизвестное оформление шортсов")
    return {"layout": layout, "caption_style": caption_style}


def load_options(job_dir: Path) -> dict:
    path = job_dir / "render-settings.json"
    if not path.is_file():
        return validate_options()
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_options(data["layout"], data["caption_style"])
