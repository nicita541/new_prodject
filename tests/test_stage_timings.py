"""End-to-end timing summaries: monotonic steps, nested stages, privacy and old-run fallback."""
import json

from scripts.export_stage_timings import summarize, main


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_complete_timing_safely_distinguishes_sequential_checks_and_nested_pipeline(tmp_path):
    private = "DIALOGUE_PASSWORD_SECRET_MODEL_LOCATION"
    run = tmp_path / "test"
    put(run / "timing_snapshot.local.json", {
        "elapsed_seconds": 600.0, "checks": [
            {"name": "python_tests", "status": "PASS", "elapsed_seconds": 20,
             "note": private},
            {"name": "full_pipeline_3min", "status": "PASS", "elapsed_seconds": 130},
            {"name": "real_model_3min", "status": "FAIL", "elapsed_seconds": 450},
            {"name": private, "status": private, "elapsed_seconds": 1000},
        ]
    })
    put(run / "full_pipeline_3min/report.json", {"status": "passed",
        "checks": [{"name": "real_pipeline_plan_and_ffmpeg_render",
                    "status": "passed", "seconds": 110,
                    "error": private}]})
    put(run / "real_model_3min/report.json", {"status": "failed",
        "checks": [{"name": "genuine_production_analysis_to_final_mp4",
                    "status": "failed", "seconds": 400, "error": private}]})
    job = run / "real_model_3min/real-job"
    put(job / "observed-outcome.json", {"elapsed_seconds": 400, "error": private})
    model = job / "actual-model"
    put(model / "request-001.json", {"prompt": private})
    put(model / "response-001.json", {"elapsed_seconds": 5, "response": private})
    put(model / "request-002.json", {"prompt": private})
    put(model / "response-002.json", {"elapsed_seconds": 7, "response": private})
    timeline = job / "diagnostics/pipeline/timeline.jsonl"
    timeline.parent.mkdir(parents=True, exist_ok=True)
    timeline.write_text("\n".join(json.dumps(x) for x in [
        {"stage": "pipeline", "action": "start", "message": private},
        {"stage": "scenes", "action": "start"},
        {"stage": "semantic_boundary", "action": "start"},
        {"stage": "semantic_boundary", "action": "end", "elapsed_seconds": 300},
        {"stage": "scenes", "action": "end", "elapsed_seconds": 350},
        {"stage": private, "action": "end", "elapsed_seconds": 1000},
        {"stage": "pipeline", "action": "end", "elapsed_seconds": 400},
    ]), encoding="utf-8")

    output = tmp_path / "public/stage_timings.json"
    assert main(["--test-dir", str(run), "--output", str(output)]) == 0
    text = output.read_text("utf-8") + output.with_suffix(".md").read_text("utf-8")
    assert private not in text and '"prompt":' not in text and '"response": "' not in text
    result = json.loads(output.read_text("utf-8"))
    assert result["total"]["seconds_until_report_generation"] == 600
    assert [step["name"] for step in result["verification_checks"]] == [
        "python_tests", "full_pipeline_3min", "real_model_3min"]
    assert result["verification_checks"][0]["share_of_test_pct"] == 3.33
    assert [x["stage"] for x in result["real_production"]["stage_order"]] == [
        "pipeline", "scenes", "semantic_boundary"]
    assert result["real_production"]["slowest_detailed_stage"]["stage"] == "semantic_boundary"
    assert result["real_production"]["slowest_detailed_stage"]["seconds"] == 300
    assert result["bottlenecks"]["slowest_verification_check"]["name"] == "real_model_3min"
    assert result["model_inference"]["sum_response_seconds"] == 12
    assert "INCLUSIVE" in text


def test_old_run_without_check_timings_never_invents_total_or_percentages(tmp_path):
    put(tmp_path / "checks.json", {
        "overall": "FAIL", "checks": [
            {"name": "real_model_3min", "status": "FAIL", "note": "secret C:\\video.mp4"}
        ]
    })
    result = summarize(tmp_path)
    assert result["total"]["seconds_until_report_generation"] is None
    assert result["total"]["measurement"] == "unavailable_old_run"
    assert result["verification_checks"][0]["seconds"] is None
    assert result["verification_checks"][0]["share_of_test_pct"] is None
