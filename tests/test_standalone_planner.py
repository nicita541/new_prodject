"""Source-backed authored fixtures; no inference, network or filesystem writes."""
import copy
import unittest

from app.standalone_planner import build_standalone_candidates
from app.story_structure_pass import source_units, validate_structure, _merge_arcs
from app.planner import validate_plan
from app.final_quality import inspect_final_quality
from tests.test_story_structure_pass import facts


def source_fixture(groups=1, *, same_parent=False, seconds=20):
    events, words = [], []
    for owner in range(1 if same_parent else groups):
        count = groups*3 if same_parent else 3
        start = 0 if same_parent else owner*(3*seconds+10)
        units, evidence = [], []
        for index in range(count):
            left = start+index*seconds
            text = ('Условие', 'Действие', 'Результат')[index % 3]
            units.append({'id': f'u{index}', 'start': left, 'end': left+seconds, 'text': text})
            words.append({'start': left+1, 'end': left+2, 'text': text})
            evidence.append({'unit': f'u{index}', 'kind': 'causal_dialogue', 'decision': 'keep',
                'confidence': .95, 'evidence': 'The original spoken statement supplies this narrative beat.',
                'speech_quote': text, 'frame_indices': [], 'frame_times': [], 'view_start': left,
                'view_end': left+seconds, 'checkpoint': 'a'*64})
        events.append({'id': f'e{owner}', 'scene_id': f's{owner}', 'start': start, 'end': start+count*seconds,
            'kind': 'story', 'importance': 4, 'summary': 'Three source-grounded narrative beats.',
            'requires': [], 'focus': [], 'units': units, 'unit_evidence': evidence, 'action_units': [],
            'selection_status': 'accepted', 'understanding_status': 'accepted', 'understanding_confidence': .95,
            'selection_confidence': .95, 'analysis_unresolved': False,
            'selected_ranges': [{'start': start, 'end': start+count*seconds}]})
    transcript = {'words': words, 'segments': copy.deepcopy(words)}
    nodes, _, _ = source_units(events, transcript)
    support = lambda n: {'ref': n['ref'], 'proof': n['proofs'][0]['id'], 'quote': n['ASR']}
    raw = {'resolved': True, 'understanding_confidence': .95, 'structure_confidence': .95,
           'units': [], 'relations': [], 'arcs': [], 'canonical_entities': [], 'limitations': []}
    for index, node in enumerate(nodes):
        role = ('setup', 'development', 'payoff')[index % 3]
        raw['units'].append({'ref': node['ref'], 'roles': [role], 'before': facts(), 'after': facts(),
            'confidence': .95, 'evidence': 'The exact original source supports this narrative function.',
            'support': [support(node)], 'viewer_interest': []})
    for index in range(0, len(nodes), 3):
        group = nodes[index:index+3]
        refs = [n['ref'] for n in group]
        raw['arcs'].append({'anchor': refs[0], 'members': [{'ref': ref, 'role': role}
            for ref, role in zip(refs, ('setup', 'development', 'payoff'))], 'closed': True,
            'closing_unit': refs[-1], 'confidence': .95, 'evidence': 'Original cause develops and reaches an observed resolution.',
            'support': [support(n) for n in group]})
        for left, right in zip(group, group[1:]):
            raw['relations'].append({'type': 'cause', 'from': left['ref'], 'to': right['ref'],
                'confidence': .95, 'evidence': 'The earlier source beat is needed to understand the following outcome.',
                'support': [support(left), support(right)]})
        raw['relations'].append({'type': 'setup_payoff', 'from': refs[0], 'to': refs[-1],
            'confidence': .95, 'evidence': 'The observed ending resolves the exact source setup.',
            'support': [support(group[0]), support(group[-1])]})
    accepted = validate_structure(raw, nodes, nodes)
    arcs = _merge_arcs({(a['anchor']['event'], a['anchor']['unit']): [a] for a in raw['arcs']},
                      nodes, accepted['relations'], 'b'*64)
    for event in events:
        own = [n for n in nodes if n['ref']['event'] == event['id']]
        event['story_structure'] = {'version': 8, 'status': 'accepted', 'unresolved_refs': [],
            'units': [{**copy.deepcopy(row), 'status': 'accepted',
                'arc_ids': [a['id'] for a in arcs if row['ref'] in a['source_unit_refs']]}
                for row in accepted['accepted_units'] if row['ref']['event'] == event['id']]}
        event['dialogue_relations'] = {'version': 4, 'status': 'accepted', 'unresolved_refs': [], 'pairs': [],
            'coverage': [{'ref': n['ref'], 'status': 'CURRENT', 'dialogue_status': 'not_dialogue_dependency',
                          'source_ranges': n['source_ranges']} for n in own]}
        event['inferred_story_arcs'] = [copy.deepcopy(a) for a in arcs if event['id'] in a['event_ids']]
        event['story_relations'] = [copy.deepcopy(r) for r in accepted['relations']
                                   if event['id'] in (r['from']['event'], r['to']['event'])]
    return {'probe': {'duration': events[-1]['end'], 'width': 640, 'height': 360, 'fps': 25, 'has_audio': True},
            'events': events, 'transcript': transcript, 'shots': [{'start': e['start'], 'end': e['end']} for e in events],
            'scenes': [{'id': e['scene_id'], 'start': e['start'], 'end': e['end'], 'uncertainty_reasons': []} for e in events]}


