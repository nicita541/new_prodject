"""Scoped ownership repair; provider responses are capture fakes, never APIs."""
import copy
import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import TEMP, FFMPEG
from app.media import run_command
from app.scoped_boundary_recovery import recover_scoped_boundaries
from app.semantic_boundary import verify_scoped_boundary
from app.source_identity import source_identity
from tests.test_semantic_boundary import decision


def segment(index,start,end):
    return {'id':f's{index}','shot_id':f's{index}','start':start,'end':end}


def scene(identifier,start,end,segments,disputed=()):
    return {'id':identifier,'start':start,'end':end,'shot_ids':[s['id'] for s in segments],
            'candidate_ids':[],'boundary_reason':['source_start'],'confidence':.94,'uncertain':bool(disputed),
            'evidence':{'visual_coverage':1,'uncertainty_reasons':['ambiguous_internal_boundary'] if disputed else [],
                'source_segments':segments,'sampled_times':[start+.1],
                'boundary_decisions':[{'time':t,'accepted':False,'uncertain':True,'signals':{'observed':True}}
                                      for t in disputed]}}


def native_proof(cut):
    return {**decision(),'accepted':cut,'uncertain':False,'signature':'accepted-native-source-proof',
            'reasons':['verified_location_change' if cut else 'verified_same_scene']}


class ScopedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory=TEMP/('scoped-boundary-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.source=self.directory/'source.mp4'
        self.source.write_bytes(b'source-identity-fixture')
        first=scene('first',0,20,[segment(0,0,10),segment(1,10,20)],[10])
        other=scene('unrelated',20,30,[segment(2,20,30)])
        self.analysis={'probe':{'duration':30},'scenes':[first,other],
            'transcript':{'words':[],'segments':[]},'shots':[segment(0,0,10),segment(1,10,20),segment(2,20,30)],
            'events':[{'id':'owned','scene_id':'first','parent_scene_id':'first','start':0,'end':20,
                'units':[{'id':'u0','start':0,'end':10},{'id':'u1','start':10,'end':20}],
                'selected_ranges':[{'start':0,'end':20}],'unit_evidence':[{'producer':'accepted-original'}],
                'scene_evidence':copy.deepcopy(first['evidence']),'sentinel':'accepted-original'},
                {'id':'outside','scene_id':'unrelated','parent_scene_id':'unrelated','start':20,'end':30,
                 'units':[{'id':'outside-unit','start':20,'end':30}],
                 'selected_ranges':[{'start':20,'end':30}],'unit_evidence':[{'producer':'unrelated-original'}],
                 'scene_evidence':copy.deepcopy(other['evidence']),'sentinel':'DO_NOT_TOUCH'}]}
        self.problems=[{'recovery_stage':'semantic_boundary','scene':'first'}]

    def tearDown(self):
        shutil.rmtree(self.directory)

    def recover(self,proof=None,rebuilder=None):
        def build(source,window,previous,*a,**kwargs):
            return {'id':kwargs['event_id'],'scene_id':window['id'],'start':window['start'],'end':window['end'],
                    'selected_ranges':[],'units':[{'id':'fresh-source-unit','start':window['start'],'end':window['end']}],
                    'native_rebuild':True}
        with (patch('app.semantic_boundary.verify_scoped_boundary',return_value=proof or native_proof(True)) as verifier,
              patch('app.scene_analysis.rebuild_scoped_event',side_effect=rebuilder or build) as rebuild):
            result=recover_scoped_boundaries(self.source,self.analysis,self.problems,self.directory,object(),
                                             lambda *a:None,lambda:False)
        return result,verifier,rebuild

    def test_only_changed_owner_is_split_and_rebuilt(self):
        original=copy.deepcopy(self.analysis)
        result,verify,rebuild=self.recover()
        self.assertEqual(result['status'],'accepted')
        self.assertEqual(self.analysis,original)
        self.assertEqual(verify.call_count,1)
        self.assertEqual(verify.call_args.args[1:4],(10,0,20))
        self.assertEqual([(c.args[1]['start'],c.args[1]['end']) for c in rebuild.call_args_list],[(0,10),(10,20)])
        self.assertEqual(result['events'][-1],original['events'][-1])
        self.assertEqual(result['scenes'][-1],original['scenes'][-1])
        self.assertEqual(result['changed_ranges'],[{'start':0,'end':20}])
        self.assertEqual(result['removed_event_ids'],['owned'])
        self.assertEqual(len(result['ownership']['owned']),2)
        self.assertTrue(all('sentinel' not in e for e in result['events'][:2]))

    def test_same_scene_proof_preserves_current_geometry_and_unit_proofs_without_reanalysis(self):
        result,verify,rebuild=self.recover(native_proof(False))
        self.assertEqual(result['status'],'accepted')
        self.assertFalse(rebuild.called)
        self.assertEqual(result['changed_ranges'],[])
        self.assertEqual(result['changed_event_ids'],[])
        self.assertEqual(result['events'][0]['units'],self.analysis['events'][0]['units'])
        self.assertEqual(result['events'][0]['unit_evidence'],self.analysis['events'][0]['unit_evidence'])
        self.assertFalse(result['scenes'][0]['uncertain'])
        self.assertEqual(result['events'][1],self.analysis['events'][1])

    def test_merging_semantic_parents_reuses_identical_current_windows(self):
        a=scene('a',0,10,[segment(0,0,10)])
        b=scene('b',10,20,[segment(1,10,20)],[10])
        self.analysis['scenes']=[a,b,self.analysis['scenes'][1]]
        self.analysis['events']=[{**self.analysis['events'][0],'id':'a-event','scene_id':'a','end':10},
                                 {**self.analysis['events'][0],'id':'b-event','scene_id':'b','start':10},
                                 self.analysis['events'][1]]
        self.problems=[{'recovery_stage':'semantic_boundary','scene':'b'}]
        result,verify,rebuild=self.recover(native_proof(False))
        self.assertEqual(result['status'],'accepted')
        self.assertFalse(rebuild.called)
        self.assertEqual([(s['start'],s['end']) for s in result['scenes']],[(0,20),(20,30)])
        self.assertEqual(result['events'][-1],self.analysis['events'][-1])
        self.assertEqual([e['id'] for e in result['events']],['a-event','b-event','outside'])
        self.assertEqual(set(result['reassociated_event_ids']),{'a-event','b-event'})

    def test_whole_word_adjustment_does_not_change_other_owners(self):
        self.analysis['transcript']['words']=[{'start':9.8,'end':10.2,'text':'whole'}]
        result,_,rebuild=self.recover()
        self.assertEqual(result['status'],'accepted')
        self.assertEqual([(c.args[1]['start'],c.args[1]['end']) for c in rebuild.call_args_list],[(0,9.8),(9.8,20)])
        self.assertEqual(result['scenes'][-1],self.analysis['scenes'][-1])

    def test_unbounded_word_shift_is_explicit_without_owner_replacement(self):
        self.analysis['transcript']['words']=[{'start':8,'end':12,'text':'indivisible'}]
        result,_,rebuild=self.recover()
        self.assertEqual(result['status'],'unresolved')
        self.assertFalse(rebuild.called)
        self.assertEqual(result['events'],self.analysis['events'])
        self.assertIn('whole-word',result['unresolved'][0]['reason'])

    def test_bare_scene_ambiguity_does_not_invent_a_boundary(self):
        self.analysis['scenes'][0]['evidence']['boundary_decisions']=[]
        result,verify,rebuild=self.recover()
        self.assertEqual(result['status'],'unresolved')
        self.assertFalse(verify.called)
        self.assertFalse(rebuild.called)

    def test_no_requested_problem_dispatches_nothing(self):
        self.problems=[]
        result,verify,rebuild=self.recover()
        self.assertEqual(result['status'],'not_required')
        self.assertFalse(verify.called)
        self.assertFalse(rebuild.called)
        self.assertEqual(result['events'],self.analysis['events'])

    def test_native_window_failure_does_not_publish_partial_geometry(self):
        def fail(*a,**k):raise ValueError('Missing CURRENT source frames')
        result,_,_=self.recover(rebuilder=fail)
        self.assertEqual(result['status'],'unresolved')
        self.assertEqual(result['events'],self.analysis['events'])
        self.assertEqual(result['scenes'],self.analysis['scenes'])
        self.assertEqual(result['ownership'],{})

    def test_native_boundary_proof_requires_actual_artifact_hashes_and_source_sides(self):
        frames=[]
        for label,time in [('before',9.5),('after',10.5)]:
            path=self.directory/(label+'.jpg')
            Image.new('RGB',(32,18),'red').save(path)
            frames.append({'time':time,'frame':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        raw={**decision(),'source':'semantic_boundary_verification','signature':'native-signature','frames':frames}
        transcript={'segments':[{'start':9,'end':11,'text':'exact current ASR'}],'words':[]}
        with patch('app.semantic_boundary.verify_boundary',return_value=raw):
            result=verify_scoped_boundary(self.source,10,0,20,transcript,{},self.directory,object(),lambda:False)
        self.assertEqual(result['source_evidence']['source']['sha256'],source_identity(self.source)['sha256'])
        self.assertEqual(result['source_evidence']['asr_sha256'],hashlib.sha256(
            json.dumps(transcript['segments'],ensure_ascii=False,sort_keys=True).encode()).hexdigest())
        raw['frames'][0]['sha256']='wrong'
        (self.directory/'before.jpg').write_bytes(b'corrupted actual frame')
        with patch('app.semantic_boundary.verify_boundary',return_value=raw),self.assertRaisesRegex(ValueError,'ownership/hash'):
            verify_scoped_boundary(self.source,10,0,20,transcript,{},self.directory,object(),lambda:False)

    def test_bare_native_label_cannot_supply_source_acceptance(self):
        with patch('app.semantic_boundary.verify_boundary',return_value=decision()),self.assertRaisesRegex(ValueError,'proof'):
            verify_scoped_boundary(self.source,10,0,20,{'segments':[]}, {},self.directory,object(),lambda:False)

    def test_uncertain_identical_native_reply_is_not_sent_again(self):
        frames=[]
        for name,time in [('before',9.5),('after',10.5)]:
            path=self.directory/(name+'.jpg')
            Image.new('RGB',(32,18),'blue').save(path)
            frames.append({'time':time,'frame':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        raw={**decision(confidence=.8),'source':'semantic_boundary_verification','signature':'native-uncertain','frames':frames}
        with patch('app.semantic_boundary.verify_boundary',return_value=raw) as native:
            first=verify_scoped_boundary(self.source,10,0,20,{'segments':[]},{},self.directory,object(),lambda:False)
            warm=verify_scoped_boundary(self.source,10,0,20,{'segments':[]},{},self.directory,object(),lambda:False)
        self.assertTrue(first['uncertain'])
        self.assertEqual(first,warm)
        self.assertEqual(native.call_count,1)

    def test_rejected_response_without_frames_is_not_reasked_unchanged(self):
        with patch('app.semantic_boundary.verify_boundary',return_value=decision()) as native:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'proof'):
                    verify_scoped_boundary(self.source,10,0,20,{'segments':[]},{},self.directory,object(),lambda:False)
        self.assertEqual(native.call_count,1)

    @unittest.skipUnless(FFMPEG.is_file(),'Portable FFmpeg is unavailable')
    def test_native_changed_window_uses_real_frames_and_warm_cache_only(self):
        from app.scene_analysis import rebuild_scoped_event
        run_command([str(FFMPEG),'-y','-v','error','-f','lavfi','-i','color=red:s=160x90:r=10:d=4',
                     '-c:v','libx264','-pix_fmt','yuv420p',str(self.source)],self.directory)
        (self.directory/'probe.json').write_text(json.dumps({'duration':4}),encoding='utf-8')
        window=scene('new-owner',1,3,[segment(0,1,3)])
        class Vision:
            model='fake';projector='fake';supports_image_pages=False
            def __init__(self):self.calls=[]
            def query(self,prompt,image,**options):
                self.calls.append((prompt,image))
                if 'resolved' in options['schema']['properties']:
                    payload=json.JSONDecoder().raw_decode('{'+prompt.split('\n{',1)[1])[0]
                    units,frames=payload['CURRENT']['units'],payload['CURRENT']['frames']
                    return {'summary':'Однородный красный технический тестовый кадр.','resolved':True,
                        'understanding_confidence':.95,'selection_confidence':.95,'keep_units':[],
                        'drop_units':[u['id'] for u in units],'action_units':[],
                        'unit_evidence':[{'unit':u['id'],'kind':'neutral_scenery',
                            'evidence':'В исходном CURRENT виден только однородный красный цвет без действия.',
                            'confidence':.95,'frame_indices':[next(i+1 for i,f in enumerate(frames)
                                if u['start']<=f['time']<u['end'])],'speech_quote':''} for u in units],
                        'causal_links':[],'state_before':{'locations':[],'character_state':'','objects':[]},
                        'state_after':{'locations':[],'character_state':'','objects':[]}}
                ids=options['schema']['properties']['keep_units']['items']['enum']
                return {'summary':'Красный тестовый кадр.','kind':'story','importance':3,'uncertain':False,
                        'semantic_confidence':.95,'visual_confidence':.95,'context_confidence':.95,
                        'selection_confidence':.95,'uncertainty_reasons':[],'keep_units':ids,'action_units':[],
                        'narrative_bridge':False,'state_before':{},'state_after':{}}
        vision=Vision()
        stamp=source_identity(self.source)
        from app.selection_adjudication import adjudicate_event
        with patch('app.selection_adjudication.adjudicate_event',wraps=adjudicate_event) as selection:
            first=rebuild_scoped_event(self.source,window,self.analysis['events'][0],{'segments':[],'words':[]},
                [segment(0,0,4)],self.directory,vision,lambda *a:None,lambda:False,source_key=stamp,event_id='event_boundary_test')
            warm=Vision()
            second=rebuild_scoped_event(self.source,window,self.analysis['events'][0],{'segments':[],'words':[]},
                [segment(0,0,4)],self.directory,warm,lambda *a:None,lambda:False,source_key=stamp,event_id='event_boundary_test')
        self.assertEqual(len(vision.calls),2,[prompt[:90] for prompt,_ in vision.calls])
        self.assertEqual(warm.calls,[])
        self.assertEqual(first,second)
        self.assertEqual((first['start'],first['end']),(1,3))
        from app.selection_gate import source_selection_readiness
        self.assertEqual(source_selection_readiness([first])['status'],'passed')
        self.assertTrue((self.directory/'visual/event_boundary_test.jpg').is_file())
        self.assertTrue(all((call.args[1]['start'],call.args[1]['end'])==(1,3) for call in selection.call_args_list))
        self.assertFalse((self.directory/'diagnostics/pipeline/storyboard.json').exists())


if __name__=='__main__':unittest.main()
