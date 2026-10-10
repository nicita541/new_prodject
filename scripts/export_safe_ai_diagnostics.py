"""Allowlisted AI run telemetry for publication to the isolated test-reports branch.

Never publish media, ASR dialogue, prompts, model replies, exception messages,
local filesystem paths, or raw debug logs. Runs even after TIMEOUT/FAIL.
"""
import argparse
from collections import Counter, defaultdict, deque
import json
import math
from pathlib import Path
import re
from statistics import median

SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
# A regex alone is insufficient: an arbitrary dialogue word or sensitive
# marker may be a syntactically valid identifier. Only internal vocabulary
# may cross from the user's computer into a potentially public report branch.
ALLOWED = set("""
running passed failed incomplete skipped timeout cancelled ok error invalid pending
RuntimeError ValueError TypeError KeyError IndexError AssertionError TimeoutError
OSError FileNotFoundError PermissionError InterruptedError ImportError
AttributeError MemoryError NameError ZeroDivisionError OverflowError
ConnectionError HTTPError URLError JSONDecodeError CalledProcessError
UnicodeDecodeError EOFError SystemExit KeyboardInterrupt
pipeline prepare transcribe scenes shot_detection scene_detection semantic_boundary
media_perception scene_analysis scene_recovery story_refinement analyze analysis
condense render export finishing planner plan global_story selection_gate
final_quality quality_gate title_detection title_screen source_roles
subtitles audio speech_scene detection story_review scene_understanding
visual_verification selection pacing preview caching startup verify
start end cache_miss cache_hit request response_accepted response_rejected
chunk_cache_miss chunk_cache_hit chunk_cache_saved suppressed accepted
scene_created unresolved exception verification_unresolved semantic_identity
result warning triage level_a level_b cache_saved cache_invalidated
planning rendering framing completed part_context final_selection_adjudication
ending_selection_adjudication story_structure_analysis dialogue_relations
global_visual_verification selection_adjudication
final_selection selection_verification continuity_verification
editing music_processing media_render preparation scene_segmentation
quality_planning video_export audio_mix frame_sampling
genuine_production_analysis_to_final_mp4 genuine_model_and_video_cache_resume
""".split())


def name(value):
    return value if isinstance(value, str) and SAFE_NAME.fullmatch(value) and value in ALLOWED else None


def numeric(value):
    return round(float(value), 4) if type(value) in (float, int) and math.isfinite(value) else None


def boolean(value):
    return value if type(value) is bool else None


def json_file(path):
    try:
        if not path.is_file() or path.stat().st_size > 24 * 1024 * 1024:
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError, OSError):
        return None


def json_lines(path):
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            return
        with path.open(encoding="utf-8-sig") as stream:
            for raw in stream:
                try:
                    item = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    yield item
    except (OSError, UnicodeError):
        return


