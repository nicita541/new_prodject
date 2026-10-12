"""Authored source-evidence gate mechanisms; no model, render or E2E claim."""
import copy
import unittest
from unittest.mock import patch

from app import final_quality
from app.subtitles import make_cues, remap_words


def fixture():
    words = [{'start': a, 'end': b, 'text': text} for a, b, text in (
        (1, 1.3, 'Где'), (1.4, 1.7, 'лежит'), (1.8, 2.1, 'папка'),
        (4.5, 4.8, 'Она'), (4.9, 5.2, 'в'), (5.3, 5.6, 'нижнем'), (5.7, 6, 'ящике'))]
    transcript = {'words': words, 'segments': [
        {'start': 1, 'end': 2.1, 'text': 'Где лежит папка'},
        {'start': 4.5, 'end': 6, 'text': 'Она в нижнем ящике'}]}
    units = [{'id': 'q', 'start': 0, 'end': 4, 'text': 'Где лежит папка'},
             {'id': 'a', 'start': 4, 'end': 8, 'text': 'Она в нижнем ящике'}]
    evidence = [{'unit': u['id'], 'decision': 'keep', 'kind': 'causal_dialogue' if i == 0 else 'response',
        'confidence': .95, 'evidence': 'В исходной реплике дан вопрос о месте либо конкретный ответ на него.',
        'speech_quote': u['text'], 'frame_indices': [], 'frame_times': [],
        'view_start': u['start'], 'view_end': u['end'], 'checkpoint': 'a'*64}
        for i, u in enumerate(units)]
    pair = {'status': 'confirmed', 'requires_answer': True, 'protect_bidirectional': True,
        'question_ranges': [{'start': 1, 'end': 2.1}], 'answer_ranges': [{'start': 4.5, 'end': 6}],
        'question_refs': [{'event': 'e', 'unit': 'q'}], 'answer_refs': [{'event': 'e', 'unit': 'a'}],
        'confidence': .95, 'evidence': {'question_text': units[0]['text'], 'answer_text': units[1]['text']}}
    facts = {'location_id': None, 'character_ids': [], 'physical_state_ids': [],
        'object_ids': [], 'topic_id': None, 'relationship_state_id': None}
    assigned = [{'ref': {'event': 'e', 'unit': u['id']},
        'roles': ['setup' if i == 0 else 'payoff'], 'before': copy.deepcopy(facts),
        'after': copy.deepcopy(facts), 'arc_ids': ['arc'], 'status': 'accepted'} for i, u in enumerate(units)]
    coverage = [{'ref': {'event': 'e', 'unit': u['id']}, 'status': 'CURRENT', 'dialogue_status': 'paired',
        'start': u['start'], 'end': u['end'], 'source_ranges': [{'start': u['start'], 'end': u['end']}],
        'confirmed_exclusions': []} for u in units]
    event = {'id': 'e', 'scene_id': 's', 'start': 0, 'end': 8, 'units': units, 'unit_evidence': evidence,
        'kind': 'story', 'importance': 4, 'summary': 'Исходный вопрос и его конкретный ответ.', 'requires': [], 'focus': [],
        'selection_status': 'accepted', 'understanding_status': 'accepted', 'summary_source': 'recovery',
        'understanding_confidence': .95, 'selection_confidence': .95, 'uncertain': False,
        'selection_uncertain': False, 'analysis_unresolved': False, 'analysis_unresolved_reasons': [],
        'selected_ranges': [{'start': 0, 'end': 8}], 'action_units': [], 'story_relations': [],
        'story_structure': {'version': 2, 'status': 'accepted', 'units': assigned, 'unresolved_refs': []},
        'dialogue_relations': {'version': 1, 'status': 'accepted', 'pairs': [pair], 'coverage': coverage,
            'unresolved_refs': [], 'understanding_confidence': .95, 'relation_confidence': .95}}
    event['part_endings']=[{'id':'end8','kind':'closure','time':8,'confidence':.95,
        'verification':{'boundary':'end8','supported':True,'confidence':.95,'last_reply':'r0001',
                        'next_reply':'none','evidence':'The original response completes the supplied source exchange.'}}]
    analysis = {'quality_policy': 'source_proved_v1', 'duration': 8, 'transcript': transcript,
        'probe': {'duration': 8, 'width': 320, 'height': 180, 'has_audio': True, 'audio_stream': 0},
        'shots': [{'id': 'shot0', 'start': 0, 'end': 4}, {'id': 'shot1', 'start': 4, 'end': 8}],
        'episode_profile': {'duration': 8},
        'events': [event], 'scenes': [{'id': 's', 'start': 0, 'end': 8, 'uncertainty_reasons': []}]}
    return analysis, make_plan(analysis, [[{'start': 0, 'end': 8}]])


