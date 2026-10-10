"""Separate, opt-in $0.05 *estimated* peak-priced Flash pilot.

All networking is stubbed. Existing eight-request pilot must stay unchanged.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import STORY_MODEL, VLM_MODEL, VLM_PROJECTOR
from app.flash_story_trial import (
    BUDGETED_ESTIMATED_PEAK_USD, BUDGETED_MAX_PAID_ATTEMPTS,
    BUDGETED_PROFILE, MAX_PAID_ATTEMPTS, TrialStoryVision, routing_profile,
)
from app.deepseek import RemoteError, provider_identity
from app.vision import vision_session
from scripts.export_safe_ai_diagnostics import summarize


class FastLocal:
    def __init__(self, job, cancel, **settings):
        self.settings = settings
        self.calls = 0
    def __enter__(self):
        return self
    def close(self):
        pass
    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        self.calls += 1
        return {"kept": ["source_unit"], "mode": "local4b"}


class MeteredFlash:
    def __init__(self, *, broken=False):
        self._fetch = self.network
        self.calls = 0
        self.broken = broken
    def __enter__(self):
        return self
    def close(self):
        pass
    def network(self, body):
        self.calls += 1
        if self.broken:
            raise RemoteError("unavailable")
        return {
            "kept": ["source_unit"], "mode": "flash",
            "usage": {
                "prompt_tokens": 2000,
                "prompt_cache_hit_tokens": 500,
                "prompt_cache_miss_tokens": 1500,
                "completion_tokens": 100,
                "total_tokens": 2100,
            },
        }
    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        return self._fetch({"model": "deepseek-flash", "max_tokens": 2048,
                            "prompt": prompt})


def make(tmp_path, flash):
    return TrialStoryVision(tmp_path, lambda: False, budgeted=True,
                            local_factory=FastLocal,
                            remote_factory=lambda *args: flash,
                            model=STORY_MODEL, thinking=True)


def test_budgeted_mode_requires_explicit_provider_and_preserves_8_call_mode(tmp_path):
    assert MAX_PAID_ATTEMPTS == 8
    assert BUDGETED_MAX_PAID_ATTEMPTS == 96
    assert BUDGETED_ESTIMATED_PEAK_USD == .05
    assert routing_profile()["after_limit"] == "local9b_fallback"
    profile = provider_identity("local_flash_story_budgeted")
    assert profile["after_limit"] == "local4b_conservative_fallback"
    assert profile["framing"] == "flash_or_local4b"
    assert profile["pacing"] == "flash_or_local4b"
    from app.analysis import framing_provider
    assert framing_provider("local_flash_story_budgeted") == "local_flash_story_budgeted"
    assert profile["estimated_peak_budget_usd"] == .05
    with patch("app.analysis.LocalVision", FastLocal):
        visual = vision_session(tmp_path, lambda: False, "local_flash_story_budgeted")
        assert isinstance(visual, FastLocal)
        story = vision_session(tmp_path, lambda: False, "local_flash_story_budgeted",
                               model=STORY_MODEL, thinking=True)
        assert story.budgeted is True
        assert story.local is None


def test_reported_billing_replaces_worst_case_reservations_and_allows_multiple_requests(tmp_path):
    flash = MeteredFlash()
    with make(tmp_path, flash) as vision:
        for i in range(12):
            assert vision.query(f"source-{i}")["mode"] == "flash"
        assert flash.calls == 12
        assert vision.local is None
        assert len(vision._state["reserved"]) == 12
        # Peak rate estimate: 1500*.30 + 500*.006 + 100*1.2 per 1M.
        expected = round((1500*.30 + 500*.006 + 100*1.2)/1e6, 9)
        assert all(abs(x-expected) < 1e-9 for x in
                   vision._state["charged_peak_usd"].values())
        assert sum(vision._state["charged_peak_usd"].values()) < .01
    diagnostics = summarize(tmp_path)
    # No private prompt data is exported; no fabricated green PASS.
    assert json.loads((tmp_path / "deepseek-story-budgeted.json").read_text())["profile"] == BUDGETED_PROFILE
    assert diagnostics["flash_story_pilot"]["available"] is False
    assert not (tmp_path / "deepseek-story-pilot.json").exists()


def test_budgeted_limit_falls_back_to_fast_4b_instead_of_9b(tmp_path):
    flash = MeteredFlash()
    with make(tmp_path, flash) as vision:
        # Simulate durable cost ledger close to the maximum. The next
        # transaction can't reserve worst-case prompt+completion expenditure.
        vision._state["charged_peak_usd"] = {}
        vision._state["reserved"] = ["a" * 64]
        vision._state["charged_peak_usd"]["a"*64] = .02
        assert vision.query("new-story")["mode"] == "local4b"
        assert flash.calls == 0
        assert vision.local.settings["model"] == VLM_MODEL
        assert vision.local.settings["projector"] == VLM_PROJECTOR
        assert vision.local.settings["thinking"] is False
        assert vision._state["fallbacks"] == 1


def test_network_failure_keeps_worst_case_reserve_then_falls_back_4b(tmp_path):
    flash = MeteredFlash(broken=True)
    with make(tmp_path, flash) as vision:
        assert vision.query("unavailable-story")["mode"] == "local4b"
        assert flash.calls == 1
        budget = sum(vision._state["charged_peak_usd"].values())
        assert budget > .039
    with make(tmp_path, flash) as restarted:
        assert restarted.query("another-scene")["mode"] == "local4b"
        assert flash.calls == 1
        assert restarted.local.settings["model"] == VLM_MODEL


def test_budgeted_profile_reports_aggregates_without_request_hashes(tmp_path):
    from scripts.export_safe_ai_diagnostics import summarize
    job = tmp_path / "real_model_3min" / "real-job"
    job.mkdir(parents=True)
    flash = MeteredFlash()
    with make(job, flash) as v:
        assert v.query("PRIVATE_SOURCE_NAME")["mode"] == "flash"
    summary = summarize(tmp_path)
    pilot = summary["flash_story_pilot"]
    assert pilot["available"] is True
    assert pilot["profile"] == "budgeted"
    assert pilot["max_paid_attempts"] == 96
    assert pilot["reserved_paid_attempts"] == 1
    assert 0 < pilot["estimated_reserved_peak_usd"] < .05
    json_text = json.dumps(summary)
    journal = json.loads((job / "deepseek-story-budgeted.json").read_text())
    assert "PRIVATE_SOURCE_NAME" not in json_text
    assert journal["reserved"][0] not in json_text


def test_budgeted_bat_requires_explicit_yes_and_all_real_pipeline_checks():
    root = Path(__file__).resolve().parents[1]
    bat = (root / "ТЕСТЫ" / "6_ПОЛНАЯ_ПРОВЕРКА_FLASH_БЮДЖЕТ.bat").read_text("utf-8")
    ps = (root / "scripts" / "verify_project.ps1").read_text("utf-8")
    py = (root / "scripts" / "full_pipeline_3min.py").read_text("utf-8")
    assert "-RequireRealModel -FlashBudgeted" in bat
    assert '"!KADR_CONFIRM!"=="YES"' in bat
    assert '"--local-provider", "local_flash_story_budgeted"' in ps
    assert '"local_flash_story_budgeted"' in py
    assert "genuine_model_and_video_cache_resume" in py
    assert "$script:verificationBudgetSeconds = 2200" in ps
