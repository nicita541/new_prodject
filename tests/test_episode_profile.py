"""Observed montage pace, adaptive scene settings and retention budget invariants."""
import copy
import json
import unittest

from app.episode_profile import (EPISODE_PROFILE_POLICY, EPISODE_PROFILE_VERSION,
    adaptive_retention_budget, build_episode_profile, scene_settings)
from app.scene_detection import DEFAULT_SETTINGS, detect_semantic_scenes


EMPTY = {'words': [], 'segments': []}


def footage(duration, spacing, score=.1, **features):
    count = int(duration/spacing)
    return [{'id': f'shot_{index}', 'start': index*spacing, 'end': min(duration, (index+1)*spacing),
             'scene_score': score, **features} for index in range(count)]


def dialogue(duration):
    return {'words': [], 'segments': [{'start': index*60, 'end': index*60+45, 'text': 'Длинный разговор.'}
                                     for index in range(int(duration/60))]}


def confirmed_event(start, end, **fields):
    return {'id': f'event_{start}', 'start': start, 'end': end, 'kind': 'story', 'importance': 4,
            'uncertain': False, 'understanding_status': 'accepted', 'confidence': .95,
            'narrative_bridge': False, 'units': [], 'action_units': [], **fields}


class EpisodeProfileTests(unittest.TestCase):
    def test_equal_duration_dialogue_action_balanced_and_mixed_are_distinct(self):
        duration = 600
        cases = [
            ('dialogue_slow', dialogue(duration), footage(duration, 30, .1)),
            ('action_dense', {'words': [], 'segments': [{'start': 0, 'end': 10, 'text': 'Вперёд!'}]}, footage(duration, .75, .7)),
            ('balanced', {'words': [], 'segments': [{'start': 0, 'end': 300, 'text': 'Обычная сцена.'}]}, footage(duration, 10, .15)),
            ('mixed', dialogue(duration), footage(duration, .75, .7))]
        profiles = {}
        for expected, transcript, shots in cases:
            with self.subTest(profile=expected):
                profile = build_episode_profile(duration, transcript, shots)
                self.assertEqual(profile['profile'], expected)
                self.assertEqual(profile['phase'], 'initial')
                self.assertEqual(profile['metrics']['action_units'], 0)
                profiles[expected] = profile
        targets = {name: value['planner_budget']['optimal'] for name, value in profiles.items()}
        self.assertEqual(len(set(targets.values())), 4)
        self.assertLess(targets['dialogue_slow'], targets['balanced'])
        self.assertLess(targets['balanced'], targets['action_dense'])
        self.assertEqual(len({json.dumps(scene_settings(value), sort_keys=True) for value in profiles.values()}), 4)

    def test_speech_union_clips_overlaps_and_ignores_duplicate_container_spans(self):
        transcript = {'words': [], 'segments': [{'start': -10, 'end': 20}, {'start': 10, 'end': 40},
            {'start': 10, 'end': 40}, {'start': 80, 'end': 120}, {'start': 200, 'end': 210}]}
        metrics = build_episode_profile(100, transcript, [])['metrics']
        self.assertEqual(metrics['speech_duration'], 60)
        self.assertEqual(metrics['speech_density'], .6)
        self.assertEqual(metrics['pause_duration'], 40)
        self.assertEqual(metrics['average_pause_duration'], 40)
        self.assertEqual(metrics['pause_count'], 1)
        self.assertAlmostEqual(metrics['average_utterance_duration'], 70/3, places=5)

    def test_actual_word_timings_override_overbroad_asr_segment(self):
        metrics = build_episode_profile(180, {'words': [{'start': 60, 'end': 61, 'text': 'Да.'}],
            'segments': [{'start': 0, 'end': 180, 'text': 'oversized ASR container'}]}, [])['metrics']
        self.assertEqual(metrics['speech_duration'], 1)
        self.assertEqual(metrics['speech_timing_source'], 'words')
        self.assertLess(metrics['speech_density'], .01)

    def test_raw_suppressed_candidate_activity_remains_visible_in_profile(self):
        candidates = [{'time': index*.5, 'score': .5, 'accepted': False, 'reason': 'suppressed_as_camera_motion'}
                      for index in range(1, 120)]
        profile = build_episode_profile(60, EMPTY, footage(60, 30), raw_candidates=candidates)
        self.assertEqual(profile['profile'], 'action_dense')
        self.assertEqual(profile['metrics']['raw_candidates'], 119)
        self.assertEqual(profile['metrics']['shots'], 2)
        self.assertEqual(profile['metrics']['motion_evidence'], 'scene_change_score_proxy')
        self.assertEqual(profile['metrics']['action_units'], 0)

    def test_duplicate_candidate_timestamps_are_one_boundary_with_peak_score(self):
        profile = build_episode_profile(60, EMPTY, [], raw_candidates=[(10, .2), (10, .5), (10, .5)])
        self.assertEqual(profile['metrics']['raw_candidates'], 1)
        self.assertAlmostEqual(profile['metrics']['motion_density'], .5/30, places=5)

    def test_supplied_motion_is_duration_weighted_and_not_confused_with_cut_scores(self):
        shots = [{'start': 0, 'end': 90, 'motion_score': .1}, {'start': 90, 'end': 100, 'motion_score': .9}]
        profile = build_episode_profile(100, EMPTY, shots, raw_candidates=[(50, .99)])
        self.assertEqual(profile['metrics']['motion_density'], .18)
        self.assertEqual(profile['metrics']['motion_evidence'], 'supplied_motion_score')

    def test_confirmed_actions_silent_units_and_bridges_refine_budget(self):
        events = [confirmed_event(0, 100, narrative_bridge=True,
            units=[{'id': 'spoken', 'start': 10, 'end': 20}, {'id': 'silent', 'start': 50, 'end': 70}],
            action_units=['spoken', 'silent']), confirmed_event(100, 180, importance=5)]
        transcript = {'words': [{'start': 10, 'end': 20, 'text': 'Важная реплика.'}], 'segments': []}
        initial = build_episode_profile(180, transcript, [])
        refined = build_episode_profile(180, transcript, [], scenes=[{'start': 0, 'end': 100}, {'start': 100, 'end': 180}], events=events)
        metrics = refined['metrics']
        self.assertEqual(refined['phase'], 'refined')
        self.assertEqual(metrics['action_units'], 2)
        self.assertEqual(metrics['silent_action_units'], 1)
        self.assertEqual(metrics['narrative_bridges'], 1)
        self.assertEqual(metrics['action_duration'], 30)
        self.assertEqual(metrics['importance_mean'], 4.5)
        self.assertEqual(metrics['average_scene_duration'], 90)
        self.assertGreater(refined['planner_budget']['optimal'], initial['planner_budget']['optimal'])
        self.assertIn('narrative_bridges', refined['planner_budget']['reason'])

    def test_uncertain_or_foreign_actions_never_become_confirmed_story_density(self):
        action = {'id': 'action', 'start': 0, 'end': 60}
        events = [confirmed_event(0, 60, uncertain=True, narrative_bridge=True, units=[action], action_units=['action']),
                  confirmed_event(60, 120, units=[{'id': 'foreign', 'start': 0, 'end': 60}], action_units=['foreign'])]
        metrics = build_episode_profile(120, EMPTY, [], events=events)['metrics']
        self.assertEqual(metrics['action_units'], 0)
        self.assertEqual(metrics['narrative_bridges'], 0)
        self.assertEqual(metrics['action_density'], 0)
        self.assertEqual(metrics['unknown_action_ids'], 1)

    def test_overlapping_confirmed_actions_and_duplicate_events_do_not_double_count_duration(self):
        event = confirmed_event(0, 100, narrative_bridge=True,
            units=[{'id': 'one', 'start': 10, 'end': 30}, {'id': 'two', 'start': 20, 'end': 40}],
            action_units=['one', 'two'])
        metrics = build_episode_profile(100, EMPTY, [], events=[event, copy.deepcopy(event)])['metrics']
        self.assertEqual(metrics['action_duration'], 30)
        self.assertEqual(metrics['action_density'], .3)
        self.assertEqual(metrics['story_events'], 1)
        self.assertEqual(metrics['narrative_bridges'], 1)

    def test_profile_is_jsonable_and_does_not_mutate_inputs_or_policy(self):
        transcript, shots, events = dialogue(600), footage(600, 30), [confirmed_event(0, 60)]
        originals = copy.deepcopy((transcript, shots, events, EPISODE_PROFILE_POLICY))
        profile = build_episode_profile(600, transcript, shots, events=events)
        json.dumps(profile, allow_nan=False)
        self.assertEqual((transcript, shots, events, EPISODE_PROFILE_POLICY), originals)
        self.assertEqual(profile['version'], EPISODE_PROFILE_VERSION)
        profile['policy']['classifier']['speech_high'] = -1
        self.assertEqual(EPISODE_PROFILE_POLICY, originals[3])

    def test_empty_and_short_sources_have_bounded_metrics_and_budget(self):
        for duration in (0, 1e-8, 1, 600):
            with self.subTest(duration=duration):
                profile = build_episode_profile(duration, EMPTY, [])
                budget = profile['planner_budget']
                self.assertLessEqual(0, budget['min'])
                self.assertLessEqual(budget['min'], budget['optimal'])
                self.assertLessEqual(budget['optimal'], budget['max'])
                self.assertLessEqual(budget['max'], duration)
                self.assertEqual(profile['metrics']['speech_density'], 0)
                self.assertEqual(profile['metrics']['motion_density'], 0)
                json.dumps(profile, allow_nan=False)
        one = build_episode_profile(1, EMPTY, [{'start': 0, 'end': 1}])
        self.assertEqual(one['profile'], 'balanced')

    def test_budgets_scale_with_source_and_story_density_not_fixed_520(self):
        short = build_episode_profile(600, dialogue(600), footage(600, 30))
        long = build_episode_profile(1200, dialogue(1200), footage(1200, 30))
        self.assertAlmostEqual(long['planner_budget']['optimal'], short['planner_budget']['optimal']*2)
        dense = build_episode_profile(600, dialogue(600), footage(600, 30),
            events=[confirmed_event(index*20, index*20+20, importance=5) for index in range(30)])
        self.assertGreater(dense['planner_budget']['optimal'], short['planner_budget']['optimal'])
        self.assertNotEqual(short['planner_budget']['optimal'], 520)
        self.assertNotEqual(dense['planner_budget']['optimal'], 520)

    def test_all_confirmed_action_source_can_raise_soft_optimal_to_source_duration(self):
        for duration in (100, 5e-7):
            with self.subTest(duration=duration):
                event = confirmed_event(0, duration, units=[{'id': 'action', 'start': 0, 'end': duration}], action_units=['action'])
                budget = build_episode_profile(duration, EMPTY, [], events=[event])['planner_budget']
                self.assertEqual(budget['optimal'], duration)
                self.assertEqual(budget['max'], duration)

    def test_malformed_finite_values_and_shapes_are_rejected(self):
        for duration in (True, -1, float('nan'), float('inf'), '600'):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                build_episode_profile(duration, EMPTY, [])
        cases = [({'words': [{'start': float('nan'), 'end': 1}]}, [], {}),
                 ({'segments': [{'start': 10, 'end': 2}]}, [], {}),
                 ({'words': None}, [], {}), (EMPTY, [{'start': 0, 'end': 60, 'scene_score': float('nan')}], {}),
                 (EMPTY, [{'start': 0, 'end': 60, 'motion_score': True}], {}),
                 (EMPTY, [], {'raw_candidates': [(1, float('inf'))]}),
                 (EMPTY, [], {'scenes': {}}), (EMPTY, [], {'events': {}}),
                 (EMPTY, [], {'events': [confirmed_event(0, 60, uncertain=True, confidence=float('nan'))]})]
        for transcript, shots, extra in cases:
            with self.subTest(extra=extra, shots=shots), self.assertRaises(ValueError):
                build_episode_profile(60, transcript, shots, **extra)
        with self.assertRaises(ValueError):
            adaptive_retention_budget({'profile': 'balanced', 'duration': 60, 'metrics': {'speech_density': 1.1}})
        with self.assertRaises(ValueError):
            scene_settings('invented')

    def test_settings_only_override_current_detector_keys_and_preserve_fast_location_change(self):
        shots = [{'id': 'one', 'start': 0, 'end': 10, 'features': {'location': 'room'}},
                 {'id': 'two', 'start': 10, 'end': 11.5, 'features': {'location': 'street'}},
                 {'id': 'three', 'start': 11.5, 'end': 20, 'features': {'location': 'car'}}]
        for kind in ('dialogue_slow', 'balanced', 'action_dense', 'mixed'):
            with self.subTest(kind=kind):
                settings = scene_settings(kind)
                self.assertLessEqual(set(settings), set(DEFAULT_SETTINGS))
                self.assertTrue(all(type(value) in (int, float) and value > 0 for value in settings.values()))
                scenes = detect_semantic_scenes(shots, EMPTY, 20, settings=settings)
                self.assertEqual([(scene['start'], scene['end']) for scene in scenes], [(0, 10), (10, 11.5), (11.5, 20)])


if __name__ == '__main__':
    unittest.main()
