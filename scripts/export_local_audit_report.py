"""Allowlisted local benchmark report; never exports source text or raw logs.

Uses stdlib only. Phase-start filtering separates append-only fresh/resume
telemetry. Inclusive model and diagnostics spans remain explicitly labelled.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import re
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_safe_ai_diagnostics import _model_statistics

STAGES = frozenset(("initialization", "prepare", "transcribe", "scenes", "analyze",
    "framing", "planning", "part_context", "rendering", "completed", "pipeline",
    "shot_detection", "media_perception", "scene_detection", "semantic_boundary",
    "scene_analysis", "story_refinement", "global_visual_verification",
    "selection_adjudication", "global_story", "pacing", "global_visual",
    "choose_units", "verify_omissions", "credit_classifier", "source_roles",
    "titles", "general", "selection_gate", "ending_recovery", "final_quality_gate",
    "analysis", "condense", "global_verify", "quality_gate", "final_selection_adjudication",
    "ending_selection_adjudication", "story_structure_analysis", "dialogue_relations"))
MODELS = frozenset(("visual4b", "story9b", "other"))
MODEL_STATUSES = frozenset(("ok", "failed", "cancelled", "retried", "fallback", "timeout"))
RUN_STATUSES = frozenset(("completed", "failed", "timeout", "cancelled", "running"))
GATE_STATUSES = frozenset(("passed", "failed", "blocked", "unresolved", "pending"))
ERROR_TYPES = frozenset(("RuntimeError", "ValueError", "TimeoutError", "InterruptedError",
    "FileNotFoundError", "PermissionError", "OSError", "AssertionError", "HTTPError"))
RESOURCE_FIELDS = ("system_cpu_percent", "system_ram_used_mib", "system_ram_total_mib",
    "system_ram_load_percent", "gpu_utilization_percent", "gpu_memory_used_mib",
    "gpu_memory_total_mib", "gpu_power_w", "gpu_temperature_c")
COLOURS = ("#2563eb", "#d97706", "#059669", "#9333ea", "#e11d48", "#0891b2")


def number(value):
    return round(float(value), 6) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e12 else None


def divide(a, b):
    return round(a / b, 4) if a is not None and b is not None and b > 0 else None


def read_json(path):
    try:
        value = json.loads(Path(path).read_text("utf-8"))
        return value if isinstance(value, (dict, list)) else {}
    except (OSError, ValueError):
        return {}


def lines(path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
                except ValueError:
                    continue  # A live writer can leave an incomplete final row.
    except OSError:
        return


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo is not None else None
    except ValueError:
        return None


def belongs(row, began, key):
    event_time = timestamp(row.get(key))
    return began is not None and event_time is not None and event_time >= began


def phase_file(record, job, name):
    return record / name if (record / name).is_file() else job / name


def performance(rows):
    starts, ends, startups = {}, {}, []
    for row in rows:
        model, event = row.get("model"), row.get("event")
        if model not in MODELS:
            continue
        if event == "startup":
            startups.append({"model": model, "seconds": number(row.get("seconds")),
                "cpu": row.get("cpu") is True,
                "status": row.get("status") if row.get("status") in MODEL_STATUSES else "failed"})
            continue
        ident, stage = row.get("id"), row.get("stage")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident) or stage not in STAGES:
            continue
        if event == "request_start":
            starts[ident] = {"model": model, "stage": stage, "pages": number(row.get("pages")),
                "prompt_chars": number(row.get("prompt_chars")),
                "cpu": row.get("cpu") is True, "thinking": row.get("thinking") is True}
        elif event == "request_end":
            ends[ident] = {"model": model, "stage": stage,
                "status": row.get("status") if row.get("status") in MODEL_STATUSES else "failed",
                "finish_reason": row.get("finish_reason") if row.get("finish_reason") in
                    ("stop", "length", "tool_calls", "content_filter") else None,
                **{key: number(row.get(key)) for key in ("seconds", "prompt_tokens", "completion_tokens",
                    "reasoning_tokens", "prompt_ms", "predicted_ms", "prompt_n", "predicted_n")}}
    by_model, by_purpose = defaultdict(list), defaultdict(list)
    retried = 0
    for ident, start in starts.items():
        end = ends.get(ident)
        if end and (end["model"], end["stage"]) != (start["model"], start["stage"]):
            end = None
        retried += int(bool(end and end["status"] == "retried"))
        by_model[start["model"]].append((start, end))
        by_purpose[start["model"], start["stage"]].append((start, end))
    startup_by_model = []
    for model in sorted({row["model"] for row in startups}):
        group = [row for row in startups if row["model"] == model]
        seconds = [row["seconds"] for row in group if row["seconds"] is not None]
        startup_by_model.append({"model": model, "attempts": len(group),
            "measured_attempts": len(seconds), "sum_seconds": round(sum(seconds), 4),
            "cpu_attempts": sum(row["cpu"] for row in group),
            "statuses": dict(Counter(row["status"] for row in group))})
    return {"request_attempts": len(starts), "retried_outer_spans": retried,
        "time_is_inclusive": True,
        "sum_seconds_additive_without_retries": retried == 0,
        "startup": startup_by_model,
        "by_model": [_model_statistics(group, model=model) for model, group in sorted(by_model.items())],
        "by_model_and_purpose": [_model_statistics(group, model=model, stage=stage)
            for (model, stage), group in sorted(by_purpose.items())]}


def timeline_summary(rows):
    groups = defaultdict(lambda: {"started": 0, "ended": 0, "seconds": 0.0,
        "cache_hits": 0, "cache_misses": 0, "exceptions": 0})
    for row in rows:
        stage, action = row.get("stage"), row.get("action")
        if stage not in STAGES:
            continue
        group = groups[stage]
        if action == "start": group["started"] += 1
        if action == "end" and number(row.get("elapsed_seconds")) is not None:
            group["ended"] += 1
            group["seconds"] += number(row["elapsed_seconds"])
        if action in ("cache_hit", "chunk_cache_hit"): group["cache_hits"] += 1
        if action in ("cache_miss", "chunk_cache_miss"): group["cache_misses"] += 1
        if action == "exception": group["exceptions"] += 1
    return [{"stage": stage, **group,
        "seconds": round(group["seconds"], 4) if group["ended"] else None,
        "unfinished": max(0, group["started"] - group["ended"]), "inclusive": True}
        for stage, group in groups.items()]


def measured_processes(rows):
    results = []
    for name in ("asr_process", "audio_prepare", "media_process", "model_teardown"):
        ends = [row for row in rows if row.get("event") == name + "_end" or
                name == "model_teardown" and row.get("event") == name]
        values = [number(row.get("seconds")) for row in ends]
        values = [value for value in values if value is not None]
        starts = sum(row.get("event") == name + "_start" for row in rows)
        results.append({"name": name, "starts": starts, "completed": len(values),
            "seconds": round(sum(values), 4) if values else None})
    return results


def resource_summary(rows):
    samples = []
    for row in rows:
        if row.get("event") != "resources": continue
        point = {"elapsed_seconds": number(row.get("elapsed_seconds")),
            "stage": row.get("stage") if row.get("stage") in STAGES else "general",
            **{key: number(row.get(key)) for key in RESOURCE_FIELDS}}
        if point["elapsed_seconds"] is not None: samples.append(point)
    gpu = next((row.get("gpu_name") for row in rows if isinstance(row.get("gpu_name"), str)
                and re.fullmatch(r"NVIDIA GeForce (?:RTX|GTX) [0-9]{3,4}(?: Ti| SUPER| Laptop GPU)?", row["gpu_name"])), None)
    statistics = {}
    for key in RESOURCE_FIELDS:
        values = [row[key] for row in samples if row[key] is not None]
        statistics[key] = {"samples": len(values), "sample_mean": round(sum(values)/len(values), 3) if values else None,
            "sample_min": min(values, default=None), "sample_peak": max(values, default=None)}
    return {"scope": "whole_system_including_other_apps", "gpu_name": gpu,
        "samples": len(samples), "statistics": statistics, "trace": samples,
        "peak_definition": "maximum_observed_sample_not_process_peak"}


def current_artifact(record, job, name, complete, began):
    if (record / name).is_file(): return read_json(record / name)
    if complete: return {}
    candidate = read_json(job / name)
    # timings manifests identify their start; observer outcome has no timestamp.
    if name == "timings.json" and belongs(candidate, began, "started_at"):
        return candidate
    return {}


def material_counts(job):
    """Numeric complexity from current checkpoints; no source text or paths."""
    shots = read_json(job / "shots.json")
    scenes = read_json(job / "scenes.json")
    events = read_json(job / "events.json")
    frame_backed = read_json(job / "diagnostics/pipeline/frame_backed_scenes.json")
    evidence = read_json(job / "media-evidence.json")
    boards = read_json(job / "diagnostics/pipeline/storyboard.json")
    coverage = "complete_scene_analysis_checkpoint"
    if not isinstance(boards, list) or not boards:
        boards = [read_json(path) for path in (job / "visual").glob("*.storyboard.json")]
        coverage = "available_visual_metadata_partial"
    frames_by_role, unique_times = Counter(), set()
    pages = 0
    for board in boards:
        if not isinstance(board, dict): continue
        role = board.get("role")
        if role not in ("current", "context_only", "recovery_current", "legacy_overview"):
            role = "context_only" if board.get("context") is True else "unspecified"
        frames = board.get("frames", [])
        frames_by_role[role] += len(frames)
        pages += len(board.get("pages", []))
        unique_times.update(number(frame.get("time")) for frame in frames if isinstance(frame, dict)
                            and number(frame.get("time")) is not None)
    plan = read_json(job / "plan.json")
    parts = plan.get("parts", [])
    parents = []
    for path in (job / "visual").glob("event_*.json"):
        if not re.fullmatch(r'event_[0-9]{4}\.json', path.name): continue
        event = read_json(path).get("event")
        if isinstance(event, dict): parents.append(event)
    technical_chunks = sum(len(parent.get("analysis_chunks", [])) or 1 for parent in parents)
    announcements = []
    for row in lines(job / "observed-progress.jsonl"):
        value = row.get("message")
        if row.get("stage") == "condense" and isinstance(value, str):
            match = re.fullmatch(r'Сокращение по репликам: сцена ([0-9]+) из ([0-9]+)', value)
            if match: announcements.append((int(match.group(1)), int(match.group(2))))
    return {"scope": "current_job_checkpoints_not_per_phase_compute_delta",
        "shots": len(shots) if isinstance(shots, list) else None,
        "semantic_scenes": len(scenes) if isinstance(scenes, list) else None,
        "events_checkpoint": len(events) if isinstance(events, list) else None,
        "semantic_parent_events_checkpoint": len(parents) if parents else None,
        "analysis_technical_chunks_checkpoint": technical_chunks if parents else None,
        "story_refinement_work_items_announced": max((total for _, total in announcements), default=None),
        "story_refinement_last_item_announced_not_completed": announcements[-1][0] if announcements else None,
        "source_video_frames": number(frame_backed.get("source_frame_count")),
        "perception_samples": len(evidence.get("samples", [])) if evidence else None,
        "perception_proposals": len(evidence.get("proposals", [])) if evidence else None,
        "storyboard_metadata_coverage": coverage,
        "storyboard_records": len(boards), "storyboard_frame_slots_by_role": dict(frames_by_role),
        "storyboard_unique_source_times": len(unique_times), "storyboard_page_slots": pages,
        "planned_parts": len(parts) if plan else None,
        "planned_cuts": sum(len(part.get("cuts", [])) for part in parts) if plan else None,
        "planned_output_seconds": round(sum(number(part.get("duration")) or 0 for part in parts), 4) if plan else None}


def phase_summary(root, duration, phase):
    job = root / f"job-{duration}s"
    record = job / "benchmark" / phase
    started = read_json(record / "started.json")
    result = read_json(record / "summary.json")
    exists = bool(started)
    finished = bool(result)
    began = timestamp(started.get("time_utc"))
    measurements = list(lines(record / "measurements.jsonl"))
    timeline_path = record / "timeline.jsonl" if (record / "timeline.jsonl").is_file() else job / "diagnostics/pipeline/timeline.jsonl"
    timeline = [row for row in lines(timeline_path) if belongs(row, began, "time")]
    model_rows = [row for row in lines(phase_file(record, job, "model-performance.jsonl"))
                  if belongs(row, began, "timestamp_utc")]
    timing = current_artifact(record, job, "timings.json", finished, began)
    outcome = current_artifact(record, job, "observed-outcome.json", finished, began)
    probe = read_json(job / "probe.json")
    preparation = read_json(root / f"input-{duration}s/preparation.json")
    settings = preparation.get("settings", {})
    occupancy = read_json(record / "stage-occupancy.json")
    if not isinstance(occupancy, list) or not finished:
        # Only closed progress intervals; the currently running stage is partial.
        occupancy, last, last_time = [], "initialization", 0.0
        for row in measurements:
            stage, at = row.get("stage"), number(row.get("elapsed_seconds"))
            if row.get("event") == "progress" and stage in STAGES and at is not None and stage != last:
                occupancy.append({"stage": last, "seconds": max(0, at-last_time)})
                last, last_time = stage, at
        if measurements:
            last_at = max(number(row.get("elapsed_seconds")) or 0 for row in measurements)
            occupancy.append({"stage": last, "seconds": max(0, last_at-last_time), "partial": True})
    occupancy = [{"stage": row["stage"], "seconds": number(row.get("seconds")),
        "partial": row.get("partial") is True} for row in occupancy if isinstance(row, dict)
        and row.get("stage") in STAGES and number(row.get("seconds")) is not None]
    pipeline_ends = [number(row.get("elapsed_seconds")) for row in timeline
        if row.get("stage") == "pipeline" and row.get("action") == "end"]
    wall = number(timing.get("elapsed_seconds"))
    if wall is None: wall = next((value for value in reversed(pipeline_ends) if value is not None), None)
    source_seconds = number(probe.get("duration")) or duration
    child = read_json(job / "transcript.json") if phase == "fresh" else {}
    process_rows = measured_processes(measurements)
    asr_process = next(row for row in process_rows if row["name"] == "asr_process")
    asr = {"subprocess_seconds": asr_process["seconds"], "subprocess_count": asr_process["completed"],
        "child_seconds": number(child.get("elapsed_seconds")) if asr_process["completed"] else None,
        "child_device": child.get("device") if asr_process["completed"] and child.get("device") in ("cuda", "cpu") else None,
        "repair_candidates": len(child.get("repair_log", [])) if asr_process["completed"] else None,
        "repair_accepted": sum(row.get("status") == "accepted" for row in child.get("repair_log", [])
            if isinstance(row, dict)) if asr_process["completed"] else None,
        "note": "child includes load/decode/repair; subprocess includes Python imports; resume ASR may be cache-only"}
    stages = timing.get("stages_seconds", {})
    top = [{"stage": stage, "seconds": number(stages.get(stage)),
        "availability": "measured" if number(stages.get(stage)) is not None else
            "unfinished_or_not_reached" if exists else "not_started"}
        for stage in ("analysis", "planning", "part_context", "rendering")]
    parts = timing.get("parts", [])
    gate = read_json(record / "final_quality_gate.json")
    latest = max((number(row.get("elapsed_seconds")) or 0 for row in measurements), default=None)
    return {"label": f"{duration}s-{phase}", "input_nominal_seconds": duration, "phase": phase,
        "status": result.get("status") if result.get("status") in RUN_STATUSES else "running" if exists else "not_started",
        "finished": finished, "complete": result.get("complete") is True,
        "error_type": result.get("error_type") if result.get("error_type") in ERROR_TYPES else None,
        "final_quality_gate": gate.get("status") if gate.get("status") in GATE_STATUSES else None,
        "last_stage": result.get("stage_at_end") if result.get("stage_at_end") in STAGES else
            next((row.get("stage") for row in reversed(measurements) if row.get("stage") in STAGES), None),
        "input": {"duration_seconds": source_seconds, "width": number(probe.get("width")),
            "height": number(probe.get("height")), "fps": number(probe.get("fps")),
            "audio_stream": number(probe.get("audio_stream")), "has_audio": probe.get("has_audio") is True if probe else None,
            "excerpt_start_seconds": number(settings.get("start"))},
        "preparation_seconds_excluded": number(preparation.get("seconds")),
        "wall": {"pipeline_seconds": wall, "observer_seconds": number(outcome.get("elapsed_seconds")),
            "benchmark_including_sampler_and_snapshot_seconds": number(result.get("elapsed_seconds")),
            "latest_sample_elapsed_seconds_partial": latest if not finished else None,
            "rtf_pipeline": divide(wall, source_seconds),
            "rtf_scope": "completed_processing" if result.get("complete") is True else "incomplete_attempt_not_full_processing_speed",
            "seconds_per_input_minute": divide(wall * 60 if wall is not None else None, source_seconds)},
        "occupancy": occupancy, "occupancy_sum_seconds": round(sum(row["seconds"] for row in occupancy), 4),
        "top_stages": top, "diagnostic_stages_inclusive": timeline_summary(timeline),
        "processes": process_rows, "asr": asr, "model": performance(model_rows),
        "render": {"parts_recorded": len(parts), "cached_parts": sum(row.get("cached") is True for row in parts),
            "part_seconds_sum_nonadditive": round(sum(number(row.get("seconds")) or 0 for row in parts), 4),
            "encoders": dict(Counter(row.get("encoder") for row in parts
                if row.get("encoder") in ("h264_nvenc", "libx264"))),
            "workers": number(timing.get("render_workers"))},
        "resources": resource_summary(measurements),
        "material": material_counts(job),
        "hardware": {"logical_cpus": number(started.get("logical_cpus"))},
        "metrics_missing": ["process_tree_cpu_rss", "model_specific_vram", "ASR_load_decode_repair_split",
            "TTFT_queue_wait", "image_encoder_time", "render_encode_validation_split"]}


def machine_summary(root):
    raw = read_json(Path(root) / "machine.json")
    candidate = raw.get("cpu_name", "")
    match = re.search(r'\bi[3579]-[0-9]{4,5}[A-Z]{0,3}\b', candidate) if isinstance(candidate, str) else None
    cpu = "Intel Core " + match.group(0) if match else None
    versions = {}
    for key, pattern in (("python_version", r'(?:Python )?([0-9]+\.[0-9]+\.[0-9]+)'),
            ("node_version", r'v?([0-9]+\.[0-9]+\.[0-9]+)'),
            ("ffmpeg_version", r'ffmpeg version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)'),
            ("llama_version", r'([0-9]+\.[0-9]+\.[0-9]+(?:-dev)?)')):
        value = raw.get(key, "")
        found = re.match(pattern, value) if isinstance(value, str) else None
        versions[key] = found.group(1) if found else None
    return {"cpu_name": cpu, "physical_cores": number(raw.get("physical_cores")),
        "logical_cpus": number(raw.get("logical_cpus")), **versions}


def native_warning_flags(job):
    patterns = {
        "auto_fit_blocked_explicit_gpu_layers": r'common_fit_params: failed to fit params to free device memory: n_gpu_layers already set by user to [0-9]+, abort',
        "qwen_grounding_image_minimum_warning": r'load_hparams: Qwen-VL models require at minimum 1024 image tokens',
        "idle_cache_disabled": r'--cache-idle-slots requires --cache-ram, disabling',
        "non_consecutive_token_positions": r'find_slot: non-consecutive token position [0-9]+ after [0-9]+',
    }
    counts = {key: 0 for key in patterns}
    exists = (job / "vision.log").is_file()
    if exists:
        with (job / "vision.log").open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                for key, pattern in patterns.items():
                    counts[key] += int(bool(re.search(pattern, line)))
    return {"available": exists, "scope": "job_cumulative_at_export_not_phase_specific",
        "counts": counts if exists else {key: None for key in patterns},
        "causality": "warnings_do_not_prove_OOM_CPU_fallback_or_Windows_shared_memory_spill"}


def summarize(root):
    root = Path(root)
    phases = [phase_summary(root, duration, phase) for duration in (120, 180)
              for phase in ("fresh", "resume") if phase == "fresh" or
              (root / f"job-{duration}s/benchmark/{phase}/started.json").is_file()]
    return {"schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
        "final": all(row["finished"] for row in phases if row["phase"] == "fresh"),
        "provider": "local", "asr": "Whisper-large-v3", "visual_model": "Qwen3.5-4B",
        "story_model": "Qwen3.5-9B", "phases": phases,
        "machine": machine_summary(root),
        "native_warnings": [{"input_nominal_seconds": duration,
            **native_warning_flags(root / f"job-{duration}s")} for duration in (120, 180)],
        "configuration": {"context_tokens": 8192, "parallel_slots": 1, "gpu_layers_requested": 99,
            "batch": 256, "microbatch": 128, "image_min_tokens": 256, "image_max_tokens": 2048,
            "thinking_additional_output_budget": 512, "prompt_cache_enabled": False,
            "ASR_beam_size": 5, "ASR_word_timestamps": True, "render_workers": 2,
            "layout": "cinema", "caption_style": "classic", "portrait_focus_required": False},
        "notes": ["Fresh/resume telemetry is filtered by phase start UTC; malformed/incomplete rows omitted",
            "Stage occupancy partitions progress states; diagnostics/model timings are inclusive and not additive",
            "Resource readings are whole-system samples, not process-specific measurements",
            "Production is instrumented: recorder image hashing and JSON writes add unmeasured overhead inside pipeline",
            "Preparation excluded; pending or unreached metrics are null, never zero substitutes"]}


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def svg_document(title, body, height=460):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="' + str(height) +
        '" viewBox="0 0 1100 ' + str(height) + '"><rect width="100%" height="100%" fill="#f8fafc"/>'
        '<style>text{font-family:Arial,sans-serif;fill:#0f172a;font-size:14px}.small{font-size:12px;fill:#475569}</style>'
        '<text x="28" y="30" font-size="19">' + escape(title) + '</text>' + body + '</svg>')


def bar_chart(title, rows, note, unit="s"):
    max_value = max((value for _, _, value in rows), default=1) or 1
    body = '<text x="28" y="56" class="small">' + escape(note) + '</text>'
    for index, (label, category, value) in enumerate(rows):
        y = 83 + index * 28
        width = 590 * value / max_value
        body += f'<text x="28" y="{y+14}">{escape(label + " / " + category)}</text>'
        body += f'<rect x="385" y="{y}" width="{width:.2f}" height="19" fill="{COLOURS[index % len(COLOURS)]}" rx="3"/>'
        body += f'<text x="{390+width:.2f}" y="{y+14}" class="small">{value:.2f} {escape(unit)}</text>'
    if not rows: body += '<text x="28" y="105">Нет завершённых измерений</text>'
    return svg_document(title, body, max(170, 112 + len(rows)*28))


def trace_chart(phases):
    metrics = (("system_cpu_percent", "CPU всей системы, %"),
        ("gpu_utilization_percent", "GPU всей системы, %"),
        ("system_ram_used_mib", "RAM всей системы, MiB"),
        ("gpu_memory_used_mib", "VRAM всей системы, MiB"))
    max_time = max((row["elapsed_seconds"] for phase in phases for row in phase["resources"]["trace"]), default=1) or 1
    body = '<text x="28" y="56" class="small">Максимум — по выборке; другие приложения включены. Fresh/resume показаны отдельно.</text>'
    for pindex, phase in enumerate(phases):
        body += f'<text x="{28+pindex*220}" y="80" style="fill:{COLOURS[pindex%6]}">{escape(phase["label"])}</text>'
    for index, (metric, title) in enumerate(metrics):
        top = 110 + index * 150
        max_value = max((row[metric] for phase in phases for row in phase["resources"]["trace"] if row[metric] is not None), default=1) or 1
        if metric.endswith("percent"): max_value = max(100, max_value)
        body += f'<text x="28" y="{top}">{escape(title)}</text><line x1="110" y1="{top+115}" x2="1025" y2="{top+115}" stroke="#cbd5e1"/>'
        body += f'<text x="28" y="{top+23}" class="small">{max_value:.1f}</text>'
        for pindex, phase in enumerate(phases):
            trace = phase["resources"]["trace"]
            step = max(1, math.ceil(len(trace)/1800))
            points = ' '.join(f'{110+row["elapsed_seconds"]/max_time*915:.2f},{top+115-row[metric]/max_value*95:.2f}'
                for row in trace[::step] if row[metric] is not None)
            if points: body += f'<polyline fill="none" stroke="{COLOURS[pindex%6]}" stroke-width="1.4" points="{points}"/>'
        body += f'<text x="110" y="{top+134}" class="small">0 s</text><text x="950" y="{top+134}" class="small">{max_time:.0f} s</text>'
    return svg_document("Ресурсы во времени", body, 750)


def fmt(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "не измерено"


def markdown(data):
    text = ["# Локальные замеры обработки KADR", "",
        "Статус отчёта: **" + ("все первые попытки завершены" if data["final"] else "предварительный: измерения ещё выполняются") + "**.", "",
        "Целевой предел пользователя для 180 секунд исходника — **30 минут (1800 с)**. Исторические попытки ниже получили лимит 3600 с до уточнения требования; обе не завершили монтаж. Это провал по скорости, а не допустимое время обработки. Новые benchmark-запуски по умолчанию ограничены 1800 с.", "",
        "Провайдер local: настоящий Whisper large-v3, Qwen3.5 4B и 9B, штатные критерии качества. Подготовка видео вынесена из времени обработки. "
        "Ошибка или таймаут означает незавершённый полный монтаж; измеренные предыдущие этапы остаются полезными. "
        "Условия: layout=cinema, caption_style=classic, ASR распознаётся заново на fresh. Portrait focus9B для этого layout не требуется.", "",
        "Замеры выполнены с диагностическим observer: он хэширует изображения, сохраняет запросы/ответы и schema, а sampler опрашивает ресурсы. "
        "Этот overhead внутри production отдельно не измерен; время не является uninstrumented baseline. Разница observer и pipeline wall не равна всему overhead.", "",
        "| Вход / попытка | Статус | Полный результат | Pipeline, с | Observer, с | RTF | с на минуту входа | Подготовка отдельно, с |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in data["phases"]:
        wall = row["wall"]
        text.append(f'| {row["label"]} | {row["status"]} | {"да" if row["complete"] else "нет"} | {fmt(wall["pipeline_seconds"])} | '
            f'{fmt(wall["observer_seconds"])} | {fmt(wall["rtf_pipeline"])} | {fmt(wall["seconds_per_input_minute"])} | {fmt(row["preparation_seconds_excluded"])} |')
    text += ["", "RTF = секунды pipeline / секунды входа. Например RTF10 означает десять минут обработки одной минуты видео. "
        "Для failed/timeout это незавершённая попытка до прерывания: её RTF не является скоростью готового монтажа. Наблюдённое время — нижняя граница полного времени при продолжении оставшейся работы. "
        "Нельзя сравнивать такой RTF со скоростью completed как равнозначный результат. "
        "Benchmark summary включает остановку sampler и snapshots; его wall отличается от pipeline/observer. Fresh означает новый application cache; кэш диска Windows не сбрасывался.",
        "", "![Верхние стадии](measurements/stage-comparison.svg)", "",
        "![Progress occupancy](measurements/progress-occupancy.svg)", "",
        "![Workload fanout](measurements/workload-fanout.svg)", "",
        "| Попытка / checkpoints | Shots | Semantic scenes | Parents | Technical chunks | Story work items announced |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in data["phases"]:
        counts = row["material"]
        text.append(f'| {row["label"]} | {counts["shots"]} | {counts["semantic_scenes"]} | {counts["semantic_parent_events_checkpoint"]} | '
            f'{counts["analysis_technical_chunks_checkpoint"]} | {counts["story_refinement_work_items_announced"]} |')
    text += ["", "Это разрастание числа технических задач. Story work items объединяются обратно в semantic parents; checkpoint count не равен числу завершённых9B запросов.",
        "", "## Каждый этап и состояние попытки", ""]
    for row in data["phases"]:
        text += [f'### {row["label"]}', "", f'Статус: {row["status"]}; последняя стадия: {row["last_stage"] or "не началась"}; '
            f'ошибка: {row["error_type"] or "не зарегистрирована"}; final gate: {row["final_quality_gate"] or "нет результата"}.', "",
            "| Верхняя стадия | Секунды | Доступность |", "| --- | ---: | --- |"]
        for stage in row["top_stages"]: text.append(f'| {stage["stage"]} | {fmt(stage["seconds"])} | {stage["availability"]} |')
        text += ["", f'ASR subprocess: **{fmt(row["asr"]["subprocess_seconds"])} с**; child load+decode+repair: '
            f'**{fmt(row["asr"]["child_seconds"])} с**; устройство: {row["asr"]["child_device"] or "не выполнялся / неизвестно"}; '
            f'repair candidates/accepted: {row["asr"]["repair_candidates"]}/{row["asr"]["repair_accepted"]}.', "",
            "| Состояние progress | Секунды occupancy | Частично |", "| --- | ---: | --- |"]
        for stage in row["occupancy"]: text.append(f'| {stage["stage"]} | {fmt(stage["seconds"])} | {"да" if stage["partial"] else "нет"} |')
        text += ["", "Occupancy делит время между сообщениями progress и включает внутренние этапы. Это отдельное представление wall, "
            "его нельзя прибавлять к верхним стадиям или model timings.", "",
            "| Вложенная диагностика | Секунды inclusive | Незавершено | Cache hit/miss |", "| --- | ---: | ---: | --- |"]
        for stage in row["diagnostic_stages_inclusive"]:
            text.append(f'| {stage["stage"]} | {fmt(stage["seconds"])} | {stage["unfinished"]} | {stage["cache_hits"]}/{stage["cache_misses"]} |')
        text += ["", "| Модель / назначение | Попытки / pending / failed | Latency P50 / P95, с | Input / output tokens | Prefill / decode, tokens/s | Pages | CPU |",
            "| --- | --- | --- | --- | --- | ---: | ---: |"]
        for model in row["model"]["by_model_and_purpose"]:
            text.append(f'| {model["model"]}/{model["stage"]} | {model["requests"]}/{model["pending"]}/{model["failed"]} | '
                f'{fmt(model["latency_p50_s"])}/{fmt(model["latency_p95_s"])} | {model["prompt_tokens"]}/{model["completion_tokens"]} | '
                f'{fmt(model["prefill_tokens_per_second"])}/{fmt(model["generation_tokens_per_second"])} | {model["image_pages"]} | {model["cpu_requests"]} |')
        text += ["", "| Загрузка модели | Попыток | CPU | Сумма измеренных попыток, с |", "| --- | ---: | ---: | ---: |"]
        for startup in row["model"]["startup"]:
            text.append(f'| {startup["model"]} | {startup["attempts"]} | {startup["cpu_attempts"]} | {fmt(startup["sum_seconds"])} |')
        text += ["", f'Model request attempts: {row["model"]["request_attempts"]}; nested retried spans: {row["model"]["retried_outer_spans"]}. '
            "Request latency — inclusive; при retry внешнее время содержит внутреннюю попытку и startup. Tokens — только reported usage завершённых HTTP-ответов; pending/unknown не оценивались. "
            "Pages не равны frames. ASR import/load/decode/repair отдельно не выделены.", "",
            f'Render: частей зафиксировано {row["render"]["parts_recorded"]}; cached {row["render"]["cached_parts"]}; '
            f'actual encoders: {json.dumps(row["render"]["encoders"], ensure_ascii=False)}. Сумма per-part секунд не является wall при параллельном рендере.', ""]
        material = row["material"]
        text += [f'Сложность материала по доступным checkpoints: shots={material["shots"]}, scenes={material["semantic_scenes"]}, '
            f'final events={material["events_checkpoint"]}, semantic parent events={material["semantic_parent_events_checkpoint"]}, '
            f'technical chunks={material["analysis_technical_chunks_checkpoint"]}, story refinement work items announced={material["story_refinement_work_items_announced"]}, '
            f'perception samples={material["perception_samples"]}, '
            f'реальных source video frames={material["source_video_frames"]}; storyboard slots={json.dumps(material["storyboard_frame_slots_by_role"], ensure_ascii=False)}, '
            f'уникальных source times={material["storyboard_unique_source_times"]}, page slots={material["storyboard_page_slots"]}. '
            f'План: parts={material["planned_parts"]}, cuts={material["planned_cuts"]}, output={fmt(material["planned_output_seconds"])} с. '
            "Это состояние checkpoint, а не число заново вычисленных кадров конкретной попытки. Work items — технические дети смысловых сцен: "
            "после проверки они объединяются обратно в родителей; это не количество итоговых сюжетных событий. Индекс announced означает начало пункта, а не его завершение.", ""]
    machine = data["machine"]
    text += ["## Модель и ресурсы", "",
        f'Машина: {machine["cpu_name"] or "CPU не определён"}; физических ядер {machine["physical_cores"]}, '
        f'логических {machine["logical_cpus"]}. Python {machine["python_version"] or "не измерено"}, '
        f'Node {machine["node_version"] or "не измерено"}, FFmpeg {machine["ffmpeg_version"] or "не измерено"}.', "",
        "![Model request inclusive time](measurements/model-time.svg)", "",
        "![Resource trace](measurements/resource-trace.svg)", "",
        "| Попытка | GPU | Samples | CPU mean/peak, % | RAM sample peak, MiB | VRAM sample peak, MiB |", "| --- | --- | ---: | --- | ---: | ---: |"]
    for row in data["phases"]:
        stats = row["resources"]["statistics"]
        text.append(f'| {row["label"]} | {row["resources"]["gpu_name"] or "не измерено"} | {row["resources"]["samples"]} | '
            f'{fmt(stats["system_cpu_percent"]["sample_mean"])}/{fmt(stats["system_cpu_percent"]["sample_peak"])} | '
            f'{fmt(stats["system_ram_used_mib"]["sample_peak"])} | {fmt(stats["gpu_memory_used_mib"]["sample_peak"])} |')
    text += ["", "Ресурсы измерены для всей системы, включая другие приложения. Peak означает максимальный sample; между samples возможен более высокий пик. "
        "Mean — среднее по samples, не интеграл времени. PID-specific RSS/CPU/VRAM, TTFT, очередь, image encoder, ASR split и encode/validation split пока отсутствуют.", "",
        "## Предупреждения portable llama.cpp и следующий эксперимент", "",
        "| Вход | Auto-fit заблокирован explicit GPU layers | Qwen grounding image minimum | Idle cache disabled | Nonconsecutive positions |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for warning in data["native_warnings"]:
        counts = warning["counts"]
        text.append(f'| {warning["input_nominal_seconds"]} с | {counts["auto_fit_blocked_explicit_gpu_layers"]} | '
            f'{counts["qwen_grounding_image_minimum_warning"]} | {counts["idle_cache_disabled"]} | {counts["non_consecutive_token_positions"]} |')
    text += ["", "Это allowlisted счётчики всего vision.log задания на момент экспорта; per-phase attribution отсутствует. Сырые строки не публикуются. "
        "Auto-fit abort завершает подбор параметров, а не обязательно сервер: baseline действительно продолжал запуск и ответы. "
        "Указанные `-ngl99` и `-c8192` фиксируют настройки, которые штатный `--fit` может менять только если они не заданы. "
        "Медленная9B требует отдельного A/B: сначала auto GPU layers при том же контексте8192, модели, исходнике и gate, с детальными buffer/offload логами и throughput; "
        "затем отдельно image-min256→1024 с оценкой выбранных диапазонов/кадрирования и увеличения image tokens. "
        "Warning о grounding — повод проверить качество, а не доказательство неверного анализа. Нельзя выводить Windows shared-VRAM spill из одного предупреждения, system RAM или CPUfallback=false.", "",
        "Локально проверенный portable runtime использует Vulkan0; Whisper использует отдельный CUDA backend. Исходные параметры baseline не изменялись.", "",
        "Данные: [JSON](measurements/local-benchmark.json), [попытки CSV](measurements/attempts.csv), [этапы CSV](measurements/stages.csv), "
        "[модели CSV](measurements/models.csv), [resources CSV](measurements/resources.csv). Методика: [performance-design.md](performance-design.md).", "",
        "Sanitized экспорт не содержит prompt, ASR text, paths источников, raw response, текст исключений или произвольные строки из console.log. "
        "Повторный запуск генератора после завершения обеих попыток заменяет предварительные значения окончательными.", ""]
    # No arbitrary strings are interpolated; None is the public missing-value
    # marker in count-only cells as well as the numeric fmt() columns.
    return '\n'.join(text).replace("None", "не измерено")


def export(data, output):
    output.mkdir(parents=True, exist_ok=True)
    assets = output / "measurements"
    assets.mkdir(exist_ok=True)
    (assets / "local-benchmark.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding="utf-8")
    attempts, stage_rows, model_rows, resource_rows, workload_rows = [], [], [], [], []
    for phase in data["phases"]:
        attempts.append({"attempt": phase["label"], "status": phase["status"], "complete": phase["complete"],
            "input_seconds": phase["input"]["duration_seconds"], **phase["wall"],
            "preparation_seconds_excluded": phase["preparation_seconds_excluded"]})
        for category, rows in (("top_stage", phase["top_stages"]), ("occupancy", phase["occupancy"]),
                               ("nested_inclusive", phase["diagnostic_stages_inclusive"])):
            stage_rows.extend({"attempt": phase["label"], "type": category, "stage": row["stage"],
                "seconds": row["seconds"], "availability": row.get("availability"), "partial": row.get("partial"),
                "unfinished": row.get("unfinished"), "cache_hits": row.get("cache_hits"), "cache_misses": row.get("cache_misses")} for row in rows)
        model_rows.extend({"attempt": phase["label"], **row} for row in phase["model"]["by_model_and_purpose"])
        resource_rows.extend({"attempt": phase["label"], **row} for row in phase["resources"]["trace"])
        workload_rows.append({"attempt": phase["label"], **phase["material"]})
    write_csv(assets / "attempts.csv", attempts, list(attempts[0]) if attempts else ["attempt"])
    write_csv(assets / "stages.csv", stage_rows, ("attempt", "type", "stage", "seconds", "availability", "partial", "unfinished", "cache_hits", "cache_misses"))
    write_csv(assets / "models.csv", model_rows, ("attempt", "model", "stage", "requests", "completed", "pending", "failed", "sum_request_seconds",
        "latency_p50_s", "latency_p95_s", "prompt_tokens", "completion_tokens", "unknown_token_calls", "image_pages", "cpu_requests",
        "thinking_requests", "finish_length_calls", "prefill_tokens_per_second", "generation_tokens_per_second"))
    write_csv(assets / "resources.csv", resource_rows, ("attempt", "elapsed_seconds", "stage", *RESOURCE_FIELDS))
    write_csv(assets / "workload.csv", workload_rows, ("attempt", "shots", "semantic_scenes", "semantic_parent_events_checkpoint",
        "analysis_technical_chunks_checkpoint", "story_refinement_work_items_announced", "story_refinement_last_item_announced_not_completed",
        "source_video_frames", "perception_samples", "storyboard_records", "storyboard_unique_source_times", "storyboard_page_slots",
        "planned_parts", "planned_cuts", "planned_output_seconds", "scope"))
    stage_bars = [(phase["label"], row["stage"], row["seconds"]) for phase in data["phases"]
                  for row in phase["top_stages"] if row["seconds"] is not None]
    model_bars = [(phase["label"], row["model"] + '/' + row["stage"], row["sum_request_seconds"])
                  for phase in data["phases"] for row in phase["model"]["by_model_and_purpose"] if row["completed_timed_calls"]]
    occupancy_bars = []
    fanout_bars = []
    for phase in data["phases"]:
        totals = Counter()
        for row in phase["occupancy"]: totals[row["stage"]] += row["seconds"]
        occupancy_bars.extend((phase["label"], stage, seconds) for stage, seconds in totals.items())
        for key in ("shots", "semantic_scenes", "semantic_parent_events_checkpoint", "analysis_technical_chunks_checkpoint", "story_refinement_work_items_announced"):
            value = phase["material"][key]
            label = {"shots": "планы shots", "semantic_scenes": "смысловые сцены",
                "semantic_parent_events_checkpoint": "родительские события", "analysis_technical_chunks_checkpoint": "technical chunks",
                "story_refinement_work_items_announced": "story work items"}[key]
            if value is not None: fanout_bars.append((phase["label"], label, value))
    (assets / "stage-comparison.svg").write_text(bar_chart("Верхние последовательные этапы", stage_bars,
        "Fresh/resume разделены; отсутствующий timer не означает нулевую длительность"), encoding="utf-8")
    (assets / "progress-occupancy.svg").write_text(bar_chart("Время по состояниям progress", occupancy_bars,
        "Partition между progress messages; partial содержит незавершённый текущий интервал; не складывать с model time"), encoding="utf-8")
    (assets / "workload-fanout.svg").write_text(bar_chart("Разрастание работы: планы, сцены, технические дети", fanout_bars,
        "Checkpoint counts; story work items не равны итоговым сюжетным событиям; current job, не fresh/resume compute delta", unit="items"), encoding="utf-8")
    (assets / "model-time.svg").write_text(bar_chart("Время model requests по назначению", model_bars,
        "Inclusive сумма запросов; не прибавлять к анализу; nested retries могут перекрываться"), encoding="utf-8")
    (assets / "resource-trace.svg").write_text(trace_chart(data["phases"]), encoding="utf-8")
    (output / "performance-results.md").write_text(markdown(data), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/audit")
    parser.add_argument("--require-finished", action="store_true")
    args = parser.parse_args(argv)
    for path in (args.benchmark_dir, args.output_dir):
        if not path.resolve().is_relative_to(ROOT.resolve()): parser.error("Paths must stay inside the project")
    data = summarize(args.benchmark_dir)
    if args.require_finished and not data["final"]:
        parser.error("Both fresh attempts must finish before final report generation")
    export(data, args.output_dir)
    print(json.dumps({"final": data["final"], "attempts": [{"label": row["label"], "status": row["status"]} for row in data["phases"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