def summarize(test_dir):
    folder = Path(test_dir) / "real_model_3min"
    job = folder / "real-job"
    model = job / "actual-model"
    report = json_file(folder / "report.json")
    outcome = json_file(job / "observed-outcome.json")
    report = report if isinstance(report, dict) else {}
    outcome = outcome if isinstance(outcome, dict) else {}
    raw_steps = report.get("checks")
    if not isinstance(raw_steps, list):
        raw_steps = []
    steps = [{"name": name(item.get("name")), "status": name(item.get("status")),
              "error_type": name(item.get("error_type")), "seconds": numeric(item.get("seconds"))}
             for item in raw_steps[:100] if isinstance(item, dict)]
    result = {
        "schema_version": 1,
        "scope": "safe_numeric_and_status_metadata_only",
        "available": bool(report or outcome or job.exists()),
        "real_e2e": {
            "status": name(report.get("status")), "error_type": name(report.get("error_type")),
            "duration_seconds": numeric(report.get("duration_seconds")), "steps": steps},
        "production": {
            "complete": boolean(outcome.get("complete")), "error_type": name(outcome.get("error_type")),
            "elapsed_seconds": numeric(outcome.get("elapsed_seconds")),
            "pipeline_code_stable": boolean(outcome.get("pipeline_code_stable"))},
    }
    for key, file in (("shots", "shots.json"), ("semantic_scenes", "scenes.json")):
        rows = json_file(job / file)
        result[key] = len(rows) if isinstance(rows, list) else None
    result["checkpoint_counts"] = {
        "scene_analysis": sum(1 for _ in (job / "visual").glob("event_[0-9][0-9][0-9][0-9].json")),
        "technical_chunks": sum(1 for _ in (job / "visual").glob("event_*_chunk_*.checkpoint.json")),
        "story_refinement": sum(1 for _ in (job / "story_refinement").glob("*.json")),
        "title_screen": sum(1 for _ in (job / "title_units").glob("screen_*.json")
                            if not _.name.endswith(".storyboard.json"))
    }
    scenes = json_file(job / "scenes.json")
    durations = []
    if isinstance(scenes, list):
        for row in scenes[:5000]:
            if isinstance(row, dict):
                a, b = numeric(row.get("start")), numeric(row.get("end"))
                if a is not None and b is not None and b > a:
                    durations.append(round(b - a, 4))
    result["scene_durations"] = {
        "count": len(durations), "below_1s": sum(d < 1 for d in durations),
        "below_2s": sum(d < 2 for d in durations),
        "min_s": min(durations, default=None),
        "median_s": round(median(durations), 4) if durations else None,
        "max_s": max(durations, default=None)}
    requests, responses = {}, {}
    for label, target in (("request", requests), ("response", responses)):
        for file in model.glob(label + "-*.json"):
            match = re.fullmatch(label + r"-(\d{1,8})\.json", file.name)
            if match:
                target[int(match.group(1))] = file
    elapsed, errors, latest = [], Counter(), deque(maxlen=20)
    for request_id in sorted(set(requests) | set(responses)):
        payload = json_file(responses[request_id]) if request_id in responses else None
        error_type = name(payload.get("error_type")) if isinstance(payload, dict) else None
        duration = numeric(payload.get("elapsed_seconds")) if isinstance(payload, dict) else None
        if duration is not None and duration >= 0:
            elapsed.append(duration)
        if error_type:
            errors[error_type] += 1
        status = "pending" if request_id not in responses else (
            "invalid" if not isinstance(payload, dict) else "error" if error_type else "ok")
        latest.append({"id": request_id, "status": status,
                       "seconds": duration, "error_type": error_type})
    result["model_requests"] = {
        "requests": len(requests), "responses": len(responses),
        "pending": len(set(requests) - set(responses)),
        "errors": dict(sorted(errors.items())),
        "median_seconds": round(median(elapsed), 4) if elapsed else None,
        "max_seconds": max(elapsed, default=None), "last_20": list(latest)}
    actions, durations_by_stage, errors_by_stage = Counter(), defaultdict(list), Counter()
    last = deque(maxlen=30)
    for item in json_lines(job / "diagnostics" / "pipeline" / "timeline.jsonl"):
        stage, action, error = name(item.get("stage")), name(item.get("action")), name(item.get("error_type"))
        seconds = numeric(item.get("elapsed_seconds"))
        if stage:
            actions[stage] += 1
            if action == "end" and seconds is not None and seconds >= 0:
                durations_by_stage[stage].append(seconds)
            if error or action in ("exception", "warning", "response_rejected", "verification_unresolved"):
                errors_by_stage[(stage, error or action or "unknown")] += 1
        last.append({"stage": stage, "action": action, "error_type": error, "seconds": seconds})
    result["timeline"] = {
        "events_by_stage": dict(sorted(actions.items())),
        "duration_seconds_by_stage": {k: round(sum(v), 4) for k, v in sorted(durations_by_stage.items())},
        "issues": [{"stage": stage, "type": error, "count": count}
                   for (stage, error), count in sorted(errors_by_stage.items())],
        "last_30": list(last)}
    progress_counts, recent = Counter(), deque(maxlen=20)
    for item in json_lines(job / "observed-progress.jsonl"):
        stage = name(item.get("stage"))
        if stage:
            progress_counts[stage] += 1
        recent.append({"stage": stage, "progress": numeric(item.get("progress"))})
    result["progress"] = {"events_by_stage": dict(sorted(progress_counts.items())),
                          "last_20": list(recent)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = summarize(args.test_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print("SAFE_AI_DIAGNOSTICS_EXPORTED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
