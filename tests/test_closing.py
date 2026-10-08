import copy
import json
import unittest
import uuid
from unittest.mock import patch

from PIL import Image

from app.closing import CLOSING_VERSION, refine_closing_novelty
from app.config import TEMP


class Vision:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.counts = []

    def token_count(self, text):
        count = len(text) // 2
        self.counts.append(count)
        return count

    def query(self, prompt, image, max_tokens, schema):
        self.calls.append((prompt, image, max_tokens, schema))
        return self.answers.pop(0)


def decision(nonstory, new, confidence=.95, uncertain=False, dialogue=None, titles=None, visible=None):
    return {'nonstory_units':nonstory, 'new_story_units':new, 'confidence':confidence,
            'uncertain':uncertain, 'reason':'Previously established routines repeated as musical montage.',
            'meaningful_dialogue_units':dialogue or [], 'narrated_title_units':titles or [], 'visible_title_units':visible or []}


def fixture():
    directory = TEMP / ('closing_' + uuid.uuid4().hex)
    directory.mkdir()
    (directory/'visual').mkdir()
    source = directory/'исходная серия.mkv'
    source.write_bytes(b'unchanged source')
    (directory/'source.json').write_text(json.dumps({'path':str(source)}), encoding='utf-8')
    events = [{'id':'office', 'start':0, 'end':80, 'kind':'story', 'importance':4,
               'summary':'He returns to the store after work and talks to the cashier.',
               'requires':[], 'selected_ranges':[{'start':0,'end':80}]},
              {'id':'mixed', 'start':80, 'end':90, 'kind':'story', 'importance':4,
               'summary':'An answer resolves the preceding question, then production credits.',
               'contains_credits':True, 'credits_kind':'ending', 'requires':['office'],
               'selected_ranges':[{'start':80,'end':90}]},
              {'id':'recap', 'start':90, 'end':100, 'kind':'story', 'importance':4,
               'summary':'A musical montage of commute, smoking and familiar shop encounters.',
               'requires':[], 'selected_ranges':[{'start':90,'end':100}]}]
    for event in events:
        Image.new('RGB', (48, 27), 'gray').save(directory/'visual'/(event['id']+'.jpg'))
    return directory, events, source


