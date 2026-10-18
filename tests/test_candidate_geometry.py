"""Private physical proposal geometry, with no model or editorial acceptance."""
import copy
import unittest

from app.edit_integrity import MAX_EDIT_FRAMES, inspect_edits, timing
from app.planner import validate_plan
from app.source_ranges import merge_ranges
from app.standalone_planner import _plan
from app.story_candidates import candidate_cases, prototype_plan


LEFT = {'start': 20.0, 'end': 21.647}
RIGHT = {'start': 21.680, 'end': 24.0}
CONTRACT = 'standalone_candidate_proved_v1'


def analysis_fixture():
    return {'probe': {'duration': 40.0, 'width': 640, 'height': 360, 'fps': 24.0, 'has_audio': True},
        'transcript': {'words': [], 'segments': []},
        'shots': [{'id': 'physical', 'start': 0.0, 'end': 40.0}],
        'events': [{'id': 'physical', 'start': 0.0, 'end': 40.0, 'kind': 'story',
                    'source_interval': True, 'selected_ranges': [copy.deepcopy(LEFT), copy.deepcopy(RIGHT)]}],
        'quality_policy': CONTRACT}


def candidate_fixture():
    analysis = analysis_fixture()
    analysis.pop('events')
    analysis.pop('quality_policy')
    points = [0.0, LEFT['start'], LEFT['end'], RIGHT['start'], RIGHT['end'], 40.0]
    analysis['shots'] = [{'id': f'shot_{index}', 'start': start, 'end': end}
                         for index, (start, end) in enumerate(zip(points, points[1:]))]
    source_sha = 'a'*64
    episode_map = {'source_sha256': source_sha, 'authority': 'hypothesis_only',
        'windows': [{'id': 'all', 'start': 0.0, 'end': 40.0}],
        'hypotheses': [{'id': 'authored', 'window_ids': ['all'], 'prerequisite_window_ids': []}]}
    case = candidate_cases(analysis, episode_map, source_sha)[0]
    left = next(unit for unit in case['units'] if unit['start'] == LEFT['start'] and unit['end'] == LEFT['end'])
    right = next(unit for unit in case['units'] if unit['start'] == RIGHT['start'] and unit['end'] == RIGHT['end'])
    proposal = {'viable': True, 'title': 'Authored physical proposal', 'reason': 'Geometry test only',
        'interest': 1, 'cuts': [{'first': left['id'], 'last': left['id']},
                                {'first': right['id'], 'last': right['id']}]}
    return analysis, case, proposal


