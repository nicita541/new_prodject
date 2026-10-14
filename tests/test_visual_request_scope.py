"""Source-local model packets; all inference and extraction are capture fakes."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.closing import _relevant_prior, refine_closing_novelty
from app.global_verification import _reasons
from app.production_sequence import sequence_clusters, verify_boundaries
from app.semantic_boundary import _prepare_boundary
from app.source_roles import refine_source_roles
from tests.test_production_sequence import decision
from tests.test_source_roles import role_answer
from tests.test_story import edge_fixture


class VisualRequestScopeTests(unittest.TestCase):
    def test_long_parent_role_check_sends_only_actual_target_units(self):
        directory,event,_=edge_fixture(start=0,end=30)
        event.update(contains_credits=True,selected_ranges=[{'start':0,'end':30}],
                     review_target_ranges=[{'start':10,'end':15,'checks':['source_roles']}])
        units=[{'id':'first','start':0,'end':10,'text':'UNNEEDED_BEFORE'},
               {'id':'target','start':10,'end':15,'text':'Needed source reply'},
               {'id':'last','start':15,'end':30,'text':'UNNEEDED_AFTER'}]
        class Vision:
            model=Path('model');projector=Path('profile');supports_image_pages=False
            def query(self,prompt,images,**kwargs):
                self.prompt=prompt
                return role_answer('current_story',meaningful=True)
        vision=Vision()
        with patch('app.story_review.candidate_units',return_value=units), patch(
                'app.production.sequence_sheet',return_value=[directory/'target.jpg']) as sheet:
            result=refine_source_roles([event],{'segments':[],'words':[]},[],directory,vision,
                                      lambda *a:None,lambda:False)
        self.assertEqual([(u['start'],u['end']) for u in sheet.call_args.args[1]],[(10,15)])
        self.assertNotIn('UNNEEDED',vision.prompt)
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])

    def test_closing_target_media_and_omission_preserve_unchecked_parent_ranges(self):
        from PIL import Image
        from tests.test_closing import decision as closing_decision
        directory,event,_=edge_fixture(start=80,end=100,kind='ending')
        event.update(contains_credits=True,credits_kind='ending',selected_ranges=[{'start':80,'end':100}],
                     review_target_ranges=[{'start':90,'end':95,'checks':['closing']}])
        units=[{'id':'u000','start':80,'end':90,'text':'UNNEEDED_BEFORE'},
               {'id':'u001','start':90,'end':95,'text':''},
               {'id':'u002','start':95,'end':100,'text':'UNNEEDED_AFTER'}]
        class Vision:
            def query(self,prompt,image,**kwargs):
                self.prompt,self.image=prompt,image
                return closing_decision(['u001'],[])
        def render(source,start,end,shots,transcript,image,cancelled):
            Image.new('RGB',(48,27)).save(image)
            return [start,end]
        vision=Vision()
        with patch('app.story_review.candidate_units',return_value=units), patch(
                'app.vision.storyboard',side_effect=render) as frames:
            result=refine_closing_novelty([event],{'segments':[],'words':[]},[],directory,vision,
                lambda *a:None,lambda:False,episode_duration=100)
        self.assertEqual(frames.call_args.args[1:3],(90,95))
        self.assertNotIn('UNNEEDED',vision.prompt)
        self.assertEqual(result[0]['selected_ranges'],[{'start':80,'end':90},{'start':95,'end':100}])

    def test_role_confirmation_renders_only_proposals_and_nearby_source(self):
        directory,event,_=edge_fixture(start=0,end=15)
        event.update(contains_credits=True,selected_ranges=[{'start':0,'end':15}])
        remote={**copy.deepcopy(event),'id':'far_context_sentinel','start':1000,'end':1005,
                'selected_ranges':[{'start':1000,'end':1005}]}
        units=[{'id':f'u{i:03d}','start':i*5,'end':i*5+5,
                'text':'Subscribe official channel' if i==0 else f'UNRELATED_ROW_{i}'} for i in range(3)]
        proposed=role_answer('uploader',quote=units[0]['text'],visible='OFFICIAL CHANNEL')
        current=role_answer('current_story',meaningful=True)['decisions'][0]
        first={'decisions':[proposed['decisions'][0],dict(current,unit='B'),dict(current,unit='C')]}
        class Vision:
            model=Path('test-model');projector=Path('test-profile');cache_profile='bounded-sentinel'
            supports_image_pages=True
            def __init__(self):self.answers=[first,proposed];self.calls=[]
            def query(self,prompt,images,**kwargs):
                self.calls.append((prompt,images))
                return self.answers.pop(0)
        vision=Vision()
        with patch('app.story_review.candidate_units',return_value=units), patch(
                'app.production.sequence_sheet',side_effect=lambda source,rows,times,path,*a,**k:[path]) as sheet:
            result=refine_source_roles([event,remote],{'segments':[],'words':[]},[],directory,vision,
                lambda *a:None,lambda:False,event_ids={event['id']},episode_duration=1010)
        self.assertEqual(len(vision.calls),2)
        self.assertEqual([u['id'] for u in sheet.call_args_list[0].args[1]],['A','B','C'])
        self.assertEqual([u['id'] for u in sheet.call_args_list[1].args[1]],['A'])
        self.assertTrue(all(t<=16 for call in sheet.call_args_list for t in call.args[2]))
        self.assertNotIn('UNRELATED_ROW',vision.calls[1][0])
        self.assertNotEqual(vision.calls[0][1],vision.calls[1][1])
        self.assertEqual(result[1],remote)

    def test_tail_position_alone_does_not_dispatch_source_role_or_closing(self):
        directory,event,_=edge_fixture(start=80,end=100)
        event.update(kind='story',selected_ranges=[{'start':80,'end':100}])
        for key in ('contains_credits','credit_montage','credits_kind'):
            event.pop(key,None)
        class Vision:
            model=Path('model');projector=Path('projector')
            def query(self,*a,**k):raise AssertionError('No concrete source-role/closing problem')
        for callback in (refine_source_roles,refine_closing_novelty):
            with self.subTest(check=callback.__name__):
                result=callback([event],{'segments':[],'words':[]},[],directory,Vision(),
                                lambda *a:None,lambda:False,episode_duration=100)
                self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])

    def test_sparse_credit_windows_do_not_become_adjacent_by_list_index(self):
        events=[{'id':'opening','start':30,'end':40,'contains_credits':True},
                {'id':'ending','start':1200,'end':1210,'contains_credits':True}]
        self.assertEqual(sequence_clusters(events,{'words':[]},duration=1400),[[0],[1]])

    def test_closing_witnesses_are_relevant_and_bounded(self):
        event={'id':'current','summary':'The locker key changes hands','requires':['cause']}
        prior=[{'id':'cause','start':1,'end':2,'summary':'A required setup'},
               {'id':'matching','start':3,'end':4,'summary':'Earlier locker key exchange'},
               *[{'id':f'unrelated_{i}','start':10+i,'end':11+i,
                  'summary':'PRIVATE_UNRELATED_SENTINEL scenery'} for i in range(100)]]
        result=_relevant_prior(event,[{'text':'locker key'}],prior)
        self.assertEqual([e['id'] for e in result],['cause','matching'])
        self.assertNotIn('PRIVATE_UNRELATED_SENTINEL',json.dumps(result))

    def test_importance_and_bridge_are_not_errors_to_recheck(self):
        self.assertEqual(_reasons({'importance':5,'narrative_bridge':True}),[])
        self.assertEqual(_reasons({'importance':5,'local_conflict':True}),['conflicting_local_decisions'])

    def test_semantic_boundary_does_not_send_entire_neighboring_scenes(self):
        directory,_,source=edge_fixture(start=0,end=1000)
        transcript={'segments':[{'start':1,'end':3,'text':'DISTANT_PRIVATE_SENTINEL'},
                                {'start':499,'end':501,'text':'Current boundary reply'},
                                {'start':990,'end':991,'text':'OTHER_DISTANT_SENTINEL'}]}
        frames=[{'time':499.25,'frame':'before.jpg','sha256':'one'},
                {'time':500.75,'frame':'after.jpg','sha256':'two'}]
        with patch('app.semantic_boundary.boundary_frames',return_value=(directory/'pair.jpg',frames)):
            result=_prepare_boundary(source,500,0,1000,transcript,{},directory,object(),lambda:False)
        self.assertIn('Current boundary reply',result['prompt'])
        self.assertNotIn('DISTANT',result['prompt'])

    def test_independent_boundary_cannot_move_endpoint_to_unseen_interior(self):
        units=[{'id':f'U{i:03d}','start':i*5,'end':i*5+5,'text':''} for i in range(40)]
        initial={**decision(),'first_unit':'U004','last_unit':'U030','before_unit':'U003',
                 'after_unit':'U031','anchors':[{'unit':'U006','type':'theme_credit','visible_text':'STAFF'}],
                 'narrative_units':[]}
        class Vision:
            def query(self,*a,**k):return {**initial,'first_unit':'U015','before_unit':'U014'}
        with self.assertRaisesRegex(ValueError,'не показана'):
            verify_boundaries(initial,units,['full-overview'],Vision(),200,['bounded-edges'])


if __name__=='__main__':
    unittest.main()
