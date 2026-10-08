"""Mechanism tests only: authored semantics are not production quality proof."""
import copy
import unittest
from unittest.mock import patch, MagicMock

from app.selection_gate import adjudicate_selections, positive_ranges, selection_problems, selection_readiness
from app.source_roles import apply_exclusions
from app.planner import validate_analysis


def accepted():
    return {'id':'event_0000', 'start':0, 'end':10, 'kind':'story', 'importance':4,
        'requires':[], 'uncertain':False, 'selection_uncertain':False, 'analysis_unresolved':False,
        'selection_status':'accepted', 'understanding_status':'accepted',
        'understanding_confidence':.95, 'selection_confidence':.96,
        'units':[{'id':'cause', 'start':0, 'end':10, 'text':'Потому что дверь закрыта.'}],
        'selected_ranges':[{'start':0, 'end':10}], 'action_units':[],
        'unit_evidence':[{'unit':'cause', 'kind':'causal_dialogue', 'decision':'keep',
            'confidence':.95, 'evidence':'Реплика объясняет причину следующего действия.',
            'frame_indices':[], 'speech_quote':'Потому что дверь закрыта.'}]}


class SelectionGateTests(unittest.TestCase):
    def test_source_gate_preserves_downstream_failure_without_repeating_visual_inference(self):
        from app.selection_gate import source_selection_readiness
        event = accepted()
        event.update(analysis_unresolved=True, analysis_unresolved_reasons=[
            'story_structure_unresolved', 'dialogue_relations_unresolved'])
        original = copy.deepcopy(event)
        with patch('app.selection_adjudication.adjudicate_event') as inspect:
            result = adjudicate_selections('source', [event], {}, [], 'job', None,
                lambda *a: None, lambda: False, source_only=True)
        inspect.assert_not_called()
        self.assertEqual(source_selection_readiness(result)['status'], 'passed')
        self.assertEqual(selection_readiness(result)['status'], 'unresolved')
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertEqual(result[0]['analysis_unresolved_reasons'], original['analysis_unresolved_reasons'])
        self.assertEqual(result[0]['unit_evidence'], original['unit_evidence'])

    def test_downstream_projection_cannot_hide_missing_proof_or_source_uncertainty(self):
        from app.selection_gate import source_selection_readiness
        for field in ('unit_evidence', 'selection_uncertain', 'source_role_unresolved'):
            event = accepted()
            event.update(analysis_unresolved=True, analysis_unresolved_reasons=['story_structure_unresolved'])
            event[field] = [] if field == 'unit_evidence' else True
            with self.subTest(field=field):
                self.assertEqual(source_selection_readiness([event])['status'], 'unresolved')
        for reasons in ([], ['other_failure'], ['story_structure_unresolved', 'other_failure'], [{}]):
            event = accepted(); event.update(analysis_unresolved=True, analysis_unresolved_reasons=reasons)
            self.assertEqual(source_selection_readiness([event])['status'], 'unresolved')

    def test_failed_text_pass_retries_its_owner_and_cannot_clear_quality_without_success(self):
        from app.analysis import finalize_editorial_selection
        event = accepted()
        event.update(analysis_unresolved=True, analysis_unresolved_reasons=['story_structure_unresolved'])
        diagnostics = MagicMock()
        with patch('app.selection_adjudication.adjudicate_event') as visual, \
                patch('app.endings.refine_endings') as endings, \
                patch('app.story_structure_pass.infer_story_structure', return_value={'events': [event]}) as structure, \
                patch('app.dialogue_relations.infer_dialogue_relations', return_value={}) as dialogue, \
                patch('app.dialogue_relations.attach_dialogue_result', return_value=[event]), \
                patch('app.analysis.atomic_json'):
            result = finalize_editorial_selection('source', [event], {}, [], {}, 'job', None,
                lambda *a: None, lambda: False, diagnostics, 'local')
        visual.assert_not_called(); endings.assert_not_called()
        structure.assert_called_once(); dialogue.assert_called_once()
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertEqual(diagnostics.write.call_args.args[1]['status'], 'unresolved')

    def test_frame_only_spoken_proof_is_rejected_but_silent_reaction_remains_eligible(self):
        event = accepted()
        event['units'][0]['text'] = ''
        record = event['unit_evidence'][0]
        record.update(speech_quote='', frame_indices=[1], frame_times=[1.], frame_count=1)
        self.assertEqual(positive_ranges(event), [])
        self.assertIn('unexplained_selected_ranges', selection_problems(event))
        record['kind'] = 'character_reaction'
        self.assertEqual(positive_ranges(event), [{'start': 0, 'end': 10}])

    def test_unresolved_analysis_persists_gate_without_invoking_ending_planner(self):
        from app.analysis import finalize_editorial_selection
        event=accepted();event.update(analysis_unresolved=True,selection_uncertain=True)
        diagnostics=MagicMock()
        with patch('app.selection_gate.adjudicate_selections',return_value=[event]), \
                patch('app.endings.refine_endings') as endings:
            result=finalize_editorial_selection('source',[event],{},[],{},'job',None,
                lambda *a:None,lambda:False,diagnostics,'local')
        endings.assert_not_called()
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertEqual(diagnostics.write.call_args.args[0], 'selection_gate.json')
        self.assertEqual(diagnostics.write.call_args.args[1]['status'], 'unresolved')

    def test_endings_run_after_resolution_and_new_selection_is_rechecked(self):
        from app.analysis import finalize_editorial_selection
        ready=accepted();changed=accepted();changed['selected_ranges']=[{'start':0,'end':11}]
        diagnostics=MagicMock()
        with patch('app.selection_gate.adjudicate_selections',side_effect=[[ready],[ready]]) as adjudicate, \
                patch('app.endings.refine_endings',return_value=[changed]) as endings, \
                patch('app.story_structure_pass.infer_story_structure',return_value={'events':[ready]}) as structure, \
                patch('app.dialogue_relations.infer_dialogue_relations',return_value={}) as dialogue, \
                patch('app.dialogue_relations.attach_dialogue_result',return_value=[ready]), \
                patch('app.analysis.atomic_json'):
            result=finalize_editorial_selection('source',[ready],{},[],{},'job',None,
                lambda *a:None,lambda:False,diagnostics,'local')
        self.assertEqual(adjudicate.call_count,2)
        self.assertEqual(endings.call_count,1)
        structure.assert_called_once()
        dialogue.assert_called_once()
        self.assertEqual(result,[ready])
        self.assertEqual(diagnostics.write.call_args.args[1]['status'],'passed')

    def test_evidenced_selection_passes_and_bare_ownership_is_not_enough(self):
        event=accepted()
        self.assertEqual(selection_problems(event), [])
        event.pop('unit_evidence')
        event['verified_current_story_ranges']=[{'start':0,'end':10}]
        self.assertIn('unexplained_selected_ranges', selection_problems(event))

    def test_each_unresolved_flag_requires_recovery(self):
        for key in ('uncertain','selection_uncertain','analysis_unresolved','global_verification_unresolved',
                    'source_role_unresolved','whole_scene_last_resort'):
            with self.subTest(key=key):
                event=accepted();event[key]=True
                self.assertIn(key, selection_problems(event))

    def test_high_understanding_does_not_substitute_for_selection_confidence(self):
        event=accepted();event['selection_confidence']=.5
        self.assertEqual(selection_problems(event), ['selection_confidence_insufficient'])
        event['selection_confidence']=float('nan')
        self.assertEqual(selection_readiness([event])['status'], 'unresolved')

    def test_generic_atmosphere_unknown_action_and_unverified_empty_selection_fail(self):
        event=accepted();event.update(protected_atmosphere_units=['cause'], action_units=['foreign'], selected_ranges=[])
        self.assertEqual(selection_problems(event), ['generic_atmosphere','unknown_action_ownership','empty_selection_not_verified'])

    def test_confident_empty_neutral_selection_is_valid_without_expansion(self):
        event=accepted();event.update(selected_ranges=[],selection_empty_verified=True,unit_evidence=[])
        self.assertEqual(selection_problems(event), [])
        event['verified_current_story_ranges']=[{'start':0,'end':10}]
        self.assertEqual(apply_exclusions([event])[0]['selected_ranges'], [])

    def test_existing_ownership_proof_does_not_expand_accepted_replacement(self):
        event=accepted();event['selected_ranges']=[{'start':4,'end':6}]
        event['verified_current_story_ranges']=[{'start':0,'end':10}]
        self.assertEqual(apply_exclusions([event])[0]['selected_ranges'], [{'start':4,'end':6}])

    def test_empty_selection_stays_empty_with_confirmed_exclusions(self):
        event=accepted();event.update(selected_ranges=[],excluded_title_units=[{'start':0,'end':2}])
        self.assertEqual(apply_exclusions([event])[0]['selected_ranges'], [])

    def test_view_evidence_must_cover_the_retained_interval(self):
        event=accepted();event['unit_evidence'][0].update(view_start=2,view_end=7)
        self.assertEqual(positive_ranges(event), [{'start':2,'end':7}])
        self.assertIn('unexplained_selected_ranges', selection_problems(event))
        event['selected_ranges']=[{'start':3,'end':6}]
        self.assertEqual(selection_problems(event), [])

    def test_drop_low_confidence_generic_and_unanchored_evidence_cannot_cover_selection(self):
        for change in ({'decision':'drop'},{'confidence':.89},{'evidence':'атмосфера сцены'},
                       {'frame_indices':[],'speech_quote':''},{'kind':'neutral_scenery'}):
            with self.subTest(change=change):
                event=accepted();event['unit_evidence'][0].update(change)
                self.assertEqual(positive_ranges(event), [])

    def test_invalid_confidence_or_foreign_current_geometry_cannot_pass_gate(self):
        for change in ({'confidence':2.0},{'frame_indices':[999],'frame_times':[20.]},
                       {'frame_indices':[1],'frame_times':[]},
                       {'frame_indices':[1],'frame_times':[float('nan')]},
                       {'frame_indices':[True],'frame_times':[3.]},
                       {'frame_indices':[1,1],'frame_times':[3.,3.]}):
            event=accepted();record=event['unit_evidence'][0]
            record.update(kind='character_reaction',speech_quote='',frame_indices=[1],frame_times=[3.],frame_count=2)
            record.update(change)
            with self.subTest(change=change):
                self.assertEqual(positive_ranges(event),[])
                self.assertIn('unexplained_selected_ranges',selection_problems(event))

    def test_quote_is_actual_unit_speech_and_visual_types_need_current_frame_times(self):
        event=accepted();event['unit_evidence'][0]['speech_quote']='Выдуманная причинная реплика.'
        self.assertEqual(positive_ranges(event),[])
        event=accepted();event['unit_evidence'][0]['kind']='character_reaction'
        self.assertEqual(positive_ranges(event),[])
        event['unit_evidence'][0].update(frame_indices=[2],frame_times=[3.],frame_count=2)
        self.assertEqual(positive_ranges(event),[{'start':0,'end':10}])

    def test_adjudication_rebuilds_choice_and_leaves_unresolved_failure_explicit(self):
        original=accepted();original.update(uncertain=True,selected_ranges=[])
        fixed=accepted()
        with patch('app.selection_adjudication.adjudicate_event',return_value=fixed) as query:
            result=adjudicate_selections('source.mp4',[original],{},[],'job',None,lambda *x:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'], [{'start':0,'end':10}])
        self.assertFalse(result[0]['analysis_unresolved'])
        self.assertIn('uncertain', query.call_args.kwargs['questions'][-1])
        with patch('app.selection_adjudication.adjudicate_event',return_value=copy.deepcopy(original)):
            result=adjudicate_selections('source.mp4',[original],{},[],'job',None,lambda *x:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'], [])
        self.assertTrue(result[0]['analysis_unresolved'])

    def test_cancellation_and_provider_controls_propagate(self):
        with self.assertRaises(InterruptedError):
            adjudicate_selections('source.mp4',[accepted()],{},[],'job',None,lambda *x:None,lambda:True)
        event=accepted();event['uncertain']=True
        with patch('app.selection_adjudication.adjudicate_event',side_effect=InterruptedError('cancelled')):
            with self.assertRaises(InterruptedError):
                adjudicate_selections('source.mp4',[event],{},[],'job',None,lambda *x:None,lambda:False)

    def test_planner_rejects_analysis_unresolved_before_timeline_work(self):
        for analysis in ({'selection_gate':{'status':'unresolved'}}, {'events':[{'analysis_unresolved':True}]}):
            with self.subTest(analysis=analysis):
                with self.assertRaisesRegex(ValueError, 'analysis_unresolved'):
                    validate_analysis(analysis)


if __name__=='__main__':
    unittest.main()