class ClosingTests(unittest.TestCase):
    def run_closing(self, directory, events, answers, transcript=None, shots=None):
        vision = Vision(answers)
        result = refine_closing_novelty(events, transcript or {'words':[], 'segments':[]},
            shots or [], directory, vision, lambda *a:None, lambda:False)
        return result, vision

    def test_recaps_removed_only_after_ending_anchor_and_office_unchanged(self):
        directory, events, source = fixture()
        original = copy.deepcopy(events)
        result, vision = self.run_closing(directory, events,
            [decision(['u001'], ['u000']), decision(['u000','u001'], [])], shots=[{'start':85}, {'start':95}])
        self.assertEqual(result[0], events[0])
        self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':85}])
        self.assertTrue(result[2]['credit_montage'])
        self.assertEqual(result[2]['importance'], 1)
        self.assertEqual(result[2]['excluded_closing_units'], ['u000','u001'])
        self.assertEqual(events, original)
        self.assertEqual(source.read_bytes(), b'unchanged source')
        self.assertIn(events[0]['summary'], vision.calls[1][0])
        self.assertNotIn(events[2]['summary'], vision.calls[1][0])
        self.assertEqual(len(vision.calls), 2)
        self.assertIn('uncertain', vision.calls[0][3]['required'])

    def test_quiet_tail_and_opening_are_not_assumed_to_be_ending(self):
        directory, events, _ = fixture()
        events[1].update(credits_kind='opening')
        result, vision = self.run_closing(directory, events, [decision([], ['u000']), decision([], ['u000'])])
        self.assertFalse(any(event.get('credit_montage') for event in result))
        self.assertTrue(all('UNCONFIRMED' in call[0] for call in vision.calls))
        events[1].pop('contains_credits')
        result, vision = self.run_closing(directory, events, [decision([], ['u000']), decision([], ['u000'])])
        self.assertFalse(any(event.get('credit_montage') for event in result))

    def test_actual_question_and_answer_survive_erroneous_nonstory_decision(self):
        directory, events, _ = fixture()
        transcript = {'segments':[{'start':81,'end':83,'text':'Ты придёшь?'},
                                  {'start':84,'end':86,'text':'Нет, я работаю.'}],
                      'words':[{'start':81,'end':83,'text':'Ты придёшь?', 'probability':.9},
                               {'start':84,'end':86,'text':'Нет,', 'probability':.9}]}
        result, _ = self.run_closing(directory, events,
            [decision(['u000','u001','u002'], []), decision(['u000'], [])], transcript)
        self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':86}])
        self.assertFalse(result[1].get('credit_montage', False))
        self.assertEqual(result[1]['excluded_closing_units'], ['u002'])
        self.assertTrue(any('реплика' in warning for warning in result[1]['story_warnings']))

    def test_new_silent_consequence_inside_credit_window_is_restored(self):
        directory, events, _ = fixture()
        events[1].update(credit_montage=True, kind='ending', importance=1,
                         selected_ranges=[{'start':80,'end':82}])
        result, _ = self.run_closing(directory, events,
            [decision(['u000'], ['u001']), decision(['u000'], [])], shots=[{'start':85}])
        self.assertFalse(result[1]['credit_montage'])
        self.assertEqual(result[1]['kind'], 'story')
        self.assertEqual(result[1]['importance'], 4)
        self.assertEqual(result[1]['selected_ranges'], [{'start':85,'end':90}])

    def test_verified_current_story_range_survives_later_closing_omission(self):
        directory,events,_=fixture()
        events[1].update(credit_montage=True,kind='ending',importance=1,
                         selected_ranges=[{'start':80,'end':82}],
                         verified_current_story_ranges=[{'start':85,'end':90}])
        result,_=self.run_closing(directory,events,
            [decision(['u000','u001'],[]),decision(['u000','u001'],[])],shots=[{'start':85}])
        self.assertEqual(result[1]['selected_ranges'],[{'start':85,'end':90}])
        self.assertFalse(result[1]['credit_montage'])
        self.assertEqual(result[1]['kind'],'story')

    def test_invalid_partitions_and_uncertainty_preserve_existing_ranges(self):
        failures = [[], decision(['invented'], []), decision([], []),
                    decision(['u000'], ['u000']), decision(['u000','u000'], []),
                    decision(['u000'], [], uncertain=True), decision(['u000'], [], confidence=.8),
                    {**decision(['u000'], []), 'confidence':float('nan')},
                    {**decision(['u000'], []), 'uncertain':'false'}]
        for failure in failures:
            with self.subTest(failure=failure):
                directory, events, _ = fixture()
                result, _ = self.run_closing(directory, events[:2], [failure])
                self.assertEqual(result[1]['selected_ranges'], events[1]['selected_ranges'])
                self.assertFalse(result[1].get('credit_montage', False))
                self.assertTrue(result[1]['story_warnings'])

    def test_context_budget_preserves_chronology_and_never_exceeds_limit(self):
        directory, events, _ = fixture()
        prior = [{**events[0], 'id':f'fact_{i}', 'start':i, 'end':i+1,
                  'summary':f'Chronological new event {i} ' + 'long detail '*80} for i in range(50)]
        events = prior + [{**events[1], 'start':50,'end':60,'selected_ranges':[{'start':50,'end':60}]}]
        result, vision = self.run_closing(directory, events, [decision(['u000'], [])])
        self.assertTrue(result[-1]['credit_montage'])
        prompt = vision.calls[0][0]
        self.assertLessEqual(vision.token_count(prompt), 5300)
        self.assertLess(prompt.index('fact_0'), prompt.index('fact_49'))
        self.assertGreater(vision.counts[0], 5300)

    def test_cached_decisions_invalidate_prior_image_source_and_thinking(self):
        directory, events, source = fixture()
        events = events[:2]
        answer = decision(['u000'], [])
        self.run_closing(directory, events, [answer])
        result, cached = self.run_closing(directory, events, [])
        self.assertFalse(cached.calls)
        self.assertEqual(result[1]['closing_refinement_version'], CLOSING_VERSION)
        events[0]['summary'] = 'New earlier cause changes comparison.'
        _, changed = self.run_closing(directory, events, [answer])
        self.assertEqual(len(changed.calls), 1)
        Image.new('RGB', (48,27), 'red').save(directory/'visual/mixed.jpg')
        _, changed = self.run_closing(directory, events, [answer])
        self.assertEqual(len(changed.calls), 1)
        source.write_bytes(b'changed source identity')
        _, changed = self.run_closing(directory, events, [answer])
        self.assertEqual(len(changed.calls), 1)
        thinking = Vision([answer])
        thinking.thinking = True
        refine_closing_novelty(events, {'words':[],'segments':[]}, [], directory, thinking, lambda *a:None, lambda:False)
        self.assertEqual(len(thinking.calls), 1)

    def test_cancel_after_model_response_never_saves_partial_decision(self):
        directory, events, _ = fixture()
        original = copy.deepcopy(events)
        vision = Vision([decision(['u000'], [])])
        with self.assertRaises(InterruptedError):
            refine_closing_novelty(events, {'words':[],'segments':[]}, [], directory, vision,
                lambda *a:None, lambda:bool(vision.calls))
        self.assertEqual(events, original)
        self.assertFalse(list((directory/'closing_novelty').glob('*.json')))

    def test_missing_current_images_preserves_silent_action(self):
        directory, events, _ = fixture()
        (directory/'visual/mixed.jpg').unlink()
        result, vision = self.run_closing(directory, events[:2], [])
        self.assertEqual(result[1]['selected_ranges'], events[1]['selected_ranges'])
        self.assertTrue(result[1]['story_warnings'])
        self.assertFalse(vision.calls)

    def test_production_closing_uses_each_current_chunk_and_original_unit_ids(self):
        directory, events, _ = fixture()
        events = events[:2]
        events[1]['units'] = [{'id':'c000_u000','start':80,'end':85,'text':''},
                              {'id':'c001_u000','start':85,'end':90,'text':''}]
        events[1]['analysis_chunks'] = [{'start':80,'end':85}, {'start':85,'end':90}]
        for number in range(2):
            Image.new('RGB',(48,27),('red','blue')[number]).save(
                directory/'visual'/f'mixed_chunk_{number:03d}.jpg')
        result, vision = self.run_closing(directory, events,
            [decision(['c000_u000'],[]), decision([],['c001_u000'])])
        self.assertEqual(result[1]['selected_ranges'],[{'start':85,'end':90}])
        self.assertEqual([call[1].name for call in vision.calls],
                         ['mixed_chunk_000.jpg','mixed_chunk_001.jpg'])
        for number,call in enumerate(vision.calls):
            ids=call[3]['properties']['new_story_units']['items']['enum']
            self.assertEqual(ids,[f'c{number:03d}_u000'])
            self.assertLessEqual(vision.token_count(call[0]),4000)
        _, cached = self.run_closing(directory, events, [])
        self.assertFalse(cached.calls)
        Image.new('RGB',(48,27),'green').save(directory/'visual/mixed_chunk_001.jpg')
        _, changed = self.run_closing(directory, events,
            [decision(['c000_u000'],[]), decision([],['c001_u000'])])
        self.assertEqual(len(changed.calls),2)

    def test_incomplete_current_closing_coverage_requires_adjudication(self):
        directory, events, _ = fixture()
        events = events[:2]
        events[1]['units'] = [{'id':'c000_u000','start':80,'end':85,'text':''},
                              {'id':'c001_u000','start':85,'end':90,'text':''}]
        events[1]['analysis_chunks'] = [{'start':80,'end':85}, {'start':85,'end':90}]
        Image.new('RGB',(48,27),'red').save(directory/'visual/mixed_chunk_000.jpg')
        result, vision = self.run_closing(directory, events, [])
        self.assertFalse(vision.calls)
        self.assertEqual(result[1]['selected_ranges'],events[1]['selected_ranges'])
        self.assertTrue(result[1]['selection_needs_adjudication'])

    def test_no_anchor_discovers_silent_montage_then_verifies_narrated_title(self):
        directory, events, source = fixture()
        events[1].pop('contains_credits')
        events[1].pop('credits_kind')
        title = {**events[2], 'id':'title', 'start':100, 'end':110,
                 'selected_ranges':[{'start':100, 'end':110}]}
        events.append(title)
        Image.new('RGB', (48,27)).save(directory/'visual/title.jpg')
        transcript = {'segments':[{'start':81,'end':83,'text':'Ты придёшь?'},
                                  {'start':84,'end':86,'text':'Нет.'},
                                  {'start':101,'end':105,'text':'История одного неожиданного вечера.'}],
                      'words':[{'start':81,'end':83,'text':'Ты придёшь?', 'probability':.9},
                               {'start':84,'end':86,'text':'Нет.', 'probability':.9},
                               *[{'start':101+i,'end':102+i,'text':word,'probability':.995}
                                 for i,word in enumerate(['История','одного','неожиданного','вечера.'])]]}
        vision = Vision([decision(['u000','u001','u002'], []),
                         decision(['u000','u001'], [], titles=['u000'], visible=['u000']),
                         {'visible_production_title':True,'meaningful_character_dialogue':False,'confidence':.95}])
        def frames(src, start, end, shots, text, destination, cancelled):
            Image.new('RGB', (48,27)).save(destination)
            return [start,end]
        with patch('app.analysis.storyboard', side_effect=frames) as images:
            result = refine_closing_novelty(events, transcript, [{'start':94},{'start':97}],
                directory, vision, lambda *a:None, lambda:False)
        self.assertEqual(result[0], events[0])
        self.assertEqual(result[1], events[1])
        self.assertTrue(result[2]['closing_novelty_anchor'])
        self.assertTrue(result[2]['credit_montage'])
        self.assertTrue(result[3]['credit_montage'])
        self.assertIn('UNCONFIRMED', vision.calls[0][0])
        self.assertIn('established ending', vision.calls[1][0])
        self.assertEqual(images.call_args.args[0], source)
        self.assertEqual(images.call_args.args[1:3], (100.8,105))

    def test_spoken_title_requires_current_visible_title_confirmation(self):
        for visible in (False, True):
            with self.subTest(visible=visible):
                directory, events, _ = fixture()
                transcript = {'segments':[{'start':81,'end':85,'text':'Объявление нового вечера.'}],
                              'words':[{'start':81+i,'end':82+i,'text':str(i),'probability':.995}
                                       for i in range(3)]}
                answers = [decision(['u000','u001'], [], titles=['u000'], visible=['u000'] if visible else [])]
                if visible:
                    answers.append({'visible_production_title':False,'meaningful_character_dialogue':False,'confidence':.95})
                vision = Vision(answers)
                def frames(src, start, end, shots, text, destination, cancelled):
                    Image.new('RGB', (48,27)).save(destination)
                with patch('app.analysis.storyboard', side_effect=frames):
                    result = refine_closing_novelty(events[:2], transcript, [], directory, vision, lambda *a:None, lambda:False)
                self.assertFalse(result[1].get('credit_montage', False))
                self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':85}])

    def test_visible_narrated_title_is_verified_even_when_narrated_list_is_empty(self):
        directory, events, source = fixture()
        transcript = {'segments':[{'start':81,'end':85,'text':'История одного нового вечера.'}],
                      'words':[{'start':81+i,'end':82+i,'text':word,'probability':.995}
                               for i,word in enumerate(['История','одного','нового','вечера.'])]}
        vision = Vision([decision(['u000','u001'], [], visible=['u000']),
                         {'visible_production_title':True,
                          'meaningful_character_dialogue':False,'confidence':.95}])
        def frames(src, start, end, shots, text, destination, cancelled):
            Image.new('RGB', (48,27), 'blue').save(destination)
        original = copy.deepcopy(events)
        with patch('app.analysis.storyboard', side_effect=frames) as images:
            result = refine_closing_novelty(events[:2], transcript, [], directory, vision,
                                           lambda *a:None, lambda:False)
        self.assertTrue(result[1]['credit_montage'])
        self.assertEqual(result[1]['excluded_closing_units'], ['u000','u001'])
        self.assertEqual(len(vision.calls), 2)
        self.assertEqual(images.call_count, 1)
        self.assertEqual(images.call_args.args[0], source)
        self.assertEqual(images.call_args.args[1:3], (80.8,85))
        title_prompt, title_image, _, schema = vision.calls[1]
        self.assertIn(transcript['segments'][0]['text'], title_prompt)
        self.assertTrue(title_image.is_relative_to(directory/'closing_novelty'))
        self.assertTrue(title_image.is_file())
        self.assertIn('meaningful_character_dialogue', schema['required'])
        self.assertEqual(events, original)
        # A confirmed answer is reusable without another model or image request.
        with patch('app.analysis.storyboard') as cached_images:
            cached, cached_vision = self.run_closing(directory, events[:2], [], transcript)
        self.assertTrue(cached[1]['credit_montage'])
        self.assertFalse(cached_vision.calls)
        cached_images.assert_not_called()

    def test_visible_title_claim_does_not_remove_speech_when_current_image_is_signage(self):
        directory, events, _ = fixture()
        transcript = {'segments':[{'start':81,'end':85,'text':'Встретимся у нашего магазина.'}],
                      'words':[{'start':81+i,'end':82+i,'text':word,'probability':.98}
                               for i,word in enumerate(['Встретимся','у','нашего','магазина.'])]}
        vision = Vision([decision(['u000','u001'], [], visible=['u000']),
                         {'visible_production_title':False,
                          'meaningful_character_dialogue':True,'confidence':.95}])
        def frames(src, start, end, shots, text, destination, cancelled):
            Image.new('RGB', (48,27), 'green').save(destination)
        with patch('app.analysis.storyboard', side_effect=frames) as images:
            result = refine_closing_novelty(events[:2], transcript, [], directory, vision,
                                           lambda *a:None, lambda:False)
        self.assertEqual(images.call_count, 1)
        self.assertEqual(len(vision.calls), 2)
        self.assertIn('Street/shop/train signs', vision.calls[1][0])
        self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':85}])
        self.assertFalse(result[1].get('credit_montage', False))
        self.assertEqual(result[1]['excluded_closing_units'], ['u001'])

    def test_raw_dialogue_label_is_overridden_only_by_confirmed_current_production_title(self):
        checks = [({'visible_production_title':True,'meaningful_character_dialogue':False,'confidence':.95}, True),
                  ({'visible_production_title':False,'meaningful_character_dialogue':False,'confidence':.95}, False),
                  ({'visible_production_title':True,'meaningful_character_dialogue':True,'confidence':.95}, False),
                  ({'visible_production_title':True,'meaningful_character_dialogue':False,'confidence':.8}, False)]
        for current_check, should_remove in checks:
            with self.subTest(current_check=current_check):
                directory, events, _ = fixture()
                transcript = {'segments':[{'start':81,'end':85,'text':'Начало следующей истории.'}],
                              'words':[{'start':81+i,'end':82+i,'text':word,'probability':.99}
                                       for i,word in enumerate(['Начало','следующей','истории.'])]}
                vision = Vision([decision(['u000','u001'], [], dialogue=['u000'], visible=['u000']), current_check])
                def frames(src, start, end, shots, text, destination, cancelled):
                    Image.new('RGB', (48,27)).save(destination)
                with patch('app.analysis.storyboard', side_effect=frames) as images:
                    result = refine_closing_novelty(events[:2], transcript, [], directory, vision,
                                                   lambda *a:None, lambda:False)
                self.assertEqual(images.call_count, 1)
                self.assertEqual(bool(result[1].get('credit_montage')), should_remove)
                if not should_remove:
                    self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':85}])
                    self.assertEqual(result[1]['excluded_closing_units'], ['u001'])

    def test_protected_ending_question_answer_cannot_be_overridden_by_visible_title_claim(self):
        directory, events, _ = fixture()
        transcript = {'segments':[{'start':81,'end':83,'text':'Ты придёшь?'},
                                  {'start':84,'end':86,'text':'Нет, работаю.'}],
                      'words':[{'start':81,'end':82,'text':'Ты','probability':.98},
                               {'start':82,'end':83,'text':'придёшь?','probability':.98},
                               {'start':84,'end':85,'text':'Нет,','probability':.99},
                               {'start':85,'end':86,'text':'работаю.','probability':.99}]}
        vision = Vision([decision(['u000','u001','u002'], [],
                                 dialogue=['u000','u001'], visible=['u000','u001'])])
        with patch('app.analysis.storyboard') as images:
            result = refine_closing_novelty(events[:2], transcript, [], directory, vision,
                                           lambda *a:None, lambda:False)
        images.assert_not_called()
        self.assertEqual(len(vision.calls), 1)
        self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':86}])
        self.assertEqual(result[1]['excluded_closing_units'], ['u002'])
        self.assertFalse(result[1].get('credit_montage', False))

    def test_eight_word_character_reply_is_protected_even_if_classified_as_visible_title(self):
        directory, events, _ = fixture()
        text = 'Я останусь здесь потому что обещал помочь тебе.'
        transcript = {'segments':[{'start':81,'end':85,'text':text}],
                      'words':[{'start':81+i*.5,'end':81.5+i*.5,'text':word,'probability':.99}
                               for i,word in enumerate(text.split())]}
        vision = Vision([decision(['u000','u001'], [], visible=['u000'])])
        with patch('app.analysis.storyboard') as images:
            result = refine_closing_novelty(events[:2], transcript, [], directory, vision,
                                           lambda *a:None, lambda:False)
        images.assert_not_called()
        self.assertEqual(len(vision.calls), 1)
        self.assertEqual(result[1]['selected_ranges'], [{'start':80,'end':85}])
        self.assertEqual(result[1]['excluded_closing_units'], ['u001'])
        self.assertFalse(result[1].get('credit_montage', False))

    def test_mid_episode_ending_label_does_not_route_subsequent_story(self):
        directory, events, _ = fixture()
        early = {**events[1], 'start':20,'end':30,'selected_ranges':[{'start':20,'end':30}]}
        speech = {'segments':[{'start':91,'end':99,'text':'Подробное новое объяснение.'}],
                  'words':[{'start':91,'end':99,'text':'Объяснение','probability':.9}]}
        result, vision = self.run_closing(directory, [events[0],early,events[2]], [], speech)
        self.assertEqual(result, [events[0],early,events[2]])
        self.assertFalse(vision.calls)
