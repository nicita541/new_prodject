"""CPU-only scene-threshold calibration on explicitly requested local windows.

Usage: python scripts/shot_diagnostic.py JOB --window START:END [--window ...]
Produces score logs, threshold counts and before/after contact sheets. It never
changes application checkpoints, source media or production detector settings.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import FFMPEG, setup_environment
from PIL import Image, ImageDraw, ImageFont

THRESHOLDS = (.04, .06, .08, .10, .12, .24)
SAMPLE_FPS = 30


def contained(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def scores(text: str, offset: float) -> list[dict]:
    result, timestamp = [], None
    for line in text.splitlines():
        match = re.search(r"pts_time:([-+0-9.eE]+)", line)
        if match:
            timestamp = float(match.group(1))
        match = re.search(r"lavfi.scene_score=([-+0-9.eE]+)", line)
        if match and timestamp is not None:
            result.append({"time": round(offset + timestamp, 6),
                           "local_time": timestamp, "score": float(match.group(1))})
    return result


def command(arguments: list[str], directory: Path, log: str) -> None:
    with (directory / log).open("wb") as stream:
        subprocess.run([str(FFMPEG), "-hide_banner", "-nostdin", "-y", *arguments],
                       cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def diagnose(job: Path, windows: list[tuple[float, float]]) -> dict:
    setup_environment()
    job = contained(job)
    source_info = json.loads((job / "source.json").read_text(encoding="utf-8"))
    source = contained(Path(source_info["path"]))
    duration = float(json.loads((job / "probe.json").read_text(encoding="utf-8"))["duration"])
    directory = contained(job / "diagnostics" / "shot-diagnostic", job)
    directory.mkdir(parents=True, exist_ok=True)
    result = {"source_name": source_info.get("name", source.name), "scale_width": 320,
              "candidate_threshold": .015, "thresholds": list(THRESHOLDS), "windows": []}
    for index, (start, end) in enumerate(windows, 1):
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end <= duration:
            raise ValueError("Diagnostic window is outside the source")
        target = contained(directory / f"window_{index:02}", directory)
        target.mkdir(exist_ok=True)
        command(["-ss", str(start), "-threads", "2", "-i", str(source), "-t", str(end-start),
                 "-filter_threads", "1", "-vf",
                 "scale=320:-2,select='gt(scene,0.015)',metadata=print:file=scores.txt,showinfo",
                 "-an", "-fps_mode", "passthrough", "-f", "null", "-"], target, "scene.log")
        candidates = [item for item in scores((target / "scores.txt").read_text(encoding="utf-8"), start)
                      if 0 <= item["local_time"] < end-start]
        record = {"start": start, "end": end, "scores": candidates,
                  "threshold_times": {str(t): [c["time"] for c in candidates if c["score"] > t]
                                      for t in THRESHOLDS}, "contact_sheets": []}
        review = [c for c in candidates if c["score"] > min(THRESHOLDS)]
        frame_indices = set()
        for item in review:
            frame = round(item["local_time"] * SAMPLE_FPS)
            before = max(0, frame - 2)
            after = min(int((end-start) * SAMPLE_FPS) - 1, frame + 2)
            item["before_index"], item["after_index"] = before, after
            frame_indices.update((before, after))
        ordered = sorted(frame_indices)
        if ordered:
            selection = "+".join(f"eq(n,{n})" for n in ordered)
            # Decode a short tail so FPS rounding cannot omit the last requested
            # comparison frame at the diagnostic window's right edge.
            command(["-ss", str(start), "-threads", "2", "-i", str(source), "-t", str(min(duration-start, end-start+.2)),
                     "-filter_threads", "1", "-vf", f"fps={SAMPLE_FPS}:start_time=0,scale=320:-2,select='{selection}'",
                     "-an", "-fps_mode", "passthrough", "-q:v", "2", "frame_%04d.jpg"],
                    target, "frames.log")
            frames = {n: target / f"frame_{i:04}.jpg" for i, n in enumerate(ordered, 1)}
            font = ImageFont.load_default(size=16)
            for page_start in range(0, len(review), 6):
                page = review[page_start:page_start+6]
                canvas = Image.new("RGB", (660, 224 * len(page)), "#121212")
                draw = ImageDraw.Draw(canvas)
                for row, item in enumerate(page):
                    y = row * 224
                    draw.text((8, y+5), f"source {item['time']:.3f}s   score {item['score']:.4f}   BEFORE / AFTER",
                              fill="white", font=font)
                    for x, key in ((8, "before_index"), (332, "after_index")):
                        image_path = frames[item[key]]
                        with Image.open(image_path) as picture:
                            canvas.paste(picture.convert("RGB"), (x, y+33))
                sheet = target / f"contact_{page_start//6+1:02}.jpg"
                canvas.save(sheet, quality=94)
                record["contact_sheets"].append(str(sheet.relative_to(directory)))
        result["windows"].append(record)
        print(f"Window {start:g}..{end:g}: " + ", ".join(
            f"{threshold}: {len(times)}" for threshold, times in record["threshold_times"].items()), flush=True)
    output = directory / "scores.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Diagnostics: {output}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--window", action="append", required=True)
    args = parser.parse_args()
    windows = [tuple(map(float, text.split(":"))) for text in args.window]
    if any(len(window) != 2 for window in windows):
        raise ValueError("Use START:END for each diagnostic window")
    diagnose(args.job, windows)


if __name__ == "__main__":
    main()