class StandalonePlannerTests(unittest.TestCase):
    def test_complete_source_story_has_beginning_development_payoff_and_native_gate(self):
        analysis = source_fixture()
        before = copy.deepcopy(analysis)
        result = build_standalone_candidates(analysis)
        self.assertEqual(len(result['candidates']), 1, result['declined'])
        candidate = result['candidates'][0]
        self.assertTrue(candidate['export_eligible'])
        self.assertEqual(candidate['duration'], 60)
        self.assertEqual(len(candidate['premise_refs']), 1)
        self.assertEqual(len(candidate['development_refs']), 1)
        self.assertEqual(len(candidate['payoff_refs']), 1)
        self.assertEqual(inspect_final_quality(candidate['scoped_analysis'], candidate['plan'])['status'], 'passed')
        self.assertEqual(analysis, before)

    def test_independent_rank_can_place_later_source_first_without_reordering_inside_clip(self):
        analysis = source_fixture(3)
        analysis['events'][2]['importance'] = 5
        analysis['events'][0]['importance'] = 2
        result = build_standalone_candidates(analysis)
        self.assertEqual([c['plan']['selected_event_ids'] for c in result['candidates']], [['e2'], ['e1'], ['e0']])
        for candidate in result['candidates']:
            validate_plan(candidate['plan'], candidate['scoped_analysis'])

    def test_unrelated_unknown_source_does_not_veto_qualified_clip(self):
        analysis = source_fixture(2)
        analysis['events'][1].update(analysis_unresolved=True, understanding_confidence=.4)
        result = build_standalone_candidates(analysis)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['plan']['selected_event_ids'], ['e0'])
        self.assertTrue(result['declined'])
        self.assertTrue(result['drafts'])
        for draft in result['drafts']:
            self.assertFalse(draft['export_eligible'])
            with self.assertRaisesRegex(ValueError, 'Черновой'):
                validate_plan(draft['plan'], analysis)

    def test_native_interest_can_promote_a_later_payoff(self):
        analysis = source_fixture(2)
        analysis['events'][0]['importance'] = 5
        analysis['events'][1]['story_structure']['units'][-1]['viewer_interest'] = ['emotional_payoff']
        result = build_standalone_candidates(analysis, {'max_clips': 1})
        candidate = result['candidates'][0]
        self.assertEqual(candidate['plan']['selected_event_ids'], ['e1'])
        self.assertGreater(candidate['score']['viewer_interest_value'], 0)

    def test_same_parent_arcs_keep_native_ids_and_only_touched_units(self):
        analysis = source_fixture(2, same_parent=True)
        before = copy.deepcopy(analysis)
        result = build_standalone_candidates(analysis)
        self.assertEqual(len(result['candidates']), 2, result['declined'])
        projected = [c['scoped_analysis']['events'][0] for c in result['candidates']]
        self.assertEqual([[u['id'] for u in e['units']] for e in projected], [['u0', 'u1', 'u2'], ['u3', 'u4', 'u5']])
        self.assertEqual([e['id'] for e in projected], ['e0', 'e0'])
        self.assertEqual([e['end'] for e in projected], [120, 120])
        self.assertEqual(analysis, before)

    def test_missing_beginning_or_closure_cannot_be_ready(self):
        for missing in ('beginning', 'closure', 'proof'):
            analysis = source_fixture()
            arc = analysis['events'][0]['inferred_story_arcs'][0]
            if missing == 'beginning':
                arc['roles'][0]['role'] = 'development'
            elif missing == 'closure':
                arc.update(complete_ending=False, ending_verified=False)
            else:
                arc['verification']['proofs'][0]['proof'] = 'forged'
            with self.subTest(missing=missing):
                result = build_standalone_candidates(analysis)
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['declined'])

    def test_required_unknown_prerequisite_declines_only_its_consumer(self):
        analysis = source_fixture(3)
        analysis['events'][1]['requires'] = ['e0']
        analysis['events'][0]['analysis_unresolved'] = True
        result = build_standalone_candidates(analysis)
        self.assertEqual([c['plan']['selected_event_ids'] for c in result['candidates']], [['e2']])
        self.assertTrue(any(r['reason'] == 'required_source_unresolved' for r in result['declined']))

    def test_added_context_must_also_supply_a_supported_opening(self):
        analysis = source_fixture(2)
        analysis['events'][1]['requires'] = ['e0']
        analysis['events'][0]['story_structure']['units'][0]['roles'] = ['development']
        result = build_standalone_candidates(analysis)
        self.assertTrue(any(r['reason'] == 'missing_supported_context_opening' for r in result['declined']))

    def test_required_context_cost_is_included_without_splitting_into_separate_shorts(self):
        analysis = source_fixture(2)
        analysis['events'][1]['requires'] = ['e0']
        result = build_standalone_candidates(analysis)
        later = next((c for c in result['candidates'] if c['arc_id'] == analysis['events'][1]['inferred_story_arcs'][0]['id']), None)
        self.assertIsNotNone(later, result['declined'])
        self.assertEqual(later['duration'], 120)
        self.assertEqual(len(later['plan']['parts']), 1)
        self.assertEqual(later['plan']['selected_event_ids'], ['e0', 'e1'])
        self.assertEqual(later['overlap_seconds'], 60)

    def test_confirmed_dialogue_endpoint_is_closed_inside_each_candidate(self):
        analysis = source_fixture(2)
        pair = {'status': 'confirmed', 'requires_answer': True, 'protect_bidirectional': True,
            'question_refs': [{'event': 'e0', 'unit': 'u2'}], 'answer_refs': [{'event': 'e1', 'unit': 'u0'}],
            'question_ranges': [{'start': 41, 'end': 42}], 'answer_ranges': [{'start': 71, 'end': 72}],
            'confidence': .95, 'evidence': {'question_text': 'Результат', 'answer_text': 'Условие'}}
        for event in analysis['events']:
            event['dialogue_relations']['pairs'] = [copy.deepcopy(pair)]
        result = build_standalone_candidates(analysis)
        # e0's candidate cannot end before its newly required actual response;
        # e1's candidate owns both endpoints and includes the original context.
        self.assertEqual(len(result['candidates']), 1, result['declined'])
        candidate = result['candidates'][0]
        self.assertEqual(candidate['duration'], 120)
        self.assertEqual(candidate['plan']['selected_event_ids'], ['e0', 'e1'])

    def test_exclusions_are_not_reintroduced_by_candidate_or_draft(self):
        analysis = source_fixture()
        analysis['events'][0]['excluded_review_ranges'] = [{'start': 4, 'end': 5}]
        result = build_standalone_candidates(analysis)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['drafts'], [])
        self.assertTrue(any(r['reason'] == 'required_source_excluded' for r in result['declined']))

    def test_overlength_is_declined_and_count_or_minimum_are_never_forced(self):
        self.assertEqual(len(build_standalone_candidates(source_fixture(seconds=5))['candidates']), 1)
        result = build_standalone_candidates(source_fixture(seconds=45))
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['drafts'], [])
        self.assertTrue(any(r['reason'] == 'complete_story_exceeds_duration' for r in result['declined']))
        result = build_standalone_candidates(source_fixture(4))
        self.assertEqual(len(result['candidates']), 3)
        self.assertTrue(any(r['reason'] == 'requested_count_reached' for r in result['declined']))

    def test_corrupt_technical_input_is_not_reported_as_semantic_decline(self):
        analysis = source_fixture()
        analysis['transcript']['words'][0]['start'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'transcript timing'):
            build_standalone_candidates(analysis)
        with self.assertRaises(ValueError):
            build_standalone_candidates(source_fixture(), {'max_duration': 180})


if __name__ == '__main__':
    unittest.main()
