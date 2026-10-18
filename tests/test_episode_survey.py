"""Sparse discovery contracts; no model, network or media subprocesses."""
import copy
import json
import shutil
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.episode_survey import survey_windows, survey_episode, build_episode_map, _speech_rows


SHA = 'a'*64
SCENES = [{'id': 'a', 'start': 0., 'end': 10.},
          {'id': 'quiet', 'start': 10., 'end': 80.},
          {'id': 'z', 'start': 80., 'end': 90.}]
ASR = {'segments': [{'start': 1., 'end': 2., 'text': 'Начало'},
                    {'start': 85., 'end': 86., 'text': 'Конец'}], 'words': []}


class Vision:
    max_current_frames = 8
    model = 'authored-test'

    def __init__(self):
        self.requests = []
        self.bad = False

    def query(self, prompt, image, **kwargs):
        self.requests.append((prompt, image, kwargs))
        if image is None:
            return {'hypotheses': [], 'unanswered_questions': ['Inspect silent action more densely']}
        catalog = json.loads(prompt.split('\n', 1)[1])
        rows = [{'window_id': w['id'], 'summary': 'Sparse source observation', 'uncertain': True}
                for w in catalog]
        if self.bad:
            rows[0]['window_id'] = 'foreign'
        return {'observations': rows}


class Journal:
    def __init__(self):
        self.saved = {}

    def run(self, name, inputs, callback, producer):
        key = (name, json.dumps(inputs, sort_keys=True))
        if key not in self.saved:
            self.saved[key] = callback()
        return copy.deepcopy(self.saved[key])


class EpisodeSurveyTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parents[1]/'temp'/('survey-test-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.image = self.directory/'frame.jpg'
        Image.new('RGB', (320, 180)).save(self.image)
        self.counter = 0

    def tearDown(self):
        shutil.rmtree(self.directory)

    def frames(self, source, start, end, directory, cancelled, times):
        return ({'sha256': SHA}, [{'time': t, 'requested_time': t, 'pts': round(t*1000),
                'time_base': '1/1000', 'sha256': 'b'*64} for t in times], [self.image]*len(times))

    def survey(self, vision=None, **kwargs):
        with patch('app.episode_survey.source_frame_files', self.frames):
            return survey_episode(self.directory/'source.mp4', SCENES, ASR, self.directory,
                                  vision or Vision(), lambda: False, source_evidence=SHA, **kwargs)

    def test_quiet_middle_has_full_windows_and_true_source_neighbors(self):
        windows = survey_windows(SCENES, ASR, SHA)
        quiet = [w for w in windows if w['scene_id'] == 'quiet']
        self.assertEqual(len(quiet), 3)
        self.assertEqual((quiet[0]['start'], quiet[-1]['end']), (10., 80.))
        self.assertTrue(all(w['original_before_id'] == 'a' and w['original_after_id'] == 'z' for w in quiet))
        self.assertTrue(all(w['ASR']['segments'] == [] for w in quiet))
        self.assertNotEqual(windows[0]['id'], survey_windows(SCENES, ASR, 'c'*64)[0]['id'])

    def test_shared_batches_respect_capacity_without_missing_coverage(self):
        vision = Vision()
        result = self.survey(vision)
        self.assertEqual(len(vision.requests), 2)
        self.assertEqual(len(result['observations']), 5)
        self.assertEqual(set(result['coverage']), {w['id'] for w in result['windows']})
        for prompt, _, _ in vision.requests:
            self.assertLessEqual(sum(len(w['frames']) for w in json.loads(prompt.split('\n', 1)[1])), 8)
        self.assertNotIn('selected_ranges', result)

    def test_warm_stages_issue_no_queries_and_empty_map_is_cached(self):
        vision, journal = Vision(), Journal()
        result = self.survey(vision, journal=journal)
        self.survey(vision, journal=journal)
        mapped = build_episode_map(result, ASR, self.directory, vision, lambda: False, journal=journal)
        build_episode_map(result, ASR, self.directory, vision, lambda: False, journal=journal)
        self.assertEqual(len(vision.requests), 3)
        self.assertEqual(mapped['hypotheses'], [])
        payload = json.loads(vision.requests[-1][0].split('\n', 1)[1])
        self.assertEqual(payload['exact_ASR'], ASR['segments'])
        self.assertEqual(len(payload['catalog']), 5)
        self.assertTrue(all('frames' not in w and 'ASR' not in w for w in payload['catalog']))

    def test_sparse_observation_contract_cannot_expand_into_unbounded_questions(self):
        from app.episode_survey import _validate
        vision = Vision()
        result = self.survey(vision)
        for prompt, _, kwargs in vision.requests:
            catalog = json.loads(prompt.split('\n', 1)[1])
            bounded = {'observations': [{'window_id': w['id'], 'summary': 'Uncertain visible state',
                                        'uncertain': True} for w in catalog]}
            _validate(bounded, kwargs['schema'])
            unbounded = copy.deepcopy(bounded)
            unbounded['observations'][0]['unanswered_questions'] = ['Repeated speculation']*2048
            with self.assertRaises(ValueError):
                _validate(unbounded, kwargs['schema'])
        self.assertTrue(all(row['uncertain'] for row in result['observations']))
        # Full-map ownership still receives every uncertain physical window and
        # exact speech; removing speculative local questions hides no source fact.
        build_episode_map(result, ASR, self.directory, vision, lambda: False)
        payload = json.loads(vision.requests[-1][0].split('\n', 1)[1])
        self.assertEqual(len(payload['catalog']), len(result['windows']))
        self.assertTrue(all(row['observation']['uncertain'] for row in payload['catalog']))
        self.assertEqual(payload['exact_ASR'], ASR['segments'])

    def test_unknown_observation_ref_rejected(self):
        vision = Vision()
        vision.bad = True
        with self.assertRaises(ValueError):
            self.survey(vision)

    def test_outside_actual_frame_time_rejected_before_query(self):
        def outside(*args):
            identity, rows, paths = self.frames(*args)
            rows[0]['time'] = args[2]
            return identity, rows, paths
        with patch('app.episode_survey.source_frame_files', outside):
            with self.assertRaises(ValueError):
                survey_episode('source', SCENES, ASR, self.directory, Vision(), lambda: False, source_evidence=SHA)

    def test_map_schema_rejects_unknown_window_and_unowned_times(self):
        survey = self.survey()
        hypothesis = {'id': 'h', 'window_ids': ['foreign'], 'prerequisite_window_ids': [],
                      'premise': 'p', 'development': 'd', 'payoff': 'o', 'interesting_why': 'i', 'unanswered_questions': []}
        vision = Vision()
        vision.query = lambda *a, **k: {'hypotheses': [hypothesis], 'unanswered_questions': []}
        with self.assertRaises(ValueError):
            build_episode_map(survey, ASR, self.directory, vision, lambda: False)
        hypothesis['window_ids'] = [survey['windows'][0]['id']]
        hypothesis['start'] = 5
        with self.assertRaises(ValueError):
            build_episode_map(survey, ASR, self.directory, vision, lambda: False)

    def test_ask_receives_exact_request_and_evidence_refs(self):
        questions = []
        def ask(question, callback):
            questions.append(question)
            return callback()
        self.survey(ask=ask)
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(q['affected_refs'] and q['request_identity']['frame_hashes'] for q in questions))
        self.assertTrue(all(q['request_identity']['image_sha256'] for q in questions))

    def test_chapters_fit_hard_budget_and_preserve_all_speech_and_quiet_tail(self):
        scenes = [{'id': 's'+str(i), 'start': i*10., 'end': (i+1)*10.} for i in range(12)]
        transcript = {'segments': [{'start': i*10.+1, 'end': i*10.+9,
                        'text': 'exact-'+str(i)+' '+('слово '*450)} for i in range(11)], 'words': []}
        windows = survey_windows(scenes, transcript, SHA)
        survey = {'source_sha256': SHA, 'windows': windows, 'coverage': [w['id'] for w in windows],
                  'observations': [{'window_id': w['id'], 'summary': 'Silent action' if i == 11 else 'Spoken event',
                   'uncertain': True, 'unanswered_questions': []} for i, w in enumerate(windows)]}
        vision = Vision()
        vision.text_budget = 16000
        vision.token_count = lambda text: len(text.encode('utf-8'))+512
        counted = []
        def query(prompt, image, **kwargs):
            wire = prompt+'\n'+json.dumps(kwargs['schema'], ensure_ascii=False)
            self.assertLessEqual(len(wire.encode('utf-8'))+4096, vision.text_budget)
            counted.append(json.loads(prompt.split('\n', 1)[1]))
            return {'hypotheses': [], 'unanswered_questions': []}
        vision.query = query
        journal = Journal()
        mapped = build_episode_map(survey, transcript, self.directory, vision, lambda: False, journal=journal)
        chapter_payloads = [p for p in counted if 'exact_ASR' in p]
        self.assertGreater(len(chapter_payloads), 1)
        self.assertEqual([r for p in chapter_payloads for r in p['exact_ASR']], transcript['segments'])
        self.assertEqual([r for rows in mapped['chapter_coverage'] for r in rows], survey['coverage'])
        self.assertIn(windows[-1]['id'], mapped['chapter_coverage'][-1])
        vision.token_count = lambda text: self.fail('Warm map counted tokens')
        build_episode_map(survey, transcript, self.directory, vision, lambda: False, journal=journal)

    def test_speech_projection_uses_words_when_segment_misses_text(self):
        transcript = {'segments': [{'start': 0, 'end': 3, 'text': 'hello'}],
                      'words': [{'start': 1, 'end': 2, 'text': 'missing'}]}
        self.assertEqual({r['text'] for r in _speech_rows(transcript)}, {'hello', 'missing'})

    def test_survey_splits_image_batches_on_actual_text_context_without_dropping_speech(self):
        scenes = [{'id': str(i), 'start': i*10., 'end': (i+1)*10.} for i in range(6)]
        transcript = {'words': [], 'segments': [{'start': i*10.+1, 'end': i*10.+9,
            'text': ' '.join('длинноеслово'+str(n) for n in range(80))} for i in range(6)]}
        vision = Vision()
        vision.max_current_frames = 18
        vision.token_count = lambda text: len(text.encode('utf-8'))//2
        speech = []
        original_query = vision.query
        def query(prompt, image, **kwargs):
            wire = prompt+'\n'+json.dumps(kwargs['schema'], ensure_ascii=False)
            self.assertLessEqual(vision.token_count(wire)+2048+1024+2048, 8192)
            speech.extend(row for window in json.loads(prompt.split('\n', 1)[1]) for row in window['ASR'])
            return original_query(prompt, image, **kwargs)
        vision.query = query
        with patch('app.episode_survey.source_frame_files', self.frames):
            result = survey_episode(self.directory/'source.mp4', scenes, transcript, self.directory,
                                    vision, lambda: False, source_evidence=SHA)
        self.assertGreater(len(vision.requests), 1)
        self.assertEqual(speech, transcript['segments'])
        self.assertEqual(len(result['coverage']), len(scenes))


if __name__ == '__main__':
    unittest.main()
