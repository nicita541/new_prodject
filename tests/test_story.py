import copy
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import TEMP
from app.story import (_credit_decision, refine_story, clean_credit_continuations,
                       preserve_dialogue_in_credits, verify_omissions, _valid_cache,
                       _unit_for_frame_time)
from app.planner import build_plan


class FakeVision:
    def __init__(self, answers):
        self.answers = story_answers(*answers)
        self.calls = []
        self.schemas = []

    def query(self, prompt, image=None, max_tokens=650, schema=None):
        self.calls.append((prompt, image, max_tokens))
        self.schemas.append(schema)
        return self.answers.pop(0)


def authored_units(boundaries, transcript):
    """Explicit source geometry for selection/proof mechanisms, not perception E2E.

    Production candidate generation is tested separately. These units purposely
    include reply setup/reaction context to test retention inside supplied units.
    """
    return [{'id': f'u{i:03d}', 'start': a, 'end': b,
             'boundary_reason': ['authored_test_interval'],
             'text': ' '.join(w['text'] for w in transcript.get('words', [])
                              if a <= w['start'] and w['end'] <= b)}
            for i, (a, b) in enumerate(zip(boundaries, boundaries[1:]))]


def fixture():
    directory = TEMP / ("story_" + uuid.uuid4().hex)
    directory.mkdir()
    (directory / "analysis.meta.json").write_text(json.dumps({"source": "source-one", "version": 3}), encoding="utf-8")
    (directory / 'visual').mkdir(exist_ok=True)
    Image.new('RGB', (48, 27), 'white').save(directory / 'visual/event_0000.jpg')
    events = [{"id": "event_0000", "start": 0, "end": 20, "summary": "Персонажи разговаривают.",
               "kind": "story", "importance": 4, "requires": [], "focus": []}]
    transcript = {"segments": [{"start": 3, "end": 6, "text": "Я решил вернуться."},
                               {"start": 8, "end": 12, "text": "Да, повторю еще раз."},
                               {"start": 15, "end": 19, "text": "Я согласна."}],
                  "words": [{"start": 3, "end": 6, "text": "Решение."},
                            {"start": 8, "end": 12, "text": "Повтор."},
                            {"start": 15, "end": 19, "text": "Согласие."}]}
    events[0]['units'] = authored_units([0, 6, 12, 19, 20], transcript)
    return directory, events, transcript


def decision(keep, preserve=None, uncertain=False):
    return {"summary": "Он решил вернуться, она согласилась.", "keep_units": keep,
            "preserve_silent_units": preserve or [], "uncertain": uncertain,
            'omit_units':[{'unit':u,'reason':'redundant_exchange'} for u in ['u000','u001','u002','u003']
                          if u not in set(keep) | set(preserve or [])]}


def story_answers(*answers):
    """Pair story proposals with independent, conservative visual proof."""
    result=[]
    for index,raw in enumerate(answers):
        result.append(raw)
        if not isinstance(raw,dict) or 'summary' not in raw or not raw.get('omit_units'):
            continue
        if any(not isinstance(raw.get(key),list) or any(not isinstance(unit,str) for unit in raw[key])
               for key in ('keep_units','preserve_silent_units')):
            continue
        if not (set(raw['keep_units'])|set(raw['preserve_silent_units'])) <= {'u000','u001','u002','u003'}:
            continue
        if any(not isinstance(omission,dict) or omission.get('unit') not in
               {'u000','u001','u002','u003'} or omission.get('reason') not in
               {'waiting','redundant_exchange','repeated_information'}
               for omission in raw['omit_units']):
            continue
        if (index+1<len(answers) and isinstance(answers[index+1],dict)
                and any(isinstance(item,dict) and 'keep' in item
                        for item in answers[index+1].get('decisions',[]))):
            continue  # Caller supplied the independent proof explicitly.
        if any(not isinstance(omission,dict) or omission.get('unit') not in
               {'u000','u001','u002','u003'} or omission.get('reason') not in
               {'waiting','redundant_exchange','repeated_information'}
               for omission in raw['omit_units']):
            continue
        selected=set(raw.get('keep_units',[]))|set(raw.get('preserve_silent_units',[]))
        units={'u000':(0,6),'u001':(6,12),'u002':(12,19),'u003':(19,20)}
        decisions=[]
        for omission in raw['omit_units']:
            unit=omission['unit']
            if omission.get('reaction_or_humor'):
                continue  # Balanced-atmosphere profile protects these in pass one.
            if omission['reason']=='waiting':
                decisions.append({'unit':unit,'keep':False,'story_change':False,
                    'current_episode_story':False,'confidence':.98,
                    'reaction_or_humor':False,'evidence':'No action, response, or distinct atmosphere appears here.',
                    'retained_witness':'none'})
                continue
            earlier=[candidate for candidate in selected if units[candidate][1]<=units[unit][0]]
            decisions.append({'unit':unit,'keep':not bool(earlier),'story_change':False,
                'current_episode_story':False,'confidence':.98,
                'reaction_or_humor':False,
                'evidence':'The earlier retained unit already conveys this repeated exchange.' if earlier
                           else 'No earlier retained unit proves this is redundant.',
                'retained_witness':max(earlier,key=lambda candidate:units[candidate][1]) if earlier else 'none'})
        result.append({'decisions':decisions})
    return result


