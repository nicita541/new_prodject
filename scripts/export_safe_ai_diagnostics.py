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



PERF_STAGES = frozenset(("general", "semantic_boundary", "scene_analysis", "story_refinement",
    "choose_units", "verify_omissions", "credit_classifier", "global_story",
    "global_visual", "source_roles", "titles", "framing", "pacing"))
PERF_MODELS = frozenset(("visual4b", "story9b", "deepseek_flash", "other"))
PERF_STATUSES = frozenset(("ok", "failed", "cancelled", "retried", "fallback", "timeout"))


def _model_statistics(rows, *, model, stage=None):
    """Actual measured tokens and times, never estimates from char counts.

    All per-call averages use only completed calls with the relevant metric.
    Throughput uses llama.cpp decoded-token counts / measured decode seconds,
    not output tokens divided by full HTTP wall-clock duration.
    """
    latencies, prefill, decode = [], [], []
    generated_for_speed = decode_time = 0.0
    prefill_for_speed = prefill_time = 0.0
    prompt_sum = completion_sum = paired_sum = 0.0
    prompt_calls = completion_calls = both_calls = 0
    prompt_char_count = pages = reasoning_tokens = 0.0
    reasoning_calls = length_calls = cpu_calls = thinking_calls = 0
    finished = failures = 0
    for start, end in rows:
        prompt_char_count += start["prompt_chars"] or 0
        pages += start["pages"] or 0
        cpu_calls += int(start["cpu"])
        thinking_calls += int(start["thinking"])
        if end is None:
            continue
        finished += 1
        failures += int(end["status"] not in ("ok", "retried"))
        length_calls += int(end["finish_reason"] == "length")
        value = end["seconds"]
        if value is not None:
            latencies.append(value)
        prompt = end["prompt_tokens"]
        completion = end["completion_tokens"]
        if prompt is not None:
            prompt_calls += 1
            prompt_sum += prompt
        if completion is not None:
            completion_calls += 1
            completion_sum += completion
        if prompt is not None and completion is not None:
            both_calls += 1
            paired_sum += prompt + completion
        if end["reasoning_tokens"] is not None:
            reasoning_tokens += end["reasoning_tokens"]
            reasoning_calls += 1
        if end["prompt_ms"] is not None:
            prefill.append(end["prompt_ms"])
            if end["prompt_n"] is not None and end["prompt_ms"] > 0:
                prefill_for_speed += end["prompt_n"]
                prefill_time += end["prompt_ms"] / 1000
        if end["predicted_ms"] is not None:
            decode.append(end["predicted_ms"])
            # Prefer provider timing token count, which can include internal
            # reasoning tokens. Fall back to usage.completion_tokens only if
            # provider-specific predicted_n was not exposed.
            generated = end["predicted_n"]
            if generated is None:
                generated = completion
            if generated is not None and end["predicted_ms"] > 0:
                generated_for_speed += generated
                decode_time += end["predicted_ms"] / 1000

    def average(total, count):
        return round(total / count, 3) if count else None

    def pct(values, fraction):
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered)-1, math.ceil(fraction * len(ordered))-1)], 3)

    result = {
        "model": model,
        "requests": len(rows), "completed": finished, "pending": len(rows) - finished,
        "failed": failures, "image_pages": int(pages),
        "thinking_requests": thinking_calls, "cpu_requests": cpu_calls,
        "prompt_chars": int(prompt_char_count),
        "prompt_tokens": int(prompt_sum),
        "completion_tokens": int(completion_sum),
        "total_tokens": int(paired_sum),
        "prompt_token_reported_calls": prompt_calls,
        "completion_token_reported_calls": completion_calls,
        "token_reported_calls": both_calls,
        "unknown_token_calls": len(rows) - both_calls,
        "avg_prompt_tokens_per_call": average(prompt_sum, prompt_calls),
        "avg_completion_tokens_per_call": average(completion_sum, completion_calls),
        "avg_total_tokens_per_measured_call": average(paired_sum, both_calls),
        "reasoning_tokens": int(reasoning_tokens),
        "reasoning_reported_calls": reasoning_calls,
        "finish_length_calls": length_calls,
        "completed_timed_calls": len(latencies),
        "sum_request_seconds": round(sum(latencies), 3),
        "avg_seconds_per_completed_call": average(sum(latencies), len(latencies)),
        "latency_p50_s": pct(latencies, .50),
        "latency_p90_s": pct(latencies, .90),
        "latency_p95_s": pct(latencies, .95),
        "max_latency_s": max(latencies, default=None),
        "prefill_p50_ms": pct(prefill, .50),
        "decode_p50_ms": pct(decode, .50),
        "prefill_samples": len(prefill),
        "decode_samples": len(decode),
        "prefill_tokens_per_second": average(prefill_for_speed, prefill_time),
        "generation_tokens_per_second": average(generated_for_speed, decode_time),
        "generation_measured_tokens": int(generated_for_speed),
        "generation_measured_seconds": round(decode_time, 3),
        "measurement_note": "Latency averages include only completed calls. Token averages "
                            "use calls whose provider reported usage. Decode throughput "
                            "uses llama.cpp predicted_n/predicted_ms (or completion tokens "
                            "when predicted_n is missing). Pending/unknown calls are excluded.",
    }
    if stage is not None:
        result["stage"] = stage
    return result