def make_plan(analysis, cuts_by_part):
    parts = [{'index': i, 'cuts': copy.deepcopy(cuts),
        'duration': sum(c['end']-c['start'] for c in cuts),
        'ending': {'kind': 'accepted_source_payoff', 'confidence': .95}}
        for i, cuts in enumerate(cuts_by_part, 1)]
    for part in parts:
        for cut in part['cuts']:
            cut.setdefault('event_ids', ['e']); cut.setdefault('focus', [])
        part['subtitles'] = make_cues(remap_words(analysis['transcript']['words'], part['cuts']), 'classic')
    return {'schema_version': 1, 'source': {'duration': analysis['probe']['duration']},
        'parts': parts, 'events': copy.deepcopy(analysis['events']),
        'planner_diagnostics': {'transitions': [], 'bridges': []}, 'selected_event_ids': ['e']}


def codes(result):
    return {p['code'] for p in result['problems']}


class FinalQualityTests(unittest.TestCase):
    def test_unchanged_recovery_stops_but_improved_gate_can_continue(self):
        from app.final_quality import recovery_stalled, quality_failure_message
        gate = {'status': 'unresolved', 'problems': [{'code': 'dialogue_relations_unresolved'}]}
        history = [{'gate': copy.deepcopy(gate)}, {'gate': copy.deepcopy(gate)}]
        self.assertTrue(recovery_stalled(history))
        self.assertIn('повтор того же кэша остановлен', quality_failure_message(gate, stalled=True))
        self.assertIn('dialogue_relations_unresolved (1)', quality_failure_message(gate))
        history[-1]['gate'] = {'status': 'passed', 'problems': []}
        self.assertFalse(recovery_stalled(history))

    def test_complete_production_proof_chain_before_render(self):
        analysis, plan = fixture()
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertEqual(result['status'], 'passed'); self.assertEqual(result['phase'], 'before_render')
        self.assertEqual(result['retained_duration'], 8)
        self.assertEqual([r['ref'] for r in result['evidence_chain']],
            [{'event': 'e', 'unit': 'q'}, {'event': 'e', 'unit': 'a'}])
        for row in result['evidence_chain']:
            self.assertEqual(row['scene'], 's'); self.assertTrue(row['source_proofs'])
            self.assertTrue(row['selection_reasons']); self.assertTrue(row['part_boundary_reasons'])
            self.assertEqual(row['semantic_understanding'], {'source': 'recovery', 'confidence': .95})

    def test_before_planner_requires_accepted_production_passes(self):
        for name in ('story_structure', 'dialogue_relations'):
            analysis, _ = fixture(); analysis['events'][0][name]['status'] = 'unresolved'
            result = final_quality.inspect_final_quality(analysis)
            self.assertEqual(result['status'], 'unresolved'); self.assertIn(name+'_unresolved', codes(result))
            problem = next(p for p in result['problems'] if p['code'] == name+'_unresolved')
            self.assertEqual(problem['recovery_stage'], name)

    def test_missing_or_foreign_story_assignment_never_becomes_accepted_by_status_alone(self):
        for mutation in ('missing', 'foreign_event', 'foreign_unit', 'unresolved', 'unknown_role', 'foreign_role', 'role_string'):
            analysis, _ = fixture(); rows = analysis['events'][0]['story_structure']['units']
            if mutation == 'missing': rows.pop(0)
            if mutation == 'foreign_event': rows[0]['ref']['event'] = 'foreign'
            if mutation == 'foreign_unit': rows[0]['ref']['unit'] = 'foreign'
            if mutation == 'unresolved': rows[0]['status'] = 'unresolved'
            if mutation == 'unknown_role': rows[0]['roles'] = ['unknown']
            if mutation == 'foreign_role': rows[0]['roles'] = ['invented_role']
            if mutation == 'role_string': rows[0]['roles'] = 'setup'
            with self.subTest(mutation=mutation):
                result = final_quality.inspect_final_quality(analysis)
                self.assertIn('unexplained_story_structure_unit', codes(result))
                problem = next(p for p in result['problems'] if p['code'] == 'unexplained_story_structure_unit')
                self.assertEqual(problem['unit'], 'q'); self.assertEqual(problem['recovery_stage'], 'story_structure')

    def test_absent_unresolved_or_foreign_dialogue_coverage_blocks_selected_source_unit(self):
        for mutation in ('missing', 'foreign_event', 'foreign_unit', 'unresolved', 'context_only', 'empty_ranges', 'partial_ranges'):
            analysis, _ = fixture(); rows = analysis['events'][0]['dialogue_relations']['coverage']
            if mutation == 'missing': rows.pop(0)
            if mutation == 'foreign_event': rows[0]['ref']['event'] = 'foreign'
            if mutation == 'foreign_unit': rows[0]['ref']['unit'] = 'foreign'
            if mutation == 'unresolved': rows[0]['dialogue_status'] = 'unresolved'
            if mutation == 'context_only': rows[0]['status'] = 'CONTEXT_ONLY'
            if mutation == 'empty_ranges': rows[0]['source_ranges'] = []
            if mutation == 'partial_ranges': rows[0]['source_ranges'] = [{'start': 0, 'end': 1}]
            with self.subTest(mutation=mutation):
                result = final_quality.inspect_final_quality(analysis)
                self.assertIn('unexplained_dialogue_unit', codes(result))
                problem = next(p for p in result['problems'] if p['code'] == 'unexplained_dialogue_unit')
                self.assertEqual(problem['unit'], 'q'); self.assertEqual(problem['recovery_stage'], 'dialogue_relations')

    def test_unselected_source_needs_no_optional_semantic_pass(self):
        analysis, _ = fixture(); event = analysis['events'][0]
        event.update(selected_ranges=[], selection_empty_verified=True)
        event.pop('story_structure'); event.pop('dialogue_relations')
        self.assertEqual(final_quality.inspect_final_quality(analysis)['status'], 'passed')

    def test_source_and_plan_are_not_mutated_by_inspection(self):
        analysis, plan = fixture(); original = copy.deepcopy((analysis, plan))
        final_quality.inspect_final_quality(analysis, plan)
        self.assertEqual((analysis, plan), original)

    def test_eof_or_forged_plan_ending_does_not_replace_original_semantic_proof(self):
        analysis,plan=fixture()
        analysis['events'][0].pop('part_endings')
        plan['parts'][0]['ending']={'kind':'closure','time':8,
            'verification':{'supported':True,'confidence':1,'evidence':'Invented derived plan claim.'}}
        result=final_quality.inspect_final_quality(analysis,plan)
        self.assertIn('missing_original_semantic_ending',codes(result))
        self.assertEqual(result['evidence_chain'][0]['part_boundary_reasons'],[{'kind':'unresolved_source_ending'}])

    def test_verified_original_ending_survives_missing_plan_label_but_rejects_foreign_asr_context(self):
        analysis,plan=fixture();plan['parts'][0].pop('ending')
        self.assertEqual(final_quality.inspect_final_quality(analysis,plan)['status'],'passed')
        analysis['events'][0]['part_endings'][0]['verification']['last_reply']='foreign'
        self.assertIn('missing_original_semantic_ending',codes(final_quality.inspect_final_quality(analysis,plan)))

    def test_semantic_scene_ambiguity_routes_to_boundary_inspection(self):
        analysis, _ = fixture(); analysis['scenes'][0]['uncertainty_reasons'] = ['ambiguous_internal_boundary']
        result = final_quality.inspect_final_quality(analysis)
        self.assertIn('semantic_scene_ambiguity', codes(result))
        self.assertEqual(result['problems'][0]['recovery_stage'], 'semantic_boundary')

    def test_mocked_selection_failure_routes_to_own_downstream_recovery(self):
        for reason, stage in [('story_structure_unresolved', 'story_structure'),
                              ('dialogue_relations_unresolved', 'dialogue_relations'),
                              ('source_role_unresolved', 'source_roles')]:
            analysis, _ = fixture(); analysis['events'][0]['analysis_unresolved_reasons'] = [reason]
            with patch.object(final_quality, 'selection_readiness', return_value={
                'status': 'unresolved', 'unresolved': [{'event': 'e', 'problems': [reason]}]}):
                result = final_quality.inspect_final_quality(analysis)
            self.assertEqual(result['problems'][0]['recovery_stage'], stage)

    def test_source_role_failure_routes_from_actual_gate_even_with_administrative_unresolved_flag(self):
        analysis,_=fixture()
        analysis['events'][0].update(source_role_unresolved={'category':'unresolved'},
                                    analysis_unresolved=True,analysis_unresolved_reasons=['source_role_unresolved'])
        result=final_quality.inspect_final_quality(analysis)
        problem=next(p for p in result['problems'] if p['code']=='unresolved_source_selection')
        self.assertIn('source_role_unresolved',problem['problems'])
        self.assertEqual(problem['recovery_stage'],'source_roles')

    def test_retained_quote_is_checked_against_source_asr_not_cached_unit_text(self):
        analysis, plan = fixture()
        analysis['events'][0]['units'][0]['text'] = 'Несуществующий ответ'
        analysis['events'][0]['unit_evidence'][0]['speech_quote'] = 'Несуществующий ответ'
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('unexplained_retained_unit', codes(result))
        self.assertIn('unexplained_retained_ranges', codes(result))
        self.assertEqual(result['evidence_chain'][0]['source_proofs'], [])

    def test_forged_cached_quote_also_blocks_before_planner(self):
        analysis, _ = fixture()
        analysis['events'][0]['units'][0]['text'] = 'Несуществующий ответ'
        analysis['events'][0]['unit_evidence'][0]['speech_quote'] = 'Несуществующий ответ'
        self.assertEqual(final_quality.inspect_final_quality(analysis)['status'], 'unresolved')

    def test_source_proof_is_still_checked_when_upstream_gate_is_mocked_clear(self):
        analysis, plan = fixture(); analysis['events'][0]['unit_evidence'] = []
        with patch.object(final_quality, 'selection_readiness', return_value={'unresolved': []}):
            result = final_quality.inspect_final_quality(analysis, plan)
        self.assertIn('unexplained_retained_unit', codes(result))
        self.assertIn('unexplained_retained_ranges', codes(result))

    def test_malformed_frame_domain_and_nonfinite_proof_never_enter_chain(self):
        for kind in ('out_of_domain', 'outside_unit', 'nonfinite'):
            analysis, plan = fixture(); record = analysis['events'][0]['unit_evidence'][0]
            record.update(kind='physical_action', frame_indices=[1], frame_times=[1], frame_count=1)
            if kind == 'out_of_domain': record['frame_indices'] = [2]
            if kind == 'outside_unit': record['frame_times'] = [4.5]
            if kind == 'nonfinite': record['confidence'] = float('nan')
            with self.subTest(kind=kind):
                result = final_quality.inspect_final_quality(analysis, plan)
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['evidence_chain'][0]['source_proofs'], [])

    def test_retained_time_outside_source_units_has_no_proof(self):
        analysis, _ = fixture(); plan = make_plan(analysis, [[{'start': 0, 'end': 9}]])
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertIn('unexplained_retained_ranges', codes(result))

    def test_missing_dialogue_endpoint_is_bidirectional(self):
        for cut in ({'start': 0, 'end': 4}, {'start': 4, 'end': 8}):
            analysis, _ = fixture(); plan = make_plan(analysis, [[cut]])
            result = final_quality.inspect_final_quality(analysis, plan)
            self.assertIn('missing_required_dialogue_endpoint', codes(result))

    def test_derived_plan_cannot_erase_confirmed_source_dialogue(self):
        for mutation in ('clear_pairs','remove_event'):
            analysis,_ = fixture(); plan = make_plan(analysis,[[{'start':0,'end':4}]])
            if mutation == 'clear_pairs': plan['events'][0]['dialogue_relations']['pairs'] = []
            else: plan['events'] = []
            with self.subTest(mutation=mutation):
                self.assertIn('missing_required_dialogue_endpoint',codes(final_quality.inspect_final_quality(analysis,plan)))

    def test_derived_plan_cannot_erase_source_action_before_truncation_check(self):
        analysis,_ = fixture(); analysis['events'][0]['action_units'] = ['q']
        plan = make_plan(analysis,[[{'start':0,'end':1}]])
        plan['events'] = []
        self.assertIn('consequential_action_truncated',codes(final_quality.inspect_final_quality(analysis,plan)))

    def test_word_safe_partial_question_cannot_lose_the_required_pair(self):
        analysis, _ = fixture(); plan = make_plan(analysis, [[{'start': 1, 'end': 1.3}]])
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertNotIn('cut_asr_word', codes(result))
        self.assertIn('missing_required_dialogue_endpoint', codes(result))

    def test_complete_question_and_answer_cannot_be_split_between_parts(self):
        analysis, _ = fixture(); plan = make_plan(analysis, [[{'start': 0, 'end': 4}], [{'start': 4, 'end': 8}]])
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertIn('question_response_split_between_parts', codes(result))

    def test_omitting_both_dialogue_endpoints_does_not_force_them_back(self):
        analysis, _ = fixture(); plan = make_plan(analysis, [[{'start': 2.1, 'end': 4.5}]])
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertNotIn('missing_required_dialogue_endpoint', codes(result))
        self.assertNotIn('question_response_split_between_parts', codes(result))

    def test_unknown_and_unresolved_transition_cannot_reach_render(self):
        for status in ('unknown', 'unresolved', None):
            analysis, plan = fixture()
            plan['planner_diagnostics']['transitions'] = [{'status': status, 'reason': 'unknown_transition_state'}]
            result = final_quality.inspect_final_quality(analysis, plan)
            self.assertIn('unresolved_transition', codes(result)); self.assertEqual(result['status'], 'unresolved')

    def test_cleared_plan_audit_cannot_hide_an_actual_unexplained_source_gap(self):
        analysis,_ = fixture()
        plan = make_plan(analysis,[[{'start':0,'end':1},{'start':7,'end':8}]])
        plan['planner_diagnostics']['transitions'] = []
        result = final_quality.inspect_final_quality(analysis,plan)
        self.assertIn('unresolved_transition',codes(result))
        gap = next(p['transition']['gap'] for p in result['problems'] if p['code'] == 'unresolved_transition')
        self.assertEqual((gap['left_end'],gap['right_start']),(1,7))

    def test_accepted_consistent_transition_is_included_without_false_recovery(self):
        analysis, plan = fixture()
        plan['planner_diagnostics']['transitions'] = [{'status': 'consistent', 'reason': 'consecutive_original_source_units'}]
        self.assertEqual(final_quality.inspect_final_quality(analysis, plan)['status'], 'passed')

    def test_bridge_endpoint_context_or_uncertainty_is_not_concrete_proof(self):
        for bridge in ({'source_event': 'e', 'source_unit': 'q', 'uncertain': False, 'evidence': []},
                       {'source_event': 'e', 'source_unit': 'q', 'uncertain': False, 'evidence': [{'kind': 'endpoint_context'}]},
                       {'source_event': 'e', 'source_unit': 'q', 'uncertain': True, 'evidence': [{'kind': 'physical_action'}]}):
            analysis, plan = fixture(); plan['planner_diagnostics']['bridges'] = [bridge]
            result = final_quality.inspect_final_quality(analysis, plan)
            self.assertIn('unverified_bridge', codes(result))

    def test_asr_word_cut_routes_to_planner_and_reports_exact_source_time(self):
        analysis, plan = fixture()
        # Deliberately corrupt a valid plan after subtitle creation: source-safe
        # cue generation correctly rejects this boundary before a gate could.
        plan['parts'][0]['cuts'][0]['start'] = 1.1
        plan['parts'][0]['duration'] = 6.9
        result = final_quality.inspect_final_quality(analysis, plan)
        problem = next(p for p in result['problems'] if p['code'] == 'cut_asr_word')
        self.assertEqual(problem['source_time'], 1.1); self.assertEqual(problem['recovery_stage'], 'planner')

    def test_exact_source_word_boundary_is_not_a_word_cut(self):
        analysis, _ = fixture(); plan = make_plan(analysis, [[{'start': 1, 'end': 6}]])
        self.assertNotIn('cut_asr_word', codes(final_quality.inspect_final_quality(analysis, plan)))

    def test_confirmed_exclusion_is_not_reintroduced_by_a_positive_source_record(self):
        analysis, plan = fixture(); analysis['events'][0]['excluded_review_ranges'] = [{'start': 0, 'end': 4}]
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertIn('retained_confirmed_exclusion', codes(result))

    def test_specific_physical_action_cannot_be_partially_retained(self):
        analysis, _ = fixture(); event = analysis['events'][0]
        event['action_units'] = ['q']
        event['unit_evidence'][0].update(kind='physical_action', frame_indices=[1], frame_times=[1], frame_count=1)
        plan = make_plan(analysis, [[{'start': 0, 'end': 2.1}]])
        self.assertIn('consequential_action_truncated', codes(final_quality.inspect_final_quality(analysis, plan)))

    def test_part_boundary_cannot_split_an_action_even_when_union_retains_it_all(self):
        analysis, _ = fixture(); event = analysis['events'][0]
        event['action_units'] = ['q']
        event['unit_evidence'][0].update(kind='physical_action', frame_indices=[1], frame_times=[1], frame_count=1)
        plan = make_plan(analysis, [[{'start': 0, 'end': 2.1}], [{'start': 2.1, 'end': 8}]])
        result = final_quality.inspect_final_quality(analysis, plan)
        self.assertIn('part_boundary_inside_action', codes(result))
        self.assertNotIn('consequential_action_truncated', codes(result))

    def test_source_arc_requires_a_verified_ending_for_an_internal_part_boundary(self):
        from tests.test_structure_planner_integration import StructurePlannerIntegrationTests
        integration = StructurePlannerIntegrationTests(); integration.setUp()
        self.addCleanup(integration.doCleanups)
        data,_ = integration.source_analysis()
        data['quality_policy'] = 'source_proved_v1'
        data['events'][0]['dialogue_relations'] = {'status':'accepted','pairs':[],
            'coverage':[{'ref':{'event':e['id'],'unit':u['id']},'status':'CURRENT',
                'dialogue_status':'not_dialogue_dependency','source_ranges':[u]}
                for e in data['events'] for u in e['units']]}
        plan = make_plan(data,[[{'start':0,'end':30}]])
        plan['events'] = copy.deepcopy(data['events'])
        result = final_quality.inspect_final_quality(data,plan)
        self.assertIn('unverified_boundary_inside_story_arc',codes(result))
        plan['parts'][0]['ending']={'kind':'closure','time':30,
            'verification':{'supported':True,'confidence':1,'evidence':'Derived unsupported claim'}}
        self.assertIn('unverified_boundary_inside_story_arc',codes(final_quality.inspect_final_quality(data,plan)))

    def test_complete_original_arc_end_has_specific_inherited_closing_proof(self):
        from tests.test_structure_planner_integration import StructurePlannerIntegrationTests
        integration=StructurePlannerIntegrationTests();integration.setUp();self.addCleanup(integration.doCleanups)
        data,result=integration.source_analysis()
        data['quality_policy']='source_proved_v1'
        # This is an authored proof mechanism, not a genuine provider/quality assertion.
        endings=final_quality._source_part_endings(data['events'],data['transcript'],
            [{'index':1,'cuts':[{'start':0,'end':60}]}],result['arcs'])
        self.assertEqual(endings[1]['arc_id'],result['arcs'][0]['id'])
        result['arcs'][0]['verification']['proofs']=[]
        self.assertEqual(final_quality._source_part_endings(data['events'],data['transcript'],
            [{'index':1,'cuts':[{'start':0,'end':60}]}],result['arcs']),{})

    def test_unknown_action_in_final_plan_does_not_silently_disappear(self):
        analysis, plan = fixture(); plan['events'][0]['action_units'] = ['invented_unit']
        self.assertEqual(final_quality.inspect_final_quality(analysis, plan)['status'], 'unresolved')

    def test_generic_atmosphere_and_uncertainty_do_not_authorize_keep_all(self):
        for change, code in (({'protected_atmosphere_units': ['q']}, 'generic_protected_atmosphere'),
                            ({'protected_atmosphere_ranges': [{'start': 0, 'end': 4}]}, 'generic_protected_atmosphere'),
                            ({'fallback': 'whole_scene'}, 'generic_uncertainty_retention'),
                            ({'selection_uncertain': True}, 'generic_uncertainty_retention')):
            analysis, plan = fixture(); plan['events'][0].update(change)
            result = final_quality.inspect_final_quality(analysis, plan)
            self.assertEqual(result['status'], 'unresolved'); self.assertIn(code, codes(result))


if __name__ == '__main__':
    unittest.main()
