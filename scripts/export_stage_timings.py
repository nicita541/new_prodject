"""Public, allowlisted wall-clock timing report for a complete KADR test run.

Top-level verification steps are SEQUENTIAL and have monotonic stopwatch
measurements. Production pipeline stages can be NESTED and their inclusive
durations MUST NOT be summed to infer total runtime. Source video, transcript,
prompts, model outputs, arbitrary log text and exception messages are excluded.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import median
import sys

# Direct invocation by Windows BAT/PowerShell must resolve the project package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_safe_ai_diagnostics import (
    json_file, json_lines, name, numeric, model_perf_summary, token_ledger_summary
)

# These names come from source code, never from a user-controlled log message.
CHECKS = set("""
python_compile python_dependencies python_tests react_tests react_lint
react_build ffmpeg ffprobe full_pipeline_3min prepare_real_source
real_model_3min safe_ai_diagnostics stage_timings
""".split())

STEPS = set("""
generate_true_180_second_mp4
ffprobe_source_and_prepare_decision_fixture
real_pipeline_plan_and_ffmpeg_render
decode_validate_mp4_audio_srt_and_plan
second_full_pipeline_run_for_cache
invalidate_corrupted_subtitles_and_rerender
ffmpeg_finishing_zoom_music_and_edited_captions
real_studio_http_source_plan_mp4_srt_and_range
genuine_production_analysis_to_final_mp4
genuine_model_and_video_cache_resume
""".split())

STATUSES = set("PASS FAIL TIMEOUT SKIP INCOMPLETE passed failed skipped running".split())


def positive(value):
    n = numeric(value)
    return n if n is not None and n >= 0 else None


def percent(seconds, total):
    if seconds is None or total is None or total <= 0:
        return None
    return round(100 * seconds / total, 2)


def safe_step(obj, *, allowed, overall):
    if not isinstance(obj, dict):
        return None
    label = obj.get("name")
    if not isinstance(label, str) or label not in allowed:
        return None
    seconds = positive(obj.get("elapsed_seconds" if overall else "seconds"))
    status = obj.get("status")
    return {"name": label, "status": status if isinstance(status, str) and status in STATUSES else None,
            "seconds": seconds}


def steps_from(path, *, allowed, overall=False):
    data = json_file(path)
    if not isinstance(data, dict):
        return [], None
    vals = data.get("checks")
    if not isinstance(vals, list):
        return [], positive(data.get("elapsed_seconds")) if overall else None
    steps = [step for item in vals[:200] if (step := safe_step(item, allowed=allowed, overall=overall))]
    return steps, positive(data.get("elapsed_seconds")) if overall else None


def longest(items):
    measured = [item for item in items if item.get("seconds") is not None]
    return max(measured, key=lambda item: item["seconds"]) if measured else None


def model_request_timing(job):
    folder = job / "actual-model"
    latencies = []
    errors = 0
    completed = 0
    ids = set()
    for path in folder.glob("response-*.json"):
        part = path.stem.removeprefix("response-")
        if not part.isdigit() or len(part) > 8:
            continue
        ids.add(int(part))
        result = json_file(path)
        if not isinstance(result, dict):
            continue
        completed += 1
        value = positive(result.get("elapsed_seconds"))
        if value is not None:
            latencies.append(value)
        if name(result.get("error_type")) is not None:
            errors += 1
    requests = sum(1 for path in folder.glob("request-*.json")
                   if path.stem.removeprefix("request-").isdigit())
    return {
        "requests": requests, "responses": completed, "errors": errors,
        "sum_response_seconds": round(sum(latencies), 3),
        "average_response_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "median_response_seconds": round(median(latencies), 3) if latencies else None,
        "max_response_seconds": max(latencies, default=None),
        "measurement_note": "Sum of model request durations; not an independent wall-clock phase.",
    }


def production_stage_timing(job, real_elapsed):
    groups = {}
    for event in json_lines(job / "diagnostics" / "pipeline" / "timeline.jsonl"):
        stage = name(event.get("stage"))
        if not stage:
            continue
        if stage not in groups:
            groups[stage] = {"stage": stage, "invocations": 0,
                             "completed_invocations": 0, "seconds": 0.0,
                             "exceptions": 0}
        item = groups[stage]
        action = name(event.get("action"))
        if action == "start":
            item["invocations"] += 1
        if action == "end":
            duration = positive(event.get("elapsed_seconds"))
            if duration is not None:
                item["seconds"] += duration
                item["completed_invocations"] += 1
        elif action == "exception":
            item["exceptions"] += 1
    return [
        {**item,
         "unfinished_invocations": max(0, item["invocations"] - item["completed_invocations"]),
         "seconds": round(item["seconds"], 3) if item["completed_invocations"] else None,
         "share_of_real_run_pct": percent(item["seconds"], real_elapsed)
             if item["completed_invocations"] else None}
        for item in groups.values()
    ]


def production_run_manifests(job):
    """All persisted first-pass/resume render timings, not just the last run.

    Per-run stage seconds are independent within one invocation; a second
    cached run is shown separately, not silently substituted for the first.
    """
    entries = []
    paths = list((job / "runs").glob("*.json"))[:100]
    if not paths and (job / "timings.json").is_file():
        paths = [job / "timings.json"]
    for path in paths:
        doc = json_file(path)
        if not isinstance(doc, dict):
            continue
        stages = doc.get("stages_seconds")
        if not isinstance(stages, dict):
            stages = {}
        allowed_stages = ("analysis", "planning", "part_context", "rendering")
        stage_rows = [
            {"stage": stage, "seconds": positive(stages.get(stage))}
            for stage in allowed_stages if stage in stages
        ]
        parts = doc.get("parts")
        parts = parts if isinstance(parts, list) else []
        status = doc.get("status")
        entries.append({
            "_started": str(doc.get("started_at", ""))[:40],
            "status": status if status in ("completed", "failed", "cancelled", "running") else None,
            "elapsed_seconds": positive(doc.get("elapsed_seconds")),
            "stages": stage_rows,
            "parts": len(parts),
            "cached_parts": sum(row.get("cached") is True for row in parts if isinstance(row, dict)),
        })
    entries.sort(key=lambda item: item["_started"])
    entries = entries[-20:]
    for index, item in enumerate(entries, 1):
        item.pop("_started", None)
        item["run_number"] = index
    return entries


def summarize(test_dir):
    test_dir = Path(test_dir)
    timing_file = test_dir / "timing_snapshot.local.json"
    checks_file = timing_file if timing_file.is_file() else test_dir / "checks.json"
    checks, total = steps_from(checks_file, allowed=CHECKS, overall=True)
    for check in checks:
        check["share_of_test_pct"] = percent(check["seconds"], total)

    offline = test_dir / "full_pipeline_3min" / "report.json"
    real = test_dir / "real_model_3min" / "report.json"
    offline_steps, _ = steps_from(offline, allowed=STEPS)
    real_steps, _ = steps_from(real, allowed=STEPS)
    outcome = json_file(test_dir / "real_model_3min" / "real-job" / "observed-outcome.json")
    outcome = outcome if isinstance(outcome, dict) else {}
    real_elapsed = positive(outcome.get("elapsed_seconds"))
    for step in real_steps:
        step["share_of_production_pct"] = percent(step["seconds"], real_elapsed)

    job = test_dir / "real_model_3min" / "real-job"
    stages = production_stage_timing(job, real_elapsed)
    # These stages may be nested: pipeline > scenes > semantic_boundary.
    # The individual percentage may be useful but summing them is invalid.
    stage_rows = sorted(stages, key=lambda row: row["seconds"] or 0, reverse=True)
    leaf_candidates = [row for row in stages if row["seconds"] is not None and row["stage"] not in
                       {"pipeline", "analysis", "analyze", "scenes", "scene_detection"}]
    slowest_leaf = max(leaf_candidates, key=lambda row: row["seconds"]) if leaf_candidates else None
    bottleneck_check = longest(checks)
    return {
        "schema_version": 1,
        "time_unit": "seconds",
        "scope": "full_verification_and_nested_production",
        "total": {
            "seconds_until_report_generation": total,
            "measurement": "monotonic_wall_clock" if total is not None else "unavailable_old_run",
            "excludes": "git_report_upload",
        },
        "verification_checks": checks,
        "offline_180s_e2e_steps": offline_steps,
        "real_ai_e2e_steps": real_steps,
        "real_production": {
            "elapsed_seconds": real_elapsed,
            "stage_order": stages,
            "slowest_inclusive_stages": stage_rows[:12],
            "slowest_detailed_stage": slowest_leaf,
            "measurement": "inclusive_nested_stage_seconds_not_additive",
        },
        "model_inference": model_request_timing(job),
        "model_performance": model_perf_summary(job),
        "token_usage_totals": token_ledger_summary(job),
        "production_invocations": production_run_manifests(job),
        "bottlenecks": {
            "slowest_verification_check": bottleneck_check,
            "slowest_detailed_production_stage": slowest_leaf,
        },
        "missing_timing_checks": [step["name"] for step in checks if step["seconds"] is None],
    }


def human(seconds):
    if seconds is None:
        return "not measured"
    return f"{seconds:.1f} s ({int(seconds // 60)}m {seconds % 60:.1f}s)"


def markdown(data):
    parts = [
        "# KADR — complete verification timing",
        "",
        f"**Elapsed until reporting:** {human(data['total']['seconds_until_report_generation'])}",
        "",
        "This clock covers verification and model processing, but excludes the subsequent Git push.",
        "A missing measurement means the test was recorded by an older launcher, not zero time.",
        "",
        "## 1. Verification steps, in execution order (sequential)",
        "",
        "| Step | Status | Duration | % of test |",
        "| --- | --- | ---: | ---: |",
    ]
    for step in data["verification_checks"]:
        share = step["share_of_test_pct"]
        parts.append(f"| {step['name']} | {step['status'] or 'unknown'} | "
                     f"{human(step['seconds'])} | {str(share)+'%' if share is not None else '—'} |")
    for title, key in (
        ("## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)", "offline_180s_e2e_steps"),
        ("## 3. Real ASR/VLM + render acceptance substeps (inside real_model_3min)", "real_ai_e2e_steps")
    ):
        parts.extend(["", title, "", "| Step | Status | Duration |", "| --- | --- | ---: |"])
        for step in data[key]:
            parts.append(f"| {step['name']} | {step['status'] or 'unknown'} | {human(step['seconds'])} |")
    parts.extend([
        "", "## 4. Real production stages in first-seen order", "",
        "| Stage | Completed calls | Unfinished | Inclusive time | % of production |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for item in data["real_production"]["stage_order"]:
        share = item["share_of_real_run_pct"]
        parts.append(f"| {item['stage']} | {item['completed_invocations']} | "
                     f"{item['unfinished_invocations']} | "
                     f"{human(item['seconds'])} | {str(share)+'%' if share is not None else '—'} |")
    parts.extend([
        "",
        "**Important:** production stage durations are INCLUSIVE and can overlap "
        "(e.g. pipeline contains scenes, and scenes contain semantic_boundary). "
        "Do not add their times or percentages. Stages terminated without an end event "
        "are marked unfinished and their actual execution time is NOT invented.",
        "", "## 5. Planning / rendering for each production invocation", "",
        "| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for run in data["production_invocations"]:
        by_stage = {item["stage"]: item["seconds"] for item in run["stages"]}
        parts.append(f"| {run['run_number']} | {run['status'] or 'unknown'} | "
                     f"{human(run['elapsed_seconds'])} | "
                     f"{human(by_stage.get('analysis'))} | "
                     f"{human(by_stage.get('planning'))} | "
                     f"{human(by_stage.get('part_context'))} | "
                     f"{human(by_stage.get('rendering'))} | "
                     f"{run['cached_parts']}/{run['parts']} |")
    parts.extend([
        "", "## 6. Model inference", ""
    ])
    model = data["model_inference"]
    parts.extend([
        f"Requests: **{model['requests']}**, responses: **{model['responses']}**, errors: **{model['errors']}**.",
        f"Sum of response durations: **{human(model['sum_response_seconds'])}**; "
        f"median: {human(model['median_response_seconds'])}.",
    ])
    perf = data["model_performance"]
    ledger = data["token_usage_totals"]

    def measured(value, suffix=""):
        return f"{value:,.2f}{suffix}" if value is not None else "not measured"

    parts.extend([
        "", "## 7. Local llama.cpp per-model and per-task profile", "",
        "### Total tokens used in this run (whole-run usage ledger)", "",
        f"**All providers combined: {measured(ledger['total_reported_tokens'], ' tokens')}**.",
        "These are actual provider-reported tokens for completed HTTP replies, "
        "not a prediction of the unfinished calls. Do NOT add the separate "
        "local-model breakdown again — it measures some of the same responses.",
        "",
        "| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for provider, entry in ledger["by_provider"].items():
        parts.append(f"| {provider} | {entry['calls']} | {entry['prompt_tokens']} | "
                     f"{entry['completion_tokens']} | {entry['total_tokens']} | "
                     f"{entry['unknown_calls']} |")
    parts.extend([
        "", "### Average model cost: visual 4B versus story 9B", "",
        "Average latency includes completed model requests only. Token averages "
        "count ONLY calls with usage data. Generation speed uses measured "
        "llama.cpp decode timing and token counts, not total network latency.",
        "",
        "| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for group in perf["by_model"]:
        parts.append(
            f"| {group['model']} | {group['completed']}/{group['requests']} | "
            f"{group['token_reported_calls']}/{group['unknown_token_calls']} | "
            f"{group['prompt_tokens']} | {group['completion_tokens']} | "
            f"{group['total_tokens']} | {measured(group['avg_prompt_tokens_per_call'])} | "
            f"{measured(group['avg_completion_tokens_per_call'])} | "
            f"{measured(group['avg_total_tokens_per_measured_call'])} | "
            f"{human(group['avg_seconds_per_completed_call'])} | "
            f"{measured(group['generation_tokens_per_second'])} | "
            f"{human(group['latency_p95_s'])} |")
    parts.extend([
        "", "### By task (choose_units, credit_classifier, scene_analysis, etc.)", "",
        "| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for group in perf["by_model_and_stage"]:
        parts.append(
            f"| {group['model']} | {group['stage']} | "
            f"{group['completed']}/{group['pending']} | "
            f"{human(group['avg_seconds_per_completed_call'])} | "
            f"{human(group['latency_p95_s'])} | "
            f"{measured(group['avg_prompt_tokens_per_call'])} | "
            f"{measured(group['avg_completion_tokens_per_call'])} | "
            f"{measured(group['generation_tokens_per_second'])} | "
            f"{group['prompt_tokens']} | {group['completion_tokens']} | "
            f"{group['unknown_token_calls']} |")
    parts.extend(["",
        "The visual model corresponds to the configured Qwen visual GGUF "
        "(normally 4B; a configured 3B would require a matching alias update). "
        "The story model corresponds to the configured 9B GGUF.",
        "", "**llama.cpp startup attempts:**", ""])
    for item in perf["startup"]:
        parts.append(f"- {item['model']} / {item['status']} / "
                     f"{'CPU' if item['cpu'] else 'GPU'}: {human(item['seconds'])}")
    parts.append("")
    bottleneck = data["bottlenecks"]
    check = bottleneck["slowest_verification_check"]
    detail = bottleneck["slowest_detailed_production_stage"]
    parts.extend([
        "", "## 8. Bottleneck candidates", "",
        f"Slowest verification step: **{check['name']} — {human(check['seconds'])}**." if check else "No per-check timing available.",
        f"Slowest detailed production stage: **{detail['stage']} — {human(detail['seconds'])}**." if detail else "No detailed production timing available.",
        "", "Only fixed internal check/stage names and numeric measurements are published.",
        ""
    ])
    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = summarize(args.test_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print("SAFE_STAGE_TIMINGS_EXPORTED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