def model_perf_summary(job):
    """Strict model/stage whitelist; no prompt text, paths, or raw responses."""
    starts, ends, loads = {}, {}, []
    for row in json_lines(job / "model-performance.jsonl"):
        model, kind = row.get("model"), row.get("event")
        if model not in PERF_MODELS:
            continue
        if kind == "startup":
            status = row.get("status")
            loads.append({"model": model,
                          "status": status if status in PERF_STATUSES else "failed",
                          "seconds": numeric(row.get("seconds")),
                          "cpu": row.get("cpu") is True})
            continue
        if kind not in ("request_start", "request_end"):
            continue
        ident, stage = row.get("id"), row.get("stage")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident) or stage not in PERF_STAGES:
            continue
        if kind == "request_start":
            starts[ident] = {
                "model": model, "stage": stage,
                "pages": numeric(row.get("pages")),
                "prompt_chars": numeric(row.get("prompt_chars")),
                "thinking": row.get("thinking") is True, "cpu": row.get("cpu") is True,
            }
        else:
            status = row.get("status")
            ends[ident] = {
                "model": model, "stage": stage,
                "status": status if status in PERF_STATUSES else "failed",
                **{field: numeric(row.get(field)) for field in (
                    "seconds", "prompt_tokens", "completion_tokens", "reasoning_tokens",
                    "prompt_ms", "predicted_ms", "prompt_n", "predicted_n")},
                "finish_reason": (row.get("finish_reason")
                                  if row.get("finish_reason") in
                                  ("stop", "length", "tool_calls", "content_filter") else None),
            }

    # A stray END record without START is not evidence of a complete request.
    groups = defaultdict(list)
    models = defaultdict(list)
    all_rows = []
    for ident, start in starts.items():
        end = ends.get(ident)
        if end is not None and (end["model"], end["stage"]) != (start["model"], start["stage"]):
            end = None
        item = (start, end)
        groups[(start["model"], start["stage"])].append(item)
        models[start["model"]].append(item)
        all_rows.append(item)

    by_stage = [_model_statistics(items, model=model, stage=stage)
                for (model, stage), items in sorted(groups.items())]
    by_model = [_model_statistics(items, model=model)
                for model, items in sorted(models.items())]
    overall = _model_statistics(all_rows, model="all_local_models") if all_rows else None
    return {
        "schema_version": 2, "available": bool(starts or loads),
        "requests": len(starts),
        "pending": sum(item["pending"] for item in by_model),
        "startup": loads[-60:],
        "by_model": by_model,
        "by_model_and_stage": by_stage,
        "overall_local_models": overall,
        "note": "Measured response usage only. Pending or missing usage stays unknown; "
                "prefill/decode timing is optional and not equal to HTTP latency.",
    }