class CandidateGeometryTests(unittest.TestCase):
    def test_private_actual_gap_is_restored_before_native_review_without_changing_original_core(self):
        analysis, case, proposal = candidate_fixture()
        before = copy.deepcopy((analysis, case, proposal))
        plan, scoped = prototype_plan(analysis, case, proposal)
        self.assertEqual((analysis, case, proposal), before)
        self.assertEqual(plan['semantic_ranges'], [LEFT, RIGHT])
        self.assertEqual([(cut['start'], cut['end']) for cut in plan['parts'][0]['cuts']], [(20.0, 24.0)])
        self.assertEqual(plan['parts'][0]['duration'], 4.0)
        self.assertEqual(inspect_edits(scoped, plan), [])
        validate_plan(plan, scoped)
        self.assertEqual(plan['technical_normalizations'], [{
            'reason': 'restore_tiny_silent_gap_before_native_review',
            'range': {'start': 21.647, 'end': 21.680},
            'fps': 24.0, 'timing_basis': 'source_average_fps'}])
        self.assertIsNot(plan.get('export_eligible'), True)
        self.assertNotIn('quality_gate', plan)
        self.assertNotIn('candidate_evidence', scoped)
        self.assertNotIn('review', case)

    def test_framing_rebuild_reproduces_identical_actual_geometry_and_normalization(self):
        analysis, case, proposal = candidate_fixture()
        plan, scoped = prototype_plan(analysis, case, proposal)
        for event in scoped['events']:
            event['focus'] = [{'time': event['start'], 'x': .4, 'y': .6, 'confidence': .8}]
        before = copy.deepcopy((scoped, plan['semantic_ranges']))
        rebuilt = _plan(scoped, plan['semantic_ranges'])
        self.assertEqual((scoped, plan['semantic_ranges']), before)
        geometry = lambda item: [(part['duration'], [(cut['start'], cut['end'], cut['event_ids'])
            for cut in part['cuts']]) for part in item['parts']]
        self.assertEqual(geometry(rebuilt), geometry(plan))
        self.assertEqual(rebuilt['technical_normalizations'], plan['technical_normalizations'])
        self.assertEqual(rebuilt['semantic_ranges'], plan['semantic_ranges'])
        validate_plan(rebuilt, scoped)

    def test_word_or_complete_segment_overlapping_gap_keeps_normal_edit_integrity_rejection(self):
        for container in ('words', 'segments'):
            analysis = analysis_fixture()
            analysis['transcript'][container] = [{'start': 21.647, 'end': 21.680,
                                                  'text': 'Original source speech'}]
            before = copy.deepcopy(analysis)
            plan = _plan(analysis, [LEFT, RIGHT])
            self.assertEqual(analysis, before)
            self.assertEqual(len(plan['parts'][0]['cuts']), 2)
            self.assertNotIn('technical_normalizations', plan)
            self.assertEqual(inspect_edits(analysis, plan)[0]['code'], 'introduced_micro_gap')
            with self.subTest(container=container), self.assertRaisesRegex(ValueError, 'introduced_micro_gap'):
                validate_plan(plan, analysis)

    def test_speech_touching_gap_edges_does_not_count_as_overlapping_omitted_speech(self):
        analysis = analysis_fixture()
        analysis['transcript']['segments'] = [
            {**LEFT, 'text': 'Complete original first utterance'},
            {**RIGHT, 'text': 'Complete original next utterance'}]
        plan = _plan(analysis, [LEFT, RIGHT])
        self.assertEqual(len(plan['parts'][0]['cuts']), 1)
        validate_plan(plan, analysis)

    def test_legacy_and_source_only_contracts_leave_the_same_gap_unchanged(self):
        for policy in ('source_proved_v1', 'standalone_selective_v1', 'standalone_source_v2', None):
            analysis = analysis_fixture()
            analysis['quality_policy'] = policy
            plan = _plan(analysis, [LEFT, RIGHT])
            self.assertEqual([(cut['start'], cut['end']) for cut in plan['parts'][0]['cuts']],
                             [(LEFT['start'], LEFT['end']), (RIGHT['start'], RIGHT['end'])])
            self.assertNotIn('technical_normalizations', plan)
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'introduced_micro_gap'):
                validate_plan(plan, analysis)

    def test_only_existing_frame_threshold_applies_and_micro_islands_are_not_changed(self):
        analysis = analysis_fixture()
        limit = MAX_EDIT_FRAMES/timing(analysis)['fps']
        near = {'start': LEFT['end']+limit, 'end': 24.0}
        plan = _plan(analysis, [LEFT, near])
        self.assertEqual(len(plan['parts'][0]['cuts']), 1)
        beyond = {'start': LEFT['end']+limit+.00001, 'end': 24.0}
        plan = _plan(analysis, [LEFT, beyond])
        self.assertEqual(len(plan['parts'][0]['cuts']), 2)
        self.assertNotIn('technical_normalizations', plan)
        island = [{'start': 21.0, 'end': 21.04}]
        plan = _plan(analysis, island)
        self.assertEqual(plan['semantic_ranges'], island)
        self.assertEqual([(cut['start'], cut['end']) for cut in plan['parts'][0]['cuts']], [(21.0, 21.04)])
        self.assertNotIn('technical_normalizations', plan)
        with self.assertRaisesRegex(ValueError, 'introduced_micro_fragment'):
            validate_plan(plan, analysis)

    def test_unreviewed_scope_gap_is_not_restored_and_candidate_context_guard_still_rejects(self):
        analysis = analysis_fixture()
        analysis['review_scope'] = {'ranges': [LEFT, RIGHT]}
        plan = _plan(analysis, [LEFT, RIGHT])
        self.assertEqual(len(plan['parts'][0]['cuts']), 2)
        self.assertNotIn('technical_normalizations', plan)
        source, case, proposal = candidate_fixture()
        wanted = {cut['first'] for cut in proposal['cuts']}
        case['units'] = [unit for unit in case['units'] if unit['id'] in wanted]
        case['source_ranges'] = merge_ranges(case['units'])
        before = copy.deepcopy((source, case, proposal))
        with self.assertRaisesRegex(ValueError, 'Audio handles leave reviewed candidate source context'):
            prototype_plan(source, case, proposal)
        self.assertEqual((source, case, proposal), before)


if __name__ == '__main__':
    unittest.main()
