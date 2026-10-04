import copy
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

from app.config import TEMP
from app.pacing import silent_units, apply_review, refine_pacing, BudgetPacingVision, retained_context, neighboring_replies


class PacingTests(unittest.TestCase):
    def test_cancel_during_frame_read_is_not_swallowed_as_preserve_warning(self):
        from pathlib import Path
        directory=TEMP/('pacing_cancel_'+uuid.uuid4().hex);directory.mkdir()
        source=directory/'source.mp4';source.write_bytes(b'fixture')
        events=[{'id':'one','start':0,'end':10,'kind':'story','importance':4,'requires':[],
                 'summary':'A silent action','selected_ranges':[{'start':0,'end':10}]}]
        vision=Mock(model=Path('model'),projector=Path('profile'),cache_profile='fixture')
        with patch('app.pacing.make_sheet',side_effect=InterruptedError('cancel')):
            with self.assertRaises(InterruptedError):
                refine_pacing(source,events,{'words':[],'segments':[]},[],directory,vision,lambda *a:None,lambda:False)
        vision.query.assert_not_called()
        self.assertFalse(list((directory/'pacing').glob('*.json')))

    def test_silent_emotional_consequence_survives_waiting_label(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        apply_review(event,[{'id':'A','start':1,'end':3}],
            {'decisions':[{'unit':'A','keep':False,'reason':'waiting','story_change':True,
                           'evidence':'Unmoving reaction conveys the consequence of the preceding event'}],
             'uncertain':False})
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':4}])
        self.assertNotIn('pacing_excluded',event)

    def test_neutral_scenery_can_be_removed_but_story_change_is_protected(self):
        for reason,change,expected in [('scenery',False,[{'start':0,'end':1},{'start':3,'end':4}]),
                                       ('scenery',True,[{'start':0,'end':4}]),
                                       ('action',True,[{'start':0,'end':4}]),
                                       ('reaction',True,[{'start':0,'end':4}])]:
            event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
            apply_review(event,[{'id':'s000','start':1,'end':3}],
                {'decisions':[{'unit':'s000','keep':False,'reason':reason,'story_change':change,
                               'evidence':'Current before/middle/after views','retained_witness':'none'}],'uncertain':False})
            self.assertEqual(event['selected_ranges'],expected)

    def test_reaction_or_humor_and_disabled_empty_hold_removal_are_preserved(self):
        from app.editorial import DEFAULT_PROFILE
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        units=[{'id':'s000','start':1,'end':3}]
        apply_review(event,units,{'decisions':[{'unit':'s000','keep':False,'reason':'waiting',
            'story_change':False,'reaction_or_humor':True,'evidence':'A quiet character reaction adds atmosphere'}],
            'uncertain':False})
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':4}])
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        profile={**DEFAULT_PROFILE,'remove_empty_holds':False}
        apply_review(event,units,{'decisions':[{'unit':'s000','keep':False,'reason':'waiting',
            'story_change':False,'reaction_or_humor':False,'evidence':'Unchanged empty view compared with neighbors'}],
            'uncertain':False},profile)
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':4}])

    def test_tentative_atmosphere_label_does_not_override_current_empty_hold_review(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}],
               'protected_atmosphere_ranges':[{'start':0,'end':4}]}
        apply_review(event,[{'id':'s000','start':1,'end':3}],{'decisions':[{
            'unit':'s000','keep':False,'reason':'scenery','story_change':False,
            'reaction_or_humor':False,'evidence':'Same empty hallway in the current frames and both neighboring views.'
        }],'uncertain':False})
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':1},{'start':3,'end':4}])

    def test_independently_verified_story_and_visible_reactions_still_survive(self):
        for event,decision in [
            ({'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}],
              'verified_current_story_ranges':[{'start':1,'end':3}]},
             {'reason':'scenery','story_change':False,'reaction_or_humor':False}),
            ({'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}],
              'protected_atmosphere_ranges':[{'start':0,'end':4}]},
             {'reason':'reaction','story_change':False,'reaction_or_humor':True}),
        ]:
            apply_review(event,[{'id':'s000','start':1,'end':3}],{'decisions':[{
                'unit':'s000','keep':False,**decision,
                'evidence':'A specific expression and gesture visibly changes in the current frames.'
            }],'uncertain':False})
            self.assertEqual(event['selected_ranges'],[{'start':0,'end':4}])

    def test_tentative_atmosphere_units_are_sent_for_current_frame_review(self):
        directory=TEMP/('pacing_atmosphere_'+uuid.uuid4().hex)
        directory.mkdir()
        source=directory/'source.mp4';source.write_bytes(b'fixture')
        event={'id':'silent','start':0,'end':2,'kind':'story','importance':4,'requires':[],
               'selected_ranges':[{'start':0,'end':2}],
               'protected_atmosphere_ranges':[{'start':0,'end':2}]}
        vision=Mock(model=Path('model'),projector=Path('profile'),cache_profile='fixture')
        vision.query.return_value={'decisions':[{'unit':'A','keep':False,'reason':'scenery',
            'story_change':False,'reaction_or_humor':False,
            'evidence':'The current frames show the same empty hallway as the neighboring views.'}],
            'uncertain':False}
        with patch('app.pacing.make_sheet'):
            result=refine_pacing(source,[event],{'words':[],'segments':[]},[],directory,vision,
                                 lambda *a:None,lambda:False)
        vision.query.assert_called_once()
        self.assertEqual(result[0]['selected_ranges'],[])
        self.assertTrue(result[0]['pacing_excluded'])

    def test_repeat_cannot_cite_an_omitted_neighbor(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        units=[{'id':'s000','start':1,'end':3,'repeat_witnesses':['before']}]
        raw={'decisions':[{'unit':'s000','keep':False,'reason':'repeat','story_change':False,
                            'evidence':'Same state','retained_witness':'after'}],'uncertain':False}
        apply_review(event,units,raw)
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':4}])
        raw['decisions'][0]['retained_witness']='before'
        apply_review(event,units,raw)
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':1},{'start':3,'end':4}])

    def test_deleted_batch_unit_cannot_prove_another_deletion(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        units=[{'id':'s000','start':0,'end':2}, {'id':'s001','start':2,'end':4,'repeat_witnesses':['s000']}]
        raw={'decisions':[{'unit':'s000','keep':False,'reason':'scenery','story_change':False,
                            'evidence':'Neutral view','retained_witness':'none'},
                          {'unit':'s001','keep':False,'reason':'repeat','story_change':False,
                            'evidence':'Same view','retained_witness':'s000'}], 'uncertain':False}
        apply_review(event,units,raw)
        self.assertEqual(event['selected_ranges'],[{'start':2,'end':4}])
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        raw['decisions'][0]['keep']=True
        apply_review(event,units,raw)
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':2}])

    def test_invalid_repeat_does_not_cancel_other_grounded_scenery_decisions(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        units=[{'id':'A','start':0,'end':2}, {'id':'B','start':2,'end':4,'repeat_witnesses':[]}]
        apply_review(event,units,{'decisions':[
            {'unit':'A','keep':False,'reason':'scenery','story_change':False,'evidence':'Empty neutral exterior'},
            {'unit':'B','keep':False,'reason':'repeat','story_change':False,'evidence':'Unconfirmed duplicate','retained_witness':'before'}],
            'uncertain':False})
        self.assertEqual(event['selected_ranges'],[{'start':2,'end':4}])
        self.assertTrue(event['story_warnings'])

    def test_tiny_silent_shot_is_preserved_without_a_model_query_row(self):
        units=silent_units({'start':0,'end':5}, {'segments':[],'words':[]}, [{'start':.2}])
        self.assertTrue(all(u['start']>=.2 and u['end']-u['start']>=.75 for u in units))

    def test_source_neighbor_marks_omitted_speech_as_interpretation_only(self):
        transcript={'segments':[{'start':0,'end':2,'text':'Удалённая.'},{'start':4,'end':7,'text':'Сохранённая.'}]}
        events=[{'id':'one','start':0,'end':7,'selected_ranges':[{'start':4,'end':7}]}]
        neighbors=neighboring_replies({'start':2.55,'end':3.82},transcript,events,{'one'})
        self.assertFalse(neighbors['before']['retained'])
        self.assertTrue(neighbors['after']['retained'])

    def test_unsupported_deletion_without_evidence_is_rejected_before_mutation(self):
        event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}]}
        original=copy.deepcopy(event)
        with self.assertRaises(ValueError):
            apply_review(event,[{'id':'s000','start':1,'end':2}],
                {'decisions':[{'unit':'s000','keep':False,'reason':'waiting'}],'uncertain':False})
        self.assertEqual(event,original)

    def test_budget_fallback_never_sends_more_paid_queries_and_closes_local_model(self):
        from app.deepseek import EpisodeBudgetExceeded
        from PIL import Image
        directory = TEMP / ('pacing_budget_'+uuid.uuid4().hex)
        directory.mkdir()
        image = directory / 'sheet.jpg'
        Image.new('RGB',(960,2300),'gray').save(image)
        remote = Mock(model=Path('remote'),projector=Path('profile'),cache_profile='test')
        remote.query.side_effect = EpisodeBudgetExceeded('cap')
        local = MagicMock()
        local.query.return_value = {'decisions':[], 'uncertain':False}
        with patch('app.analysis.LocalVision', return_value=local):
            with BudgetPacingVision(remote,directory,lambda:False) as vision:
                vision.query('prompt',image,max_tokens=800,schema={})
                vision.query('next prompt',image,max_tokens=800,schema={})
                self.assertTrue(vision.budget_fallback)
        self.assertEqual(remote.query.call_count,1)
        self.assertEqual(local.query.call_count,2)
        local.close.assert_called_once()
        with Image.open(image.with_name('sheet.local.jpg')) as resized:
            self.assertLessEqual(resized.height,1176)

    def test_silent_splits_never_touch_spoken_words_or_leading_context(self):
        event = {'start': 0, 'end': 30, 'selected_ranges': [{'start':0,'end':30}]}
        transcript = {'segments':[{'start':12,'end':16}], 'words':[{'start':12,'end':16}]}
        units = silent_units(event, transcript, [{'start':5}, {'start':13}, {'start':24}])
        self.assertTrue(units)
        self.assertTrue(all(u['end'] <= 11.82 or u['start'] >= 16.55 for u in units))
        self.assertTrue(all(u['end']-u['start'] <= 4.001 for u in units))

    def test_short_redundant_pause_is_reviewable_without_touching_speech_tail(self):
        event={'start':0,'end':10,'selected_ranges':[{'start':0,'end':10}]}
        transcript={'segments':[{'start':0,'end':3},{'start':7,'end':10}],
                    'words':[{'start':0,'end':3},{'start':7,'end':10}]}
        units=silent_units(event,transcript,[])
        self.assertEqual(units[0]['start'],3.55)
        self.assertEqual(units[-1]['end'],6.82)
        self.assertTrue(all(u['end']-u['start']<=4 for u in units))

    def test_sub_two_second_margin_gets_exact_neighboring_replies(self):
        event={'start':0,'end':7,'selected_ranges':[{'start':0,'end':7}]}
        transcript={'segments':[{'start':0,'end':2,'text':'Первая.'},{'start':4,'end':7,'text':'Следующая.'}], 'words':[]}
        unit=silent_units(event,transcript,[])[0]
        self.assertEqual(unit,{'id':'s000','start':2.55,'end':3.82})
        self.assertEqual(neighboring_replies(unit,transcript),{'before':transcript['segments'][0],'after':transcript['segments'][1]})

    def test_discarded_event_is_not_a_retained_repetition_witness(self):
        events=[{'id':'omit','start':0,'end':10,'kind':'story','importance':4,'global_excluded':True,'requires':[]},
                {'id':'keep','start':10,'end':20,'kind':'story','importance':4,'requires':[],
                 'selected_ranges':[{'start':15,'end':20}]}]
        transcript={'segments':[{'start':1,'end':2,'text':'Удалено.'},{'start':11,'end':12,'text':'Тоже удалено.'},
                                {'start':16,'end':17,'text':'Оставлено.'}]}
        self.assertEqual(retained_context(events,transcript),[{'id':'keep','retained_speech':[transcript['segments'][2]]}])
        self.assertEqual(retained_context(events[:1],transcript),[])
        events[1]['requires']=['omit']
        from app.speech_context import _retained
        self.assertEqual(retained_context(events[:1],transcript,_retained(events)),
                         [{'id':'omit','retained_speech':[transcript['segments'][0]]}])

    def test_short_pause_action_remains_when_reviewed(self):
        event={'start':0,'end':10,'selected_ranges':[{'start':0,'end':10}]}
        units=[{'id':'s000','start':3.55,'end':6.82}]
        apply_review(event,units,{'decisions':[{'unit':'s000','keep':True,'reason':'action'}], 'uncertain':False})
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':10}])

    def test_only_examined_silent_waiting_removed_action_and_dialogue_remain(self):
        event = {'start':0,'end':20,'selected_ranges':[{'start':0,'end':20}]}
        units = [{'id':'s000','start':0,'end':4}, {'id':'s001','start':4,'end':8}]
        apply_review(event, units, {'decisions':[{'unit':'s000','keep':False,'reason':'action'},
                                                {'unit':'s001','keep':False,'reason':'waiting','story_change':False,'evidence':'Unchanged held state compared with neighbors'}], 'uncertain':False})
        self.assertEqual(event['selected_ranges'], [{'start':0,'end':4}, {'start':8,'end':20}])

    def test_unknown_duplicate_or_missing_unit_rejected_before_mutation(self):
        original = {'start':0,'end':10,'selected_ranges':[{'start':0,'end':10}]}
        units = [{'id':'s000','start':0,'end':10}]
        for ids in ([], ['invented'], ['s000','s000']):
            event = copy.deepcopy(original)
            with self.assertRaises(ValueError):
                apply_review(event, units, {'decisions':[{'unit':i,'keep':False,'reason':'waiting','story_change':False,'evidence':'Unchanged held state compared with neighbors'} for i in ids], 'uncertain':False})
            self.assertEqual(event, original)

    def test_pacing_cannot_delete_unconfirmed_credit_or_narrative_transition(self):
        event = {'start':0,'end':10,'selected_ranges':[{'start':0,'end':10}], 'requires':[], 'kind':'story','importance':4}
        units = [{'id':'s000','start':0,'end':10}]
        decision = {'decisions':[{'unit':'s000','keep':False,'reason':'production_credit'}], 'uncertain':True}
        apply_review(event, units, decision)
        self.assertEqual(event['selected_ranges'], [{'start':0,'end':10}])
        decision['uncertain'] = False
        apply_review(event, units, decision)
        self.assertNotIn('pacing_excluded',event)
        self.assertEqual(event['selected_ranges'],[{'start':0,'end':10}])
        self.assertTrue(event['story_warnings'])

    def test_cached_review_reuses_answers_and_removes_dependencies_on_nonstory(self):
        directory = TEMP / ('pacing_test_'+uuid.uuid4().hex)
        directory.mkdir()
        source = directory / 'source.mp4'
        source.write_bytes(b'fixture')
        events = [{'id':'credits','start':0,'end':10,'summary':'Production credits','kind':'story','importance':4,
                   'requires':[], 'selected_ranges':[{'start':0,'end':10}]},
                  {'id':'dialogue','start':12,'end':16,'summary':'Real response','kind':'story','importance':4,
                   'requires':['credits'], 'selected_ranges':[{'start':12,'end':16}]}]
        vision = Mock(model=Path('model'),projector=Path('profile'),cache_profile='fixture')
        vision.query.side_effect = lambda prompt, image, **kw: {'decisions':[
            {'unit':u,'keep':False,'reason':'waiting','story_change':False,'evidence':'Unchanged held state compared with neighbors'} for u in kw['schema']['properties']['decisions']['items']['properties']['unit']['enum']], 'uncertain':False}
        with patch('app.pacing.make_sheet'):
            transcript={'words':[{'start':12,'end':16}], 'segments':[{'start':12,'end':16}]}
            first = refine_pacing(source, events, transcript, [], directory, vision, lambda *a:None, lambda:False)
            self.assertEqual(first[1]['requires'], [])
            self.assertTrue(first[0]['pacing_excluded'])
            self.assertEqual(vision.query.call_count, 1)
            second = refine_pacing(source, events, transcript, [], directory, vision, lambda *a:None, lambda:False)
            self.assertEqual(vision.query.call_count, 1)
            self.assertEqual(second, first)

    def test_local_fallback_batch_is_separate_from_paid_cache_and_provenance(self):
        from types import SimpleNamespace
        directory=TEMP/('pacing_degraded_'+uuid.uuid4().hex)
        directory.mkdir()
        source=directory/'source.mp4';source.write_bytes(b'fixture')
        events=[{'id':'paid','start':0,'end':2,'kind':'story','importance':4,'requires':[],
                 'selected_ranges':[{'start':0,'end':2}]},
                {'id':'fallback','start':4,'end':6,'kind':'story','importance':4,'requires':[],
                 'selected_ranges':[{'start':4,'end':6}]}]
        transcript={'words':[],'segments':[]}
        answer=lambda prompt,image,**kwargs:{'decisions':[
            {'unit':unit,'keep':True,'reason':'action'}
            for unit in kwargs['schema']['properties']['decisions']['items']['properties']['unit']['enum']],
            'uncertain':False}
        remote=Mock(model=Path('deepseek-flash'),projector=Path('profile'),cache_profile='remote',
                    budget_fallback=False)
        remote.query.side_effect=answer
        with patch('app.pacing.make_sheet'):
            initial=refine_pacing(source,events,transcript,[],directory,remote,lambda *a:None,lambda:False)
            self.assertEqual(remote.query.call_count,2)
            paid_cache=list((directory/'pacing').glob('*.json'))
            self.assertEqual(len(paid_cache),2)

            # Preserve one paid checkpoint and remove the other so only one
            # batch needs local fallback on the next deterministic pass.
            paid_cache[1].unlink()
            class MixedVision:
                model=Path('deepseek-flash')
                projector=Path('profile')
                cache_profile='remote'
                budget_fallback=False
                local=SimpleNamespace(model=Path('qwen-local'))
                fallback_reason={'category':'transport','endpoint':'/user/balance'}
                def query(self,*args,**kwargs):
                    self.budget_fallback=True
                    return answer(*args,**kwargs)
            mixed=MixedVision()
            replay=refine_pacing(source,events,transcript,[],directory,mixed,lambda *a:None,lambda:False)
            self.assertEqual(sorted(event['pacing_provider'] for event in replay),
                             ['deepseek-flash','qwen-local'])
            degraded=[event for event in replay if event.get('pacing_degraded')]
            self.assertEqual(len(degraded),1)
            self.assertEqual(degraded[0]['pacing_provider'],'qwen-local')
            self.assertEqual(degraded[0]['pacing_fallback_reason'],mixed.fallback_reason)
            self.assertEqual(len(list((directory/'pacing').glob('*.json'))),1)
            degraded_files=list((directory/'pacing'/'degraded').glob('*.json'))
            self.assertEqual(len(degraded_files),1)
            self.assertEqual(json.loads(degraded_files[0].read_text('utf-8'))['used_provider'],'qwen-local')

            retry=Mock(model=Path('deepseek-flash'),projector=Path('profile'),cache_profile='remote',
                       budget_fallback=False)
            retry.query.side_effect=answer
            again=refine_pacing(source,events,transcript,[],directory,retry,lambda *a:None,lambda:False)
            self.assertEqual(retry.query.call_count,1)
            self.assertTrue(all(event.get('pacing_provider')=='deepseek-flash' for event in again))
