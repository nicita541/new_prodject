"""Explicit DeepSeek-story real-E2E opt-in and cache-safe billing contracts.

No real network requests are made. The normal full BAT remains all-local.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text("utf-8")


def test_paid_story_launcher_requires_explicit_confirmation_and_real_production():
    launcher = source("ТЕСТЫ/5_ПОЛНАЯ_ПРОВЕРКА_DEEPSEEK_FLASH.bat")
    ps = source("scripts/verify_project.ps1")
    assert "setlocal EnableDelayedExpansion" in launcher
    assert 'if /I not "!KADR_CONFIRM!"=="YES"' in launcher
    assert "-RequireRealModel -FlashStory" in launcher
    assert '$FlashStory' in ps
    assert 'if ($FlashStory) { $realArgs += @("--local-provider", "local_flash_story") }' in ps
    assert '$script:verificationBudgetSeconds = 2200' in ps
    assert 'Run-Check "real_model_3min" $python $realArgs $root $script:verificationBudgetSeconds' in ps
    assert 'full_with_limited_deepseek_flash_story' in ps
    assert 'Run-Check "deepseek_key_preflight"' in ps
    assert 'public_status' in ps
    assert 'DeepSeek key is not configured; paid pilot was not started' in ps
    normal_launcher = source("ТЕСТЫ/2_ПОЛНАЯ_ПРОВЕРКА_С_ИИ.bat")
    assert "-FlashStory" not in normal_launcher


def test_real_e2e_accepts_cloud_story_only_when_explicit_and_checks_paid_resume():
    script = source("scripts/full_pipeline_3min.py")
    runner = source("scripts/run_production_raw_quality.py")
    assert '"local_flash_story"' in script
    assert "real_local_whisper_and_paid_deepseek_story" in script
    assert 'local_provider: str = "local"' in script
    assert "paid_before_resume" in script and "paid_after_resume" in script
    assert "Cache-resume sent another paid DeepSeek request" in script
    assert "genuine_production_analysis_to_final_mp4" in script
    assert "genuine_model_and_video_cache_resume" in script
    assert 'analysis_provider="local"' in runner
    assert 'analysis_provider not in ("local", "local_fast_story", "local_flash_story")' in runner
    assert 'isinstance(vision, LocalVision)' in runner
    assert 'isinstance(vision, TrialStoryVision)' in runner
    assert "recorded=vision" not in runner  # no fake wrapper pretending to be LocalVision
    assert "public['new_requests'] = current - initial" in runner


def test_paid_trial_cap_and_local_response_cache_are_independent():
    router = source("app/flash_story_trial.py")
    assert "MAX_PAID_ATTEMPTS = 8" in router
    assert 'if len(self._state["reserved"]) >= MAX_PAID_ATTEMPTS:' in router
    assert 'self._state["local_cache_hits"] += 1' in router
    assert 'if not dispatched:' in router
    assert 'self._reserve(body)' in router
    assert 'return self._local().query' in router