def token_ledger_summary(job):
    """Independent provider-wide token accounting, for local AND DeepSeek.

    The private token_usage ledger records actual HTTP responses (including
    ones with invalid generated JSON). This total MUST NOT be added to the
    model profiler's local-token subtotal: they overlap by design.
    """
    entries = {"local": {"calls": 0, "unknown_calls": 0,
                         "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
               "deepseek": {"calls": 0, "unknown_calls": 0,
                            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                            "api_context_cache_hit_tokens": 0,
                            "api_context_cache_miss_tokens": 0,
                            "api_context_cache_reported_calls": 0}}
    available = (job / "token-usage.jsonl").is_file()
    def allowed_count(value):
        return value if type(value) is int and 0 <= value <= 1_000_000_000 else None
    for row in json_lines(job / "token-usage.jsonl"):
        provider = row.get("provider")
        if provider not in entries:
            continue
        dest = entries[provider]
        if row.get("usage_reported") is not True:
            dest["unknown_calls"] += 1
            continue
        tokens = allowed_count(row.get("total_tokens"))
        input_tokens = allowed_count(row.get("prompt_tokens"))
        output_tokens = allowed_count(row.get("completion_tokens"))
        if tokens is None and input_tokens is not None and output_tokens is not None:
            tokens = input_tokens + output_tokens
        if tokens is None:
            dest["unknown_calls"] += 1
            continue
        dest["calls"] += 1
        dest["total_tokens"] += tokens
        if input_tokens is not None:
            dest["prompt_tokens"] += input_tokens
        if output_tokens is not None:
            dest["completion_tokens"] += output_tokens
        if provider == "deepseek":
            cache_hit = allowed_count(row.get("prompt_cache_hit_tokens"))
            cache_miss = allowed_count(row.get("prompt_cache_miss_tokens"))
            if (input_tokens is not None and cache_hit is not None and
                    cache_miss is not None and cache_hit + cache_miss == input_tokens):
                dest["api_context_cache_hit_tokens"] += cache_hit
                dest["api_context_cache_miss_tokens"] += cache_miss
                dest["api_context_cache_reported_calls"] += 1
    remote = entries["deepseek"]
    hit = remote["api_context_cache_hit_tokens"]
    miss = remote["api_context_cache_miss_tokens"]
    # Conservative price estimate for reported replies only:
    # unreported input cache proportions are charged at cache-MISS prices.
    unknown_split = max(0, remote["prompt_tokens"] - hit - miss)
    offpeak = (hit * .003 + (miss + unknown_split) * .15 +
               remote["completion_tokens"] * .60) / 1_000_000
    peak = (hit * .006 + (miss + unknown_split) * .30 +
            remote["completion_tokens"] * 1.20) / 1_000_000
    return {
        "available": available,
        "deepseek_estimated_cost_usd": {
            "off_peak": round(offpeak, 7) if available else None,
            "peak": round(peak, 7) if available else None,
            "missing_usage_calls": remote["unknown_calls"],
            "incomplete_context_breakdown_input_tokens": unknown_split,
            "price_reference": "deepseek-flash-2026-09-10",
            "note": "Partial estimate: provider usage only. Pending and missing-usage "
                    "requests cannot be priced. DeepSeek context-cache hits are billed. "
                    "KADR full-response-cache hits incur no API request.",
        },
        "by_provider": entries,
        "total_reported_tokens": (sum(v["total_tokens"] for v in entries.values())
                                  if available else None),
        "unknown_calls": sum(v["unknown_calls"] for v in entries.values()),
        "note": "Whole-run provider ledger. Includes local and DeepSeek if used. "
                "Unknown calls and pending requests are NOT estimated. "
                "Do not add these totals to the local profiler totals.",
    }


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
    boundary_triage = None
    scene_inference_pages = {"requests": 0, "image_pages": 0, "context_image_pages": 0}
    last = deque(maxlen=30)
    for item in json_lines(job / "diagnostics" / "pipeline" / "timeline.jsonl"):
        stage, action, error = name(item.get("stage")), name(item.get("action")), name(item.get("error_type"))
        seconds = numeric(item.get("elapsed_seconds"))
        if stage:
            actions[stage] += 1
            if stage == "semantic_boundary" and action == "triage":
                # Numeric-only statistics: report VLM calls avoided without
                # exposing decision descriptions, transcript or model prompts.
                boundary_triage = {field: numeric(item.get(field)) for field in
                    ("candidates", "ambiguous", "selected", "deferred", "high_signal",
                     "interval_seconds", "weak_interval_seconds")}
            if stage == "scene_analysis" and action == "request":
                scene_inference_pages["requests"] += 1
                for field in ("image_pages", "context_image_pages"):
                    count = numeric(item.get(field))
                    if count is not None and 0 <= count <= 100:
                        scene_inference_pages[field] += int(count)
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
    trial = json_file(job / "deepseek-story-pilot.json")
    trial = trial if isinstance(trial, dict) else {}
    reservations = trial.get("reserved")
    # Only counts, never source-bearing request hashes or text.
    result["flash_story_pilot"] = {
        "available": trial.get("profile") == "local4b-deepseek-flash-story-pilot-v1",
        "reserved_paid_attempts": (len(reservations) if isinstance(reservations, list)
                                   and len(reservations) <= 8 else None),
        "local_response_cache_hits": (trial.get("local_cache_hits") if
                                      type(trial.get("local_cache_hits")) is int and
                                      0 <= trial["local_cache_hits"] <= 1_000_000 else None),
        "local_story_fallbacks": (trial.get("fallbacks") if
                                  type(trial.get("fallbacks")) is int and
                                  0 <= trial["fallbacks"] <= 1_000_000 else None),
        "max_paid_attempts": 8,
        "note": "HTTP attempt cap, not a guaranteed USD spending cap.",
    }
    result["model_performance"] = model_perf_summary(job)
    result["token_usage_totals"] = token_ledger_summary(job)
    result["optimization"] = {"semantic_boundary_triage": boundary_triage,
                              "visual_context_payload": scene_inference_pages}
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
