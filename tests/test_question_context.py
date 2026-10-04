import copy
import unittest

from app.speech_context import protect_speech_context


def fixture():
    events = [{'id': 'q', 'start': 1250, 'end': 1259.5, 'kind': 'story', 'importance': 1, 'requires': [],
               'selected_ranges': [{'start': 1250, 'end': 1251}]},
              {'id': 'a', 'start': 1259.5, 'end': 1265, 'kind': 'story', 'importance': 4, 'requires': [],
               'selected_ranges': [{'start': 1259.74, 'end': 1261.72}]}]
    transcript = {'segments': [{'start': 1256.16, 'end': 1259.32, 'text': 'Что мне тогда брать?'},
                               {'start': 1259.74, 'end': 1261.72, 'text': 'Не ходи туда и всё!'}],
                  'words': [{'start': 1256.16, 'end': 1259.32, 'text': 'Что мне тогда брать?', 'probability': .99},
                            {'start': 1259.74, 'end': 1261.72, 'text': 'Не ходи туда и всё!', 'probability': .99}]}
    return events, transcript


class QuestionContextTests(unittest.TestCase):
    def test_global_redundancy_cannot_leave_retained_answer_without_question(self):
        events,transcript=fixture()
        events[0].update(global_excluded=True, unit_selection_version=1)
        events[1]['unit_selection_version']=1
        result=protect_speech_context(events,transcript)
        self.assertNotIn('global_excluded',result[0])
        self.assertEqual(result[0]['selected_ranges'],[{'start':1255.91,'end':1259.5}])

    def test_retained_answer_restores_actual_question_across_event_boundary(self):
        events, transcript = fixture()
        original = copy.deepcopy(events)
        result = protect_speech_context(events, transcript)
        self.assertEqual(events, original)
        self.assertEqual(result[0]['selected_ranges'], [{'start': 1255.91, 'end': 1259.5}])
        self.assertEqual(result[0]['importance'], 4)
        self.assertEqual(result[0]['question_pair_protections'][0]['start'], 1256.16)
        self.assertEqual(protect_speech_context(result, transcript), result)

    def test_distant_unselected_or_low_confidence_question_is_not_restored(self):
        for mutation in ('distant', 'unselected', 'low_probability', 'no_question'):
            events, transcript = fixture()
            if mutation == 'distant': transcript['segments'][1]['start'] = 1265
            if mutation == 'unselected': events[1]['selected_ranges'] = [{'start': 1263, 'end': 1265}]
            if mutation == 'low_probability': transcript['words'][0]['probability'] = .2
            if mutation == 'no_question': transcript['segments'][0]['text'] = 'Что мне тогда брать.'
            self.assertEqual(protect_speech_context(events, transcript), events)

    def test_confirmed_pure_credit_question_does_not_reopen_excluded_montage(self):
        events, transcript = fixture()
        events[0].update(credit_montage=True, kind='opening')
        self.assertEqual(protect_speech_context(events, transcript), events)
