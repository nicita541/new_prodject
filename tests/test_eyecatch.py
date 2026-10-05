import unittest

from app.eyecatch import detect_eyecatches, apply_eyecatch_exclusions


class EyecatchTests(unittest.TestCase):
    def test_detect_eyecatches_finds_mid_episode_bumper(self):
        duration = 1440.0  # 24-minute anime
        events = [
            {'id': 'e1', 'start': 0.0, 'end': 100.0},
            {'id': 'e2', 'start': 100.0, 'end': 680.0},
            # Eyecatch around 11.5 minutes (690s - 696s, 6 seconds duration)
            {'id': 'e_eyecatch', 'start': 690.0, 'end': 696.0},
            {'id': 'e3', 'start': 696.0, 'end': 1300.0},
            {'id': 'e4', 'start': 1300.0, 'end': 1440.0},
        ]
        shots = [{'start': 690.0, 'end': 696.0}]
        transcript = {'words': []}

        indices = detect_eyecatches(events, transcript, shots, duration=duration)
        self.assertEqual(indices, [2])

        excluded = apply_eyecatch_exclusions(events, indices)
        self.assertEqual(excluded[2]['kind'], 'eyecatch')
        self.assertEqual(excluded[2]['importance'], 0)
        self.assertEqual(excluded[2]['selected_ranges'], [])

    def test_detect_eyecatches_ignores_normal_dialogue_scene(self):
        duration = 1440.0
        events = [
            # Scene in mid-episode but with dialogue and long duration (40s)
            {'id': 'e1', 'start': 700.0, 'end': 740.0},
        ]
        shots = []
        transcript = {
            'words': [{'start': 705.0 + i, 'end': 705.5 + i, 'text': f'слово_{i}'} for i in range(20)]
        }
        indices = detect_eyecatches(events, transcript, shots, duration=duration)
        self.assertEqual(indices, [])


if __name__ == '__main__':
    unittest.main()
