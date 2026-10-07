"""Bounded child refinement preserves parent ownership and omission evidence."""
import copy
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP
from app.scene_refinement import refine_scene_story
from app.source_roles import confirmed_exclusions, verified_story_ranges
from app.story import _valid_cache, STORY_VERSION


EMPTY = {'words': [], 'segments': []}


def parent():
    return {'id': 'event_0000', 'scene_id': 'scene_0000', 'parent_scene_id': 'scene_0000',
            'start': 0, 'end': 90, 'summary': 'Initial', 'kind': 'story', 'importance': 4,
            'requires': [], 'focus': [], 'uncertain': False,
            'selected_ranges': [{'start': 0, 'end': 90}],
            'scene_evidence': {'large': 'only for the parent'},
            'analysis_chunks': [{'id': f'scene_0000_chunk_{i:03d}', 'parent_scene_id': 'scene_0000',
                                 'start': a, 'end': b} for i, (a, b) in enumerate(((0, 40), (40, 80), (80, 90)))],
            'chunk_analyses': [{'summary': s, 'kind': 'story', 'importance': 4, 'uncertain': False}
                               for s in ('setup', 'development', 'late payoff')]}


def refined(child, **changes):
    return {**copy.deepcopy(child), 'story_warnings': [], 'selection_uncertain': False,
            'unit_selection_version': 1, **changes}


def review(start, end):
    return {'version': 2, 'decision': {'decisions': [
        {'unit': 'u001', 'retained_witness': 'none', 'keep': True, 'story_change': True,
         'reaction_or_humor': False, 'current_episode_story': True, 'confidence': .98,
         'evidence': 'Current footage shows a new state change.'},
        {'unit': 'u002', 'retained_witness': 'u000', 'keep': False, 'story_change': False,
         'reaction_or_humor': False, 'current_episode_story': False, 'confidence': .98,
         'evidence': 'An earlier retained source unit already shows this action.'}]},
        'restored_units': ['u001'], 'verified_units': [{'id': 'u001', 'start': start, 'end': end}]}


class SceneRefinementTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP / ('scene-refinement-' + uuid.uuid4().hex)
        self.job.mkdir(parents=True)

    def tearDown(self):
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    def run_refinement(self, event, callback):
        with patch('app.story.refine_story', side_effect=callback) as refine:
            result = refine_scene_story([event], EMPTY, [], self.job, object(), lambda *a: None, lambda: False)
        return result[0], refine

    def test_child_collage_ids_and_single_parent_with_bounded_selections(self):
        original = parent()
        snapshot = copy.deepcopy(original)
        def fake(children, *args):
            self.assertEqual([c['id'] for c in children], ['event_0000_chunk_000', 'event_0000_chunk_001', 'event_0000_chunk_002'])
            self.assertTrue(all(c['parent_event_id'] == original['id'] for c in children))
            self.assertTrue(all('analysis_chunks' not in c and 'chunk_analyses' not in c and 'scene_evidence' not in c for c in children))
            return [refined(c, selected_ranges=[{'start': c['start'] + 1, 'end': c['end'] - 1}]) for c in children]
        result, refine = self.run_refinement(original, fake)
        refine.assert_called_once()
        self.assertEqual(original, snapshot)
        self.assertEqual(result['id'], original['id'])
        self.assertEqual(result['scene_id'], original['scene_id'])
        self.assertEqual(result['selected_ranges'], [{'start': 1, 'end': 39}, {'start': 41, 'end': 79}, {'start': 81, 'end': 89}])
        self.assertEqual(result['unit_selection_version'], 1)
        self.assertIn('late payoff', result['summary'])
        self.assertEqual(len(result['chunk_refinements']), 3)

    def test_proofs_and_witnesses_have_unique_chunk_ids_and_survive_serialization_contract(self):
        def fake(children, *args):
            return [refined(c, story_omission_review=review(c['start'] + 2, c['start'] + 4),
                            verified_current_story_ranges=[{'start': c['start'] + 2, 'end': c['start'] + 4}],
                            omitted_story_units=[{'id': 'u002', 'start': c['start'] + 5, 'end': c['start'] + 6,
                                                  'reason': 'repeated_information'}]) for c in children]
        result, _ = self.run_refinement(parent(), fake)
        proof = result['story_omission_review']
        self.assertEqual(proof['version'], 2)
        self.assertEqual(proof['restored_units'], ['c000_u001', 'c001_u001', 'c002_u001'])
        self.assertEqual([u['id'] for u in proof['verified_units']], proof['restored_units'])
        self.assertEqual([d['retained_witness'] for d in proof['decision']['decisions'] if d['unit'].endswith('u002')],
                         ['c000_u000', 'c001_u000', 'c002_u000'])
        self.assertEqual(verified_story_ranges(result), [{'start': 2, 'end': 4}, {'start': 42, 'end': 44}, {'start': 82, 'end': 84}])
        self.assertTrue(_valid_cache({'version': STORY_VERSION, 'signature': 'proof', 'event': result}, 'proof', parent()))
        self.assertEqual([u['id'] for u in result['omitted_story_units']], ['c000_u002', 'c001_u002', 'c002_u002'])

    def test_one_pure_credit_child_does_not_authorize_whole_parent_exclusion(self):
        def fake(children, *args):
            return [refined(c, kind='opening', importance=1, credit_montage=True, contains_credits=True)
                    if i == 0 else refined(c) for i, c in enumerate(children)]
        result, _ = self.run_refinement(parent(), fake)
        self.assertTrue(result['contains_credits'])
        self.assertFalse(result['credit_montage'])
        self.assertEqual(result['kind'], 'story')
        self.assertEqual(result['importance'], 4)
        self.assertEqual(confirmed_exclusions(result), [])
        self.assertEqual(result['selected_ranges'], [{'start': 0, 'end': 90}])

    def test_all_confirmed_pure_credit_children_can_keep_pure_parent_label(self):
        def fake(children, *args):
            result = []
            for child in children:
                value = refined(child, kind='opening', importance=1, credit_montage=True, contains_credits=True)
                value.pop('unit_selection_version')
                result.append(value)
            return result
        result, _ = self.run_refinement(parent(), fake)
        self.assertTrue(result['credit_montage'])
        self.assertEqual(result['importance'], 1)
        self.assertEqual(result['unit_selection_version'], 1)
        self.assertEqual(confirmed_exclusions(result), [])

    def test_ambiguous_child_does_not_grant_parent_validated_unit_partition(self):
        def fake(children, *args):
            result = [refined(c) for c in children]
            result[1].pop('unit_selection_version')
            result[1]['selection_uncertain'] = True
            return result
        result, _ = self.run_refinement(parent(), fake)
        self.assertNotIn('unit_selection_version', result)
        self.assertTrue(result['selection_uncertain'])

    def test_malformed_positive_proof_is_not_promoted_to_source_authority(self):
        def fake(children, *args):
            result = [refined(c) for c in children]
            result[0]['story_omission_review'] = review(2, 4)
            result[0]['verified_current_story_ranges'] = [{'start': 2, 'end': 4}]
            result[0]['story_omission_review']['decision']['decisions'][0]['current_episode_story'] = 1
            return result
        result, _ = self.run_refinement(parent(), fake)
        self.assertNotIn('story_omission_review', result)
        self.assertEqual(verified_story_ranges(result), [])
        self.assertTrue(result['selection_uncertain'])
        self.assertTrue(result['chunk_refinements'][0]['proof_rejected'])
        self.assertNotIn('unit_selection_version', result)

    def test_atmosphere_and_speech_context_protections_remain_selected(self):
        original = parent()
        original['speech_context_protections'] = [{'prefix': 'не', 'start': 1, 'end': 2,
                                                   'continuation_start': 4, 'continuation_end': 8}]
        def fake(children, *args):
            return [refined(c, selected_ranges=[{'start': c['start'] + 10 if c['end'] - c['start'] > 10 else c['start'] + 5,
                                                'end': c['end']}],
                            protected_atmosphere_units=['u000'],
                            protected_atmosphere_ranges=[{'start': c['start'] + 2, 'end': c['start'] + 3}],
                            speech_context_protections=[{'prefix': 'как', 'start': c['start'] + 3, 'end': c['start'] + 4}])
                    for c in children]
        result, _ = self.run_refinement(original, fake)
        self.assertEqual(result['protected_atmosphere_units'], ['c000_u000', 'c001_u000', 'c002_u000'])
        self.assertEqual(len(result['speech_context_protections']), 4)
        for a, b in ((1, 2), (2, 4), (42, 44), (82, 84)):
            self.assertTrue(any(r['start'] <= a and r['end'] >= b for r in result['selected_ranges']))

    def test_no_child_generated_exclusion_ranges_gain_authority(self):
        result, _ = self.run_refinement(parent(), lambda children, *a: [refined(c, excluded_credit_ranges=[{'start': c['start'], 'end': c['end']}]) for c in children])
        self.assertEqual(confirmed_exclusions(result), [])
        self.assertNotIn('excluded_credit_ranges', result)

    def test_legacy_event_without_chunks_uses_original_refiner_contract(self):
        original = parent()
        original.pop('analysis_chunks')
        result, refine = self.run_refinement(original, lambda children, *a: [refined(c) for c in children])
        self.assertEqual(refine.call_args.args[0][0]['id'], original['id'])
        self.assertNotIn('chunk_refinements', result)

    def test_invalid_chunk_partition_is_rejected_before_refinement(self):
        original = parent()
        original['analysis_chunks'][1]['start'] = 41
        with patch('app.story.refine_story') as refine, self.assertRaises(ValueError):
            refine_scene_story([original], EMPTY, [], self.job, object(), lambda *a: None, lambda: False)
        refine.assert_not_called()


if __name__ == '__main__':
    unittest.main()
