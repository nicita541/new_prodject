"""Fast harness contracts; heavy real 180s media is tested in dedicated CI."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.full_pipeline_3min import fixture_analysis, inspect_step, run_real


class FullPipelineHarnessContracts(unittest.TestCase):
    def test_synthetic_fixture_always_has_six_bounded_intervals_in_real_180s_clock(self):
        probe = {"duration": 180.0, "width": 320, "height": 180,
                 "fps": 12.0, "has_audio": True, "audio_stream": 0}
        with patch("scripts.full_pipeline_3min.probe_media", return_value=probe):
            plan_inputs = fixture_analysis(Path("not-a-real-video-in-fast-tests.mp4"))
        self.assertTrue(plan_inputs["synthetic_semantic_fixture"])
        self.assertEqual(len(plan_inputs["events"]), 6)
        self.assertEqual(len(plan_inputs["transcript"]["words"]), 6)
        self.assertEqual(len(plan_inputs["transcript"]["segments"]), 6)
        self.assertEqual(plan_inputs["events"][0]["start"], 0)
        self.assertEqual(plan_inputs["events"][-1]["end"], 180)
        for i, event in enumerate(plan_inputs["events"]):
            self.assertEqual(event["start"], 30 * i)
            self.assertEqual(event["end"], 30 * (i + 1))
            self.assertEqual(event["unit_selection_version"], 1)
            self.assertTrue(all(0 <= w["start"] < w["end"] <= 180
                                for w in plan_inputs["transcript"]["words"]))

    def test_every_step_records_failure_type_and_does_not_fake_success(self):
        report = {"checks": []}
        with self.assertRaisesRegex(ValueError, "corrupted checkpoint"):
            inspect_step(report, "validate_cache",
                         lambda: (_ for _ in ()).throw(ValueError("corrupted checkpoint")))
        self.assertEqual(report["checks"][0]["name"], "validate_cache")
        self.assertEqual(report["checks"][0]["status"], "failed")
        self.assertEqual(report["checks"][0]["error_type"], "ValueError")
        self.assertEqual(len(report["checks"]), 1)

    def test_real_mode_requires_a_story_video_before_any_model_request(self):
        report = {"checks": [], "pipeline_stages": []}
        # The real mode must not silently feed sine-wave test patterns to VLM
        # and claim a successful semantic acceptance run.
        with self.assertRaisesRegex(ValueError, "requires --source"):
            run_real(Path("."), report, None, None)
        self.assertNotIn("real_model_requests", report)


if __name__ == "__main__":
    unittest.main()
