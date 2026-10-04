import copy
import json
import unittest
from unittest.mock import patch

from app.production_sequence import sequence_decision, clean_whole_sequences, original_clusters
from tests.test_story import edge_fixture, FakeVision


def decision():
    return {'kind':'opening','first_unit':'U001','last_unit':'U003','before_unit':'U000','after_unit':'U004',
            'anchors':[{'unit':'U002','type':'theme_credit','visible_text':'Opening theme: Music'}],
            'narrative_units':['U000','U004'],'confidence':.95,
            'boundary_evidence':'Conversation changes to stylized credits then returns to a new chronological scene.'}


class WholeSequenceTests(unittest.TestCase):
    units=[{'id':f'U{i:03}','start':i*5,'end':(i+1)*5,'text':''} for i in range(5)]

    def test_text_free_middle_and_tail_belong_to_one_sequence(self):
        excluded,anchors=sequence_decision(decision(),self.units,25)
        self.assertEqual(excluded,{'U001','U002','U003'})
        self.assertEqual(anchors[0]['type'],'theme_credit')

    def test_quiet_emotional_exception_remains_inside_credits(self):
        raw=decision();raw['narrative_units'].append('U003')
        self.assertEqual(sequence_decision(raw,self.units,25)[0],{'U001','U002'})

    def test_title_or_object_label_cannot_establish_a_production_sequence(self):
        for anchor_type in ('episode_title','series_title'):
            raw=decision();raw['anchors'][0]['type']=anchor_type
            self.assertFalse(sequence_decision(raw,self.units,25)[0])
        raw=decision();raw['anchors'][0]['type']='product_label'
        with self.assertRaises(ValueError):sequence_decision(raw,self.units,25)

    def test_boundaries_need_immediate_outside_witnesses_and_anchor_inside(self):
        for key,value in (('before_unit','U002'),('after_unit','none'),('first_unit','U004'),('last_unit','invented')):
            raw=decision();raw[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):sequence_decision(raw,self.units,25)
        raw=decision();raw['anchors'][0]['unit']='U000'
        with self.assertRaises(ValueError):sequence_decision(raw,self.units,25)
        raw=decision();raw.update(first_unit='U000',before_unit='none')
        shifted=[{**u,'start':u['start']+30,'end':u['end']+30} for u in self.units]
        with self.assertRaises(ValueError):sequence_decision(raw,shifted,55)

    def test_original_clusters_do_not_expand_from_derived_labels(self):
        events=[{}, {'contains_credits':True}, {'credit_montage':True}, {}, {}, {'contains_credits':True}]
        self.assertEqual(original_clusters(events),[[1,2],[5]])

    def test_one_sequence_query_plus_independent_anchor_then_paid_checkpoint_reuse(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(credit_montage=True,contains_credits=True,summary='Credits')
        original=copy.deepcopy(event)
        vision=FakeVision([decision(),{'confirmed':True,'confidence':.95,'evidence':'Opening theme: Music'}])
        vision.model='test';vision.projector='test';vision.thinking=False
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(5)]
        with patch('app.production.sequence_sheet',return_value=[directory/'source-page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
            self.assertEqual(len(vision.calls),2)
            self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':5},{'start':20,'end':25}])
            self.assertFalse(result[0]['credit_montage'])
            replay=FakeVision([]);replay.model='test';replay.projector='test';replay.thinking=False
            same=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,replay,lambda *a:None,lambda:False)
            self.assertEqual(result,same);self.assertFalse(replay.calls)
        self.assertEqual(event,original)

    def test_failed_independent_anchor_restores_a_false_coarse_credit_window(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(credit_montage=True,contains_credits=True,summary='Quiet story')
        vision=FakeVision([decision(),{'confirmed':False,'confidence':.95,'evidence':'A product label'}])
        vision.model='test';vision.projector='test';vision.thinking=False
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(5)]
        with patch('app.production.sequence_sheet',return_value=[directory/'source-page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
        self.assertFalse(result[0]['credit_montage'])
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':25}])
        self.assertTrue(result[0]['story_warnings'])

