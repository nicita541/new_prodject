"""Source-scoped editorial mechanisms; authored judgments are not quality acceptance."""
import copy
import shutil
import unittest
import uuid

from app.config import TEMP
from app.dramatic_planner import build_dramatic_plan, _event_dramatic_score
from app.planner import build_plan
from app.story_structure_pass import infer_story_structure, source_units, validate_structure
from app.viewer_interest import score_event, score_source, ending_cost
from app.editorial import DRAMATIC_PROFILE
from app.story_review import apply_global_selection
from tests.test_retention_allocation import event
from tests.test_story_structure_pass import fixture, FakeProvider, response


EMPTY = {'words': [], 'segments': []}


def story(identifier, start, end, importance, kind='physical_action'):
    value = event(identifier, start, end)
    value.update(kind='story', importance=importance, requires=[], focus=[], summary='Observed source beat.',
                 unit_selection_version=1)
    value['unit_evidence'][0]['kind'] = kind
    return value


class ViewerInterestTests(unittest.TestCase):
    def test_silent_emotional_payoff_outweighs_high_importance_explanation(self):
        quiet = story('quiet', 0, 4, 2, 'emotional_pause')
        talk = story('talk', 10, 14, 5)
        speech = [{'start': 10, 'end': 14, 'text': 'Long factual explanation.'}]
        transcript = {'words': speech, 'segments': speech}
        self.assertGreater(score_event(quiet, transcript)['total'], score_event(talk, transcript)['total'])
        self.assertEqual(_event_dramatic_score(talk, speech), _event_dramatic_score(talk, []))
        self.assertEqual(score_event(talk, transcript)['speech_density_bonus'], 0)

    def test_quota_retains_emotion_and_balanced_mode_accepts_low_plot_importance(self):
        quiet = story('quiet', 0, 4, 2, 'emotional_pause')
        talk = story('talk', 10, 14, 5)
        data = {'probe': {'duration': 20, 'width': 640, 'height': 360, 'has_audio': True},
                'events': [quiet, talk], 'transcript': EMPTY, 'shots': [],
                'episode_profile': {'source_duration': 20,
                    'retention_budget': {'min': 4, 'optimal': 4, 'max': 4}}}
        snapshot = copy.deepcopy(data)
        plan = build_dramatic_plan(data)
        self.assertEqual(plan['selected_event_ids'], ['quiet'])
        self.assertEqual(plan['retention_allocation']['retained_duration'], 4)
        self.assertIn('quiet', build_plan(data)['selected_event_ids'])
        diagnostic = next(r for r in plan['planner_diagnostics']['candidates'] if r['event_id'] == 'quiet')
        self.assertGreater(diagnostic['score_components']['viewer_interest_value'], 0)
        self.assertTrue(diagnostic['score_components']['signals'][0]['proof'])
        self.assertEqual(data, snapshot)

    def test_unknown_or_unanchored_or_excluded_emotion_does_not_gain_interest(self):
        for change in ('uncertain', 'unanchored', 'foreign_frame', 'excluded', 'nonstory'):
            value = story('quiet', 0, 4, 2, 'emotional_pause')
            if change == 'uncertain':
                value['selection_uncertain'] = True
            elif change == 'unanchored':
                value['unit_evidence'][0].update(frame_indices=[], frame_times=[])
            elif change == 'foreign_frame':
                value['unit_evidence'][0]['frame_times'] = [8]
            elif change == 'excluded':
                value['excluded_title_units'] = [{'start': 0, 'end': 4}]
            else:
                value['kind'] = 'opening'
            with self.subTest(change=change):
                self.assertEqual(score_event(value, EMPTY)['viewer_interest_value'], 0)

    def test_repeated_emotional_proofs_do_not_accumulate_a_count_bonus(self):
        first = story('first', 0, 4, 3, 'emotional_pause')
        second = story('second', 4, 8, 3, 'emotional_pause')
        one = score_event(first, EMPTY)
        both = score_source([first, second], {'first': first['selected_ranges'],
                            'second': second['selected_ranges']}, EMPTY)
        self.assertEqual(one['total'], both['total'])

    def test_legacy_generic_closure_has_no_viewer_interest(self):
        value = story('ordinary', 0, 4, 4)
        value['part_endings'] = [{'time': 4, 'kind': 'closure', 'confidence': .95,
            'verification': {'supported': True, 'confidence': .95}}] * 5
        score = score_event(value, EMPTY)
        self.assertEqual(score['viewer_interest_value'], 0)
        self.assertEqual(score['ending_value'], 0)
        closure = value['part_endings'][0]
        cliff = {**closure, 'kind': 'cliffhanger'}
        self.assertGreater(ending_cost(closure, score), ending_cost(cliff, score))
        self.assertGreater(ending_cost(closure, score), ending_cost(closure,
            score_event(story('emotion', 0, 4, 3, 'emotional_pause'), EMPTY)))

    def test_dramatic_global_review_does_not_drop_a_marked_comedic_beat(self):
        value = story('banter', 0, 4, 3)
        value['unit_evidence'] = []
        decisions = {'keep': [], 'omit': [{'event': 'banter', 'reason': 'low_stakes_filler',
            'evidence': 'The brief comic exchange adds no new plot fact.',
            'confidence': .95, 'reaction_or_humor': True}]}
        apply_global_selection([value], decisions, DRAMATIC_PROFILE)
        self.assertFalse(value.get('global_excluded', False))


class InterestStructureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP / ('viewer-interest-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)

    @staticmethod
    def dramatic_response(payload):
        value = response(payload)
        for row in value['units']:
            # Deliberately authored judgment, with exact inherited source proof.
            if row['ref']['unit'] == 'c000_u003':
                row.update(viewer_interest=['reversal', 'emotional_payoff'],
                           evidence='The evidenced response reverses expectations and supplies emotional payoff.')
        return value

    def inferred(self):
        value, transcript = fixture(4)
        value.update(kind='story', importance=4, requires=[], focus=[], unit_selection_version=1)
        result = infer_story_structure([value], transcript, self.directory,
                                      FakeProvider(self.dramatic_response), lambda: False)
        self.assertEqual(result['status'], 'accepted')
        return result, transcript

    def test_later_interesting_arc_wins_inside_same_parent_and_preserves_setup(self):
        result, transcript = self.inferred()
        data = {'probe': {'duration': 16, 'width': 640, 'height': 360, 'has_audio': True},
                'events': result['events'], 'transcript': transcript, 'shots': [],
                'episode_profile': {'source_duration': 16,
                    'retention_budget': {'min': 8, 'optimal': 8, 'max': 8}}}
        plan = build_dramatic_plan(data)
        self.assertEqual(plan['retention_allocation']['selected_ranges'], {'room': [{'start': 8, 'end': 16}]})
        first = plan['retention_allocation']['allocation_history'][0]
        self.assertEqual(first['candidate'], result['arcs'][1]['id'])
        self.assertEqual(first['score_components']['viewer_interest_value'], 32)
        self.assertEqual(plan['parts'][0]['cuts'][0]['start'], 8)
        self.assertEqual(plan['parts'][0]['cuts'][-1]['end'], 16)

    def test_interest_cannot_leak_into_another_arc_in_the_parent_scene(self):
        result, transcript = self.inferred()
        for left, right, expected in ((0, 8, 0), (8, 16, 32)):
            score = score_source(result['events'], {'room': [{'start': left, 'end': right}]}, transcript)
            self.assertEqual(score['viewer_interest_value'], expected)

    def test_foreign_or_stale_interest_citation_does_not_boost_rank(self):
        result, transcript = self.inferred()
        for change in ('foreign', 'missing', 'quote', 'uncertain', 'stale', 'bad_kind', 'malformed_support', 'malformed_proof'):
            source = copy.deepcopy(result['events'][0])
            row = source['story_structure']['units'][-1]
            if change == 'foreign':
                row['support'][0]['proof'] = source['story_structure']['units'][0]['support'][0]['proof']
            elif change == 'missing':
                row['support'] = []
            elif change == 'quote':
                row['support'][0]['quote'] = 'Words outside the actual source proof.'
            elif change == 'uncertain':
                row['confidence'] = .4
            elif change == 'stale':
                source['story_structure']['version'] = 7
            elif change == 'malformed_support':
                row['support'] = None
            elif change == 'malformed_proof':
                row['support'][0]['proof'] = []
            else:
                row['viewer_interest'] = ['made_up_category']
            with self.subTest(change=change):
                self.assertEqual(score_event(source, transcript)['viewer_interest_value'], 0)

    def test_structure_validator_rejects_unsupported_or_unknown_interest(self):
        value, transcript = fixture()
        nodes, _, _ = source_units([value], transcript)
        payload = {'CURRENT': nodes, 'CONTEXT_ONLY': [], 'MEMORY': []}
        for change in ('unknown', 'duplicate', 'confidence', 'support', 'missing'):
            raw = response(payload)
            row = raw['units'][0]
            row['viewer_interest'] = ['anticipation']
            if change == 'unknown':
                row['viewer_interest'] = ['fake']
            elif change == 'duplicate':
                row['viewer_interest'] *= 2
            elif change == 'confidence':
                row['confidence'] = .5
            elif change == 'support':
                row['support'] = []
            else:
                row.pop('viewer_interest')
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_structure(raw, nodes, nodes)


if __name__ == '__main__':
    unittest.main()
