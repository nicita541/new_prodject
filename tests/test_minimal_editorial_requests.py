"""Provider spies prove request scope; no real inference or media decoding."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app import part_context, quality_recovery, review_feedback, story_structure_pass
from tests.test_media import workspace_directory
from tests.test_final_quality import fixture


class MinimalEditorialRequestsTests(unittest.TestCase):
    def test_positioned_feedback_sends_only_nearest_whole_utterances(self):
        analysis, plan = fixture()
        plan['parts'][0]['cuts'] = [{'start':0,'end':100}]
        analysis['transcript']['segments'] = [{'start':i,'end':i+.5,'text':('UNRELATED_SENTINEL' if i<90 else 'Exact complete utterance '+str(i))}
                                              for i in range(100)]
        intent = {'actions':[],'confidence':1,'reply':'Уточните замечание.'}
        vision = Mock()
        vision.query.return_value = intent
        with workspace_directory('minimal-feedback-') as directory:
            review_feedback.interpret({'text':'Здесь обрыв','part_index':1,'source_time':97.2},
                plan,analysis,Path(directory),vision)
        payload = json.loads(vision.query.call_args.args[0].split('\n')[-1])
        self.assertEqual([r['start'] for r in payload['selected_part_ASR']],[96,97,98])
        self.assertNotIn('UNRELATED_SENTINEL',vision.query.call_args.args[0])

    def test_feedback_operation_identifier_stays_off_wire(self):
        vision = Mock()
        request = {'text':'Проверь заставку','part_index':1,'source_time':2,'operation_id':'PRIVATE_OPERATION_SENTINEL'}
        review_feedback._RecheckVision(vision,request).query('Original source question')
        self.assertNotIn('PRIVATE_OPERATION_SENTINEL',vision.query.call_args.args[0])
        self.assertIn('Проверь заставку',vision.query.call_args.args[0])

    def test_economy_cover_uses_extractive_result_without_provider_or_frames(self):
        analysis, plan = fixture()
        with workspace_directory('minimal-cover-') as directory, \
                patch('app.vision.vision_session') as session, patch('app.part_context.frames') as frames:
            part_context.generate(plan,Path(directory),lambda *a:None,lambda:False)
        session.assert_not_called()
        frames.assert_not_called()
        self.assertEqual(plan['parts'][0]['cover_context']['method'],'extractive')

    def test_text_evidence_aliases_are_lossless_and_do_not_mutate_native_nodes(self):
        from tests.test_story_structure_pass import fixture as source_fixture
        event, transcript = source_fixture(2)
        nodes,_,_ = story_structure_pass.source_units([event],transcript)
        original = copy.deepcopy(nodes[0])
        compact = story_structure_pass.model_source_unit(nodes[0])
        self.assertEqual(nodes[0],original)
        self.assertEqual(compact['mentions']['ASR']['text_ref'],'ASR')
        self.assertEqual(compact['proofs'][0]['speech_quote_ref'],'ASR')
        self.assertEqual(compact['ASR'],original['proofs'][0]['speech_quote'])
        self.assertEqual(compact['proofs'][0]['ASR_ranges'][0]['text_ref'],'ASR')
        self.assertLess(len(json.dumps(compact)),len(json.dumps(original)))

    def test_unlocalized_semantic_recovery_cannot_dispatch_whole_episode(self):
        analysis,_ = fixture()
        analysis['scenes'][0]['uncertainty_reasons'] = ['semantic_boundary_unresolved']
        gate = {'problems':[{'code':'semantic_scene_ambiguity','recovery_stage':'semantic_boundary','scene':'s'}]}
        with workspace_directory('minimal-recovery-') as directory, \
                patch('app.scene_detection.scene_checkpoint') as detect, \
                patch('app.editorial_pipeline.finalize_editorial_selection') as finalize, \
                patch('app.analysis_result.analysis_result',return_value=copy.deepcopy(analysis)):
            source = Path(directory)/'source.mp4'
            source.write_bytes(b'authored source')
            result = quality_recovery.recover_final_quality(source,analysis,None,gate,Path(directory),Mock(),lambda *a:None,lambda:False)
        detect.assert_not_called()
        finalize.assert_not_called()
        self.assertEqual(result['scenes'][0]['uncertainty_reasons'],['semantic_boundary_unresolved'])

    def test_selection_repair_does_not_dispatch_other_unresolved_owners(self):
        analysis,_ = fixture()
        unrelated = copy.deepcopy(analysis['events'][0])
        unrelated['id'] = 'unrelated'
        analysis['events'].append(unrelated)
        gate = {'problems':[{'code':'selection_conflict','recovery_stage':'selection_adjudication','event':'e'}]}
        with workspace_directory('minimal-selection-') as directory, \
                patch('app.selection_gate.source_selection_readiness',return_value={'unresolved':[{'event':'e'},{'event':'unrelated'}]}), \
                patch('app.selection_adjudication.adjudicate_event',side_effect=lambda source,event,*a,**kw:event) as adjudicate, \
                patch('app.editorial_pipeline.finalize_editorial_selection',side_effect=lambda source,events,*a,**kw:events) as finalize, \
                patch('app.analysis_result.analysis_result',return_value=copy.deepcopy(analysis)):
            source = Path(directory)/'source.mp4'
            source.write_bytes(b'authored source')
            quality_recovery.recover_final_quality(source,analysis,None,gate,Path(directory),Mock(),lambda *a:None,lambda:False)
        self.assertEqual([call.args[1]['id'] for call in adjudicate.call_args_list],['e'])
        finalize.assert_not_called()

    def test_changed_source_proof_keeps_other_owners_and_requires_new_relations(self):
        analysis,_ = fixture()
        unrelated = copy.deepcopy(analysis['events'][0])
        unrelated['id'] = 'unrelated'
        analysis['events'].append(unrelated)
        gate = {'problems':[{'code':'selection_conflict','recovery_stage':'selection_adjudication','event':'e'}]}
        def repair(source,event,*args,**kwargs):
            event['unit_evidence'][0]['evidence'] = 'New independently inspected exact source evidence.'
            return event
        def assembled(directory,provider,probe,transcript,shots,events,**kwargs):
            return {'events':events}
        with workspace_directory('minimal-proof-change-') as directory, \
                patch('app.selection_gate.source_selection_readiness',return_value={'unresolved':[{'event':'e'}]}), \
                patch('app.selection_adjudication.adjudicate_event',side_effect=repair), \
                patch('app.editorial_pipeline.finalize_editorial_selection') as finalize, \
                patch('app.analysis_result.analysis_result',side_effect=assembled):
            source = Path(directory)/'source.mp4'
            source.write_bytes(b'authored source')
            result = quality_recovery.recover_final_quality(source,analysis,None,gate,Path(directory),Mock(),lambda *a:None,lambda:False)
        finalize.assert_not_called()
        self.assertEqual(result['events'][0]['story_structure']['status'],'unresolved')
        self.assertEqual(result['events'][0]['dialogue_relations']['status'],'unresolved')
        self.assertEqual(result['events'][1],unrelated)
