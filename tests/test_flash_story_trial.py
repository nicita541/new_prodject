"""Opt-in hybrid story routing: no real API used in tests."""
import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from app.config import STORY_MODEL, VLM_MODEL
from app.deepseek import BudgetExceeded, RemoteError, provider_identity
from app.flash_story_trial import PROFILE, TrialStoryVision
from app.vision import vision_session


class DummyLocal:
    def __init__(self, job_dir, cancelled, **settings):
        self.calls = 0
        self.entered = False
        self.closed = False
        self.settings = settings

    def __enter__(self):
        self.entered = True
        return self

    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        self.calls += 1
        return {"provider": "local", "kept": ["source_000"]}

    def close(self):
        self.closed = True


class DummyRemote:
    def __init__(self, job_dir, cancelled, *, fail=False, retry=False):
        self.calls = 0
        self.fail = fail
        self.retry = retry
        self._fetch = self.network

    def __enter__(self):
        return self

    def close(self):
        pass

    def network(self, body):
        self.calls += 1
        if self.fail:
            raise RemoteError("Remote error")
        return {"provider": "remote", "kept": ["source_000"]}

    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        body = {"model": "deepseek-flash", "prompt": prompt,
                "images": bool(image), "max_tokens": max_tokens}
        result = self._fetch(body)
        if self.retry:
            self._fetch({**body, "retry": 1})
        return result


def make_trial(tmp_path, remote, **kwargs):
    return TrialStoryVision(tmp_path, lambda: False, local_factory=DummyLocal,
                            remote_factory=lambda *args: remote, model=STORY_MODEL,
                            thinking=True, **kwargs)


