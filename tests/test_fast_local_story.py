"""Opt-in local 4B plot selection must never weaken the real E2E contract."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import STORY_MODEL, STORY_PROJECTOR, VLM_MODEL, VLM_PROJECTOR
from app.analysis import analysis_provider, framing_provider
from app.deepseek import provider_identity
from app.vision import vision_session


def test_fast_story_routes_only_story_to_local_4b_no_network(tmp_path):
    class DummyLocal:
        def __init__(self, job, cancelled, **kw):
            self.job = job
            self.settings = kw

    with patch("app.analysis.LocalVision", DummyLocal), \
         patch("app.deepseek._http", side_effect=AssertionError("Cloud forbidden")):
        early = vision_session(tmp_path, lambda: False, "local_fast_story")
        story = vision_session(tmp_path, lambda: False, "local_fast_story",
                               model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True)
        normal = vision_session(tmp_path, lambda: False, "local",
                                model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True)
    assert early.settings == {}
    assert story.settings == {"model": VLM_MODEL, "projector": VLM_PROJECTOR, "thinking": False}
    assert normal.settings["model"] == STORY_MODEL
    assert normal.settings["thinking"] is True
    assert framing_provider("local_fast_story") == "local"
    profile = provider_identity("local_fast_story")
    assert profile["story"] == "local4b-nonthinking"
    assert profile["framing"] == "local9b"


def test_fast_provider_is_explicit_and_cannot_become_silent_default(tmp_path):
    (tmp_path / "analysis-settings.json").write_text(
        json.dumps({"provider": "local_fast_story"}), encoding="utf-8")
    assert analysis_provider(tmp_path) == "local_fast_story"
    (tmp_path / "analysis-settings.json").unlink()
    assert analysis_provider(tmp_path) == "local"


def test_fast_real_mode_retains_two_model_and_video_passes():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "full_pipeline_3min.py").read_text("utf-8")
    assert '"--local-provider", choices=("local", "local_fast_story", "local_flash_story", "local_flash_story_budgeted")' in script
    assert script.count("production_run(inp, job, render=True, analysis_provider=local_provider)") == 2
    assert "genuine_model_and_video_cache_resume" in script
    assert "model_requests_unchanged" in script
    assert 'if not outcome["complete"]:' in script


def test_fast_internal_provider_retains_strict_pipeline_without_extra_launcher():
    root = Path(__file__).resolve().parents[1]
    ps = (root / "scripts" / "verify_project.ps1").read_text("utf-8")
    assert not (root / "ТЕСТЫ" / "4_ПОЛНАЯ_ПРОВЕРКА_БЫСТРАЯ_4B.bat").exists()
    assert 'if ($FastLocalStory) { $realArgs += @("--local-provider", "local_fast_story") }' in ps
    assert '$script:verificationBudgetSeconds = 2200' in ps
    assert 'Run-Check "real_model_3min" $python $realArgs $root $script:verificationBudgetSeconds' in ps
    assert "safe_ai_diagnostics" in ps and "stage_timings" in ps


def test_raw_observer_only_allows_explicit_fully_local_models(tmp_path):
    from scripts.run_production_raw_quality import run
    import inspect
    assert '"local_flash_story"' in inspect.getsource(run)
    with pytest.raises(ValueError, match="genuine local"):
        run(tmp_path, tmp_path / "output", analysis_provider="deepseek")



def test_real_model_recorder_preserves_per_request_thinking_override(tmp_path):
    # The real 180s launcher wraps LocalVision, unlike ordinary unit tests.
    # The wrapper must not silently strip or reject the nonthinking flag.
    from app.story import _profiled_query
    from app.vision import LocalVision
    from scripts.run_raw_video_quality import RecordedVision

    local = LocalVision(tmp_path, lambda: False, model=STORY_MODEL, thinking=True)
    with patch("scripts.run_raw_video_quality.workspace", lambda value: Path(value).resolve()):
        recorded = RecordedVision(local, tmp_path / "actual-model")
        with patch.object(local, "query", return_value={"decisions": []}) as query:
            result = _profiled_query(recorded, "verify_omissions", "check source",
                                     max_tokens=360, schema={"type": "object"})
        assert result == {"decisions": []}
        assert query.call_args.kwargs["thinking_override"] is False
        assert local.thinking is True
        request = json.loads((tmp_path / "actual-model" / "request-001.json").read_text("utf-8"))
        assert request["thinking"] is False
        with patch.object(local, "query", return_value={"keep": []}) as query:
            _profiled_query(recorded, "choose_units", "choose", max_tokens=650)
            assert "thinking_override" not in query.call_args.kwargs
        second = json.loads((tmp_path / "actual-model" / "request-002.json").read_text("utf-8"))
        assert second["thinking"] is True
