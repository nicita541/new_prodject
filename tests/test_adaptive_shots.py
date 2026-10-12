import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.config import TEMP
from app.media_probe import parse_shot_candidates, adaptive_shot_evidence, detect_shots, raw_shot_evidence, shot_checkpoint
from app.json_store import load_json


class AdaptiveShotsTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.directory = TEMP / ('adaptive_shots_test_' + uuid.uuid4().hex)
        self.directory.mkdir()

    def tearDown(self):
        shutil.rmtree(self.directory)

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
        times = [row['time'] for row in adaptive_shot_evidence(candidates, duration) if row['accepted']]
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
        times = [row['time'] for row in adaptive_shot_evidence(candidates, duration) if row['accepted']]
        # Verify cluster around 10s was collapsed to the peak (10.15s) and not shredded into 6 cuts
        action_cuts = [t for t in times if 9.5 <= t <= 11.5]
        self.assertEqual(len(action_cuts), 1)
        self.assertAlmostEqual(action_cuts[0], 10.15, places=2)
        # Verify calm cut at 3.0s remains
        self.assertIn(3.0, times)

    def test_adaptive_evidence_edge_cases(self):
        # Empty candidates
        self.assertEqual(adaptive_shot_evidence([], 10.0), [])
        # Near boundaries (<=0.3 and >= duration - 0.3) ignored
        candidates = [(0.1, 0.9), (0.25, 0.9), (9.8, 0.9), (9.9, 0.9)]
        self.assertTrue(all(not row['accepted'] for row in adaptive_shot_evidence(candidates, 10.0)))

    def test_detect_shots_integration(self):
        job_dir = self.directory
        log_file = job_dir / "shots.log"
        log_file.write_text("pts_time:2.5 lavfi.scene_score=0.35\npts_time:5.0 lavfi.scene_score=0.40\n", encoding="utf-8")
        
        with patch("app.media_probe.run_process") as mock_run:
            shots = detect_shots(Path("dummy.mp4"), 10.0, job_dir, lambda: False)
            self.assertTrue(len(shots) >= 2)
            self.assertEqual(shots[0]["start"], 0.0)
            self.assertEqual(shots[-1]["end"], 10.0)
            self.assertTrue(mock_run.called)

    def test_dense_threshold_preserves_every_suppressed_candidate_with_reason(self):
        candidates = [(5 + index * .1, .22) for index in range(12)] + [(15, .8)]
        evidence = adaptive_shot_evidence(candidates, 20)
        self.assertEqual(len(evidence), len(candidates))
        self.assertEqual(len({row['id'] for row in evidence}), len(evidence))
        dense = [row for row in evidence if row['time'] < 10]
        self.assertTrue(all(row['decision'] == 'suppressed' and not row['accepted'] for row in dense))
        self.assertTrue(all(row['suppression_reason'] == 'below_adaptive_threshold' for row in dense))
        self.assertTrue(all(row['local_density'] > 1 and row['adaptive_threshold'] > row['score'] for row in dense))
        self.assertEqual(evidence[-1]['decision'], 'accepted')
        self.assertIsNone(evidence[-1]['suppression_reason'])
        self.assertTrue(all(row['preserved_as_candidate'] for row in evidence))
        self.assertEqual([row['time'] for row in evidence if row['accepted']], [15])
        self.assertEqual(evidence, adaptive_shot_evidence(list(reversed(candidates)), 20))

    def test_cluster_gap_and_tail_reasons_remain_distinguishable(self):
        candidates = [(.1, .9), (.35, .9), (5, .5), (5.1, .7), (9.68, .9)]
        evidence = {row['time']: row for row in adaptive_shot_evidence(candidates, 10)}
        self.assertEqual(evidence[.1]['suppression_reason'], 'near_source_boundary')
        self.assertEqual(evidence[.35]['suppression_reason'], 'minimum_gap')
        self.assertEqual(evidence[5]['suppression_reason'], 'clustered_to_peak')
        self.assertEqual(evidence[5]['cluster_peak_time'], 5.1)
        self.assertTrue(evidence[5.1]['accepted'])
        self.assertEqual(evidence[9.68]['suppression_reason'], 'source_tail_margin')

    def test_detection_persists_suppressed_rows_in_compatible_list_and_sidecar(self):
        candidates = [(2 + index * .1, .22) for index in range(12)] + [(8, .8)]
        (self.directory / 'shots.log').write_text('\n'.join(
            f'pts_time:{time} lavfi.scene_score={score}' for time, score in candidates), encoding='utf-8')
        with patch('app.media_probe.run_process'):
            shots = detect_shots(Path('dummy.mp4'), 10, self.directory, lambda: False)
        self.assertEqual([(row['start'], row['end']) for row in shots], [(0, 8), (8, 10)])
        self.assertEqual([row['id'] for row in shots], ['shot_0000', 'shot_0001'])
        raw = raw_shot_evidence(shots)
        self.assertEqual(len(raw), len(candidates))
        self.assertEqual(raw, load_json(self.directory / 'shots.candidates.json'))
        self.assertEqual(raw, raw_shot_evidence([], self.directory))
        self.assertEqual(sum(not row['accepted'] for row in raw), 12)
        self.assertTrue(all(row['accepted'] for row in shots))

    def test_checkpoint_keeps_raw_evidence_and_identity_stable_on_reuse(self):
        raw = adaptive_shot_evidence([(1, .17), (5, .8)], 10)
        shots = [{'id': 'shot_0000', 'start': 0, 'end': 5, 'raw_shot_candidates': raw[:1]},
                 {'id': 'shot_0001', 'start': 5, 'end': 10, 'raw_shot_candidates': raw[1:]}]
        with patch('app.media_probe.detect_shots', return_value=shots) as detect:
            first = shot_checkpoint(Path('dummy.mp4'), 'source', 10, self.directory, lambda: False)
            identity = load_json(self.directory / 'shots.meta.json')
            second = shot_checkpoint(Path('dummy.mp4'), 'source', 10, self.directory, lambda: False)
            self.assertEqual(detect.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(identity, load_json(self.directory / 'shots.meta.json'))
        self.assertEqual(raw, raw_shot_evidence(second))
        diagnostic = self.directory / 'diagnostics' / 'pipeline'
        self.assertEqual(raw, load_json(diagnostic / 'shots.candidates.json'))
        summary = load_json(diagnostic / 'summary.json')
        self.assertEqual((summary['raw_shot_candidates'], summary['suppressed_shot_candidates']), (2, 1))
        records = [json.loads(line) for line in (diagnostic / 'timeline.jsonl').read_text('utf-8').splitlines()]
        self.assertEqual([row['action'] for row in records if row.get('candidate_id') == raw[0]['id']],
                         ['suppressed', 'suppressed'])
        self.assertTrue(any(row['action'] == 'cache_hit' for row in records))

    def test_invalid_raw_candidate_cannot_poison_diagnostics(self):
        for candidates in ([(float('nan'), .2)], [(1, float('inf'))], [(11, .2)], [(1, 1.1)]):
            with self.assertRaises(ValueError):
                adaptive_shot_evidence(candidates, 10)


if __name__ == '__main__':
    unittest.main()
