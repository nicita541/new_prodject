"""Pace mechanisms and cached source calibration, without model invocations."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in (HERE, *HERE.parents) if (p/'tools/python/python.exe').is_file())
if HERE == ROOT:
    from app import episode_profile as profile
else:
    spec = importlib.util.spec_from_file_location('candidate_episode_profile_tests', HERE/'app/episode_profile.py')
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
build = profile.build_episode_profile
EMPTY = {'words': [], 'segments': []}


def motion(value, **fields):
    return {'version': 2, 'signature': 'measured-source-signature', 'source': {'sha256': 'source-hash'},
            'motion': {'physical_motion_density': value, 'global_camera_motion_density': value*.3,
                       'residual_motion_density': value*.7, 'available': True, 'adequate_coverage': True,
                       'measurement_coverage': .9, 'evidence': 'source_optical_flow', **fields}}


def speech(duration=100, occupancy=.75):
    return {'words': [], 'segments': [{'start': 0, 'end': duration*occupancy, 'text': 'Actual source dialogue.'}]}


def shots(duration=100, spacing=10, **features):
    starts = list(range(0, duration, spacing))
    return [{'id': f'shot_{i}', 'start': t, 'end': starts[i+1] if i+1 < len(starts) else duration,
             **features} for i, t in enumerate(starts)]


def event(start=0, end=100, **fields):
    return {'id': 'event', 'start': start, 'end': end, 'kind': 'story', 'importance': 4,
            'uncertain': False, 'understanding_status': 'accepted', 'selection_status': 'accepted',
            'understanding_confidence': .95, 'selection_confidence': .95,
            'units': [], 'action_units': [], 'unit_evidence': [], 'selected_ranges': [],
            'narrative_bridge': False, **fields}


def unit(ident='u', start=10, end=30):
    return {'id': ident, 'start': start, 'end': end, 'text': 'Do not trust this authored text as ASR.'}


def proof(ident='u', kind='physical_action', **fields):
    return {'unit': ident, 'kind': kind, 'decision': 'keep', 'confidence': .95,
            'evidence': 'The character visibly hands the bag to the other person.',
            'frame_indices': [1], 'frame_times': [16], 'frame_count': 1, 'speech_quote': '', **fields}


def action_event(**fields):
    defaults = {'units': [unit()], 'action_units': ['u'], 'unit_evidence': [proof()],
                'selected_ranges': [{'start': 15, 'end': 22}]}
    defaults.update(fields)
    return event(**defaults)


class EpisodeProfileMechanismTests(unittest.TestCase):
    def test_four_profiles_use_measured_movement_and_actual_asr_occupancy(self):
        cases = [('dialogue_slow', .75, .1), ('action_dense', .1, .8),
                 ('balanced', .4, .4), ('mixed', .75, .8)]
        for expected, occupancy, movement in cases:
            with self.subTest(expected=expected):
                result = build(100, speech(100, occupancy), shots(), perception=motion(movement))
                self.assertEqual(result['profile'], expected)
                self.assertEqual(result['phase'], 'initial')
                self.assertEqual(result['action_score'], 0)
                self.assertEqual(result['motion_score'], movement)
                self.assertEqual(result['speech_score'], occupancy)

    def test_reverse_camera_cuts_are_editing_without_physical_activity(self):
        result = build(100, speech(), shots(spacing=1, scene_score=.95), perception=motion(.08))
        self.assertEqual(result['profile'], 'dialogue_slow')
        self.assertEqual(result['editing_score'], .99)
        self.assertEqual(result['motion_score'], .08)
        self.assertEqual(result['metrics']['action_units'], 0)

    def test_tracking_single_shot_can_have_high_motion_without_editing_or_action_proof(self):
        result = build(100, EMPTY, shots(spacing=100), perception=motion(.95))
        self.assertEqual(result['profile'], 'action_dense')
        self.assertEqual(result['editing_score'], 0)
        self.assertEqual(result['action_score'], 0)
        self.assertEqual(result['metrics']['causal_units'], 0)
        self.assertIn('optical_flow_includes_camera_motion', result['limitations'])

    def test_raw_candidates_and_scene_scores_never_supply_motion(self):
        raw = [{'time': i*.5, 'scene_score': .95, 'accepted': False} for i in range(1, 200)]
        base = build(100, speech(), shots(spacing=50), perception=motion(.1))
        dense = build(100, speech(), shots(spacing=50, scene_score=.99),
                      raw_candidates=raw, perception=motion(.1))
        self.assertEqual(dense['profile'], base['profile'])
        self.assertEqual(dense['scores'], base['scores'])
        self.assertEqual(dense['metrics']['raw_candidates'], 199)
        self.assertEqual(dense['metrics']['raw_candidate_evidence'], 'raw_candidates')

    def test_duplicate_raw_candidate_times_are_diagnostic_peak_boundaries(self):
        result = build(60, EMPTY, [], raw_candidates=[(10, .2), (10, .8), (10, .8)])
        self.assertEqual(result['metrics']['raw_candidates'], 1)
        self.assertEqual(result['metrics']['raw_candidates_per_minute'], 1)
        self.assertIsNone(result['motion_score'])
        self.assertEqual(result['editing_score'], 0)

    def test_no_perception_is_explicitly_unavailable_even_with_legacy_motion_scalars(self):
        result = build(100, speech(), shots(motion_score=.99))
        self.assertEqual(result['profile'], 'balanced')
        self.assertIsNone(result['motion_score'])
        self.assertIsNone(result['metrics']['physical_motion_density'])
        self.assertEqual(result['metrics']['motion_density'], 0)
        self.assertFalse(result['metrics']['motion_available'])
        self.assertLessEqual(result['confidence'], .5)
        self.assertIn('motion_measurement_unavailable', result['reason'])

    def test_low_coverage_reports_measurement_but_cannot_assign_dense_category(self):
        result = build(100, EMPTY, [], perception=motion(.99, measurement_coverage=.1, adequate_coverage=False))
        self.assertEqual(result['profile'], 'balanced')
        self.assertEqual(result['motion_score'], .99)
        self.assertTrue(result['metrics']['motion_available'])
        self.assertFalse(result['metrics']['motion_reliable'])
        self.assertIn('insufficient_intra_shot_motion_coverage', result['reason'])

    def test_foreign_proxy_origin_is_unavailable(self):
        result = build(100, EMPTY, [], perception=motion(.99, evidence='scene_change_score_proxy'))
        self.assertIsNone(result['motion_score'])
        self.assertEqual(result['profile'], 'balanced')

    def test_continuous_scores_remain_independent_and_keep_legacy_aliases(self):
        result = build(100, speech(), shots(), events=[action_event()], perception=motion(.4))
        expected = {'speech_score': .75, 'editing_score': .09, 'motion_score': .4,
                    'action_score': .07, 'story_density_score': .07}
        self.assertEqual(result['scores'], expected)
        for key, value in expected.items():
            self.assertEqual(result[key], value)
            self.assertEqual(result['metrics'][key], value)
        self.assertEqual(result['metrics']['speech_density'], result['speech_score'])
        self.assertEqual(result['metrics']['motion_density'], result['motion_score'])
        self.assertEqual(result['metrics']['action_density'], result['action_score'])

    def test_word_timings_override_oversized_asr_container(self):
        result = build(100, {'words': [{'start': 60, 'end': 61, 'text': 'Да.'}],
                            'segments': [{'start': 0, 'end': 100, 'text': 'Broad container'}]}, [])
        self.assertEqual(result['speech_score'], .01)
        self.assertEqual(result['metrics']['speech_timing_source'], 'words')

    def test_speech_union_clamps_source_and_deduplicates(self):
        result = build(100, {'segments': [{'start': -10, 'end': 20}, {'start': 10, 'end': 40},
            {'start': 10, 'end': 40}, {'start': 80, 'end': 120}, {'start': 200, 'end': 210}]}, [])
        self.assertEqual(result['speech_score'], .6)
        self.assertEqual(result['metrics']['pause_duration'], 40)
        self.assertEqual(result['metrics']['pause_count'], 1)

    def test_bare_legacy_actions_and_importance_do_not_establish_story_density(self):
        legacy = event(units=[unit()], action_units=['u'], selected_ranges=[{'start': 0, 'end': 100}])
        result = build(100, EMPTY, [], events=[legacy])
        self.assertEqual(result['metrics']['action_units'], 0)
        self.assertEqual(result['metrics']['causal_units'], 0)
        self.assertEqual(result['story_density_score'], 0)
        self.assertEqual(result['metrics']['story_events'], 0)
        self.assertEqual(result['metrics']['proposed_story_events'], 1)

    def test_positive_actions_count_only_selected_source_intersection(self):
        result = build(100, EMPTY, [], events=[action_event(narrative_bridge=True)])
        self.assertEqual(result['metrics']['action_units'], 1)
        self.assertEqual(result['metrics']['action_duration'], 7)
        self.assertEqual(result['metrics']['causal_units'], 1)
        self.assertEqual(result['metrics']['silent_action_units'], 1)
        self.assertEqual(result['metrics']['narrative_bridges'], 1)
        self.assertEqual(result['metrics']['confirmed_story_events'], 1)

    def test_confirmed_nonstory_exclusions_remove_action_seconds(self):
        result = build(100, EMPTY, [], events=[action_event(excluded_credit_ranges=[{'start': 18, 'end': 20}])])
        self.assertEqual(result['metrics']['action_duration'], 5)
        self.assertEqual(result['story_density_score'], .05)

    def test_empty_selection_and_frame_outside_selection_do_not_count(self):
        for modified in (event(units=[unit()], action_units=['u'], unit_evidence=[proof()]),
                         action_event(unit_evidence=[proof(frame_times=[25])])):
            with self.subTest(event=modified):
                result = build(100, EMPTY, [], events=[modified])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_missing_source_frame_times_cannot_establish_positive_metrics(self):
        record = proof()
        record.pop('frame_times')
        result = build(100, EMPTY, [], events=[action_event(unit_evidence=[record], narrative_bridge=True)])
        self.assertEqual(result['metrics']['action_units'], 0)
        self.assertEqual(result['metrics']['causal_units'], 0)
        self.assertEqual(result['story_density_score'], 0)
        self.assertEqual(result['metrics']['narrative_bridges'], 0)

    def test_source_frame_index_must_not_exceed_full_current_board_count(self):
        for record in (proof(frame_indices=[999]), proof(frame_count=0), proof(frame_count=True), proof(frame_count=1.0)):
            with self.subTest(record=record):
                result = build(100, EMPTY, [], events=[action_event(unit_evidence=[record])])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_missing_source_frame_count_cannot_establish_visual_proof(self):
        record = proof()
        record.pop('frame_count')
        result = build(100, EMPTY, [], events=[action_event(unit_evidence=[record])])
        self.assertEqual(result['metrics']['action_units'], 0)
        self.assertEqual(result['story_density_score'], 0)

    def test_every_cited_frame_time_must_belong_to_current_unit_and_view(self):
        cases = [proof(frame_indices=[1, 2], frame_times=[16, 50], frame_count=2),
                 proof(frame_indices=[1, 2], frame_times=[16, 25], frame_count=2, view_start=15, view_end=22),
                 proof(frame_indices=[1, 2], frame_times=[16, 30], frame_count=2)]
        for record in cases:
            with self.subTest(record=record):
                result = build(100, EMPTY, [], events=[action_event(unit_evidence=[record])])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['metrics']['causal_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_source_frame_indices_must_be_unique_and_match_time_count(self):
        cases = [proof(frame_indices=[1, 1], frame_times=[16, 17]),
                 proof(frame_indices=[1, 2], frame_times=[16], frame_count=2),
                 proof(frame_times=[16, 17]), proof(frame_times=[])]
        for record in cases:
            with self.subTest(record=record):
                result = build(100, EMPTY, [], events=[action_event(unit_evidence=[record])])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_nonfinite_or_non_numeric_source_frame_times_are_not_positive_proof(self):
        for timestamp in (float('nan'), float('inf'), True, '16'):
            with self.subTest(timestamp=timestamp):
                result = build(100, EMPTY, [], events=[action_event(unit_evidence=[proof(frame_times=[timestamp])])])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_low_confidence_and_unresolved_units_do_not_count(self):
        changes = [{'selection_confidence': .89}, {'understanding_confidence': .89},
                   {'analysis_unresolved': True}, {'uncertain': True}, {'source_role_unresolved': True},
                   {'selection_status': 'unresolved'}, {'unit_evidence': [proof(confidence=.89)]}]
        for change in changes:
            with self.subTest(change=change):
                modified = action_event()
                modified.update(change)
                result = build(100, EMPTY, [], events=[modified])
                self.assertEqual(result['metrics']['action_units'], 0)
                self.assertEqual(result['story_density_score'], 0)

    def test_unknown_or_outside_current_unit_cannot_establish_action(self):
        modified = action_event()
        modified.update(units=[unit(start=-10, end=30)], action_units=['u', 'foreign'])
        result = build(100, EMPTY, [], events=[modified])
        self.assertEqual(result['metrics']['action_units'], 0)
        self.assertEqual(result['metrics']['unknown_action_ids'], 2)

    def test_duplicate_events_and_overlapping_units_do_not_inflate_source_seconds(self):
        modified = event(units=[unit('one', 10, 30), unit('two', 20, 40)], action_units=['one', 'two'],
            unit_evidence=[proof('one', frame_times=[16]), proof('two', frame_times=[25])],
            selected_ranges=[{'start': 10, 'end': 40}], narrative_bridge=True)
        result = build(100, EMPTY, [], events=[modified, copy.deepcopy(modified)])
        self.assertEqual(result['metrics']['action_duration'], 30)
        self.assertEqual(result['metrics']['action_units'], 2)
        self.assertEqual(result['metrics']['story_events'], 1)
        self.assertEqual(result['metrics']['narrative_bridges'], 1)

    def test_actual_causal_quote_counts_without_claiming_physical_action(self):
        transcript = {'words': [{'start': 12, 'end': 13, 'text': 'Отдай'},
                                {'start': 13, 'end': 14, 'text': 'сумку.'}], 'segments': []}
        modified = action_event(unit_evidence=[proof(kind='causal_dialogue', frame_indices=[],
            frame_times=[], speech_quote='Отдай сумку')], selected_ranges=[{'start': 12, 'end': 14}])
        result = build(100, transcript, [], events=[modified])
        self.assertEqual(result['metrics']['causal_units'], 1)
        self.assertEqual(result['metrics']['action_units'], 0)

    def test_actual_speech_only_quote_does_not_require_source_frame_count(self):
        transcript = {'words': [{'start': 12, 'end': 13, 'text': 'Отдай'},
                                {'start': 13, 'end': 14, 'text': 'сумку.'}], 'segments': []}
        record = proof(kind='causal_dialogue', frame_indices=[], frame_times=[], speech_quote='Отдай сумку')
        record.pop('frame_count')
        result = build(100, transcript, [], events=[action_event(unit_evidence=[record],
            selected_ranges=[{'start': 12, 'end': 14}])])
        self.assertEqual(result['metrics']['causal_units'], 1)
        self.assertEqual(result['story_density_score'], .02)
        self.assertEqual(result['action_score'], 0)

    def test_authored_unit_text_is_not_an_actual_source_quote(self):
        modified = action_event(unit_evidence=[proof(kind='causal_dialogue', frame_indices=[],
            frame_times=[], speech_quote='Do not trust this authored text as ASR')])
        result = build(100, EMPTY, [], events=[modified])
        self.assertEqual(result['metrics']['causal_units'], 0)

    def test_causal_quote_outside_selected_source_cannot_increase_story_density(self):
        transcript = {'words': [{'start': 12, 'end': 13, 'text': 'Отдай'},
                                {'start': 13, 'end': 14, 'text': 'сумку.'}], 'segments': []}
        modified = action_event(unit_evidence=[proof(kind='causal_dialogue', frame_indices=[],
            frame_times=[], speech_quote='Отдай сумку')])
        result = build(100, transcript, [], events=[modified])
        self.assertEqual(result['metrics']['causal_units'], 0)
        self.assertEqual(result['story_density_score'], 0)

    def test_speech_quote_alone_cannot_establish_reaction_or_physical_action(self):
        transcript = {'words': [{'start': 12, 'end': 13, 'text': 'Сумка.'}], 'segments': []}
        for kind in ('character_reaction', 'emotional_pause', 'physical_action', 'state_transition'):
            with self.subTest(kind=kind):
                modified = action_event(unit_evidence=[proof(kind=kind, frame_indices=[],
                    frame_times=[], speech_quote='Сумка')])
                result = build(100, transcript, [], events=[modified])
                self.assertEqual(result['story_density_score'], 0)
                self.assertEqual(result['metrics']['action_units'], 0)

    def test_neutral_or_generic_atmosphere_evidence_does_not_increase_story_density(self):
        for fields in ({'kind': 'neutral_scenery'}, {'evidence': 'generic atmosphere'}, {'decision': 'drop'}):
            with self.subTest(fields=fields):
                modified = action_event(unit_evidence=[proof(**fields)])
                result = build(100, EMPTY, [], events=[modified])
                self.assertEqual(result['story_density_score'], 0)

    def test_profile_is_jsonable_and_immutable(self):
        args = (speech(), shots(), [action_event()], motion(.4), profile.EPISODE_PROFILE_POLICY)
        before = copy.deepcopy(args)
        result = build(100, args[0], args[1], events=args[2], perception=args[3])
        json.dumps(result, allow_nan=False)
        self.assertEqual(args, before)
        result['policy']['classifier']['speech_high'] = -1
        result['perception_identity']['source']['sha256'] = 'changed'
        self.assertEqual(args, before)

    def test_empty_short_sources_have_finite_bounded_helpers(self):
        for duration in (0, 1e-8, 1, 600):
            with self.subTest(duration=duration):
                result = build(duration, EMPTY, [])
                budget = result['planner_budget']
                self.assertLessEqual(0, budget['min'])
                self.assertLessEqual(budget['min'], budget['optimal'])
                self.assertLessEqual(budget['optimal'], budget['max'])
                self.assertLessEqual(budget['max'], duration)
                json.dumps(result, allow_nan=False)

    def test_helpers_keep_existing_settings_and_source_scale_api(self):
        short = build(100, speech(), shots(), perception=motion(.1))
        long = build(200, speech(200), shots(200), perception=motion(.1))
        self.assertAlmostEqual(long['planner_budget']['optimal'], short['planner_budget']['optimal']*2)
        from app.scene_detection import DEFAULT_SETTINGS, detect_semantic_scenes
        source_shots = [{'id': 'one', 'start': 0, 'end': 10, 'features': {'location': 'room'}},
                        {'id': 'two', 'start': 10, 'end': 11.5, 'features': {'location': 'street'}},
                        {'id': 'three', 'start': 11.5, 'end': 20, 'features': {'location': 'car'}}]
        for kind in ('dialogue_slow', 'balanced', 'action_dense', 'mixed'):
            settings = profile.scene_settings(kind)
            self.assertLessEqual(set(settings), set(DEFAULT_SETTINGS))
            self.assertTrue(all(type(value) in (int, float) and value > 0 for value in settings.values()))
            detected = detect_semantic_scenes(source_shots, EMPTY, 20, settings=settings)
            self.assertEqual([(row['start'], row['end']) for row in detected], [(0, 10), (10, 11.5), (11.5, 20)])

    def test_nonfinite_or_malformed_measurements_are_rejected(self):
        for duration in (True, -1, float('nan'), float('inf'), '100'):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                build(duration, EMPTY, [])
        cases = [{'perception': motion(float('nan'))}, {'perception': motion(.1, available=1)},
                 {'perception': motion(.1, measurement_coverage=1.1)}, {'perception': {'motion': []}},
                 {'events': [action_event(understanding_confidence=float('nan'))]},
                 {'raw_candidates': [(10, float('inf'))]}, {'scenes': {}}, {'events': {}}]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                build(100, EMPTY, [], **fields)
        with self.assertRaises(ValueError):
            profile.adaptive_retention_budget({'profile': 'balanced', 'duration': 60,
                                               'metrics': {'speech_density': 1.1}})
        with self.assertRaises(ValueError):
            profile.scene_settings('invented')


class CachedSourceCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT/'scratch/stage3-profile/calibrate_episode_profile.py'
        clips = ROOT/'scratch/raw_video_quality/calibration/clips'
        if not path.is_file() or not (clips/'root_review.json').is_file():
            raise unittest.SkipTest('Optional cached source calibration artifacts are unavailable')
        spec = importlib.util.spec_from_file_location('candidate_pace_calibration_tests', path)
        cls.calibration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.calibration)
        # When these tests move into tests/, exercise the live profile, rather
        # than silently measuring a stale scratch implementation.
        cls.calibration.profile_module = lambda: profile
        cls.rows, cls.reviewed = cls.calibration.measurements()

    def test_actual_twelve_source_clips_match_training_and_holdout_pace_reviews(self):
        counts = {'training': 0, 'holdout': 0}
        for row in self.rows:
            partition = 'training' if row['clip'] in self.reviewed['training'] else 'holdout'
            with self.subTest(clip=row['clip'], partition=partition):
                self.assertEqual(row['actual'], self.reviewed[partition][row['clip']])
                self.assertTrue(row['motion_reliable'])
                self.assertEqual(row['action_score'], 0)
                self.assertEqual(len(row['source_sha256']), 64)
                counts[partition] += 1
        self.assertEqual(counts, {'training': 8, 'holdout': 4})

    def test_training_only_fit_recovers_fixed_policy(self):
        fit = self.calibration.fit_thresholds(self.rows, self.reviewed['training'])
        self.assertEqual(fit['policy'], profile.EPISODE_PROFILE_POLICY['classifier'])
        self.assertEqual(fit['training_error_count'], 0)
        self.assertEqual(fit['search_candidates'], 210)

    def test_holdout_mutation_cannot_change_fitted_policy(self):
        fit = self.calibration.fit_thresholds(self.rows, self.reviewed['training'])
        altered = copy.deepcopy(self.rows)
        for row in altered:
            if row['clip'] in self.reviewed['holdout']:
                row.update(speech_score=0, motion_score=1, actual='mixed')
        changed = self.calibration.fit_thresholds(altered, self.reviewed['training'])
        self.assertEqual(changed, fit)

    def test_actual_reverse_cuts_and_moving_single_shot_remain_separate(self):
        rows = {r['clip']: r for r in self.rows}
        self.assertEqual(rows['c009']['actual'], 'dialogue_slow')
        self.assertLess(rows['c009']['motion_score'], .2)
        self.assertGreater(rows['c009']['editing_score'], rows['c003']['editing_score'])
        self.assertEqual(rows['c003']['editing_score'], 0)
        self.assertGreater(rows['c003']['motion_score'], .8)
        self.assertGreater(rows['c003']['raw_candidates'], 30)


if __name__ == '__main__':
    unittest.main()
