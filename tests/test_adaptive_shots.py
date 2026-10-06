import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.media_probe import parse_shot_candidates, adaptive_cut_times, detect_shots


class AdaptiveShotsTests(unittest.TestCase):
    def test_parse_shot_candidates_extracts_pts_and_scores(self):
        log_sample = """
        [Parsed_showinfo_2 @ 000001] n:   1 pts:   1001 pts_time:1.001000 pos:   1234 fmt:yuv420p
        [Parsed_metadata_1 @ 000002] frame:1    pts:1001    pts_time:1.001
        [Parsed_metadata_1 @ 000002] lavfi.scene_score=0.354120
        [Parsed_showinfo_2 @ 000003] n:   2 pts:   2002 pts_time:2.500000 pos:   5678 fmt:yuv420p
        [Parsed_metadata_1 @ 000004] frame:2    pts:2002    pts_time:2.500
        [Parsed_metadata_1 @ 000004] lavfi.scene_score=0.481230
        """
        candidates = parse_shot_candidates(log_sample)
        self.assertGreaterEqual(len(candidates), 2)
        times = [c[0] for c in candidates]
        self.assertIn(1.001, times)
        self.assertIn(2.5, times)
        score_dict = dict(candidates)
        self.assertAlmostEqual(score_dict[2.5], 0.481230, places=4)

    def test_calm_dialogue_maintains_fine_sensitivity(self):
        # Sparse candidates with modest scene scores (~0.22) in calm dialogue
        duration = 30.0
        candidates = [
            (5.0, 0.22),
            (12.0, 0.24),
            (20.0, 0.21),
        ]
        times = adaptive_cut_times(candidates, duration)
        # Should include start (0.0), duration (30.0), and the dialogue cut points
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times[-1], duration)
        self.assertIn(5.0, times)
        self.assertIn(12.0, times)
        self.assertIn(20.0, times)

    def test_action_burst_clusters_to_peak_and_elevates_threshold(self):
        # Action scene with many rapid triggers (burst within 0.45s) and camera motion noise
        duration = 30.0
        # Calm cut at 3.0s
        # High motion cluster around 10.0s: 10.0 (0.28), 10.15 (0.45 - peak), 10.3 (0.31), 10.4 (0.29)
        # Plus camera jitter at 11.0s (score 0.21, but threshold elevated due to high local density)
        candidates = [
            (3.0, 0.22),
            (9.8, 0.25),
            (10.0, 0.28),
            (10.15, 0.48),  # peak action cut
            (10.30, 0.32),
            (10.45, 0.29),
            (10.60, 0.26),
            (10.75, 0.24),
            (10.90, 0.23),
            (11.10, 0.22),
            (25.0, 0.23),
        ]
        times = adaptive_cut_times(candidates, duration)
        # Verify cluster around 10s was collapsed to the peak (10.15s) and not shredded into 6 cuts
        action_cuts = [t for t in times if 9.5 <= t <= 11.5]
        self.assertEqual(len(action_cuts), 1)
        self.assertAlmostEqual(action_cuts[0], 10.15, places=2)
        # Verify calm cut at 3.0s remains
        self.assertIn(3.0, times)

    def test_adaptive_cut_times_edge_cases(self):
        # Empty candidates
        self.assertEqual(adaptive_cut_times([], 10.0), [0.0, 10.0])
        # Near boundaries (<=0.3 and >= duration - 0.3) ignored
        candidates = [(0.1, 0.9), (0.25, 0.9), (9.8, 0.9), (9.9, 0.9)]
        self.assertEqual(adaptive_cut_times(candidates, 10.0), [0.0, 10.0])

    def test_detect_shots_integration(self):
        job_dir = Path("scratch/test_job")
        job_dir.mkdir(parents=True, exist_ok=True)
        log_file = job_dir / "shots.log"
        log_file.write_text("pts_time:2.5 lavfi.scene_score=0.35\npts_time:5.0 lavfi.scene_score=0.40\n", encoding="utf-8")
        
        with patch("app.analysis.run_process") as mock_run:
            shots = detect_shots(Path("dummy.mp4"), 10.0, job_dir, lambda: False)
            self.assertTrue(len(shots) >= 2)
            self.assertEqual(shots[0]["start"], 0.0)
            self.assertEqual(shots[-1]["end"], 10.0)
            self.assertTrue(mock_run.called)


if __name__ == '__main__':
    unittest.main()