def partition(excluded, narrative, uncertain=False):
    return {'nonstory_units': excluded, 'narrative_units': narrative, 'confidence': .95, 'uncertain': uncertain}


def credit(pure, contains=True):
    return {'credit_montage': pure, 'continuous_narrative': not pure,
            'contains_credits': contains, 'confidence': .95}


def edge_fixture(start=5, end=20, kind='opening'):
    directory, events, _ = fixture()
    (directory / 'visual').mkdir(exist_ok=True)
    source = directory / 'episode.mkv'
    source.write_bytes(b'actual-source-identity')
    (directory / 'source.json').write_text(json.dumps({'path': str(source)}), encoding='utf-8')
    event = {**events[0], 'start': start, 'end': end, 'contains_credits': True,
             'credits_kind': kind, 'selected_ranges': [{'start': start, 'end': end}]}
    Image.new('RGB', (48, 27), 'white').save(directory / 'visual' / (event['id'] + '.jpg'))
    return directory, event, source


def fake_storyboard(source, start, end, shots, transcript, destination, cancelled):
    Image.new('RGB', (48, 27), (int(start) % 255, int(end) % 255, 0)).save(destination)
    return [start, end]


class StoryRefinementTests(unittest.TestCase):
    def test_frame_timestamp_rounded_to_chunk_end_retains_correct_source_owner(self):
        units = [{'id': 'u000', 'start': 0.0, 'end': 40.1234567},
                 {'id': 'u001', 'start': 40.1234567, 'end': 80.1234567}]
        self.assertEqual(_unit_for_frame_time(units, 40.123456), 'u000')
        self.assertEqual(_unit_for_frame_time(units, 40.123457), 'u001')
        self.assertEqual(_unit_for_frame_time(units, 80.123457), 'u001')
        with self.assertRaisesRegex(ValueError, 'ни одному исходному фрагменту'):
            _unit_for_frame_time(units, 80.125)
        with self.assertRaises(ValueError):
            _unit_for_frame_time(units, float('nan'))

    def test_omission_review_restores_new_wakeup_action_and_plan_cache_roundtrip(self):
        directory,events,transcript=fixture()
        raw=decision(['u000','u002','u003'])
        proof={'decisions':[{'unit':'u001','keep':False,'story_change':True,
            'current_episode_story':True,'confidence':.98,'reaction_or_humor':False,
            'evidence':'The repeated name coincides with a new wake-up and response.',
            'retained_witness':'none'}]}
        vision=FakeVision([raw,proof])
        result=refine_story(events,transcript,[],directory,vision,lambda *a:None,lambda:False)
        self.assertTrue(any(r['start']<=6 and r['end']>=12 for r in result[0]['selected_ranges']))
        self.assertEqual(result[0]['story_omission_review']['restored_units'],['u001'])
        self.assertEqual(result[0]['verified_current_story_ranges'],[{'start':6.0,'end':12.0}])
        serialized=json.loads(json.dumps(result,ensure_ascii=False))
        plan=build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                         'events':serialized,'transcript':transcript,'shots':[]})
        self.assertTrue(any(c['start']<=6 and c['end']>=12 for p in plan['parts'] for c in p['cuts']))
        cached=FakeVision([])
        self.assertEqual(refine_story(events,transcript,[],directory,cached,lambda *a:None,lambda:False),result)
        self.assertFalse(cached.calls)
        saved=json.loads(next((directory/'story_refinement').glob('*.json')).read_text('utf-8'))
        self.assertTrue(_valid_cache(saved,saved['signature'],events[0]))
        missing_range=copy.deepcopy(saved)
        missing_range['event'].pop('verified_current_story_ranges')
        self.assertFalse(_valid_cache(missing_range,saved['signature'],events[0]))

    def test_op_or_preview_novelty_without_current_episode_ownership_is_not_sticky(self):
        directory,events,transcript=fixture()
        raw=decision(['u000','u002','u003'])
        proof={'decisions':[{'unit':'u001','keep':False,'story_change':True,
            'current_episode_story':False,'confidence':.98,'reaction_or_humor':False,
            'evidence':'The new movement belongs to the episode opening montage, not its current plot.',
            'retained_witness':'none'}]}
        result=refine_story(events,transcript,[],directory,FakeVision([raw,proof]),
                            lambda *a:None,lambda:False)
        self.assertFalse(any(r['start']<12 and r['end']>6 for r in result[0]['selected_ranges']))
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertNotIn('verified_current_story_ranges',result[0])
        serialized=json.loads(json.dumps(result,ensure_ascii=False))
        self.assertNotIn('verified_current_story_ranges',serialized[0])

    def test_omission_proof_rejects_integer_booleans_and_boolean_confidence(self):
        from app.editorial import DEFAULT_PROFILE
        unit={'id':'u001','start':6,'end':12,'text':'Мари просыпается'}
        for field,value in [('current_episode_story',1),('confidence',True)]:
            with self.subTest(field=field):
                proof={'decisions':[{'unit':'u001','keep':True,'story_change':False,
                    'reaction_or_humor':False,'current_episode_story':True,'confidence':.98,
                    'evidence':'The current frame shows the character resting.','retained_witness':'none'}]}
                proof['decisions'][0][field]=value
                with self.assertRaises(ValueError):
                    verify_omissions([unit],set(),[{'unit':'u001','reason':'waiting'}],
                                     None,[],FakeVision([proof]),DEFAULT_PROFILE)

    def test_independently_verified_action_survives_later_scenery_review_and_planning(self):
        from app.analysis import apply_global_selection
        from app.editorial import DEFAULT_PROFILE
        from app.pacing import apply_review
        directory,events,transcript=fixture()
        raw=decision(['u000','u002','u003'])
        proof={'decisions':[{'unit':'u001','keep':False,'story_change':True,
            'current_episode_story':True,'confidence':.98,'reaction_or_humor':True,
            'evidence':'The repeated name accompanies a new wake-up response.',
            'retained_witness':'none'}]}
        result=refine_story(events,transcript,[],directory,FakeVision([raw,proof]),
                            lambda *a:None,lambda:False)
        apply_global_selection(result,{'keep':[],'omit':[{'event':'event_0000','reason':'nonstory',
            'evidence':'The short scene has no episode plot.','confidence':.98,'reaction_or_humor':False}],
            'dependencies':[],'summary':'No scenes'},DEFAULT_PROFILE)
        self.assertNotIn('global_excluded',result[0])
        apply_review(result[0],[{'id':'s000','start':6,'end':6.55},
                                {'id':'s001','start':6.55,'end':7.55},
                                {'id':'s002','start':7.55,'end':12}],
                     {'uncertain':False,'decisions':[
                         {'unit':'s000','keep':True,'reason':'action','story_change':True,
                          'reaction_or_humor':False,'evidence':'The action begins here.'},
                         {'unit':'s001','keep':False,'reason':'scenery','story_change':False,
                          'reaction_or_humor':False,'evidence':'No apparent plot movement in this narrow interval.'},
                         {'unit':'s002','keep':True,'reason':'action','story_change':True,
                          'reaction_or_humor':False,'evidence':'The scene resolves here.'}]})
        self.assertTrue(any(r['start']<=7 and r['end']>=7.5 for r in result[0]['selected_ranges']))
        plan=build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                         'events':result,'transcript':transcript,'shots':[]})
        self.assertTrue(any(c['start']<=7 and c['end']>=7.5 for p in plan['parts'] for c in p['cuts']))

    def test_repeat_omission_requires_an_earlier_selected_witness_and_valid_proof(self):
        from app.editorial import DEFAULT_PROFILE
        units=[{'id':'u000','start':0,'end':5},{'id':'u001','start':5,'end':10},
               {'id':'u002','start':10,'end':15}]
        omission=[{'unit':'u001','reason':'repeated_information'}]
        collage=Path('current-collage.jpg')
        class Vision:
            def __init__(self,answer): self.answer=answer
            def query(self,*args,**kwargs): return self.answer
        no_witness={'decisions':[{'unit':'u001','keep':False,'story_change':False,
            'current_episode_story':False,'confidence':.98,'reaction_or_humor':False,
            'evidence':'No retained example proves repetition.',
            'retained_witness':'none'}]}
        approved,proof=verify_omissions(units,{'u000'},omission,collage,[],Vision(no_witness),DEFAULT_PROFILE)
        self.assertEqual(approved,[])
        supported={'decisions':[{'unit':'u001','keep':False,'story_change':False,
            'current_episode_story':False,'confidence':.98,'reaction_or_humor':False,
            'evidence':'This phrase repeats the earlier retained exchange.',
            'retained_witness':'u000'}]}
        approved,_=verify_omissions(units,{'u000'},omission,collage,[],Vision(supported),DEFAULT_PROFILE)
        self.assertEqual(approved,omission)
        later_witness={'decisions':[{'unit':'u001','keep':False,'story_change':False,
            'current_episode_story':False,'confidence':.98,'reaction_or_humor':False,
            'evidence':'A later occurrence cannot witness this interval.',
            'retained_witness':'u002'}]}
        approved,_=verify_omissions(units,{'u000','u002'},omission,collage,[],Vision(later_witness),DEFAULT_PROFILE)
        self.assertEqual(approved,[])
        malformed={'decisions':[{'unit':'u001','keep':False,'story_change':False,
            'current_episode_story':False,'confidence':.98,'reaction_or_humor':False,
            'evidence':'   ','retained_witness':'u000'}]}
        with self.assertRaises(ValueError):
            verify_omissions(units,{'u000'},omission,collage,[],Vision(malformed),DEFAULT_PROFILE)

    def test_physical_reaction_after_actual_segment_end_survives_margin_review(self):
        from app.pacing import apply_review
        directory,events,_=fixture()
        transcript={'segments':[{'start':3,'end':7,'text':'Действуй!'}],
                    'words':[{'start':3,'end':7,'text':'Действуй!'}]}
        events[0]['units'] = authored_units([0, 7, 20], transcript)
        raw={**decision(['u000'],['u001']), 'omit_units':[]}
        result=refine_story(events,transcript,[],directory,FakeVision([raw]),lambda *a:None,lambda:False)
        apply_review(result[0],[{'id':'s000','start':7.55,'end':9.55},
                                {'id':'s001','start':9.55,'end':11.55}],
                     {'decisions':[{'unit':u,'keep':True,'reason':'action','story_change':True,
                                     'evidence':'Physical action progresses and finishes after the spoken cue',
                                     'retained_witness':'none'} for u in ['s000','s001']], 'uncertain':False})
        plan=build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                         'events':result,'transcript':transcript,'shots':[]})
        self.assertTrue(any(c['start']<=8 and c['end']>=11 for p in plan['parts'] for c in p['cuts']))

    def test_confirmed_redundant_exchange_is_not_restored_by_planner(self):
        directory, events, transcript = fixture()
        vision = FakeVision([decision(['u000','u002'])])
        result = refine_story(events, transcript, [], directory,
                              vision, lambda *a:None, lambda:False)
        plan = build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                           'events':result, 'transcript':transcript, 'shots':[]})
        self.assertNotIn('Повтор.', ' '.join(c['text'] for p in plan['parts'] for c in p['subtitles']))
        self.assertIn('Согласие.', ' '.join(c['text'] for p in plan['parts'] for c in p['subtitles']))
        self.assertEqual(result[0]['omitted_story_units'][0]['reason'], 'redundant_exchange')
        self.assertIn('Exact frame-to-unit mapping:', vision.calls[0][0])
        self.assertIn('NEVER convert Frame 17 into u017', vision.calls[0][0])

    def test_incomplete_or_contradictory_omission_partition_requires_adjudication(self):
        for omissions in [[], [{'unit':'u000','reason':'waiting'}],
                          [{'unit':'u001','reason':'important_action'}]]:
            directory, events, transcript = fixture()
            raw={**decision(['u000','u002']), 'omit_units':omissions}
            result=refine_story(events,transcript,[],directory,FakeVision([raw]),lambda *a:None,lambda:False)
            self.assertEqual(result[0]['selected_ranges'],[])
            self.assertEqual(result[0]['unit_selection_version'], 1)
            self.assertTrue(result[0]['analysis_unresolved'])
            self.assertTrue(result[0]['story_warnings'])

    def test_silent_reaction_after_last_word_is_not_trimmed(self):
        directory,events,_=fixture()
        transcript={'segments':[{'start':3,'end':10,'text':'Действуй!'}],
                    'words':[{'start':3,'end':7,'text':'Действуй!'}]}
        events[0]['units'] = authored_units([0, 10, 20], transcript)
        raw = {**decision(['u000']), 'omit_units':[{'unit':'u001','reason':'waiting'}]}
        result=refine_story(events,transcript,[],directory,FakeVision([raw]),
                            lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':10}])

    def test_no_current_images_is_unresolved_without_text_only_keep_all(self):
        directory,events,transcript=fixture()
        (directory/'visual/event_0000.jpg').unlink()
        vision=FakeVision([])
        result=refine_story(events,transcript,[],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[])
        self.assertTrue(result[0]['story_warnings'])
        self.assertFalse(vision.calls)
        self.assertTrue(result[0]['selection_uncertain'])

    def test_answer_during_credits_survives_visual_montage_classification(self):
        _, events, _ = fixture()
        events[0].update(kind='ending', importance=1, credit_montage=True,
                         selected_ranges=[{'start':0,'end':20}])
        transcript = {'segments':[{'start':1,'end':3,'text':'Ты простыла?'},
                                  {'start':4,'end':7,'text':'Нет, обо мне вспомнили.'}],
                      'words':[{'start':4,'end':7,'text':'Нет,','probability':.9}]}
        result = preserve_dialogue_in_credits(events, transcript)
        self.assertEqual(result[0]['selected_ranges'], [{'start':.75,'end':3.3}, {'start':3.75,'end':7.3}])
        self.assertFalse(result[0]['credit_montage'])
        self.assertTrue(result[0]['contains_credits'])

    def test_selected_reply_retains_action_before_speech_and_after_speech(self):
        directory, events, transcript = fixture()
        original = copy.deepcopy(events)
        vision = FakeVision([decision(["u000", "u002"])])
        result = refine_story(events, transcript, [], directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(events, original)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 0, "end": 6}, {"start": 12, "end": 19}])
        self.assertEqual(result[0]["summary"], "Он решил вернуться, она согласилась.")
        self.assertEqual(vision.calls[0][1], directory/'visual/event_0000.jpg')
        self.assertFalse(result[0]["story_warnings"])

    def test_disabled_repeat_removal_restores_low_plot_repetition_through_planning(self):
        directory,events,transcript=fixture()
        from app.editorial import DEFAULT_PROFILE
        profile={**DEFAULT_PROFILE,'remove_exact_repetition':False}
        (directory/'editorial-settings.json').write_text(json.dumps(profile),encoding='utf-8')
        result=refine_story(events,transcript,[],directory,
                            FakeVision([decision(['u000','u002'])]),lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':20}])
        plan=build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                         'events':result,'transcript':transcript,'shots':[]})
        subtitles=' '.join(c['text'] for p in plan['parts'] for c in p['subtitles'])
        self.assertIn('Повтор.',subtitles)

    def test_preserve_silent_units_retains_entire_source_interval(self):
        directory, events, transcript = fixture()
        vision = FakeVision([decision(["u000"], ["u002"])])
        result = refine_story(events, transcript, [], directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 0, "end": 6}, {"start": 12, "end": 19}])

    def test_unknown_nonlist_and_empty_selection_are_unresolved_without_keep_all(self):
        for raw in [decision(["invented"]), {**decision(["u000"]), "keep_units": "u000"}, decision([])]:
            directory, events, transcript = fixture()
            result = refine_story(events, transcript, [], directory, FakeVision([raw]), lambda *a: None, lambda: False)
            self.assertTrue(result[0]["story_warnings"])
            self.assertEqual(result[0]["selected_ranges"], [])
            self.assertTrue(result[0]['analysis_unresolved'])

    def test_empty_silent_selection_requires_adjudication_without_keep_all(self):
        directory, events, _ = fixture()
        transcript = {"words": [], "segments": []}
        result = refine_story(events, transcript, [], directory, FakeVision([credit(False, False), decision([])]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]["selected_ranges"], [])
        self.assertTrue(result[0]['analysis_unresolved'])

    def test_uncertain_selection_does_not_keep_all_original_units(self):
        directory, events, transcript = fixture()
        result = refine_story(events, transcript, [], directory, FakeVision([decision(["u000"], uncertain=True)]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]["selected_ranges"], [])
        self.assertTrue(result[0]["story_warnings"])
        self.assertTrue(result[0]['selection_uncertain'])

    def test_uncertainty_keeps_only_existing_specific_positive_unit(self):
        directory, events, transcript = fixture()
        events[0].update(selected_ranges=[{'start': 0, 'end': 20}], unit_evidence=[{
            'unit': 'u000', 'kind': 'causal_dialogue', 'confidence': .95, 'decision': 'keep',
            'evidence': 'Конкретная исходная реплика сообщает принятое решение вернуться.',
            'frame_indices': [], 'speech_quote': 'Решение.'}])
        result = refine_story(events, transcript, [], directory,
            FakeVision([decision(['u000'], uncertain=True)]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]['selected_ranges'], [{'start': 0, 'end': 6}])
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertTrue(result[0]['minimal_context_ranges'])

    def test_generic_atmosphere_is_review_hint_without_keep_protection(self):
        directory, events, transcript = fixture()
        raw = decision(['u000', 'u002'])
        raw['atmosphere_units'] = ['u001']
        result = refine_story(events, transcript, [], directory, FakeVision([raw]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]['atmosphere_review_units'], ['u001'])
        self.assertNotIn('protected_atmosphere_ranges', result[0])
        self.assertFalse(any(r['start'] < 12 and r['end'] > 6 for r in result[0]['selected_ranges']))
        self.assertTrue(result[0]['selection_needs_adjudication'])

    def test_reaction_boolean_without_concrete_current_frame_proof_is_not_protected(self):
        directory, events, transcript = fixture()
        raw = decision(['u000', 'u002', 'u003'])
        raw['omit_units'][0]['reaction_or_humor'] = True
        proof = {'decisions': [{'unit': 'u001', 'keep': True, 'story_change': False,
            'current_episode_story': True, 'confidence': .98, 'reaction_or_humor': True,
            'evidence': 'The current scene has generic atmosphere.', 'retained_witness': 'none'}]}
        result = refine_story(events, transcript, [], directory, FakeVision([raw, proof]), lambda *a: None, lambda: False)
        self.assertTrue(result[0]['analysis_unresolved'])
        self.assertNotIn('protected_atmosphere_ranges', result[0])
        self.assertNotIn('verified_current_story_ranges', result[0])
        self.assertFalse(any(r['start'] < 12 and r['end'] > 6 for r in result[0]['selected_ranges']))

    def test_specific_current_reaction_frame_proof_survives_and_cache_validates(self):
        from app.vision import storyboard_times
        directory, events, transcript = fixture()
        frame = next(i+1 for i, t in enumerate(storyboard_times(0, 20, [], transcript)) if 6 <= t < 12)
        raw = decision(['u000', 'u002', 'u003'])
        raw['omit_units'][0]['reaction_or_humor'] = True
        proof = {'decisions': [{'unit': 'u001', 'keep': True, 'story_change': False,
            'current_episode_story': True, 'confidence': .98, 'reaction_or_humor': True,
            'reaction_kind': 'character_reaction', 'frame_indices': [frame],
            'evidence': 'Her mouth opens in surprise and her gaze turns toward the speaker.', 'retained_witness': 'none'}]}
        result = refine_story(events, transcript, [], directory, FakeVision([raw, proof]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]['verified_current_story_ranges'], [{'start': 6, 'end': 12}])
        saved = json.loads(next((directory/'story_refinement').glob('*.json')).read_text('utf-8'))
        self.assertTrue(_valid_cache(saved, saved['signature'], events[0]))

    def test_verified_empty_selection_is_not_expanded_by_credit_dialogue_or_cleanup(self):
        directory, events, transcript = fixture()
        events[0].update(kind='ending', importance=1, credit_montage=True,
                         selected_ranges=[], selection_empty_verified=True, selection_status='accepted')
        self.assertEqual(preserve_dialogue_in_credits(events, transcript)[0]['selected_ranges'], [])
        def old_cleanup(values, *args):
            result = copy.deepcopy(values)
            result[0]['selected_ranges'] = [{'start': 0, 'end': 20}]
            return result
        with patch('app.production.clean_sequences', side_effect=old_cleanup):
            result = clean_credit_continuations(events, transcript, [], directory, object(), lambda *a: None, lambda: False)
        self.assertEqual(result[0]['selected_ranges'], [])
        self.assertTrue(result[0]['selection_empty_verified'])

    def test_failed_omission_review_does_not_restore_full_event(self):
        directory, events, transcript = fixture()
        class FailureVision:
            def __init__(self): self.calls = 0
            def query(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1: return decision(['u000', 'u002'])
                raise RuntimeError('invalid review')
        result = refine_story(events, transcript, [], directory, FailureVision(), lambda *a: None, lambda: False)
        self.assertEqual(result[0]['selected_ranges'], [])
        self.assertTrue(result[0]['analysis_unresolved'])

    def test_control_failure_in_credits_and_omission_review_propagates(self):
        from app.deepseek import RemoteError
        for transcript in [fixture()[2], {'words': [], 'segments': []}]:
            directory, events, _ = fixture()
            class FailureVision:
                def query(self, *args, **kwargs): raise RemoteError('controlled failure')
            with self.assertRaises(RemoteError):
                refine_story(events, transcript, [], directory, FailureVision(), lambda *a: None, lambda: False)

    def test_empty_unresolved_cache_is_valid_but_unexplained_empty_is_not(self):
        from app.story import STORY_VERSION
        directory, events, transcript = fixture()
        result = refine_story(events, transcript, [], directory,
            FakeVision([decision(['u000'], uncertain=True)]), lambda *a: None, lambda: False)
        saved = json.loads(next((directory/'story_refinement').glob('*.json')).read_text('utf-8'))
        self.assertTrue(_valid_cache(saved, saved['signature'], events[0]))
        invalid = copy.deepcopy(saved)
        invalid['event'].pop('analysis_unresolved')
        self.assertFalse(_valid_cache(invalid, saved['signature'], events[0]))

    def test_high_confidence_visual_credits_skip_narrative_query(self):
        directory, events, _ = fixture()
        visual = directory / "visual"
        visual.mkdir(exist_ok=True)
        (visual / "event_0000.jpg").write_bytes(b"saved visual evidence")
        events[0]["requires"] = ["old-context"]
        vision = FakeVision([{"credit_montage": True, "continuous_narrative": False, "confidence": 0.95}])
        result = refine_story(events, {"words": [], "segments": []}, [], directory, vision, lambda *a: None, lambda: False)
        self.assertTrue(result[0]["credit_montage"])
        self.assertEqual(result[0]["kind"], "opening")
        self.assertEqual(result[0]["importance"], 1)
        self.assertEqual(result[0]["requires"], [])
        self.assertEqual(len(vision.calls), 1)
        self.assertIsNotNone(vision.calls[0][1])
        self.assertNotIn("Персонажи", vision.calls[0][0])

    def test_meaningful_continuous_narrative_in_credits_remains(self):
        directory, events, transcript = fixture()
        visual = directory / "visual"
        visual.mkdir(exist_ok=True)
        (visual / "event_0000.jpg").write_bytes(b"visual evidence")
        events[0]["kind"] = "opening"
        vision = FakeVision([{"credit_montage": True, "continuous_narrative": True, "confidence": 0.95},
                             decision(["u000", "u002"])])
        result = refine_story(events, transcript, [], directory, vision, lambda *a: None, lambda: False)
        self.assertFalse(result[0].get("credit_montage", False))
        self.assertEqual(result[0]["importance"], 4)
        self.assertEqual(len(vision.calls), 3)
        self.assertTrue(result[0]['contains_credits'])
        self.assertEqual(result[0]['credits_kind'], 'opening')

    def test_mixed_production_text_marker_is_independent_from_pure_credits(self):
        directory, events, _ = fixture()
        (directory/'visual').mkdir(exist_ok=True)
        Image.new('RGB', (48, 27)).save(directory/'visual/event_0000.jpg')
        vision = FakeVision([credit(False, True), decision(['u000'])])
        result = refine_story(events, {'words':[], 'segments':[]}, [], directory, vision, lambda *a:None, lambda:False)
        self.assertTrue(result[0]['contains_credits'])
        self.assertFalse(result[0].get('credit_montage', False))
        self.assertEqual(result[0]['kind'], 'story')
        self.assertIn('contains_credits', vision.schemas[0]['required'])

    def test_credit_classifier_threshold_and_malformed_boolean(self):
        self.assertFalse(_credit_decision({"credit_montage": True, "continuous_narrative": False, "confidence": 0.8}))
        with self.assertRaises(ValueError):
            _credit_decision({"credit_montage": "true", "continuous_narrative": False, "confidence": 0.9})
        with self.assertRaises(ValueError):
            _credit_decision({**credit(False), 'contains_credits': 'true'})

    def test_preserved_opening_dialogue_keeps_opening_context(self):
        _, events, _ = fixture()
        events[0].update(kind='opening', credit_montage=True)
        transcript = {'segments':[{'start':1,'end':2,'text':'Придёшь?'}, {'start':3,'end':4,'text':'Да.'}],
                      'words':[{'start':3,'end':4,'text':'Да.','probability':.9}]}
        result = preserve_dialogue_in_credits(events, transcript)
        self.assertEqual(result[0]['credits_kind'], 'opening')
        self.assertEqual(result[0]['kind'], 'story')

    def test_refinement_thinking_profile_invalidates_cached_content(self):
        directory, events, transcript = fixture()
        refine_story(events, transcript, [], directory, FakeVision([decision(['u000'])]), lambda *a:None, lambda:False)
        changed = FakeVision([decision(['u002'])])
        changed.thinking = True
        result = refine_story(events, transcript, [], directory, changed, lambda *a:None, lambda:False)
        self.assertEqual(len(changed.calls), 2)
        self.assertTrue(any(r['start']<=12 and r['end']>=19 for r in result[0]['selected_ranges']))

    def test_checkpoint_reuse_and_source_identity_change(self):
        directory, events, transcript = fixture()
        first = FakeVision([decision(["u000", "u002"])])
        refine_story(events, transcript, [], directory, first, lambda *a: None, lambda: False)
        cached = FakeVision([])
        refine_story(events, transcript, [], directory, cached, lambda *a: None, lambda: False)
        self.assertFalse(cached.calls)
        (directory / "analysis.meta.json").write_text(json.dumps({"source": "different", "version": 3}), encoding="utf-8")
        changed = FakeVision([decision(["u000", "u002"])])
        refine_story(events, transcript, [], directory, changed, lambda *a: None, lambda: False)
        self.assertEqual(len(changed.calls), 2)

    def test_cancel_before_any_model_request(self):
        directory, events, transcript = fixture()
        vision = FakeVision([])
        with self.assertRaises(InterruptedError):
            refine_story(events, transcript, [], directory, vision, lambda *a: None, lambda: True)
        self.assertFalse(vision.calls)

    def test_focus_and_story_uncertainty_is_exposed_in_plan(self):
        directory, events, transcript = fixture()
        events[0]["focus_warnings"] = ["Удержан предыдущий говорящий"]
        events[0]["story_warnings"] = ["Сокращение не подтверждено"]
        plan = build_plan({"probe": {"duration": 20, "width": 1920, "height": 1080, "has_audio": True},
                           "transcript": transcript, "events": events, "shots": []})
        self.assertEqual(plan["warnings"], ["event_0000: Удержан предыдущий говорящий", "event_0000: Сокращение не подтверждено"])
