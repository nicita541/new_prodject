"""Only non-sensitive metadata may leave a local full-model verification."""
import json
from scripts.export_safe_ai_diagnostics import main, summarize


def put(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_failed_test_exports_diagnostics_but_never_dialogues_or_prompts(tmp_path):
    run = tmp_path / "run"
    folder = run / "real_model_3min"
    job = folder / "real-job"
    secret = "VERY_PRIVATE_DIALOGUE_WITH_API_PASSWORD_123"
    put(folder / "report.json", {"status": "failed", "error_type": "RuntimeError",
        "error": secret, "duration_seconds": 180,
        "checks": [{"name": "genuine_production_analysis_to_final_mp4",
                    "status": "failed", "error_type": "ValueError",
                    "seconds": 540.609, "error": secret}]})
    put(job / "observed-outcome.json", {"complete": False, "error_type": "ValueError",
        "error": secret, "elapsed_seconds": 537.2, "pipeline_code_stable": True})
    put(job / "scenes.json", [{"start": 0, "end": .5, "summary": secret},
                               {"start": .5, "end": 180, "summary": secret}])
    put(job / "actual-model" / "request-001.json", {"prompt": secret, "model": secret})
    put(job / "actual-model" / "response-001.json", {"elapsed_seconds": 4.6,
                                                      "response": {"text": secret}})
    put(job / "actual-model" / "request-002.json", {"prompt": secret})
    put(job / "actual-model" / "response-002.json",
        {"elapsed_seconds": 9.1, "error_type": "TimeoutError", "error": secret})
    put(job / "actual-model" / "request-003.json", {"prompt": secret})
    timeline = job / "diagnostics/pipeline/timeline.jsonl"
    timeline.parent.mkdir(parents=True, exist_ok=True)
    timeline.write_text("\n".join(json.dumps(x) for x in [
        {"stage": "scenes", "action": "end", "elapsed_seconds": 20, "error": secret},
        {"stage": "condense", "action": "exception", "error_type": "ValueError",
         "error": secret, "local_path": secret},
        {"stage": secret, "action": secret, "error_type": secret},
    ]), encoding="utf-8")
    put(job / "observed-progress.jsonl", {"stage": "condense", "progress": .4893,
                                          "message": secret})
    output = tmp_path / "published/ai_diagnostics.json"
    assert main(["--test-dir", str(run), "--output", str(output)]) == 0
    raw = output.read_text("utf-8")
    assert secret not in raw and "prompt" not in raw and "response" not in raw
    data = json.loads(raw)
    assert data["real_e2e"]["status"] == "failed"
    assert data["real_e2e"]["error_type"] == "RuntimeError"
    assert data["real_e2e"]["steps"][0]["seconds"] == 540.609
    assert data["production"]["complete"] is False
    assert data["scene_durations"]["below_1s"] == 1
    assert data["model_requests"]["requests"] == 3
    assert data["model_requests"]["responses"] == 2
    assert data["model_requests"]["pending"] == 1
    assert data["model_requests"]["errors"] == {"TimeoutError": 1}
    assert data["timeline"]["duration_seconds_by_stage"] == {"scenes": 20.0}
    assert data["timeline"]["issues"] == [{"stage": "condense", "type": "ValueError", "count": 1}]
    assert data["progress"]["last_20"][0]["progress"] == .4893


def test_missing_and_timed_out_partial_jobs_also_export(tmp_path):
    absent = summarize(tmp_path / "not-exists")
    assert absent["available"] is False
    assert absent["model_requests"]["requests"] == 0
    job = tmp_path / "real_model_3min/real-job"
    job.mkdir(parents=True)
    partial = summarize(tmp_path)
    assert partial["available"] is True
    assert partial["production"]["complete"] is None
