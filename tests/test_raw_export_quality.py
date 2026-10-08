"""Authored artifact mechanisms and synthetic media decoding, not VLM quality."""
import copy
import io
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP, FFMPEG, FFPROBE
from scripts import verify_production_raw_exports as evaluator


def span(start,end):
    return {'start':start,'end':end}


def ref(event,unit):
    return {'event':event,'unit':unit}


class RawExportQualityMechanismTests(unittest.TestCase):
    def setUp(self):
        self.job=TEMP/('raw-export-mechanism-'+uuid.uuid4().hex)
        (self.job/'input').mkdir(parents=True)
        (self.job/'output').mkdir()
        (self.job/'actual-model').mkdir()
        self.addCleanup(shutil.rmtree,self.job)
        self.source=self.job/'input/source.mp4'
        self.source.write_bytes(b'authored source video placeholder '*64)
        self.input=self.job/'input/input.json'
        self.save(self.input,{'source':str(self.source)})
        self.words=[{'start':.6,'end':.8,'text':'Причина.','probability':.95}]
        self.transcript={'words':self.words,'segments':copy.deepcopy(self.words),'language':'ru'}
        self.save('transcript.json',self.transcript)
        units=[{'id':f'u{i}',**span(a,b)} for i,(a,b) in enumerate(((0,.5),(.5,1),(1,2)))]
        records=[{'unit':'u1','kind':'causal_dialogue','decision':'keep','confidence':.95,
                  'evidence':'Источник содержит произнесённую конкретную причину последующей реакции.',
                  'speech_quote':'Причина.','frame_indices':[],'frame_times':[],'frame_count':0,
                  'view_start':.5,'view_end':1,'checkpoint':'a'*64},
                 {'unit':'u2','kind':'character_reaction','decision':'keep','confidence':.95,
                  'evidence':'В CURRENT персонаж поднимает брови и поворачивается после реплики.',
                  'speech_quote':'','frame_indices':[1],'frame_times':[1.5],'frame_count':1,
                  'view_start':1,'view_end':2,'checkpoint':'b'*64}]
        ending={'id':'ending0','time':2,'confidence':.95,'verification':{
            'boundary':'ending0','supported':True,'confidence':.95,
            'evidence':'Исходная реакция завершает последствие произнесённой причины.',
            'last_reply':'r0000','next_reply':'none'}}
        self.event={'id':'room','scene_id':'scene0','start':0,'end':2,'units':units,'unit_evidence':records,
                    'selected_ranges':[span(.5,2)],'uncertain':False,'selection_uncertain':False,
                    'analysis_unresolved':False,'understanding_confidence':.95,'selection_confidence':.95,
                    'selection_status':'accepted',
                    'part_endings':[ending]}
        self.analysis={'events':[self.event],'transcript':self.transcript,'duration':2,'quality_policy':'source_proved_v1'}
        self.plan={'parts':[{'index':1,'duration':1.5,'cuts':[span(.5,2)],
                            'subtitles':[{'start':.1,'end':.3,'text':'Причина.'}]}],
                   'events':[self.event],'planner_diagnostics':{'bridges':[],'transitions':[]}}
        self.gate={'status':'passed','phase':'before_render','problems':[],
                   'evidence_chain':[{'ref':ref('room','u1'),'ranges':[span(.5,1)],
                                      'source_proofs':[records[0]],'continuity_reasons':[]},
                                     {'ref':ref('room','u2'),'ranges':[span(1,2)],
                                      'source_proofs':[records[1]],'continuity_reasons':[]}]}
        self.export=self.job/'output/part_001.mp4'
        self.export.write_bytes(b'authored export placeholder '*64)
        self.srt=self.job/'output/part_001.srt'
        self.srt.write_text('1\n00:00:00,100 --> 00:00:00,300\nПричина.\n','utf-8')
        self.original={'source':str(self.source),'source_sha256':evaluator._sha(self.source),
                       'transcript_sha256':None,'input_manifest_sha256':evaluator._sha(self.input)}
        self.save('original-inputs.json',self.original)
        self.save('source.json',{'path':str(self.source)})
        self.save('observer-input-locations.json',{'input':str(self.input),'transcript':None})
        self.save('observer-code-identity.json',{'digest':'authored-frozen-code'})
        self.save('observer-code-identity-final.json',{'digest':'authored-frozen-code'})
        self.save('observed-sessions.json',[{'model':'authored-no-model','projector':'authored-projector',
                                             'initial_requests':0,'new_requests':2,'total_requests':2}])
        image=self.job/'actual-model/source.jpg'
        image.write_bytes(b'authored board placeholder')
        self.request(1,{'unit_evidence':{}},{'understanding_confidence':.95,'selection_confidence':.95},image)
        self.request(2,{'decisions':{}},{'decisions':[ending['verification']]})
        self.review=self.job/'review.json'
        self.review_row={'scenario':'I','source':str(self.source),'source_sha256':self.original['source_sha256'],
                         'input':str(self.input),'input_manifest_sha256':self.original['input_manifest_sha256'],
                         'facts':{'neutral_scenery':[0,.5],'expression_change':[1.1,1.9]}}
        self.save_review()
        self.sync()

    def save(self,path,data):
        path=Path(path)
        if not path.is_absolute():
            path=self.job/path
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),'utf-8')

    def save_review(self):
        self.save(self.review,{'records':[self.review_row]})

    def request(self,number,schema,response,image=None,prompt='Authored mechanism only, no model execution'):
        self.save(f'actual-model/request-{number:03d}.json',{
            'request':number,'prompt':prompt,'schema':{'properties':schema},'max_tokens':1000,
            'model':'authored-no-model','projector':'authored-projector','thinking':False,
            'images':[{'path':str(image),'sha256':evaluator._sha(image)}] if image else []})
        self.save(f'actual-model/response-{number:03d}.json',{'response':response,'elapsed_seconds':0})

    def sync(self):
        self.save('actual-analysis.json',self.analysis)
        self.save('analysis-final.json',self.analysis)
        self.save('plan.json',self.plan)
        self.save('output/plan.json',self.plan)
        self.save('final_quality_gate.json',self.gate)
        requests=len(list((self.job/'actual-model').glob('request-*.json')))
        self.outcome={'mode':'production_render','complete':True,'pipeline_code_stable':True,
                      'actual_model_requests':requests,'quality_gate':self.gate,
                      'outputs':['part_001.mp4','part_001.srt'],
                      'export_sha256':{p.name:evaluator._sha(p) for p in (self.export,self.srt)}}
        self.save('observed-outcome.json',self.outcome)

    def structure(self,arcs,relations=None):
        decision={'resolved':True,'understanding_confidence':.95,'structure_confidence':.95,
                  'units':[],'relations':copy.deepcopy(relations or []),'arcs':copy.deepcopy(arcs),
                  'canonical_entities':[],'limitations':[]}
        self.request(5,{'arcs':{}},decision,prompt='Infer actual source units structure; mechanism fixture only')
        return {'status':'accepted','understanding_confidence':.95,'structure_confidence':.95,
                'history':[{'status':'accepted','decision':decision}], 'arcs':arcs,'relations':relations or []}

    def verify(self,scenario='I',real_media=False):
        if real_media:
            return evaluator.verify_job(self.job,scenario,self.review)
        with patch.object(evaluator,'_probe',return_value={'format':{'duration':'2'}}), \
                patch.object(evaluator,'_export_media',return_value={'video_frames':45,'audio_frames':70,'duration':1.5}):
            return evaluator.verify_job(self.job,scenario,self.review)

    def assert_code(self,result,code,status='failed'):
        self.assertEqual(result['status'],status,result)
        self.assertEqual(result['checks'][-1]['code'],code,result)

    def known(self):
        return {(e['id'],u['id']):(e,u) for e in self.analysis['events'] for u in e['units']}

    def scenario(self,name,facts,analysis=None,plan=None):
        requests=[evaluator._read(p) for p in sorted((self.job/'actual-model').glob('request-*.json'))]
        responses=[evaluator._read(p.with_name(p.name.replace('request-','response-')))['response']
                   for p in sorted((self.job/'actual-model').glob('request-*.json'))]
        return evaluator._scenario(name,{'facts':facts},analysis or self.analysis,plan or self.plan,
            self.gate,responses,requests,14,self.job,self.known())

    def assert_error(self,code,action,status='failed'):
        with self.assertRaises(evaluator.AuditError) as caught:
            action()
        self.assertEqual(caught.exception.code,code)
        self.assertEqual(caught.exception.status,status)

    def boundary_scene(self,a,b,time=None,**proof):
        return {**span(a,b),'evidence':{'boundary_decisions':([] if time is None else [{
            'time':time,'boundary_verification':{'source':'semantic_boundary_verification',
                'confidence':.95,'uncertain':False,'accepted':True,**proof}}])}}

    def stage1_measurements(self,density=.04,cuts=()):
        self.save('shots.json',[{**span(0,14),'raw_shot_candidates':[
            {'id':f'camera{i}','time':t,'accepted':False,'score':.2} for i,t in enumerate(cuts)]}])
        self.save('media-evidence.json',{'source':{'sha256':self.original['source_sha256']},
            'motion':{'available':True,'adequate_coverage':True,'evidence':'source_optical_flow',
                      'physical_motion_density':density,'measurement_coverage':.8},'proposals':[]})

    def stage1_retained_transition(self):
        self.plan['parts'][0]['cuts']=[span(0,14)]
        self.event['units'].append({'id':'transition',**span(4,11)})
        self.event['unit_evidence'].append({'unit':'transition','kind':'state_transition','decision':'keep',
            'confidence':.95,'evidence':'Authored mechanism: source frames show wrists binding and vehicle transport.',
            'speech_quote':'','frame_indices':[1,2],'frame_times':[5.75,9.], 'frame_count':2,
            'view_start':4,'view_end':11,'checkpoint':'c'*64})

    def test_completed_artifact_mechanism_preserves_reaction_removes_neutral(self):
        result=self.verify()
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(result['scenario_result']['reaction_refs'],[ref('room','u2')])
        self.assertEqual(result['exports'][0]['retained_words'],1)
        self.assertIn('read_only_artifact_audit_not_independent_VLM_execution_authentication',result['limitations'])

    def test_job_and_evaluator_inputs_are_read_only(self):
        before={str(p.relative_to(self.job)):evaluator._sha(p) for p in self.job.rglob('*') if p.is_file()}
        self.assertEqual(self.verify()['status'],'passed')
        after={str(p.relative_to(self.job)):evaluator._sha(p) for p in self.job.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_analysis_only_and_incomplete_jobs_do_not_probe_or_claim_export_pass(self):
        for mode,complete in (('production_analysis_only',True),('production_render',False)):
            self.save('observed-outcome.json',{**self.outcome,'mode':mode,'complete':complete})
            with patch.object(evaluator,'_probe') as probe:
                result=evaluator.verify_job(self.job,'I',self.review)
            probe.assert_not_called()
            self.assert_code(result,'incomplete_production_render','unresolved')

    def test_frozen_code_is_required_and_both_identity_snapshots_must_match(self):
        self.save('observed-outcome.json',{**self.outcome,'pipeline_code_stable':False})
        self.assert_code(self.verify(),'unstable_pipeline_code','unresolved')
        self.sync()
        self.save('observer-code-identity-final.json',{'digest':'foreign-code'})
        self.assert_code(self.verify(),'pipeline_code_changed')

    def test_source_bytes_and_unannotated_input_contract_are_verified(self):
        original=self.source.read_bytes()
        self.source.write_bytes(original+b'changed')
        self.assert_code(self.verify(),'source_input_mismatch')
        self.source.write_bytes(original)
        self.save(self.input,{'source':str(self.source),'expected_scene':'oracle'})
        self.original['input_manifest_sha256']=evaluator._sha(self.input)
        self.save('original-inputs.json',self.original)
        self.assert_code(self.verify(),'source_input_mismatch')

    def test_missing_request_artifacts_and_changed_original_images_never_pass(self):
        self.save('observed-outcome.json',{**self.outcome,'actual_model_requests':3})
        self.assert_code(self.verify(),'missing_actual_requests','unresolved')
        self.sync()
        (self.job/'actual-model/source.jpg').write_bytes(b'foreign image')
        self.assert_code(self.verify(),'request_image_mismatch')

    def test_request_filename_and_recorded_identity_cannot_disagree(self):
        request=evaluator._read(self.job/'actual-model/request-001.json')
        request['request']=9
        self.save('actual-model/request-001.json',request)
        self.assert_code(self.verify(),'invalid_actual_request')

    def test_empty_identity_snapshots_do_not_prove_frozen_code(self):
        self.save('observer-code-identity.json',{})
        self.save('observer-code-identity-final.json',{})
        self.assert_code(self.verify(),'missing_pipeline_code_identity','unresolved')

    def test_registered_outputs_must_be_exact_and_export_bytes_unchanged(self):
        self.save('observed-outcome.json',{**self.outcome,'outputs':['../other.mp4','part_001.srt']})
        self.assert_code(self.verify(),'unregistered_exports')
        self.sync()
        self.export.write_bytes(self.export.read_bytes()+b'changed')
        self.assert_code(self.verify(),'export_hash_mismatch')

    def test_source_asr_in_final_analysis_and_cuts_are_independently_validated(self):
        self.analysis['transcript']=copy.deepcopy(self.transcript)
        self.analysis['transcript']['words'][0]['start']=.61
        self.sync()
        self.assert_code(self.verify(),'source_asr_mismatch')
        self.analysis['transcript']=self.transcript
        self.plan['parts'][0]['cuts']=[span(.65,2)]
        self.plan['parts'][0]['duration']=1.35
        self.sync()
        self.assert_code(self.verify(),'cut_asr_word')

    def test_changed_srt_even_with_updated_export_hash_cannot_invent_words_or_times(self):
        for text,start in (('Invented.',.1),('Причина.',.15)):
            self.plan['parts'][0]['subtitles']=[{'start':start,'end':.3,'text':text}]
            self.srt.write_text(f'1\n00:00:00,{int(start*1000):03d} --> 00:00:00,300\n{text}\n','utf-8')
            self.sync()
            self.assert_code(self.verify(),'subtitle_asr_mismatch')

    def test_proof_frame_domain_and_times_are_checked_after_gate_claims_passed(self):
        record=self.event['unit_evidence'][1]
        original=copy.deepcopy(record)
        for change in ({'frame_indices':[999]},{'frame_times':[.1]},{'frame_count':None},{'frame_times':[]}):
            record.clear();record.update(copy.deepcopy(original));record.update(change)
            self.sync()
            self.assert_code(self.verify(),'invalid_source_proof')

    def test_narrow_source_proof_cannot_authorize_whole_selected_unit(self):
        self.event['unit_evidence'][0].update(view_start=.6,view_end=.8)
        self.sync()
        self.assert_code(self.verify(),'incomplete_source_proof')

    def test_scoped_unit_refs_reject_foreign_parent_even_with_known_unit_id(self):
        self.gate['evidence_chain'][0]['ref']=ref('foreign','u1')
        self.sync()
        self.assert_code(self.verify(),'foreign_source_reference')

    def test_uncertainty_and_endpoint_context_are_not_positive_retention(self):
        self.event['uncertain']=True
        self.sync()
        self.assert_code(self.verify(),'unresolved_retained_event')
        self.event['uncertain']=False
        self.gate['evidence_chain'][0]['continuity_reasons']=[{
            'uncertain':False,'evidence':[{'kind':'endpoint_context'}]}]
        self.sync()
        self.assert_code(self.verify(),'endpoint_fallback')

    def test_gate_success_label_does_not_hide_material_problems(self):
        self.gate['problems']=[{'code':'unverified_bridge'}]
        self.sync()
        self.assert_code(self.verify(),'quality_gate_not_passed')

    def test_default_complete_source_boundary_and_eof_do_not_verify_semantic_ending(self):
        self.event['part_endings']=[]
        self.plan['parts'][0]['ending']={'kind':'complete_source_boundary','time':2}
        self.sync()
        self.assert_code(self.verify(),'missing_original_semantic_ending','unresolved')

    def test_original_ending_requires_the_actual_recorded_supported_response(self):
        self.event['part_endings'][0]['verification']['evidence']='Forged complete ending unsupported by the recorded verifier.'
        self.sync()
        self.assert_code(self.verify(),'missing_actual_ending_verification','unresolved')

    def test_original_ending_rejects_foreign_before_reply_or_boundary(self):
        proof=self.event['part_endings'][0]['verification']
        for field,value in (('last_reply','r0009'),('boundary','foreign-boundary')):
            original=proof[field]
            proof[field]=value
            self.request(2,{'decisions':{}},{'decisions':[proof]})
            self.sync()
            self.assert_code(self.verify(),'foreign_ending_context')
            proof[field]=original

    def test_gate_claim_cannot_hide_low_source_selection_confidence(self):
        self.event['selection_confidence']=.4
        self.sync()
        self.assert_code(self.verify(),'unresolved_retained_event')
        self.event['selection_confidence']=.95
        self.event['selection_status']='unresolved'
        self.sync()
        self.assert_code(self.verify(),'unresolved_retained_event')

    def test_original_inferred_arc_closing_requires_exact_scoped_inherited_proofs(self):
        self.event['part_endings']=[]
        current=ref('room','u2')
        self.analysis['story_structure']=self.structure([{
            'id':'actual-authored-arc','start':1,'end':2,'source_ranges':[span(1,2)],'source_unit_refs':[current],
            'complete_ending':True,'ending_verified':True,'uncertain':False,'closing_unit':current,
            'verification':{'supported':True,'confidence':.95,'proofs':[{
                'ref':current,'proof':evaluator._proof_id(current,self.event['unit_evidence'][1]),'quote':''}]}}])
        self.sync()
        self.assertEqual(self.verify()['status'],'passed')
        self.analysis['story_structure']['arcs'][0]['verification']['proofs'][0]['proof']='proof_foreign'
        self.sync()
        self.assert_code(self.verify(),'foreign_inherited_proof')

    def test_review_labels_need_matching_source_and_missing_facts_are_unresolved(self):
        self.review_row['source_sha256']='f'*64
        self.save_review()
        self.assert_code(self.verify(),'review_source_mismatch')
        result=self.verify()
        self.assertNotEqual(result['status'],'passed')
        with patch.object(evaluator,'_probe',return_value={'format':{'duration':'2'}}), \
                patch.object(evaluator,'_export_media',return_value={}):
            result=evaluator.verify_job(self.job,'I')
        self.assert_code(result,'missing_review_facts','unresolved')

    def test_reaction_missing_and_neutral_retained_are_explicit_failures(self):
        self.event['unit_evidence'][1]['kind']='physical_action'
        self.sync()
        self.assert_code(self.verify(),'reaction_missing')
        self.review_row['facts']['neutral_scenery']=[.5,1]
        self.save_review()
        self.assert_code(self.verify(),'neutral_scenery_retained')

    def test_actual_initial_uncertainty_must_be_exercised_before_h_can_pass(self):
        self.review_row.update(scenario='H',facts={'brief_visible_exchange':[.5,.8]})
        self.save_review()
        self.assert_code(self.verify('H'),'not_exercised','unresolved')
        self.request(3,{'keep_units':{}},{'uncertain':True,'visual_confidence':.4},
                     prompt='Analyze CURRENT SCENE from original footage')
        self.request(4,{'unit_evidence':{}},{'uncertain':False,'understanding_confidence':.95},
                     prompt='fresh original CURRENT adjudication')
        self.sync()
        self.assertEqual(self.verify('H')['status'],'passed')

    def test_a_binding_and_car_boundaries_need_both_existing_fixture_proofs(self):
        self.stage1_measurements()
        self.stage1_retained_transition()
        self.analysis['scenes']=[self.boundary_scene(0,5),self.boundary_scene(5,8,5,
            transition_type='binding',character_state_changed=True,physical_transition=True),
            self.boundary_scene(8,14,8,transition_type='enter_vehicle',location_changed=True)]
        self.assertTrue(self.scenario('A',{})['passed'])
        self.analysis['scenes'][2]['evidence']['boundary_decisions']=[]
        self.assert_error('scenario_criteria_failed',lambda:self.scenario('A',{}))

    def test_c_same_room_state_change_is_explicit_not_only_physical_label(self):
        self.stage1_measurements()
        self.stage1_retained_transition()
        self.analysis['scenes']=[self.boundary_scene(0,5),self.boundary_scene(5,14,5,
            transition_type='binding',character_state_changed=True,physical_transition=True,
            same_location=True,location_changed=False)]
        self.assertTrue(self.scenario('C',{})['passed'])
        self.analysis['scenes'][1]['evidence']['boundary_decisions'][0]['boundary_verification']['same_location']=False
        self.assert_error('same_room_state_not_verified',lambda:self.scenario('C',{}))

    def test_scene_detection_success_does_not_hide_an_exported_jump_over_binding_or_transport(self):
        self.stage1_measurements();self.stage1_retained_transition()
        self.analysis['scenes']=[self.boundary_scene(0,5),self.boundary_scene(5,8,5,
            transition_type='binding',character_state_changed=True,physical_transition=True),
            self.boundary_scene(8,14,8,transition_type='enter_vehicle',location_changed=True)]
        self.plan['parts'][0]['cuts']=[span(0,5),span(11,14)]
        self.assert_error('physical_transition_not_retained',lambda:self.scenario('A',{}))
        self.plan['parts'][0]['cuts']=[span(0,8),span(11,14)]
        self.assert_error('physical_transition_not_retained',lambda:self.scenario('A',{}))

    def test_retained_action_range_requires_original_physical_frames_in_each_reviewed_action(self):
        self.stage1_measurements();self.stage1_retained_transition()
        self.analysis['scenes']=[self.boundary_scene(0,5),self.boundary_scene(5,8,5,
            transition_type='binding',character_state_changed=True,physical_transition=True),
            self.boundary_scene(8,14,8,transition_type='enter_vehicle',location_changed=True)]
        record=self.event['unit_evidence'][-1]
        record.update(frame_indices=[1],frame_times=[5.75])
        self.assert_error('missing_retained_physical_proof',lambda:self.scenario('A',{}))

    def test_d_location_needs_accepted_finite_source_proof_not_bool_confidence(self):
        self.stage1_measurements()
        self.analysis['scenes']=[self.boundary_scene(0,6),self.boundary_scene(6,14,6,location_changed=True)]
        self.assertTrue(self.scenario('D',{})['passed'])
        self.analysis['scenes'][1]['evidence']['boundary_decisions'][0]['boundary_verification']['confidence']=True
        self.assert_error('invalid_boundary_proof',lambda:self.scenario('D',{}))

    def test_e_suppressed_camera_cuts_one_scene_are_not_motion(self):
        self.stage1_measurements(.04,(2,4,6,8,10,12))
        self.analysis['scenes']=[self.boundary_scene(0,14)]
        self.assertTrue(self.scenario('E',{})['passed'])
        perception=evaluator._read(self.job/'media-evidence.json')
        perception['motion']['evidence']='scene_change_candidate_density'
        self.save('media-evidence.json',perception)
        self.assert_error('missing_measured_motion',lambda:self.scenario('E',{}),'unresolved')

    def test_f_few_cuts_need_high_actual_measured_flow_and_source_identity(self):
        self.stage1_measurements(.8)
        self.analysis['scenes']=[self.boundary_scene(0,14)]
        self.assertTrue(self.scenario('F',{})['passed'])
        perception=evaluator._read(self.job/'media-evidence.json')
        perception['source']['sha256']='f'*64
        self.save('media-evidence.json',perception)
        self.assert_error('perception_source_mismatch',lambda:self.scenario('F',{}))
        self.stage1_measurements(.04)
        self.assert_error('scenario_criteria_failed',lambda:self.scenario('F',{}))

    def test_b_question_requires_prior_original_speech_in_same_part(self):
        self.words.append({'start':1.2,'end':1.4,'text':'Зачем','probability':.95})
        facts={'explanation_words':[.6,.8],'dependent_question_words':[1.2,1.4]}
        self.assertEqual(self.scenario('B',facts)['exercised_parts'],[1])
        self.plan['parts'][0]['cuts']=[span(1,2)]
        self.assert_error('unverified_structure_pass',lambda:self.scenario('B',facts))
        self.plan['parts'][0]['cuts']=[span(.5,1)]
        self.assert_error('not_exercised',lambda:self.scenario('B',facts),'unresolved')

    def test_b_supported_bridge_must_cover_each_retained_dependent_part(self):
        self.words.append({'start':1.2,'end':1.4,'text':'Зачем','probability':.95})
        action={'unit':'u0','kind':'state_transition','decision':'keep','confidence':.95,
                'evidence':'CURRENT персонаж получает ключ, который объясняет следующий вопрос.',
                'speech_quote':'','frame_indices':[1],'frame_times':[.2],'frame_count':1,
                'view_start':0,'view_end':.5,'checkpoint':'c'*64}
        self.event['unit_evidence'].append(action)
        left,right=ref('room','u0'),ref('room','u2')
        relation={'type':'cause','from':left,'to':right,'confidence':.95,'support':[
            {'ref':left,'proof':evaluator._proof_id(left,action),'quote':''},
            {'ref':right,'proof':evaluator._proof_id(right,self.event['unit_evidence'][1]),'quote':''}]}
        self.analysis['story_structure']=self.structure([],relations=[relation])
        self.plan['parts'][0]['cuts']=[span(0,.5),span(1,2)]
        facts={'explanation_words':[.6,.8],'dependent_question_words':[1.2,1.4]}
        self.assertEqual(self.scenario('B',facts)['exercised_parts'],[1])
        self.plan['parts'].append({'index':2,'cuts':[span(1,2)]})
        self.assert_error('missing_prior_explanation',lambda:self.scenario('B',facts))

    def test_g_exact_asr_pair_cannot_be_split_or_manufacture_endpoint(self):
        self.words.append({'start':1.2,'end':1.4,'text':'Поэтому','probability':.94})
        pair={'status':'confirmed','requires_answer':True,'confidence':.95,
              'question_refs':[ref('room','u1')],'answer_refs':[ref('room','u2')],
              'question_ranges':[span(.6,.8)],'answer_ranges':[span(1.2,1.4)],
              'question_asr_refs':[{'container':'words','index':0}],
              'answer_asr_refs':[{'container':'words','index':1}]}
        self.analysis['dialogue_relations']={'status':'accepted','understanding_confidence':.95,
                                            'relation_confidence':.95,'pairs':[pair]}
        facts={'question_words':[.6,.8],'answer_words':[1.2,1.4]}
        self.assertEqual(self.scenario('G',facts)['confirmed_pairs'],1)
        self.plan['parts']=[{'index':1,'cuts':[span(.5,1)]},{'index':2,'cuts':[span(1,2)]}]
        self.assert_error('split_required_dialogue',lambda:self.scenario('G',facts))
        pair['answer_ranges']=[span(1.25,1.35)]
        self.assert_error('foreign_dialogue_asr_reference',lambda:self.scenario('G',facts))

    def five_arc_fixture(self):
        units=[{'id':f'arc{i}',**span(2*i,2*i+2)} for i in range(5)]
        records=[{'unit':u['id'],'kind':'state_transition','decision':'keep','confidence':.95,
                  'evidence':'CURRENT показан конкретный итог отдельного причинного действия.',
                  'speech_quote':'','frame_indices':[1],'frame_times':[u['start']+1],'frame_count':1,
                  'view_start':u['start'],'view_end':u['end'],'checkpoint':'d'*64} for u in units]
        self.event.update(start=0,end=10,units=units,unit_evidence=records,part_endings=[])
        self.analysis['transcript']={'words':[],'segments':[]}
        self.analysis['preferred_part_count']=6
        arcs=[]
        for i,(unit,record) in enumerate(zip(units,records)):
            current=ref('room',unit['id'])
            arcs.append({'id':f'inferred{i}',**span(unit['start'],unit['end']),
                'source_unit_refs':[current],'source_ranges':[span(unit['start'],unit['end'])],
                'closing_unit':current,'complete_ending':True,'ending_verified':True,'uncertain':False,
                'verification':{'supported':True,'confidence':.95,'proofs':[
                    {'ref':current,'proof':evaluator._proof_id(current,record),'quote':''}]}})
        self.analysis['story_structure']=self.structure(arcs)
        self.plan['parts']=[{'index':i+1,'cuts':[span(u['start'],u['end'])]} for i,u in enumerate(units)]
        return {'observed_stories':[{'bounds':[u['start'],u['end']]} for u in units]}

    def test_j_five_real_source_arc_records_can_belong_to_same_parent_not_six_parts(self):
        facts=self.five_arc_fixture()
        self.assertEqual(self.scenario('J',facts),{'actual_arcs':5,'preferred_parts':6,'final_parts':5})
        self.plan['parts'].append({'index':6,'cuts':[span(0,2)]})
        self.assert_error('natural_part_count',lambda:self.scenario('J',facts))

    def test_j_closing_needs_original_proof_and_actual_structure_history(self):
        facts=self.five_arc_fixture()
        self.analysis['story_structure']['arcs'][0]['verification']['proofs'][0]['proof']='foreign-proof'
        self.assert_error('foreign_inherited_proof',lambda:self.scenario('J',facts))
        facts=self.five_arc_fixture()
        self.analysis['story_structure']['history'][0]['decision']['structure_confidence']=.1
        self.assert_error('missing_structure_query',lambda:self.scenario('J',facts),'unresolved')

    def test_j_arc_range_cannot_escape_actual_unit_or_be_split_into_two_parts(self):
        facts=self.five_arc_fixture()
        self.analysis['story_structure']['arcs'][0]['source_ranges']=[span(0,2.1)]
        self.assert_error('foreign_arc_ranges',lambda:self.scenario('J',facts))
        facts=self.five_arc_fixture()
        self.plan['parts'][0]['cuts']=[span(0,1)]
        self.plan['parts'][1]['cuts']=[span(1,4)]
        self.assert_error('split_closed_arc',lambda:self.scenario('J',facts))

    def test_g_permitted_preobtained_unpunctuated_asr_and_exact_same_part_pair(self):
        self.words[0]['text']='Почему'
        self.words.append({'start':1.2,'end':1.4,'text':'Поэтому','probability':.94})
        self.transcript['segments']=copy.deepcopy(self.words)
        self.event['part_endings'][0]['verification']['last_reply']='r0001'
        self.request(2,{'decisions':{}},{'decisions':[self.event['part_endings'][0]['verification']]})
        self.event['unit_evidence'][0]['speech_quote']='Почему'
        self.plan['parts'][0]['subtitles']=[{'start':.1,'end':.9,'text':'Почему Поэтому'}]
        self.srt.write_text('1\n00:00:00,100 --> 00:00:00,900\nПочему Поэтому\n','utf-8')
        self.save('transcript.json',self.transcript)
        self.supplied=self.job/'input/ordinary-asr.json'
        self.save(self.supplied,self.transcript)
        self.save(self.input,{'source':str(self.source),'transcript':str(self.supplied)})
        self.original.update(transcript_sha256=evaluator._sha(self.supplied),input_manifest_sha256=evaluator._sha(self.input))
        self.save('original-inputs.json',self.original)
        self.save('observer-input-locations.json',{'input':str(self.input),'transcript':str(self.supplied)})
        self.review_row.update(scenario='G',input_manifest_sha256=self.original['input_manifest_sha256'],
                               facts={'question_words':[.6,.8],'answer_words':[1.2,1.4]})
        self.save_review()
        self.analysis['dialogue_relations']={'status':'accepted','understanding_confidence':.95,'relation_confidence':.95,
            'pairs':[{'status':'confirmed','requires_answer':True,'confidence':.95,'question_refs':[ref('room','u1')],
                      'answer_refs':[ref('room','u2')],'question_ranges':[span(.6,.8)],'answer_ranges':[span(1.2,1.4)],
                      'question_asr_refs':[{'container':'words','index':0}],
                      'answer_asr_refs':[{'container':'words','index':1}]}]}
        self.sync()
        result=self.verify('G')
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(result['asr_provenance']['mode'],'provided_ordinary_ASR')
        self.analysis['dialogue_relations']['pairs'][0]['answer_refs']=[ref('foreign','u2')]
        self.sync()
        self.assert_code(self.verify('G'),'foreign_source_reference')

    def test_g_origin_transformation_preserves_words_clocks_and_probabilities(self):
        origin=self.job/'origin/transcript.json'
        raw=copy.deepcopy(self.transcript)
        raw['words'][0]['text']='Причина?'
        raw['segments'][0]['text']='Причина?'
        clean=copy.deepcopy(raw)
        clean['words'][0]['text']=clean['segments'][0]['text']='Причина'
        self.save(origin,raw)
        self.save(origin.parent/'original-inputs.json',{'source_sha256':self.original['source_sha256'],'transcript_sha256':None})
        provenance=self.job/'asr-origin-review-only.json'
        self.save(provenance,{'origin':str(origin),'origin_sha256':evaluator._sha(origin),'transformation':'remove_question_mark_only'})
        review={'asr_origin':str(provenance)}
        self.assertTrue(evaluator._g_asr(review,{'transcript':'allowed ordinary ASR'},clean,self.original)['origin_transformation_verified'])
        clean['words'][0]['probability']=.5
        with self.assertRaises(evaluator.AuditError) as caught:
            evaluator._g_asr(review,{},clean,self.original)
        self.assertEqual(caught.exception.code,'asr_transformation_changed_words')

    def test_g_origin_allows_omitted_automatic_diagnostics_not_speech_changes(self):
        origin=self.job/'origin/transcript.json'
        automatic={**copy.deepcopy(self.transcript),'device':'cuda','elapsed_seconds':1.4,
                   'repair_version':3,'repair_originals':[],'repair_log':[]}
        automatic['words'][0]['text']='Причина?'
        automatic['segments'][0]['text']='Причина?'
        ordinary=copy.deepcopy(self.transcript)
        ordinary['words'][0]['text']=ordinary['segments'][0]['text']='Причина'
        self.save(origin,automatic)
        self.save(origin.parent/'original-inputs.json',{'source_sha256':self.original['source_sha256'],'transcript_sha256':None})
        provenance=self.job/'asr-origin-review-only.json'
        self.save(provenance,{'origin':str(origin),'origin_sha256':evaluator._sha(origin),
                              'transformation':'remove_question_mark_only'})
        self.assertTrue(evaluator._g_asr({'asr_origin':str(provenance)},
            {'transcript':'ordinary-asr.json'},ordinary,self.original)['origin_transformation_verified'])
        ordinary['words'][0]['start']=.61
        self.assert_error('asr_transformation_changed_words',lambda:evaluator._g_asr(
            {'asr_origin':str(provenance)}, {},ordinary,self.original))

    def test_cli_json_and_nonzero_exit_for_noncompleted_job(self):
        self.save('observed-outcome.json',{**self.outcome,'complete':False})
        with patch('sys.stdout',new_callable=io.StringIO) as output:
            code=evaluator.main(['--job-dir',str(self.job),'--scenario','I'])
        self.assertEqual(code,2)
        self.assertEqual(json.loads(output.getvalue())['status'],'unresolved')

    @unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(),'Portable media tools unavailable')
    def test_real_synthetic_mp4_video_audio_decode_duration_and_registered_srt(self):
        evaluator._tool([FFMPEG,'-y','-v','error','-f','lavfi','-i','color=blue:s=160x90:r=30:d=2',
                         '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                         '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',self.source])
        evaluator._tool([FFMPEG,'-y','-v','error','-ss','0.5','-i',self.source,'-t','1.5',
                         '-vf','scale=1080:1920','-r','30','-c:v','libx264','-preset','ultrafast',
                         '-pix_fmt','yuv420p','-c:a','aac',self.export])
        self.original['source_sha256']=evaluator._sha(self.source)
        self.save('original-inputs.json',self.original)
        self.review_row['source_sha256']=self.original['source_sha256']
        self.save_review()
        self.sync()
        result=self.verify(real_media=True)
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(result['exports'][0]['video_frames'],45)
        self.assertGreater(result['exports'][0]['audio_frames'],0)
        self.export.write_bytes(self.export.read_bytes()[:1500])
        self.sync()
        result=self.verify(real_media=True)
        self.assertEqual(result['status'],'failed',result)


if __name__=='__main__':
    unittest.main()
