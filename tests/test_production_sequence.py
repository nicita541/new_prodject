import copy
import json
import unittest
from unittest.mock import patch

from app.production_sequence import (boundary_units, sequence_decision, verify_boundaries, verify_exceptions,
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

    def test_sequence_units_keep_reply_tail_before_actual_opening_shot(self):
        from app.production_sequence import sequence_units
        transcript={'segments':[{'start':83.7,'end':84.62,'text':'Понимаю.'}],
                    'words':[{'start':83.7,'end':84.62,'text':'Понимаю.'}]}
        units=sequence_units(77.37,100,transcript,[{'start':88.005,'end':100}])
        self.assertAlmostEqual(units[0]['end'],85.17)
        self.assertEqual(units[0]['text'],'Понимаю.')
        self.assertEqual(units[1]['end'],88.005)
        self.assertEqual(units[2]['start'],88.005)
        self.assertEqual(transcript['segments'][0]['end'],84.62)

    def test_sequence_speech_tail_stops_before_next_reply_and_no_speech_keeps_shots(self):
        from app.production_sequence import sequence_units
        transcript={'segments':[{'start':3,'end':5,'text':'Первый.'},
                                 {'start':5.2,'end':8,'text':'Ответ.'}],
                    'words':[{'start':3,'end':5,'text':'Первый.'},
                             {'start':5.2,'end':8,'text':'Ответ.'}]}
        units=sequence_units(0,15,transcript,[])
        self.assertAlmostEqual(units[0]['end'],5.16)
        self.assertAlmostEqual(units[1]['end'],8.55)
        self.assertEqual(sequence_units(0,15,{'segments':[],'words':[]},
            [{'start':5,'end':10},{'start':10,'end':15}]),
            [{'id':'u000','start':0,'end':5.,'text':''},
             {'id':'u001','start':5.,'end':10.,'text':''},
             {'id':'u002','start':10.,'end':15,'text':''}])

    def test_real_opening_boundary_does_not_clip_preceding_story_word(self):
        directory,event,_=edge_fixture(start=0,end=100)
        event.update(kind='story',importance=4,selected_ranges=[{'start':0,'end':84.62}])
        transcript={'segments':[{'start':83.7,'end':84.62,'text':'Понимаю.'}],
                    'words':[{'start':83.7,'end':84.62,'text':'Понимаю.'}]}
        shots=[{'start':88.005,'end':100}]
        raw=decision()
        raw.update(first_unit='U002',last_unit='U002',before_unit='U001',after_unit='none',
                   narrative_units=['U000','U001'],anchors=[{'unit':'U002','type':'theme_credit',
                   'visible_text':'Opening theme'}])
        vision=FakeVision([raw,raw,{'confirmed':True,'confidence':.95,'evidence':'Visible theme credit'}])
        vision.model=vision.projector='test';vision.thinking=False
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']):
            events=clean_whole_sequences([event],transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(events[0]['confirmed_opening_ranges'],[{'start':88.005,'end':100.}])
        plan=build_plan({'probe':{'duration':100,'width':1920,'height':1080,'has_audio':True},
                         'events':events,'transcript':transcript,'shots':shots})
        self.assertAlmostEqual(plan['parts'][0]['cuts'][-1]['end'],85.17)
        self.assertFalse(any(c['end']>88.005 for p in plan['parts'] for c in p['cuts']))

    def test_text_free_middle_and_tail_belong_to_one_sequence(self):
        excluded,anchors=sequence_decision(decision(),self.units,25)
        self.assertEqual(excluded,{'U001','U002','U003'})
        self.assertEqual(anchors[0]['type'],'theme_credit')

    def test_quiet_emotional_exception_remains_inside_ending_credits(self):
        raw=decision();raw['kind']='ending';raw['narrative_units'].append('U003')
        self.assertEqual(sequence_decision(raw,self.units,25)[0],{'U001','U002'})

    def test_low_confidence_wrong_kind_gets_dense_review_and_pure_ending_outranks_reaction_rescue(self):
        from app.source_roles import verified_story_ranges,apply_exclusions
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(contains_credits=True,credit_montage=True,
                     verified_current_story_ranges=[{'start':0,'end':25}],
                     protected_atmosphere_ranges=[{'start':5,'end':20}])
        first=decision();first['confidence']=.72
        first['anchors'].append({'unit':'U004','type':'episode_title','visible_text':'Episode title'})
        final=decision();final.update(kind='ending',wholly_nonstory=True)
        vision=FakeVision([first,final,{'confirmed':True,'confidence':.95,'evidence':'Visible staff credits'}])
        vision.model=vision.projector='test';vision.thinking=False;vision.supports_image_pages=True
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']) as sheets:
            result=clean_whole_sequences([event],{'words':[],'segments':[]},
                [{'start':i*5,'end':(i+1)*5} for i in range(5)],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(len(vision.calls),3)
        self.assertEqual(sheets.call_count,3)
        self.assertEqual(result[0]['confirmed_nonstory_ending_ranges'],[{'start':5.,'end':20.}])
        self.assertEqual(verified_story_ranges(result[0]),[{'start':0.,'end':5.},{'start':20.,'end':25.}])
        loaded=json.loads(json.dumps(result))
        loaded[0]['selected_ranges']=[{'start':0,'end':25}]
        loaded=apply_exclusions(loaded)
        self.assertEqual(loaded[0]['selected_ranges'],[{'start':0.,'end':5.},{'start':20.,'end':25.}])
        plan=build_plan({'probe':{'duration':25,'width':1920,'height':1080,'has_audio':True},
                         'events':loaded,'transcript':{'words':[],'segments':[]},'shots':[]})
        cuts=[(c['start'],c['end']) for part in plan['parts'] for c in part['cuts']]
        self.assertTrue(cuts)
        self.assertTrue(all(end<=5 or start>=20 for start,end in cuts))

    def test_low_confidence_production_candidate_still_retains_when_dense_review_is_uncertain(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(contains_credits=True,credit_montage=True)
        first={**decision(),'confidence':.72}
        uncertain={**decision(),'kind':'uncertain','confidence':.7}
        vision=FakeVision([first,uncertain])
        vision.model=vision.projector='test';vision.thinking=False
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},
                [{'start':i*5,'end':(i+1)*5} for i in range(5)],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(len(vision.calls),2)
        self.assertFalse(result[0].get('confirmed_nonstory_ending_ranges'))
        self.assertFalse(result[0].get('excluded_credit_ranges'))

    def test_pure_ending_cannot_claim_an_interleaved_episode_story_exception(self):
        raw=decision();raw.update(kind='ending',wholly_nonstory=True,narrative_units=['U003'])
        with self.assertRaises(ValueError):sequence_decision(raw,self.units,25)

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
            def __init__(self): self.pages=None
            def query(self,prompt,pages,**kwargs): self.pages=pages; return reviewed
        vision=Vision()
        corrected=verify_boundaries(initial,self.units,['original full pages'],vision,25,
                                     boundary_pages=['dense before/current/after pages'])
        self.assertEqual(vision.pages,['dense before/current/after pages'])
        self.assertEqual(corrected['last_unit'],'U003')
        self.assertEqual(corrected['after_unit'],'U004')
        self.assertEqual(sequence_decision(corrected,self.units,25)[0],{'U001','U002','U003'})
        self.assertIn('U003',corrected['narrative_units'])

    def test_dense_boundary_selection_includes_early_and_late_neighbors(self):
        units=[{'id':f'U{i:03}','start':i,'end':i+1} for i in range(20)]
        selected=boundary_units({'first_unit':'U004','last_unit':'U010'},units)
        ids=[unit['id'] for unit in selected]
        self.assertEqual(ids, [*(f'U{i:03}' for i in range(2,7)),
                              *(f'U{i:03}' for i in range(8,19))])

    def test_anchor_review_reads_early_middle_late_without_lowering_confirmation_threshold(self):
        from app.production_sequence import verify_anchors
        directory,_,source=edge_fixture()
        anchors=decision()['anchors']
        vision=FakeVision([{'confirmed':True,'confidence':.84,'evidence':'A difficult visible theme card.'}])
        vision.supports_image_pages=True
        with patch('app.production.sequence_sheet',return_value=[directory/'anchor.jpg']) as sheet:
            self.assertFalse(verify_anchors(anchors,self.units,source,directory,'anchor',vision,lambda:False))
        self.assertEqual(sheet.call_args.args[1],[self.units[2]])
        self.assertEqual(sheet.call_args.args[2],[])
        self.assertEqual(sheet.call_args.kwargs,{'page_size':8,'readable':True})
        self.assertEqual(vision.calls[0][1],[directory/'anchor.jpg'])

    def test_readable_boundary_pages_fit_eight_page_cap_without_dropping_units(self):
        import math
        directory,event,_=edge_fixture(start=0,end=230)
        event.update(contains_credits=True,credit_montage=True)
        raw=decision()
        raw.update(first_unit='U004',last_unit='U010',before_unit='U003',after_unit='U011',
                   anchors=[{'unit':'U006','type':'theme_credit','visible_text':'Opening theme'}],
                   narrative_units=[])
        vision=FakeVision([raw,raw,{'confirmed':True,'confidence':.95,'evidence':'Visible theme credit'}])
        vision.model='test';vision.projector='test';vision.thinking=False;vision.supports_image_pages=True
        captured=[]
        def sheet(source,units,times,path,cancelled,**kwargs):
            captured.append((units,times,kwargs))
            count=math.ceil((len(units)*3+len(times))/kwargs['page_size'])
            return [directory/f'{path.stem}-{i}.jpg' for i in range(count)]
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(46)]
        with patch('app.production.sequence_sheet',side_effect=sheet):
            clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(len(captured[0][1]),46)
        self.assertEqual([u['id'] for u in captured[1][0]],
                         [*(f'U{i:03}' for i in range(2,7)),*(f'U{i:03}' for i in range(8,19))])
        self.assertEqual(captured[1][2],{'page_size':8,'readable':True})
        self.assertEqual(len(vision.calls[1][1]),6)
        self.assertLessEqual(len(vision.calls[1][1]),8)

    def test_large_overview_is_not_resent_for_independent_boundary_review(self):
        import math
        directory,event,_=edge_fixture(start=0,end=480)
        event.update(contains_credits=True,credit_montage=True)
        raw=decision()
        raw.update(first_unit='U004',last_unit='U010',before_unit='U003',after_unit='U011',
                   anchors=[{'unit':'U006','type':'theme_credit','visible_text':'Opening theme'}],
                   narrative_units=[])
        vision=FakeVision([raw,raw,{'confirmed':True,'confidence':.95,'evidence':'Visible theme credit'}])
        vision.model='test';vision.projector='test';vision.thinking=False;vision.supports_image_pages=True
        captured=[]
        def sheet(source,units,times,path,cancelled,**kwargs):
            captured.append((units,times,kwargs))
            return [directory/f'{path.stem}-{i}.jpg' for i in range(
                math.ceil((len(units)*3+len(times))/kwargs['page_size']))]
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(96)]
        with patch('app.production.sequence_sheet',side_effect=sheet):
            clean_whole_sequences([event],{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(len(captured[0][1]),96)
        self.assertEqual(len(captured[1][0]),16)
        self.assertEqual(captured[1][2],{'page_size':8,'readable':True})
        self.assertEqual(len(vision.calls[1][1]),6)

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

    def test_verified_current_story_is_a_mandatory_mixed_ending_exception(self):
        raw=decision();raw['kind']='ending'
        units=[{**unit,'verified_current_story':unit['id']=='U002'} for unit in self.units]
        class Vision:
            def __init__(self): self.calls=0
            def query(self,*args,**kwargs): self.calls+=1; raise AssertionError('verified unit needs no paid/model review')
        vision=Vision()
        reviewed=verify_exceptions(raw,units,['full-pages'],vision,transcript={'words':[],'segments':[]})
        self.assertIn('U002',reviewed['narrative_units'])
        self.assertNotIn('U002',sequence_decision(reviewed,units,25)[0])
        self.assertEqual(vision.calls,0)

    def test_confirmed_whole_opening_outranks_action_reaction_speech_and_later_story_guards(self):
        from app.source_roles import apply_exclusions,verified_story_ranges,confirmed_exclusions
        from app.story import preserve_dialogue_in_credits
        from app.story_review import apply_global_selection
        from app.pacing import apply_review
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(contains_credits=True,credit_montage=True,
                     verified_current_story_ranges=[{'start':0,'end':25}],
                     protected_atmosphere_ranges=[{'start':5,'end':19}])
        text='A familiar character performs a plausible action and replies'
        transcript={'segments':[{'start':6,'end':19,'text':text}],
                    'words':[{'start':6+i,'end':6+i+.8,'text':w,'probability':.98}
                             for i,w in enumerate(text.split())]}
        shots=[{'start':i*5,'end':(i+1)*5} for i in range(5)]
        raw=decision()
        raw.update(first_unit='U001',last_unit='U001',before_unit='U000',after_unit='U002',
                   narrative_units=['U000','U001','U002'],
                   anchors=[{'unit':'U001','type':'theme_credit','visible_text':'Opening theme'}])
        vision=FakeVision([raw,raw,{'confirmed':True,'confidence':.95,'evidence':'Visible opening theme'}])
        vision.model=vision.projector='test';vision.thinking=False
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']):
            output=clean_whole_sequences([event],transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(len(vision.calls),3)
        loaded=json.loads(json.dumps(output))
        # Sequence units include the same acoustic tail as the final planner.
        boundary=19.55
        self.assertEqual(verified_story_ranges(loaded[0]),[{'start':0.,'end':5.},{'start':boundary,'end':25.}])
        self.assertEqual(confirmed_exclusions(loaded[0]),[{'start':5.,'end':boundary}])
        loaded=preserve_dialogue_in_credits(loaded,transcript)
        # Later guards may re-propose a plausible reaction; final ownership
        # still cuts only the confirmed interior and keeps both outside scenes.
        loaded[0]['selected_ranges']=[{'start':0,'end':25}]
        apply_review(loaded[0],[{'id':'A','start':5,'end':19}],
                     {'uncertain':False,'decisions':[{'unit':'A','keep':True,
                       'reason':'reaction','reaction_or_humor':True,'story_change':True}]})
        apply_global_selection(loaded,{'keep':[event['id']],'omit':[],'dependencies':[], 'summary':'Story'})
        loaded=apply_exclusions(loaded)
        self.assertEqual(loaded[0]['selected_ranges'],[{'start':0.,'end':5.},{'start':boundary,'end':25.}])
        plan=build_plan({'probe':{'duration':25,'width':1920,'height':1080,'has_audio':True},
                         'events':loaded,'transcript':transcript,'shots':shots})
        cuts=[(c['start'],c['end']) for part in plan['parts'] for c in part['cuts']]
        self.assertTrue(cuts)
        self.assertTrue(all(end<=5 or start>=boundary for start,end in cuts))

    def test_uncertain_opening_boundaries_do_not_create_whole_opening_authority(self):
        directory,event,_=edge_fixture(start=0,end=25)
        event.update(contains_credits=True,credit_montage=True,
                     verified_current_story_ranges=[{'start':10,'end':15}])
        uncertain={**decision(),'kind':'uncertain','confidence':.7}
        vision=FakeVision([decision(),uncertain])
        vision.model=vision.projector='test';vision.thinking=False
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']):
            result=clean_whole_sequences([event],{'words':[],'segments':[]},
                [{'start':i*5,'end':(i+1)*5} for i in range(5)],directory,vision,lambda *a:None,lambda:False)
        self.assertFalse(result[0].get('confirmed_opening_ranges'))
        self.assertFalse(result[0].get('excluded_credit_ranges'))
        self.assertEqual(result[0]['verified_current_story_ranges'],[{'start':10,'end':15}])

    def test_typical_ninety_seconds_is_not_a_hard_opening_duration(self):
        from app.production_sequence import sequence_prompt
        self.assertIn('never derive a boundary from that duration',sequence_prompt(self.units))
        for duration in (60,110):
            units=[{'id':f'U{i:03}','start':i*duration/3,'end':(i+1)*duration/3,'text':''}
                   for i in range(3)]
            raw={**decision(),'first_unit':'U000','last_unit':'U002',
                 'before_unit':'none','after_unit':'none','narrative_units':[],
                 'anchors':[{'unit':'U001','type':'theme_credit','visible_text':'Opening theme'}]}
            self.assertEqual(sequence_decision(raw,units,duration)[0],{'U000','U001','U002'})

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

    def test_distant_clusters_use_local_source_context_and_keep_both_exclusions(self):
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
        # Actual five-second neighborhoods are 0..15 and35..55. The second
        # target must not borrow the first target's distant list context.
        vision = FakeVision([sequence(1, 0, 2), sequence(1, 0, 2), anchor,
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
        self.assertEqual(cuts, [(0.0, 5), (10, 40), (45, 70)])
        self.assertTrue(all(end <= 5 or start >= 10 and end <= 40 or start >= 45 for start, end in cuts))

    def test_story_identity_tracks_sequence_version_provider_capability_and_editorial_policy(self):
        from app.production_sequence import VERSION

        base = derived_story_identity('analysis-key', 'local')
        self.assertEqual(base['production_sequence'], VERSION)
        self.assertEqual(base['credit_capability'], 'image-pages')
        for provider, capability in [('deepseek', 'image-pages'), ('deepseek_plan', 'image-pages'),
                                     ('hybrid', 'single-image')]:
            with self.subTest(provider=provider):
                self.assertEqual(derived_story_identity('analysis-key', provider)['credit_capability'], capability)
        self.assertNotEqual(base, derived_story_identity('analysis-key', 'local', 'strict-plot-v1'))
        with patch('app.production_sequence.VERSION', VERSION + 1):
            bumped = derived_story_identity('analysis-key', 'local')
        self.assertEqual(bumped['edge'], base['edge'])
        self.assertNotEqual(bumped['production_sequence'], base['production_sequence'])

    def test_sequence_clusters_requires_a_concrete_hint_not_position_or_silence(self):
        from app.production_sequence import sequence_clusters
        events = [{'id': f'e_{i}', 'start': i * 40, 'end': (i + 1) * 40} for i in range(36)]
        # Total duration: 36 * 40 = 1440s (~24 min anime)
        transcript = {
            'words': [
                {'start': 500, 'end': 502, 'text': 'Привет', 'probability': 0.9},
            ]
        }
        clusters = sequence_clusters(events, transcript, duration=1440)
        flat_indices = [idx for group in clusters for idx in group]
        self.assertEqual(flat_indices, [])
        events[10]['contains_credits'] = True
        self.assertEqual(sequence_clusters(events,transcript,duration=1440),[[10]])
        # All groups must be bounded to <= 4
        for group in clusters:
            self.assertLessEqual(len(group), 4)

    def test_protected_speech_ignores_dub_credits_and_title_narration(self):
        from app.story import _protected_speech
        unit = {'id': 'U001', 'start': 10.0, 'end': 20.0}
        # Dub intro text
        dub_transcript = {
            'segments': [{'start': 10.0, 'end': 19.5, 'text': 'Аниме переведено и озвучено творческим объединением Studio Band специально для...'}]
        }
        dub_words = [{'start': 10.0 + i * 0.5, 'end': 10.4 + i * 0.5, 'text': w, 'probability': 0.95}
                     for i, w in enumerate(dub_transcript['segments'][0]['text'].split())]
        dub_transcript['words'] = dub_words
        self.assertFalse(_protected_speech(unit, dub_transcript))

        # Genuine character dialogue
        story_transcript = {
            'segments': [{'start': 10.0, 'end': 19.5, 'text': 'Ты действительно думаешь, что мы сможем добраться до дома до заката солнца?'}]
        }
        story_words = [{'start': 10.0 + i * 0.5, 'end': 10.4 + i * 0.5, 'text': w, 'probability': 0.95}
                       for i, w in enumerate(story_transcript['segments'][0]['text'].split())]
        story_transcript['words'] = story_words
        self.assertTrue(_protected_speech(unit, story_transcript))

