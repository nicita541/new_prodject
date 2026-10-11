"""Sanitized genuine-benchmark exports: phase isolation, privacy and incomplete work."""
import json
from xml.etree import ElementTree

from scripts.export_local_audit_report import export, performance, summarize


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def put_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding="utf-8")


def request(ident, when, *, status="ok", seconds=3):
    common = {"id": ident, "model": "visual4b", "stage": "scene_analysis", "timestamp_utc": when}
    return [{**common, "event": "request_start", "pages": 2, "prompt_chars": 100,
             "thinking": False, "cpu": False},
            {**common, "event": "request_end", "seconds": seconds, "status": status,
             "prompt_tokens": 20, "completion_tokens": 10, "prompt_n": 20,
             "predicted_n": 10, "prompt_ms": 100, "predicted_ms": 200, "finish_reason": "stop"}]


def test_report_keeps_private_text_out_of_all_artifacts_and_preserves_inclusive_metrics(tmp_path):
    private = "SECRET_DIALOGUE_PASSWORD_SOURCE_PATH"
    put(tmp_path / "machine.json", {"cpu_name": "12th Gen Intel(R) Core(TM) i5-12600KF",
        "physical_cores": 10, "logical_cpus": 16, "python_version": "Python 3.12.14",
        "node_version": "v24.15.0", "ffmpeg_version": "ffmpeg version 8.0.1 " + private,
        "note": private})
    job = tmp_path / "job-120s"
    phase = job / "benchmark/fresh"
    put(phase / "started.json", {"time_utc": "2026-10-11T01:00:00+00:00", "source": private})
    put(phase / "summary.json", {"status": "failed", "elapsed_seconds": 100,
        "stage_at_end": "analyze", "error_type": "RuntimeError", "error": private})
    put(phase / "timings.json", {"elapsed_seconds": 90, "stages_seconds": {"analysis": 80},
        "identity": {"source": private}, "parts": []})
    put(phase / "observed-outcome.json", {"elapsed_seconds": 93, "error": private})
    put(job / "probe.json", {"duration": 120, "width": 1920, "height": 1080, "fps": 24})
    put(job / "transcript.json", {"elapsed_seconds": 5, "device": "cuda", "text": private,
        "repair_log": [{"status": "accepted", "original_text": private}]})
    put(job / "visual/event_0000.json", {"event": {"analysis_chunks": [{}, {}], "summary": private}})
    put_lines(job / "observed-progress.jsonl", [
        {"stage": "condense", "message": "Сокращение по репликам: сцена 5 из 52"},
        {"stage": "condense", "message": private},
    ])
    put_lines(phase / "measurements.jsonl", [
        {"event": "asr_process_start", "stage": "transcribe", "elapsed_seconds": 1},
        {"event": "asr_process_end", "stage": "transcribe", "elapsed_seconds": 7, "seconds": 6},
        {"event": "resources", "elapsed_seconds": 2, "stage": "transcribe",
         "system_cpu_percent": 20, "gpu_name": private, "source": private},
    ])
    put_lines(phase / "timeline.jsonl", [
        {"time": "2026-10-11T01:00:01Z", "stage": "pipeline", "action": "start"},
        {"time": "2026-10-11T01:01:00Z", "stage": "scene_analysis", "action": "end", "elapsed_seconds": 50, "message": private},
        {"time": "2026-10-11T01:01:30Z", "stage": "pipeline", "action": "end", "elapsed_seconds": 90},
    ])
    put_lines(phase / "model-performance.jsonl", request('a'*32, "2026-10-11T01:00:10Z"))
    (job / "vision.log").write_text(
        "common_fit_params: failed to fit params to free device memory: n_gpu_layers already set by user to 99, abort " + private + "\n"
        "load_hparams: Qwen-VL models require at minimum 1024 image tokens " + private + "\n", encoding="utf-8")
    data = summarize(tmp_path)
    export(data, tmp_path / "public")
    outputs = list((tmp_path / "public").rglob('*'))
    for path in outputs:
        if path.is_file():
            assert private not in path.read_text("utf-8-sig")
            if path.suffix == '.svg': ElementTree.parse(path)
    measured = data["phases"][0]
    assert measured["wall"]["rtf_pipeline"] == .75
    assert measured["asr"]["subprocess_seconds"] == 6
    assert measured["asr"]["child_seconds"] == 5
    assert measured["top_stages"][1]["seconds"] is None
    assert measured["model"]["by_model"][0]["generation_tokens_per_second"] == 50
    assert measured["wall"]["rtf_scope"] == "incomplete_attempt_not_full_processing_speed"
    assert measured["material"]["semantic_parent_events_checkpoint"] == 1
    assert measured["material"]["analysis_technical_chunks_checkpoint"] == 2
    assert measured["material"]["story_refinement_work_items_announced"] == 52
    assert data["final"] is False  # The 180s attempt has not started.
    assert data["machine"]["cpu_name"] == "Intel Core i5-12600KF"
    assert data["machine"]["ffmpeg_version"] == "8.0.1"
    assert data["native_warnings"][0]["counts"]["auto_fit_blocked_explicit_gpu_layers"] == 1
    assert data["native_warnings"][0]["counts"]["qwen_grounding_image_minimum_warning"] == 1


def test_partial_resume_excludes_fresh_telemetry_and_stale_outcome(tmp_path):
    job = tmp_path / "job-120s"
    phase = job / "benchmark/resume"
    put(phase / "started.json", {"time_utc": "2026-10-11T02:00:00Z"})
    put(job / "timings.json", {"started_at": "2026-10-11T01:00:00Z", "elapsed_seconds": 100})
    put(job / "observed-outcome.json", {"elapsed_seconds": 101, "complete": True})
    put_lines(job / "model-performance.jsonl", [
        *request('a'*32, "2026-10-11T01:00:10Z", seconds=90),
        *request('b'*32, "2026-10-11T02:00:10Z", seconds=2),
    ])
    put_lines(job / "diagnostics/pipeline/timeline.jsonl", [
        {"time": "2026-10-11T01:01:40Z", "stage": "pipeline", "action": "end", "elapsed_seconds": 100},
        {"time": "2026-10-11T02:00:01Z", "stage": "pipeline", "action": "start"},
    ])
    data = summarize(tmp_path)
    resume = next(row for row in data["phases"] if row["phase"] == "resume")
    assert resume["status"] == "running"
    assert resume["wall"]["pipeline_seconds"] is None
    assert resume["wall"]["observer_seconds"] is None
    assert resume["model"]["request_attempts"] == 1
    assert resume["model"]["by_model"][0]["sum_request_seconds"] == 2
    assert resume["diagnostic_stages_inclusive"][0]["unfinished"] == 1


def test_nested_model_retry_is_explicitly_nonadditive_and_unfinished_request_stays_pending():
    rows = [*request('a'*32, "2026-10-11T01:00:00Z", status="retried", seconds=20),
            *request('b'*32, "2026-10-11T01:00:01Z", seconds=10),
            request('c'*32, "2026-10-11T01:00:02Z")[0]]
    summary = performance(rows)
    assert summary["sum_seconds_additive_without_retries"] is False
    assert summary["retried_outer_spans"] == 1
    assert summary["request_attempts"] == 3
    assert summary["by_model"][0]["pending"] == 1
    assert summary["by_model"][0]["sum_request_seconds"] == 30  # Inclusive, never claimed as wall.
