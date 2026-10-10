"""Opt-in hybrid story routing: no real API used in tests."""
import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from app.config import STORY_MODEL, VLM_MODEL
from app.deepseek import BudgetExceeded, RemoteError, provider_identity
from app.flash_story_trial import MAX_PAID_ATTEMPTS, PROFILE, TrialStoryVision
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


def test_first_eight_dispatches_remote_then_fallback_to_local(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        for n in range(MAX_PAID_ATTEMPTS):
            assert router.query(f"story-{n}")["provider"] == "remote"
        assert remote.calls == 8
        assert router.local is None   # No costly Qwen9B startup on successful remote.
        assert router.query("story-8")["provider"] == "local"
        assert router.local.entered is True
        assert router.local.settings["thinking"] is True
    data = json.loads((tmp_path / "deepseek-story-pilot.json").read_text("utf-8"))
    assert len(data["reserved"]) == 8
    assert data["fallbacks"] == 1
    assert remote.calls == 8


def test_persisted_reservations_block_duplicate_billing_after_restart(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        assert router.query("same-source", image=None)["provider"] == "remote"
    with make_trial(tmp_path, remote) as restarted:
        assert restarted.query("same-source")["provider"] == "local"
        assert restarted.query("new-source")["provider"] == "remote"
    assert remote.calls == 2
    data = json.loads((tmp_path / "deepseek-story-pilot.json").read_text("utf-8"))
    assert len(data["reserved"]) == 2
    assert "same-source" not in json.dumps(data)
    assert "new-source" not in json.dumps(data)


def test_remote_failure_or_retry_never_double_pays(tmp_path):
    remote = DummyRemote(tmp_path, lambda: False, fail=True)
    with make_trial(tmp_path, remote) as router:
        assert router.query("private-anime-dialogue")["provider"] == "local"
    assert remote.calls == 1
    assert "private-anime-dialogue" not in (tmp_path / "deepseek-story-pilot.json").read_text()
    other_dir = tmp_path / "again"
    retrier = DummyRemote(other_dir, lambda: False, retry=True)
    with make_trial(other_dir, retrier) as router:
        # The pilot treats a provider's attempted retry as uncertain and
        # resumes with local Qwen9B. It cannot silently spend twice.
        assert router.query("needs-json-retry")["provider"] == "local"
    assert retrier.calls == 1


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
    assert provider_identity("local_flash_story")["paid_http_attempt_limit"] == 8
    assert provider_identity("local_flash_story")["remote_story"] == "deepseek-flash"
    with patch("app.analysis.LocalVision", DummyLocal):
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
    assert result["reserved_paid_attempts"] == 1
    assert result["local_story_fallbacks"] == 1
    assert result["local_response_cache_hits"] == 0
    assert private not in json.dumps(public)
    private_record = json.loads((job / "deepseek-story-pilot.json").read_text("utf-8"))
    assert private_record["reserved"][0] not in json.dumps(public)



def test_remote_cached_reply_can_be_reused_after_eight_paid_slots(tmp_path):
    class CachedRemote(DummyRemote):
        def query(self, prompt, image=None, max_tokens=1200, schema=None):
            if prompt == "previously-cached-answer":
                return {"provider": "remote", "cached": True}
            return super().query(prompt, image, max_tokens, schema)

    remote = CachedRemote(tmp_path, lambda: False)
    with make_trial(tmp_path, remote) as router:
        for n in range(MAX_PAID_ATTEMPTS):
            assert router.query(f"fresh-story-{n}")["provider"] == "remote"
        assert router.query("previously-cached-answer")["cached"] is True
        assert remote.calls == MAX_PAID_ATTEMPTS
        assert router.local is None
        assert router._state["local_cache_hits"] == 1
        assert router.query("fresh-story-nine")["provider"] == "local"
        assert remote.calls == MAX_PAID_ATTEMPTS
