import copy
import json
import math
import unittest
from unittest.mock import patch

from app.production import confirmed_units
from app.production import clean_sequences
from app.story import clean_credit_continuations
from tests.test_story import edge_fixture, FakeVision


def answer(removed=('A',), narrative=(), ids=('A','B')):
    return {'anchors':[{'frame':'K0','visible_production_text':True,'confidence':.95,
                        'evidence':'Visible studio production-credit text'}],
            'decisions':[{'unit':u,'credit_montage':u in removed,'continuous_narrative':u in narrative,
                          'same_sequence':u in removed,'anchor':'K0' if u in removed else 'none',
                          'speech_role':'none','confidence':.95,
                          'evidence':'Character-introduction montage continuing the credit sequence' if u in removed
                                     else 'New causal action or quiet emotional consequence'} for u in ids]}


class ProductionTests(unittest.TestCase):
    def test_legacy_provider_dispatch_applies_confirmed_credit_unit_to_final_ranges(self):
        directory,event,_=edge_fixture(start=0,end=10)
        raw=answer(('A',),(),('A','B'))
        vision=FakeVision([raw])
        vision.model='test';vision.projector='test';vision.thinking=False
        shots=[{'start':0,'end':5},{'start':5,'end':10}]
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']):
            result=clean_sequences([event],{'segments':[],'words':[]},shots,directory,
                                   vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':5,'end':10}])
        self.assertEqual(len(vision.calls),1)
        self.assertEqual(vision.calls[0][2],1300)
        self.assertFalse(isinstance(vision.calls[0][1],list))

    def test_sequence_context_includes_earlier_credit_cards_without_cascade(self):
        from app.production import production_context
        events=[{'id':f'e{i}','start':i*20,'end':(i+1)*20} for i in range(5)]
        context,times=production_context(events,[1,2,3],2,[],{'segments':[],'words':[]})
        self.assertEqual(context['original_windows'],['e1','e2','e3'])
        self.assertEqual((context['start'],context['end']),(20,80))
        self.assertLess(min(times),40);self.assertGreater(max(times),60)
        # A gap in original production evidence stops expansion.
        context,_=production_context(events,[1,3],3,[],{'segments':[],'words':[]})
        self.assertEqual(context['original_windows'],['e3'])

    def test_sequence_context_image_work_is_bounded_without_moving_source_units(self):
        from app.production import production_context
        events=[{'id':'credit','start':0,'end':200}]
        shots=[{'start':t,'end':t+3} for t in range(0,200,3)]
        context,times=production_context(events,[0],0,shots,{'segments':[],'words':[]})
        self.assertEqual(len(times),36)
        self.assertEqual((context['start'],context['end']),(0,200))
        self.assertEqual(times,sorted(times))
        self.assertLess(times[0],3);self.assertGreater(times[-1],195)

    def test_image_pages_keep_chronology_and_do_not_shrink_a_tall_sheet(self):
        import cv2
        import numpy as np
        from PIL import Image
        from unittest.mock import Mock
        from app.production import sequence_sheet
        directory,_,source=edge_fixture()
        video=Mock()
        video.get.side_effect=lambda prop:30 if prop==cv2.CAP_PROP_FPS else 3000
        video.read.return_value=(True,np.zeros((90,160,3),dtype=np.uint8))
        units=[{'id':chr(65+i),'start':i*5,'end':i*5+5} for i in range(4)]
        with patch('app.production.cv2.VideoCapture',return_value=video):
            pages=sequence_sheet(source,units,list(range(20,37)),directory/'pages.jpg',lambda:False,page_size=12)
        self.assertEqual(len(pages),3)
        positions=[call.args[1] for call in video.set.call_args_list]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual(len(positions),29)
        for page in pages:
            with Image.open(page) as picture:
                self.assertLessEqual(picture.width*picture.height,1300*1300)

    def test_cloud_sequence_review_does_not_enable_paid_reasoning(self):
        from app.deepseek import DeepSeekVision
        directory,event,_=edge_fixture()
        vision=DeepSeekVision(directory,lambda:False,cache_only=True)
        with patch('app.production.clean_sequences',return_value=['reviewed']) as review:
            self.assertEqual(clean_credit_continuations([event],{},[],directory,vision,lambda *a:None,lambda:False),['reviewed'])
        self.assertIs(review.call_args.args[4],vision)
        self.assertFalse(vision.thinking)
        self.assertTrue(vision.cache_only)

    def test_readable_pages_keep_all_current_and_context_views_in_source_order(self):
        import cv2
        import numpy as np
        from PIL import Image
        from unittest.mock import Mock
        from app.production import sequence_sheet
        directory,_,source=edge_fixture()
        video=Mock()
        video.get.side_effect=lambda prop:30 if prop==cv2.CAP_PROP_FPS else 3000
        video.read.return_value=(True,np.zeros((720,1280,3),dtype=np.uint8))
        units=[{'id':chr(65+i),'start':i*5+1,'end':i*5+5} for i in range(4)]
        context=[0,6,16,22]
        draw=Mock()
        with patch('app.production.cv2.VideoCapture',return_value=video), patch('app.production.ImageDraw.Draw',return_value=draw):
            pages=sequence_sheet(source,units,context,directory/'readable.jpg',lambda:False,
                                 page_size=8,readable=True)
        self.assertEqual(len(pages),2)
        positions=[call.args[1]/1000 for call in video.set.call_args_list]
        expected=sorted(context+[u['start']+(u['end']-u['start'])*f for u in units for f in (.08,.5,.92)])
        self.assertEqual(positions,expected)
        labels=[call.args[1] for call in draw.text.call_args_list]
        self.assertEqual(len(labels),16)
        self.assertEqual(sum(label.startswith('CONTEXT K') for label in labels),4)
        for unit in units:
            self.assertEqual(sum(label.startswith('UNIT '+unit['id']+' |') for label in labels),3)
        for page in pages:
            with Image.open(page) as picture:
                self.assertEqual(picture.size,(960,1176))
                self.assertLessEqual(picture.width*picture.height,960*1632)

    def test_sequence_batches_bound_work_and_map_all_source_units(self):
        directory,event,_=edge_fixture(start=0,end=50)
        shots=[{'start':t,'end':t+5} for t in range(0,50,5)]
        vision=FakeVision([answer((),(),tuple('ABCD')),answer((),(),tuple('ABCD')),answer((),(),tuple('AB'))])
        result=self.review([event],{'words':[],'segments':[]},shots,directory,vision)
        rows=[json.loads(call[0].split('Actual rows: ')[1].rstrip('.')) for call in vision.calls]
        self.assertEqual([len(batch) for batch in rows],[4,4,2])
        self.assertEqual([(u['start'],u['end']) for batch in rows for u in batch],[(t,t+5) for t in range(0,50,5)])
        self.assertTrue(all(call[2]<=2048 for call in vision.calls))
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])

    def test_context_after_target_is_physically_drawn_after_target(self):
        import cv2
        import numpy as np
        from unittest.mock import Mock
        from app.production import sequence_sheet
        directory,_,source=edge_fixture()
        video=Mock()
        video.get.side_effect=lambda prop: 30 if prop==cv2.CAP_PROP_FPS else 3000
        video.read.return_value=(True,np.zeros((90,160,3),dtype=np.uint8))
        with patch('app.production.cv2.VideoCapture',return_value=video):
            sequence_sheet(source,[{'id':'A','start':5,'end':10}], [20,1,15], directory/'chronology.jpg', lambda:False)
        positions=[call.args[1] for call in video.set.call_args_list]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual([round(t) for t in positions],[1000,5400,7500,9600,15000,20000])
        video.release.assert_called_once()

    def review(self, events, transcript, shots, directory, vision, cancelled=lambda:False):
        with patch('app.production.sequence_sheet'):
            return clean_credit_continuations(events, transcript, shots, directory, vision, lambda *a:None, cancelled)

    def test_text_free_opening_motion_removed_but_quiet_story_preserved(self):
        units=[{'id':'A'}, {'id':'B'}]
        raw=answer(removed=('A','B'), narrative=('B',))
        self.assertEqual(confirmed_units(raw,units,{'K0'}),{'A'})
        raw['anchors'][0]['visible_production_text']=False
        self.assertEqual(confirmed_units(raw,units,{'K0'}),set())

    def test_adjacency_or_unconfirmed_anchor_cannot_authorize_deletion(self):
        raw=answer(); units=[{'id':'A'}, {'id':'B'}]
        for change in ('same_sequence','anchor_confidence','missing_anchor'):
            value=copy.deepcopy(raw)
            if change=='same_sequence': value['decisions'][0]['same_sequence']=False
            elif change=='anchor_confidence': value['anchors'][0]['confidence']=.8
            else: value['anchors']=[]
            self.assertEqual(confirmed_units(value,units,{'K0'}),set())

    def test_unknown_duplicate_incomplete_or_malformed_response_rejected(self):
        units=[{'id':'A'}, {'id':'B'}]
        bad=[]
        for key,value in [('unit','invented'),('continuous_narrative','false'),('confidence',math.nan),
                          ('same_sequence',1),('evidence',''),('speech_role','invented'),('anchor','K99')]:
            raw=answer(); raw['decisions'][0][key]=value; bad.append(raw)
        raw=answer();raw['decisions'].pop();bad.append(raw)
        raw=answer();raw['decisions'][1]['unit']='A';bad.append(raw)
        raw=answer();raw['anchors'].append(copy.deepcopy(raw['anchors'][0]));bad.append(raw)
        raw=answer();raw['anchors'][0]['frame']='unknown';bad.append(raw)
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError): confirmed_units(raw,units,{'K0'})

    def test_mixed_sequence_uses_one_batch_and_preserves_actual_scene(self):
        directory, event, _=edge_fixture()
        original=copy.deepcopy(event)
        vision=FakeVision([answer(('A','B'),('C',),('A','B','C'))])
        result=self.review([event],{'segments':[],'words':[]},[{'start':10,'end':15},{'start':15,'end':20}],directory,vision)
        self.assertEqual(result[0]['selected_ranges'],[{'start':15,'end':20}])
        self.assertEqual(result[0]['excluded_credit_units'],['u000','u001'])
        self.assertEqual(len(vision.calls),1)
        self.assertIn('SEQUENCE CONTEXT',vision.calls[0][0])
        self.assertEqual(event,original)

    def test_preceding_mixed_window_is_reviewed_without_cascading(self):
        directory,event,_=edge_fixture(start=0,end=10)
        event.pop('contains_credits')
        opening={**event,'id':'opening','start':10,'end':20,'kind':'opening','credit_montage':True,'contains_credits':True}
        later={**event,'id':'later','start':20,'end':30,'selected_ranges':[{'start':20,'end':30}]}
        unrelated={**event,'id':'unrelated','start':30,'end':40,'selected_ranges':[{'start':30,'end':40}]}
        vision=FakeVision([answer(('A',),(),('A',)),answer(('A',),(),('A',)),answer((),('A',),('A',))])
        result=self.review([event,opening,later,unrelated],{'words':[],'segments':[]},[],directory,vision)
        self.assertTrue(result[0]['credit_montage'])
        self.assertEqual(result[2]['selected_ranges'],later['selected_ranges'])
        self.assertEqual(result[3],unrelated)
        self.assertEqual(len(vision.calls),3)

    def test_question_answer_and_long_confident_dialogue_not_sent_for_deletion(self):
        directory,event,_=edge_fixture(start=0,end=10,kind='ending')
        transcript={'segments':[{'start':1,'end':3,'text':'Придёшь?'},{'start':4,'end':6,'text':'Да.'}],
                    'words':[{'start':1,'end':3,'text':'Придёшь?','probability':.9},
                             {'start':4,'end':6,'text':'Да.','probability':.9}]}
        vision=FakeVision([answer((),('A',),('A',))])
        result=self.review([event],transcript,[],directory,vision)
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])
        rows=json.loads(vision.calls[0][0].split('Actual rows: ')[1].rstrip('.'))
        self.assertEqual([(u['start'],u['end']) for u in rows],[(6,10)])

    def test_short_character_or_unknown_speech_kept_even_if_model_marks_credit(self):
        for role,removed in [('character',False),('uncertain',False),('none',False),('title_narration',True)]:
            directory,event,_=edge_fixture(start=0,end=10,kind='ending')
            transcript={'segments':[{'start':0,'end':5,'text':'Я вернулся.'}],
                        'words':[{'start':0,'end':5,'text':'Вернулся.','probability':.9}]}
            raw=answer(('A',),('B',));raw['decisions'][0]['speech_role']=role
            result=self.review([event],transcript,[],directory,FakeVision([raw]))
            self.assertEqual(result[0]['selected_ranges'],[{'start':5,'end':10}] if removed else event['selected_ranges'])

    def test_false_pure_credit_hint_cannot_remove_quiet_emotional_payoff(self):
        directory,event,_=edge_fixture(kind='ending')
        event.update(credit_montage=True,kind='ending',importance=1)
        raw=answer((),('A','B'))
        result=self.review([event],{'words':[],'segments':[]},[{'start':10,'end':20}],directory,FakeVision([raw]))
        self.assertFalse(result[0]['credit_montage'])
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])
        self.assertEqual(result[0]['importance'],4)
        result=self.review([event],{'words':[],'segments':[]},[],directory,FakeVision([{'anchors':[],'decisions':[]}]))
        self.assertFalse(result[0]['credit_montage'])
        self.assertTrue(result[0]['selection_uncertain'])

    def test_no_source_or_bad_batch_preserves_source(self):
        directory,event,_=edge_fixture()
        vision=FakeVision([{'anchors':[],'decisions':[]}])
        result=self.review([event],{'words':[],'segments':[]},[],directory,vision)
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])
        self.assertTrue(result[0]['story_warnings'])
        (directory/'source.json').unlink()
        vision=FakeVision([])
        result=self.review([event],{'words':[],'segments':[]},[],directory,vision)
        self.assertEqual(result[0]['selected_ranges'],event['selected_ranges'])
        self.assertFalse(vision.calls)

    def test_cache_and_source_model_thinking_invalidation(self):
        directory,event,source=edge_fixture(kind='ending')
        model=directory/'model.gguf';model.write_bytes(b'first')
        vision=FakeVision([answer()]);vision.model=model
        first=self.review([event],{'words':[],'segments':[]},[{'start':10,'end':20}],directory,vision)
        cached=FakeVision([]);cached.model=model
        self.assertEqual(first,self.review([event],{'words':[],'segments':[]},[{'start':10,'end':20}],directory,cached))
        self.assertFalse(cached.calls)
        for change in ('source','model','thinking'):
            if change=='source':source.write_bytes(b'changed actual source')
            elif change=='model':model.write_bytes(b'changed model')
            vision=FakeVision([answer()]);vision.model=model;vision.thinking=change=='thinking'
            self.review([event],{'words':[],'segments':[]},[{'start':10,'end':20}],directory,vision)
            self.assertEqual(len(vision.calls),1)

    def test_cancel_after_response_does_not_publish_checkpoint_or_mutation(self):
        directory,event,_=edge_fixture(kind='ending');original=copy.deepcopy(event)
        vision=FakeVision([answer()])
        with self.assertRaises(InterruptedError):
            self.review([event],{'words':[],'segments':[]},[{'start':10,'end':20}],directory,vision,lambda:bool(vision.calls))
        self.assertEqual(event,original)
        self.assertFalse(list((directory/'credit_edges').glob('*.json')))
