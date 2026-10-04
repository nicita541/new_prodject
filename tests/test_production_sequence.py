import copy
import json
import unittest
from unittest.mock import patch

from app.production_sequence import (sequence_decision, verify_boundaries, verify_exceptions,
                                    clean_whole_sequences, original_clusters)
from app.production import clean_sequences
from app.planner import build_plan
from app.analysis import derived_story_identity
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

    def test_independent_boundary_review_corrects_familiar_character_false_ending(self):
        initial=decision()
        initial.update(last_unit='U002',after_unit='U003',
                       boundary_evidence='A familiar character appears outside the staff card.')
        reviewed=decision()
        reviewed.update(last_unit='U003',after_unit='U004',
                        narrative_units=['U000','U003','U004'],
                        boundary_evidence='The following familiar-character portraits remain part of the musical OP.')
        class Vision:
            def query(self,*args,**kwargs): return reviewed
        corrected=verify_boundaries(initial,self.units,['original full pages'],Vision(),25)
        self.assertEqual(corrected['last_unit'],'U003')
        self.assertEqual(corrected['after_unit'],'U004')
        self.assertEqual(sequence_decision(corrected,self.units,25)[0],{'U001','U002'})
        self.assertIn('U003',corrected['narrative_units'])

    def test_boundary_disagreement_and_malformed_second_review_fail_closed(self):
        initial=decision()
        class Vision:
            def __init__(self,answer): self.answer=answer
            def query(self,*args,**kwargs): return self.answer
        different_kind=decision();different_kind['kind']='ending'
        uncertain=verify_boundaries(initial,self.units,['pages'],Vision(different_kind),25)
        self.assertEqual(uncertain['kind'],'uncertain')
        malformed={**decision(),'last_unit':'invented'}
        with self.assertRaises(ValueError):
            verify_boundaries(initial,self.units,['pages'],Vision(malformed),25)

    def test_verified_current_story_is_a_mandatory_mixed_sequence_exception(self):
        raw=decision()
        units=[{**unit,'verified_current_story':unit['id']=='U002'} for unit in self.units]
        class Vision:
            def __init__(self): self.calls=0
            def query(self,*args,**kwargs): self.calls+=1; raise AssertionError('verified unit needs no paid/model review')
        vision=Vision()
        reviewed=verify_exceptions(raw,units,['full-pages'],vision,transcript={'words':[],'segments':[]})
        self.assertIn('U002',reviewed['narrative_units'])
        self.assertNotIn('U002',sequence_decision(reviewed,units,25)[0])
        self.assertEqual(vision.calls,0)

    def test_one_sequence_query_plus_independent_anchor_then_paid_checkpoint_reuse(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(credit_montage=True,contains_credits=True,summary='Credits')
        original=copy.deepcopy(event)
        vision=FakeVision([decision(),decision(),{'confirmed':True,'confidence':.95,'evidence':'Opening theme: Music'}])
        vision.model='test';vision.projector='test';vision.thinking=False
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(5)]
        with patch('app.production.sequence_sheet',return_value=[directory/'source-page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
            self.assertEqual(len(vision.calls),3)
            self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':5},{'start':20,'end':25}])
            self.assertFalse(result[0]['credit_montage'])
            replay=FakeVision([]);replay.model='test';replay.projector='test';replay.thinking=False
            same=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,replay,lambda *a:None,lambda:False)
            self.assertEqual(result,same);self.assertFalse(replay.calls)
        self.assertEqual(event,original)

    def test_failed_independent_anchor_restores_a_false_coarse_credit_window(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(credit_montage=True,contains_credits=True,summary='Quiet story')
        vision=FakeVision([decision(),decision(),{'confirmed':False,'confidence':.95,'evidence':'A product label'}])
        vision.model='test';vision.projector='test';vision.thinking=False
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(5)]
        with patch('app.production.sequence_sheet',return_value=[directory/'source-page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
        self.assertFalse(result[0]['credit_montage'])
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':25}])
        self.assertTrue(result[0]['story_warnings'])

    def test_overlapping_clusters_keep_both_confirmed_exclusions_through_planning(self):
        directory, base, _ = edge_fixture(start=0, end=70)
        events = [{**copy.deepcopy(base), 'id': f'event_{i:04d}',
                   'start': i * 10, 'end': (i + 1) * 10, 'focus': [],
                   'selected_ranges': [{'start': i * 10, 'end': (i + 1) * 10}],
                   'credit_montage': False, 'credit_dialogue_rescued': i == 2,
                   'contains_credits': i in (0, 4)} for i in range(7)]

        def sequence(first, before, after):
            return {'kind': 'opening', 'first_unit': f'U{first:03d}',
                    'last_unit': f'U{first:03d}', 'before_unit': f'U{before:03d}',
                    'after_unit': f'U{after:03d}',
                    'anchors': [{'unit': f'U{first:03d}', 'type': 'theme_credit',
                                 'visible_text': 'Theme music'}],
                    'narrative_units': [], 'confidence': .95,
                    'boundary_evidence': 'Theme between chronological story scenes.'}

        anchor = {'confirmed': True, 'confidence': .95, 'evidence': 'Visible credit.'}
        # Original clusters at events 0 and 4 have contexts [0,2] and [2,6].
        # Their only shared event contains two independently confirmed cuts.
        vision = FakeVision([sequence(4, 3, 5), sequence(4, 3, 5), anchor,
                             sequence(1, 0, 2), sequence(1, 0, 2), anchor])
        vision.model = vision.projector = 'test'
        vision.thinking = False
        vision.supports_image_pages = True
        shots = [{'start': i * 5, 'end': (i + 1) * 5} for i in range(14)]
        transcript = {'words': [], 'segments': []}

        with patch('app.production.sequence_sheet', return_value=[directory / 'page.jpg']):
            output = clean_sequences(events, transcript, shots, directory, vision,
                                     lambda *a: None, lambda: False)

        plan = build_plan({'probe': {'duration': 70, 'width': 1920, 'height': 1080,
                                     'has_audio': True},
                           'events': output, 'transcript': transcript, 'shots': shots})
        cuts = [(cut['start'], cut['end']) for part in plan['parts'] for cut in part['cuts']]
        self.assertEqual(cuts, [(0.0, 20), (30, 70)])
        self.assertTrue(all(end <= 20 or start >= 30 for start, end in cuts))

    def test_story_identity_tracks_sequence_version_provider_capability_and_editorial_policy(self):
        from app.production_sequence import VERSION

        base = derived_story_identity('analysis-key', 'local')
        self.assertEqual(base['production_sequence'], VERSION)
        self.assertEqual(base['credit_capability'], 'single-image')
        for provider, capability in [('deepseek', 'image-pages'), ('deepseek_plan', 'image-pages'),
                                     ('hybrid', 'single-image')]:
            with self.subTest(provider=provider):
                self.assertEqual(derived_story_identity('analysis-key', provider)['credit_capability'], capability)
        self.assertNotEqual(base, derived_story_identity('analysis-key', 'local', 'strict-plot-v1'))
        with patch('app.production_sequence.VERSION', VERSION + 1):
            bumped = derived_story_identity('analysis-key', 'local')
        self.assertEqual(bumped['edge'], base['edge'])
        self.assertNotEqual(bumped['production_sequence'], base['production_sequence'])

