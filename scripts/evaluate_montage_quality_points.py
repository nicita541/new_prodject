"""Score sparse reviewed source-frame points against a final plan JSON.

This deliberately does not infer continuous opening/ending boundaries or
editorial quality between the reviewed samples.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def load_plan_intervals(path: Path) -> list[tuple[float, float]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("parts"), list):
        raise ValueError("plan must contain a parts array")
    intervals = []
    for part in value["parts"]:
        if not isinstance(part, dict) or not isinstance(part.get("cuts"), list):
            raise ValueError("each plan part must contain a cuts array")
        for cut in part["cuts"]:
            if not isinstance(cut, dict):
                raise ValueError("each cut must be an object")
            start, end = float(cut["start"]), float(cut["end"])
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or start >= end:
                raise ValueError(f"invalid source interval: {cut!r}")
            intervals.append((start, end))
    return intervals


def evaluate(fixture: dict, intervals: list[tuple[float, float]]) -> dict:
    source = fixture["source"]
    tolerance = float(fixture["review"]["membership_tolerance_frames"]) / float(source["nominal_fps"])
    duration = float(source["duration_seconds"])
    failures = []
    chronology_errors = []
    prior_end = None
    for index, (start, end) in enumerate(intervals):
        if end > duration + tolerance:
            failures.append(f"cut {index} ends beyond source duration: {end:.6f}")
        if prior_end is not None and start < prior_end:
            chronology_errors.append(index)
        prior_end = end

    observations = []
    for item in fixture["observations"]:
        time = float(item["time_seconds"])
        # One-frame tolerance accounts for source-frame sampling only. It is
        # not permission to retain an entire frame that is marked removable.
        if item["expect"] == "present":
            matched = any(start - tolerance <= time <= end + tolerance for start, end in intervals)
        elif item["expect"] == "absent":
            matched = not any(start < time + tolerance and end > time - tolerance
                              for start, end in intervals)
        else:
            raise ValueError(f"unsupported expected membership: {item['expect']!r}")
        observations.append({**item, "matched": matched})
        if not matched:
            failures.append(f"{item['expect']} point {time:g}s ({item['label']}) did not match")

    return {
        "passed": not failures and not chronology_errors,
        "point_count": len(observations),
        "point_pass_count": sum(item["matched"] for item in observations),
        "chronological_nonoverlap": not chronology_errors,
        "chronology_error_cut_indices": chronology_errors,
        "interval_count": len(intervals),
        "frame_tolerance_seconds": tolerance,
        "failures": failures,
        "observations": observations,
    }


def main() -> int:
    # Windows may default stdout to CP1251 while fixture evidence contains
    # Russian and Japanese text. Keep JSON output readable without relying on
    # a caller-specific `-X utf8` flag.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True,
                        help="Final plan JSON with parts[].cuts[].start/end source times")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = evaluate(fixture, load_plan_intervals(args.plan))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
