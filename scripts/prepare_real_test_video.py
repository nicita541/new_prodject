"""Create an isolated 180-second story excerpt for genuine local-model E2E.

The chosen source is read-only. Only source excerpts inside ROOT/temp can be
generated; nothing is published to GitHub from this helper.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import config
from app.media import run_command
from app.media_probe import probe_media


def prepare(source: Path, directory: Path, *, start_seconds: float = 0.0) -> Path:
    source = source.expanduser().resolve(strict=True)
    directory = directory.resolve()
    if not source.is_file():
        raise ValueError("Choose a readable video file")
    if not directory.is_relative_to((ROOT / "temp").resolve()):
        raise ValueError("Temporary test material must stay under project/temp")
    start_seconds = float(start_seconds)
    if start_seconds < 0 or not (float("-inf") < start_seconds < float("inf")):
        raise ValueError("Start time must be a finite, non-negative number")

    media = probe_media(source)
    duration = float(media["duration"])
    if not media["has_audio"]:
        raise ValueError("Story sample must contain a spoken-audio track")
    if duration < 179.8:
        raise ValueError("Selected source is shorter than three minutes")
    if duration + 0.2 < start_seconds + 180:
        raise ValueError("Cannot extract a full 180 seconds from the chosen start time")

    directory.mkdir(parents=True, exist_ok=True)
    if start_seconds == 0 and 179.8 <= duration <= 180.2:
        if source.is_relative_to(ROOT.resolve()):
            target = source
        else:
            target = directory / "story-180s.mp4"
            shutil.copyfile(source, target)
    else:
        target = directory / "story-180s.mp4"
        if target == source:
            raise ValueError("Refusing to overwrite the original source")
        # Accurate frame/audio timestamps matter for the ASR and VLM cache.
        # Re-encode the excerpt, not the original 23-minute episode.
        run_command([
            config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(start_seconds), "-i", str(source),
            "-t", "180", "-map", "0:v:0",
            "-map", f"0:a:{int(media.get('audio_stream', 0))}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", str(target)
        ], directory, timeout=1800)
    checked = probe_media(target)
    if not (179.8 <= float(checked["duration"]) <= 180.2 and checked["has_audio"]):
        raise ValueError("Prepared excerpt failed 180-second video/audio validation")
    (directory / "selected-source.txt").write_text(str(target), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    args = parser.parse_args()
    config.setup_environment()
    prepared = prepare(args.source, args.directory,
                       start_seconds=args.start_seconds)
    print("Prepared real-model 180s sample inside the project: " + str(prepared))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
