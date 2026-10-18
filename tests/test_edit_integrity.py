"""Source-timing regressions; no model, media process or filesystem writes."""
import copy
import unittest

from app.edit_integrity import inspect_edits, normalize_proved_gaps, timing
from app.final_quality import inspect_final_quality
from app.planner import validate_plan, build_plan
from tests.test_final_quality import fixture, make_plan


class EditIntegrityTests(unittest.TestCase):
    def test_one_frame_hole_cannot_pass_existing_production_gate(self):
        analysis, _ = fixture()
        analysis['probe']['fps'] = 25
        plan = make_plan(analysis, [[{'start': 0, 'end': 3}, {'start': 3.04, 'end': 8}]])
        problems = inspect_final_quality(analysis, plan)['problems']
        tiny = [p for p in problems if p['code'] == 'introduced_micro_gap']
        self.assertEqual(len(tiny), 1)
        self.assertEqual(tiny[0]['range'], {'start': 3, 'end': 3.04})
        self.assertEqual(tiny[0]['timing_basis'], 'source_average_fps')
        with self.assertRaisesRegex(ValueError, 'edit_integrity: introduced_micro_gap'):
            validate_plan(plan, analysis)

    def test_duration_threshold_uses_source_fps_and_explicit_legacy_fallback(self):
        analysis, _ = fixture()
        plan = make_plan(analysis, [[{'start': 0, 'end': 3}, {'start': 3.08, 'end': 8}]])
        analysis['probe']['fps'] = 25
        self.assertEqual(inspect_edits(analysis, plan)[0]['code'], 'introduced_micro_gap')
        analysis['probe']['fps'] = 60
        self.assertEqual(inspect_edits(analysis, plan), [])
        for invalid in (None, 0, float('nan'), True):
            analysis['probe']['fps'] = invalid
            self.assertEqual(timing(analysis), {'fps': 30.0, 'timing_basis': 'legacy_assumed_30fps'})
        plan = make_plan(analysis, [[{'start': 0, 'end': 3}, {'start': 3.04, 'end': 8}]])
        self.assertEqual(inspect_edits(analysis, plan)[0]['timing_basis'], 'legacy_assumed_30fps')

    def test_complete_fast_source_shot_is_preserved_but_fragment_is_reported(self):
        analysis, _ = fixture()
        analysis['probe']['fps'] = 25
        analysis['shots'] = [{'start': 0}, {'start': 3}, {'start': 3.04}, {'start': 4}]
        plan = make_plan(analysis, [[{'start': 3, 'end': 3.04}, {'start': 4, 'end': 8}]])
        self.assertEqual(inspect_edits(analysis, plan), [])
        plan = make_plan(analysis, [[{'start': 3, 'end': 3.02}, {'start': 4, 'end': 8}]])
        self.assertEqual([p['code'] for p in inspect_edits(analysis, plan)], ['introduced_micro_fragment'])

    def test_contiguous_bookkeeping_cuts_and_independent_parts_are_not_holes(self):
        analysis, _ = fixture()
        plan = make_plan(analysis, [[{'start': 0, 'end': .04}, {'start': .04, 'end': 3}],
                                    [{'start': 3.04, 'end': 8}]])
        self.assertEqual(inspect_edits(analysis, plan), [])

    def test_normalization_requires_positive_evidence_without_speech_or_exclusions(self):
        analysis, _ = fixture()
        intervals = [{'start': 0, 'end': 3, 'event_ids': ['e']},
                     {'start': 3.04, 'end': 8, 'event_ids': ['e']}]
        before = copy.deepcopy(analysis)
        joined = normalize_proved_gaps(intervals, analysis, analysis['events'])
        self.assertEqual(joined, [{'start': 0, 'end': 8, 'event_ids': ['e']}])
        self.assertEqual(analysis, before)
        for kind in ('no_proof', 'word', 'exclusion', 'action', 'explicit_drop', 'review_scope'):
            changed = copy.deepcopy(analysis)
            event = changed['events'][0]
            if kind == 'no_proof':
                event['unit_evidence'] = []
            elif kind == 'word':
                changed['transcript']['words'].append({'start': 3, 'end': 3.04, 'text': 'А'})
            elif kind == 'exclusion':
                event['excluded_review_ranges'] = [{'start': 3, 'end': 3.04}]
            elif kind == 'action':
                event['unit_evidence'][0]['kind'] = 'state_transition'
            elif kind == 'explicit_drop':
                event['unit_evidence'].append({'unit': 'q', 'decision': 'drop',
                                              'view_start': 3, 'view_end': 3.04})
            else:
                changed['review_scope'] = {'ranges': [{'start': 0, 'end': 3}, {'start': 3.04, 'end': 8}]}
            with self.subTest(kind=kind):
                self.assertEqual(normalize_proved_gaps(intervals, changed, changed['events']), intervals)

    def test_classic_planner_joins_only_proved_silent_micro_gap(self):
        analysis, _ = fixture()
        analysis['events'][0]['part_endings'][0]['evidence'] = 'Original response ends the exchange.'
        analysis['events'][0]['selected_ranges'] = [{'start': 0, 'end': 3}, {'start': 3.04, 'end': 8}]
        analysis['events'][0]['unit_selection_version'] = 1
        plan = build_plan(analysis)
        self.assertEqual(plan['semantic_ranges'], [{'start': 0, 'end': 8}])
        self.assertEqual(inspect_edits(analysis, plan), [])

    def test_gap_cannot_acquire_another_source_owner(self):
        analysis, _ = fixture()
        intervals = [{'start': 0, 'end': 3, 'event_ids': ['left']},
                     {'start': 3.04, 'end': 8, 'event_ids': ['right']}]
        self.assertEqual(normalize_proved_gaps(intervals, analysis, analysis['events']), intervals)

    def test_dramatic_planner_preserves_complete_fast_shot(self):
        from app.dramatic_planner import build_dramatic_plan
        from tests.test_retention_allocation import event
        events = [event('fast', 0, .04), event('long', 4, 10)]
        for row in events:
            row.update(kind='story', importance=5, summary='Complete original source shot.',
                       requires=[], focus=[], unit_selection_version=1)
        analysis = {'probe': {'duration': 50, 'width': 640, 'height': 360, 'fps': 25, 'has_audio': True},
                    'events': events, 'transcript': {'words': [], 'segments': []},
                    'shots': [{'start': 0, 'end': .04}, {'start': .04, 'end': 4}, {'start': 4, 'end': 50}]}
        plan = build_dramatic_plan(analysis)
        first = plan['parts'][0]['cuts'][0]
        self.assertEqual((first['start'], first['end']), (0, .04))
        self.assertEqual(inspect_edits(analysis, plan), [])

    def test_planner_never_fills_even_submillisecond_confirmed_exclusion(self):
        analysis, _ = fixture()
        event = analysis['events'][0]
        event['part_endings'][0]['evidence'] = 'Original response ends the exchange.'
        event['unit_selection_version'] = 1
        event['excluded_review_ranges'] = [{'start': 3, 'end': 3.001}]
        with self.assertRaisesRegex(ValueError, 'edit_integrity: introduced_micro_gap'):
            build_plan(analysis)


if __name__ == '__main__':
    unittest.main()
