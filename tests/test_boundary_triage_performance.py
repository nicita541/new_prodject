"""Real source proposals are preserved while expensive semantic VLM requests are triaged."""
import unittest
from app.scene_detection import _select_boundary_verifications, _boundary_check_priority


def candidate(time, *, state=False, speech=False, distance=0.2, classification="ambiguous_boundary"):
    proposal = {"origins": ["state_probe"] if state else ["optical_cut"],
                "scores": {"motion": 0.3 if state else 0.01}}
    measured = {"classification": classification,
                "asr_continuity": {"dialogue_break": speech},
                "background_distance": distance,
                "perceptual_distance": distance}
    return {"time": time, "proposal": proposal, "measured": measured}


class BoundaryTriagingTests(unittest.TestCase):
    def test_selects_high_priority_physical_transition_without_inventing_scene(self):
        rows = [candidate(0.2), candidate(0.7, state=True), candidate(2.1, speech=True),
                candidate(2.4, classification="obvious_same_scene")]
        chosen = _select_boundary_verifications(rows)
        self.assertEqual(chosen, {0.7, 2.1})
        self.assertEqual(len(rows), 4)  # source evidence is unchanged

    def test_dense_noisy_candidates_do_not_force_hundreds_of_model_calls(self):
        rows = [candidate(i / 10) for i in range(1800)]  # 180s with 10 candidates/s
        selected = _select_boundary_verifications(rows)
        self.assertLessEqual(len(selected), 120)
        self.assertEqual(len(rows), 1800)

    def test_audio_dialogue_boundary_preferred_over_camera_only(self):
        chosen = _select_boundary_verifications([candidate(12.1), candidate(12.4, speech=True)])
        self.assertEqual(chosen, {12.4})

    def test_edge_behavior_and_explicit_rate_validation(self):
        self.assertEqual(_select_boundary_verifications([]), set())
        with self.assertRaises(ValueError):
            _select_boundary_verifications([candidate(0.2)], window_seconds=0)
        with self.assertRaises(ValueError):
            _select_boundary_verifications([candidate(-1.0)])
        self.assertGreater(_boundary_check_priority(candidate(1, state=True)["measured"],
                                                    candidate(1, state=True)["proposal"]),
                           _boundary_check_priority(candidate(1)["measured"],
                                                    candidate(1)["proposal"]))

    def test_deferred_proof_keeps_source_candidate_and_never_confirms_a_scene(self):
        from app.scene_detection import detect_semantic_scenes
        shots = [
            {'id': 'a', 'start': 0, 'end': 0.4, 'location': 'room'},
            {'id': 'b', 'start': 0.4, 'end': 0.7, 'location': 'street',
             'state_transition': True},
            {'id': 'c', 'start': 0.7, 'end': 2.0, 'location': 'street'}
        ]
        transcript = {'words': [], 'segments': []}
        baseline = detect_semantic_scenes(shots, transcript, 2.0)
        self.assertGreater(len(baseline), 1)
        proofs = {0.4: {'accepted': False, 'uncertain': True, 'confidence': 0,
                        'source': 'triage_deferred', 'reasons': ['deferred_for_scene_analysis']}}
        scenes = detect_semantic_scenes(shots, transcript, 2.0, boundary_verifications=proofs)
        self.assertTrue(any(d['reasons'] == ['deferred_for_scene_analysis']
                            for scene in scenes for d in scene['evidence']['boundary_decisions']))
        self.assertEqual(scenes[0]['start'], 0)
        self.assertEqual(scenes[-1]['end'], 2.0)
        self.assertTrue(any(scene['uncertain'] for scene in scenes))


if __name__ == "__main__":
    unittest.main()
