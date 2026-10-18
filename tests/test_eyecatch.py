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

        proposed = apply_eyecatch_exclusions(events, indices)
        self.assertEqual(proposed[2]['eyecatch_candidate']['status'], 'proposal')
        self.assertFalse(proposed[2]['eyecatch_candidate']['authorizes_exclusion'])
        self.assertEqual({k:v for k,v in proposed[2].items() if k != 'eyecatch_candidate'}, events[2])
        self.assertNotIn('eyecatch_candidate', events[2])

    def test_quiet_mid_episode_story_is_not_erased_and_visual_review_is_targeted(self):
        from app.review_scope import check_regions
        event = {'id':'quiet_reveal','kind':'story','start':690.,'end':696.,
                 'importance':5,'contains_credits':False,'credit_montage':False,
                 'selected_ranges':[{'start':690.,'end':696.}],
                 'action_units':[{'start':691.,'end':695.,'action':'visible reveal'}]}
        source = [event]
        candidates = detect_eyecatches(source, {'words':[]}, [], duration=1440.)
        result = apply_eyecatch_exclusions(source, candidates)
        self.assertEqual(result[0]['selected_ranges'], event['selected_ranges'])
        self.assertEqual(result[0]['action_units'], event['action_units'])
        self.assertEqual(result[0]['kind'], 'story')
        self.assertEqual(result[0]['importance'], 5)
        regions = check_regions(result)
        self.assertEqual(len(regions),1)
        self.assertEqual(regions[0]['checks'],['titles'])
        self.assertNotIn('eyecatch_candidate', event)

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
