"""Actual token accounting and speed comparisons for local 4B/9B inference.

No network or models required. Real provider timings are simulated exactly;
pending requests and absent usage must never be turned into estimated tokens.
"""
import json
from pathlib import Path

from scripts.export_safe_ai_diagnostics import model_perf_summary, token_ledger_summary, summarize as safe_summary
from scripts.export_stage_timings import summarize, markdown, main


def append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as writer:
        writer.write(json.dumps(row, ensure_ascii=False) + "\n")


def query(job, ident, model, stage, *, elapsed=None, prompt=None, generated=None,
          predicted_ms=None, predicted_n=None, prompt_ms=None, prompt_n=None):
    append(job / "model-performance.jsonl", {
        "event": "request_start", "id": f"{ident:032x}",
        "model": model, "stage": stage, "pages": 1,
        "prompt_chars": 100, "thinking": model == "story9b", "cpu": False,
        "prompt": "PRIVATE_CANNOT_EXPORT_ME",
    })
    if elapsed is not None:
        data = {"event": "request_end", "id": f"{ident:032x}",
                "model": model, "stage": stage, "status": "ok",
                "seconds": elapsed, "prompt_tokens": prompt,
                "completion_tokens": generated, "predicted_ms": predicted_ms,
                "predicted_n": predicted_n, "prompt_ms": prompt_ms,
                "prompt_n": prompt_n, "response": "PRIVATE_CANNOT_EXPORT_ME"}
        append(job / "model-performance.jsonl", data)


def ledger(job, provider, prompt, completion, *, measured=True):
    append(job / "token-usage.jsonl", {
        "provider": provider, "usage_reported": measured,
        "prompt_tokens": prompt, "completion_tokens": completion,
        "total_tokens": prompt + completion if measured else None,
        "dialogue": "PRIVATE_CANNOT_EXPORT_ME",
    })


def test_model_averages_and_generation_throughput_weight_by_calls(tmp_path):
    query(tmp_path, 1, "visual4b", "scene_analysis", elapsed=4,
          prompt=100, generated=50, predicted_ms=2500, predicted_n=50,
          prompt_ms=800, prompt_n=100)
    query(tmp_path, 2, "visual4b", "semantic_boundary", elapsed=6,
          prompt=200, generated=100, predicted_ms=5000, predicted_n=100,
          prompt_ms=1200, prompt_n=200)
    query(tmp_path, 3, "story9b", "credit_classifier", elapsed=120,
          prompt=300, generated=500, predicted_ms=100000, predicted_n=500)
    query(tmp_path, 4, "story9b", "choose_units", elapsed=140,
          prompt=500, generated=600, predicted_ms=120000, predicted_n=600)
    query(tmp_path, 5, "story9b", "credit_classifier")  # killed by shared test deadline
    results = model_perf_summary(tmp_path)
    by_model = {r["model"]: r for r in results["by_model"]}
    v = by_model["visual4b"]
    assert (v["requests"], v["completed"], v["pending"]) == (2, 2, 0)
    assert (v["prompt_tokens"], v["completion_tokens"], v["total_tokens"]) == (300, 150, 450)
    assert v["avg_seconds_per_completed_call"] == 5
    assert v["avg_prompt_tokens_per_call"] == 150
    assert v["avg_completion_tokens_per_call"] == 75
    assert v["avg_total_tokens_per_measured_call"] == 225
    assert v["generation_tokens_per_second"] == 20
    assert v["prefill_tokens_per_second"] == 150
    assert v["latency_p95_s"] == 6

    story = by_model["story9b"]
    assert (story["requests"], story["completed"], story["pending"]) == (3, 2, 1)
    assert story["avg_seconds_per_completed_call"] == 130
    assert story["avg_prompt_tokens_per_call"] == 400
    assert story["avg_completion_tokens_per_call"] == 550
    assert story["total_tokens"] == 1900
    assert story["unknown_token_calls"] == 1
    assert story["generation_tokens_per_second"] == 5
    assert story["generation_measured_tokens"] == 1100
    assert results["overall_local_models"]["total_tokens"] == 2350
    assert results["overall_local_models"]["pending"] == 1

    stage_groups = {(x["model"], x["stage"]): x for x in results["by_model_and_stage"]}
    assert stage_groups[("visual4b", "scene_analysis")]["requests"] == 1
    assert stage_groups[("story9b", "credit_classifier")]["pending"] == 1
    assert "PRIVATE_CANNOT_EXPORT_ME" not in json.dumps(results)


def test_missing_token_fields_do_not_create_fake_average(tmp_path):
    query(tmp_path, 1, "story9b", "choose_units", elapsed=10)
    query(tmp_path, 2, "story9b", "choose_units", elapsed=20,
          prompt=40, generated=10, predicted_ms=5000, predicted_n=None)
    r = model_perf_summary(tmp_path)["by_model"][0]
    assert r["avg_seconds_per_completed_call"] == 15
    assert r["prompt_token_reported_calls"] == 1
    assert r["avg_total_tokens_per_measured_call"] == 50
    assert r["unknown_token_calls"] == 1
    assert r["generation_tokens_per_second"] == 2
    r2 = model_perf_summary(tmp_path / "absent")
    assert r2["overall_local_models"] is None
    assert r2["by_model"] == []


