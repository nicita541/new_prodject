import copy
import json
import unittest
import uuid
from unittest.mock import patch

from PIL import Image

from app.config import TEMP
from app.story import _credit_decision, refine_story, clean_credit_continuations, preserve_dialogue_in_credits
from app.planner import build_plan


class FakeVision:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.schemas = []

    def query(self, prompt, image=None, max_tokens=650, schema=None):
        self.calls.append((prompt, image, max_tokens))
        self.schemas.append(schema)
        return self.answers.pop(0)


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
    return directory, events, transcript


def decision(keep, preserve=None, uncertain=False):
    return {"summary": "Он решил вернуться, она согласилась.", "keep_units": keep,
            "preserve_silent_units": preserve or [], "uncertain": uncertain,
            'omit_units':[{'unit':u,'reason':'redundant_exchange'} for u in ['u000','u001','u002','u003']
                          if u not in set(keep) | set(preserve or [])]}


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
    def test_physical_reaction_after_actual_segment_end_survives_margin_review(self):
        from app.pacing import apply_review
        directory,events,_=fixture()
        transcript={'segments':[{'start':3,'end':7,'text':'Действуй!'}],
                    'words':[{'start':3,'end':7,'text':'Действуй!'}]}
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

    def test_incomplete_or_contradictory_omission_partition_preserves_event(self):
        for omissions in [[], [{'unit':'u000','reason':'waiting'}],
                          [{'unit':'u001','reason':'important_action'}]]:
            directory, events, transcript = fixture()
            raw={**decision(['u000','u002']), 'omit_units':omissions}
            result=refine_story(events,transcript,[],directory,FakeVision([raw]),lambda *a:None,lambda:False)
            self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':20}])
            self.assertNotIn('unit_selection_version',result[0])
            self.assertTrue(result[0]['story_warnings'])

    def test_silent_reaction_after_last_word_is_not_trimmed(self):
        directory,events,_=fixture()
        transcript={'segments':[{'start':3,'end':10,'text':'Действуй!'}],
                    'words':[{'start':3,'end':7,'text':'Действуй!'}]}
        raw = {**decision(['u000']), 'omit_units':[{'unit':'u001','reason':'waiting'}]}
        result=refine_story(events,transcript,[],directory,FakeVision([raw]),
                            lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':10}])

    def test_no_current_images_preserves_whole_scene_without_text_only_cutting(self):
        directory,events,transcript=fixture()
        (directory/'visual/event_0000.jpg').unlink()
        vision=FakeVision([])
        result=refine_story(events,transcript,[],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':20}])
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

    def test_unknown_nonlist_and_empty_selection_preserve_with_warnings(self):
        for raw in [decision(["invented"]), {**decision(["u000"]), "keep_units": "u000"}, decision([])]:
            directory, events, transcript = fixture()
            result = refine_story(events, transcript, [], directory, FakeVision([raw]), lambda *a: None, lambda: False)
            self.assertTrue(result[0]["story_warnings"])
            self.assertEqual(result[0]["selected_ranges"], [{"start": 0, "end": 20}])

    def test_silent_narrative_is_not_dropped_when_model_returns_empty_selection(self):
        directory, events, _ = fixture()
        transcript = {"words": [], "segments": []}
        result = refine_story(events, transcript, [], directory, FakeVision([credit(False, False), decision([])]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 0, "end": 20}])

    def test_uncertain_keeps_all_original_units_and_warning(self):
        directory, events, transcript = fixture()
        result = refine_story(events, transcript, [], directory, FakeVision([decision(["u000"], uncertain=True)]), lambda *a: None, lambda: False)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 0, "end": 20}])
        self.assertTrue(result[0]["story_warnings"])
        self.assertTrue(result[0]['selection_uncertain'])

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
        self.assertEqual(len(vision.calls), 2)
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
        self.assertEqual(len(changed.calls), 1)
        self.assertEqual(result[0]['selected_ranges'], [{'start':12, 'end':19}])

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
        self.assertEqual(len(changed.calls), 1)

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