def test_no_artificial_http_call_cap_for_remote_story(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        for n in range(110):
            assert router.query(f"story-{n}")["provider"] == "remote"
        assert remote.calls == 110
        assert router.local is None
    data = json.loads((tmp_path / "deepseek-story-pilot.json").read_text("utf-8"))
    assert len(data["reserved"]) == 110
    assert data["fallbacks"] == 0
    assert remote.calls == 110


def test_persisted_usage_count_does_not_block_valid_requests_after_restart(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        assert router.query("same-source", image=None)["provider"] == "remote"
    with make_trial(tmp_path, remote) as restarted:
        assert restarted.query("same-source")["provider"] == "remote"
        assert restarted.query("new-source")["provider"] == "remote"
    assert remote.calls == 3
    data = json.loads((tmp_path / "deepseek-story-pilot.json").read_text("utf-8"))
    assert len(data["reserved"]) == 3
    assert "same-source" not in json.dumps(data)
    assert "new-source" not in json.dumps(data)


def test_remote_failure_falls_back_but_retries_are_not_spend_limited(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False, fail=True)
    with make_trial(tmp_path, remote) as router:
        assert router.query("private-anime-dialogue")["provider"] == "local"
    assert remote.calls == 1
    assert "private-anime-dialogue" not in (tmp_path / "deepseek-story-pilot.json").read_text()
    other_dir = tmp_path / "again"
    retrier = DummyRemote(other_dir, lambda: False, retry=True)
    with make_trial(other_dir, retrier) as router:
        assert router.query("needs-json-retry")["provider"] == "remote"
    assert retrier.calls == 2


def test_cancelled_trial_never_sends_remote_request(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False)
    with TrialStoryVision(tmp_path, lambda: True, local_factory=DummyLocal,
                          remote_factory=lambda *args: remote,
                          model=STORY_MODEL) as router:
        with pytest.raises(InterruptedError):
            router.query("cancelled")
    assert remote.calls == 0


def test_corrupted_reservation_log_fails_closed(tmp_path):
    p = tmp_path / "deepseek-story-pilot.json"
    p.write_text('{"profile":"WRONG","reserved":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="историю"):
        make_trial(tmp_path, DummyRemote(tmp_path, lambda: False))


def test_4b_always_local_only_story_model_routes_to_trial(tmp_path):
    assert provider_identity("local_flash_story")["paid_http_attempt_limit"] is None
    assert provider_identity("local_flash_story")["remote_story"] == "deepseek-flash"
    with patch("app.vision.LocalVision", DummyLocal):
        visual = vision_session(tmp_path, lambda: False, "local_flash_story")
        assert isinstance(visual, DummyLocal)
        story = vision_session(tmp_path, lambda: False, "local_flash_story",
                               model=STORY_MODEL, thinking=True)
        assert isinstance(story, TrialStoryVision)
        assert story.local is None
    assert STORY_MODEL != VLM_MODEL


def test_public_report_contains_only_flash_trial_counters(tmp_path):
    from scripts.export_safe_ai_diagnostics import summarize
    job = tmp_path / "real_model_3min" / "real-job"
    remote = DummyRemote(job, lambda: False)
    private = "SECRET_ANIME_CHARACTER_AND_MODEL_PROMPT"
    with make_trial(job, remote) as router:
        router.query(private)
        router.query(private)
    public = summarize(tmp_path)
    result = public["flash_story_pilot"]
    assert result["available"]
    assert result["reserved_paid_attempts"] == 2
    assert result["local_story_fallbacks"] == 0
    assert result["local_response_cache_hits"] == 0
    assert private not in json.dumps(public)
    private_record = json.loads((job / "deepseek-story-pilot.json").read_text("utf-8"))
    assert private_record["reserved"][0] not in json.dumps(public)


def test_free_cached_reply_is_reused_without_call_limit(tmp_path):
    class CachedRemote(DummyRemote):
        def query(self, prompt, image=None, max_tokens=1200, schema=None):
            if prompt == "previously-cached-answer":
                return {"provider": "remote", "cached": True}
            return super().query(prompt, image, max_tokens, schema)

    remote = CachedRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        for n in range(12):
            assert router.query(f"fresh-story-{n}")["provider"] == "remote"
        assert router.query("previously-cached-answer")["cached"] is True
        assert remote.calls == 12
        assert router.local is None
        assert router._state["local_cache_hits"] == 1
        assert router.query("fresh-story-thirteen")["provider"] == "remote"
        assert remote.calls == 13


def test_legacy_budgeted_mode_has_no_spending_guard(tmp_path):
    # Unreported usage must not exhaust a synthetic budget.
    remote = DummyRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote, budgeted=True) as trial:
        assert trial.query("unknown-charge")["provider"] == "remote"
        assert trial.query("another-request")["provider"] == "remote"
        assert trial.local is None
        assert remote.calls == 2
    record = json.loads((tmp_path / "deepseek-story-budgeted.json").read_text("utf-8"))
    assert len(record["reserved"]) == 2
    assert record["charged_peak_usd"] == {}
    assert record["fallbacks"] == 0


def test_flash_story_records_usage_but_never_uses_it_as_an_api_cap(tmp_path):
    class MeteredRemote(DummyRemote):
        def network(self, body):
            self.calls += 1
            return {"provider": "remote", "usage": {
                "prompt_tokens": 2200, "completion_tokens": 200,
                "prompt_cache_hit_tokens": 200, "prompt_cache_miss_tokens": 2000}}

    remote = MeteredRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote, budgeted=True) as trial:
        # Even more than 96 unique prompts are not blocked.
        for n in range(105):
            assert trial.query(f"cheap-request-{n}")["provider"] == "remote"
        assert trial.local is None
        assert remote.calls == 105
    record = json.loads((tmp_path / "deepseek-story-budgeted.json").read_text("utf-8"))
    assert len(record["reserved"]) == 105
    assert len(record["charged_peak_usd"]) == 105
    assert sum(record["charged_peak_usd"].values()) > 0
    with make_trial(tmp_path, remote, budgeted=True) as restarted:
        # A missing full-response cache may require another paid request.
        assert restarted.query("cheap-request-0")["provider"] == "remote"
        assert restarted.local is None