def test_whole_run_local_and_remote_ledgers_not_double_counted(tmp_path):
    job = tmp_path / "real_model_3min" / "real-job"
    ledger(job, "local", 100, 20)
    ledger(job, "local", 1, 1, measured=False)
    ledger(job, "deepseek", 350, 150)
    query(job, 1, "visual4b", "scene_analysis", elapsed=5, prompt=100, generated=20,
          predicted_ms=2000, predicted_n=20)
    ledger_result = token_ledger_summary(job)
    assert ledger_result["available"]
    assert ledger_result["total_reported_tokens"] == 620
    assert ledger_result["unknown_calls"] == 1
    assert ledger_result["by_provider"]["local"]["total_tokens"] == 120
    assert ledger_result["by_provider"]["deepseek"]["total_tokens"] == 500
    result = summarize(tmp_path)
    assert result["token_usage_totals"]["total_reported_tokens"] == 620
    assert result["model_performance"]["overall_local_models"]["total_tokens"] == 120
    text = markdown(result)
    assert "620.00 tokens" in text
    assert "visual4b" in text
    assert "not a prediction" in text
    assert "PRIVATE_CANNOT_EXPORT_ME" not in text
    safe = safe_summary(tmp_path)
    assert safe["token_usage_totals"]["total_reported_tokens"] == 620
    assert "PRIVATE_CANNOT_EXPORT_ME" not in json.dumps(safe)


def test_no_usage_ledger_does_not_claim_zero_tokens(tmp_path):
    empty = token_ledger_summary(tmp_path)
    assert empty["available"] is False
    assert empty["total_reported_tokens"] is None
    assert empty["unknown_calls"] == 0



def test_console_summary_contains_model_averages_without_dialogue(tmp_path, capsys):
    job = tmp_path / "real_model_3min" / "real-job"
    query(job, 1, "visual4b", "scene_analysis", elapsed=6,
          prompt=120, generated=30, predicted_ms=1500, predicted_n=30)
    ledger(job, "local", 120, 30)
    output = tmp_path / "stage_timings.json"
    assert main(["--test-dir", str(tmp_path), "--output", str(output)]) == 0
    printed = capsys.readouterr().out
    assert "TOKENS_TOTAL reported=150" in printed
    assert "MODEL_AVERAGES visual4b" in printed
    assert "avg_latency_s=6.0" in printed
    assert "decode_tokens_per_s=20.0" in printed
    assert "PRIVATE_CANNOT_EXPORT_ME" not in printed



def test_deepseek_cache_accounting_distinguishes_free_response_cache_from_billed_context(tmp_path):
    from app.token_usage import record
    job = tmp_path / "real_model_3min" / "real-job"
    record(job, "deepseek", "deepseek-flash", {"usage": {
        "prompt_tokens": 12000, "prompt_cache_hit_tokens": 10000,
        "prompt_cache_miss_tokens": 2000, "completion_tokens": 2000,
        "total_tokens": 14000}})
    report = token_ledger_summary(job)
    remote = report["by_provider"]["deepseek"]
    assert remote["api_context_cache_hit_tokens"] == 10000
    assert remote["api_context_cache_miss_tokens"] == 2000
    assert remote["api_context_cache_reported_calls"] == 1
    assert report["total_reported_tokens"] == 14000
    cost = report["deepseek_estimated_cost_usd"]
    # Official Sep 2026 DeepSeek Flash rates: cached inputs are discounted,
    # not free; full-response cache hits never generate a token ledger row.
    assert cost["off_peak"] == round((10000*.003+2000*.15+2000*.60)/1000000, 7)
    assert cost["peak"] == round((10000*.006+2000*.30+2000*1.2)/1000000, 7)
    md = markdown(summarize(tmp_path))
    assert "API context-cache hit tokens" in md
    assert "still billed" in md
    assert "PRIVATE_CANNOT_EXPORT_ME" not in md


def test_unknown_context_cache_breakdown_priced_as_miss_not_free(tmp_path):
    job = tmp_path / "real_model_3min" / "real-job"
    ledger(job, "deepseek", 15000, 300)
    result = token_ledger_summary(job)
    cost = result["deepseek_estimated_cost_usd"]
    assert cost["incomplete_context_breakdown_input_tokens"] == 15000
    assert cost["peak"] == round((15000*.30+300*1.20)/1000000, 7)
    assert result["by_provider"]["deepseek"]["api_context_cache_hit_tokens"] == 0


def test_kadr_response_cache_hits_are_not_api_ledger_entries(tmp_path):
    # A saved final response is retrieved before HTTP and consumes zero new
    # DeepSeek tokens. It must not be confused with provider prefix caching.
    job = tmp_path / "real_model_3min" / "real-job"
    job.mkdir(parents=True)
    (job / "deepseek-story-pilot.json").write_text(json.dumps({
        "profile":"local4b-deepseek-flash-story-pilot-v1",
        "reserved": ["a"*64], "fallbacks":0, "local_cache_hits":5
    }), encoding="utf-8")
    safe = safe_summary(tmp_path)
    assert safe["flash_story_pilot"]["local_response_cache_hits"] == 5
    assert safe["flash_story_pilot"]["reserved_paid_attempts"] == 1
    assert safe["token_usage_totals"]["available"] is False
    assert safe["token_usage_totals"]["total_reported_tokens"] is None
