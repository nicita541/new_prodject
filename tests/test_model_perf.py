"""Numerical local model telemetry must be useful and never leak media content."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import STORY_MODEL, VLM_MODEL
from app.model_perf import measure_request, model_started, purpose
from app.vision import LocalVision
from scripts.export_safe_ai_diagnostics import model_perf_summary
from scripts.export_stage_timings import summarize, markdown


SECRET = "A_PRIVATE_ANIME_LINE_AND_PASSWORD_SECRET"


def test_query_latency_tokens_model_stage_and_startup_are_allowlisted(tmp_path):
    client = LocalVision(tmp_path, lambda: False, model=STORY_MODEL, thinking=True)
    model_started(tmp_path, STORY_MODEL, 9.7, False, "ok")

    def fake_inference(prompt, images, max_tokens, schema, trace, effective_thinking):
        assert effective_thinking is True
        assert SECRET in prompt
        trace.response({"usage": {"prompt_tokens": 130, "completion_tokens": 42,
                                  "total_tokens": 172,
                                  "completion_tokens_details": {"reasoning_tokens": 19}},
                        "choices": [{"finish_reason": "length", "message": {"content": SECRET}}],
                        "timings": {"prompt_ms": 850, "predicted_ms": 4200}})
        return {"summary": SECRET}

    with patch.object(client, "_query_impl", side_effect=fake_inference):
        with purpose("choose_units"):
            assert client.query(SECRET, max_tokens=650)["summary"] == SECRET
    raw = (tmp_path / "model-performance.jsonl").read_text("utf-8")
    assert SECRET not in raw
    assert str(STORY_MODEL) not in raw
    assert '"prompt":' not in raw
    data = model_perf_summary(tmp_path)
    assert data["available"] is True
    assert data["requests"] == 1
    row = data["by_model_and_stage"][0]
    assert row["model"] == "story9b"
    assert row["stage"] == "choose_units"
    assert row["thinking_requests"] == 1
    assert row["prompt_chars"] == len(SECRET)
    assert row["prompt_tokens"] == 130
    assert row["completion_tokens"] == 42
    assert row["reasoning_tokens"] == 19
    assert row["finish_length_calls"] == 1
    assert row["prefill_p50_ms"] == 850
    assert row["decode_p50_ms"] == 4200
    assert data["startup"] == [{"model": "story9b", "status": "ok",
                                "seconds": 9.7, "cpu": False}]


def test_failed_or_killed_query_does_not_expose_errors_and_keeps_pending(tmp_path):
    model_started(tmp_path, VLM_MODEL, 3.5, True, "fallback")
    with purpose("semantic_boundary"):
        with pytest.raises(RuntimeError, match="private"):
            with measure_request(tmp_path, VLM_MODEL, pages=1, prompt_chars=29,
                                 max_tokens=600, thinking=False, cpu=True):
                raise RuntimeError("private local model C:\\Users\\secret\\frame.jpg")
        # Force an interrupted start with no matching END to simulate hard
        # Windows process termination or 30-minute TIMEOUT.
        from app.model_perf import RequestTrace
        RequestTrace(tmp_path, STORY_MODEL, pages=4, prompt_chars=1000,
                     max_tokens=650, thinking=True, cpu=False)
    raw = (tmp_path / "model-performance.jsonl").read_text("utf-8")
    assert "private" not in raw and "Users" not in raw and "frame.jpg" not in raw
    data = model_perf_summary(tmp_path)
    assert data["requests"] == 2
    assert data["pending"] == 1
    assert sum(row["failed"] for row in data["by_model_and_stage"]) == 1
    assert data["startup"][0]["status"] == "fallback"


def test_profile_is_visible_in_stage_timings_without_raw_content(tmp_path):
    job = tmp_path / "real_model_3min" / "real-job"
    job.mkdir(parents=True)
    model_started(job, STORY_MODEL, 8, False, "ok")
    with purpose("verify_omissions"):
        with measure_request(job, STORY_MODEL, pages=2, prompt_chars=1200,
                             max_tokens=700, thinking=True, cpu=False) as trace:
            trace.response({"usage": {"prompt_tokens": 12, "completion_tokens": 7}})
    report = summarize(tmp_path)
    md = markdown(report)
    assert report["model_performance"]["by_model_and_stage"][0]["stage"] == "verify_omissions"
    assert "## 7. Local llama.cpp" in md
    assert "story9b" in md
    assert SECRET not in md


def test_no_pseudo_numbers_when_provider_usage_missing(tmp_path):
    assert model_perf_summary(tmp_path)["available"] is False
    with measure_request(tmp_path, STORY_MODEL, pages=1, prompt_chars=22,
                         max_tokens=200, thinking=True, cpu=False):
        pass
    row = model_perf_summary(tmp_path)["by_model_and_stage"][0]
    assert row["token_reported_calls"] == 0
    assert row["prefill_p50_ms"] is None
    assert row["decode_p50_ms"] is None
