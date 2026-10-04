"""Bounded ASR repair tests use real local PCM fixtures and mocked decoding."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import sys
import unittest
import uuid
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app import config, inference


def source_word(start, end, text, probability=.95):
    return {'start': start, 'end': end, 'text': text, 'probability': probability}


def focused_segment(words, window_start=1.37, probability=.95):
    rendered = [SimpleNamespace(start=start - window_start, end=end - window_start,
                                word=text, probability=probability) for start, end, text in words]
    return SimpleNamespace(start=rendered[0].start, end=rendered[-1].end,
                           text=' '.join(word.word for word in rendered), words=rendered,
                           no_speech_prob=.1, avg_logprob=-.1)


class AsrRepairTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP / ('repair_' + uuid.uuid4().hex)
        self.root.mkdir()
        self.audio = self.root / 'Русская речь 34 секунды.wav'
        self.destination = self.root / 'transcript.json'
        with wave.open(str(self.audio), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\0' * 34 * 16000 * 2)
        self.samples = np.zeros(34 * 16000, dtype=np.float32)
        raw = [
            {'start': 1., 'end': 2., 'text': 'Предыдущая реплика.'},
            {'start': 3.37, 'end': 17.12, 'text': 'Не ответил на письмо с извинениями.'},
            {'start': 17.7, 'end': 19.12, 'text': 'Пора прощаться с роднёй.'},
        ]
        self.original = {'language': 'ru', 'device': 'cuda', 'warning': None, 'elapsed_seconds': 123.,
                         'raw_segments': copy.deepcopy(raw),
                         'segments': [raw[0], {'start': 3.37, 'end': 3.89, 'text': 'Не'},
                                      {'start': 14.7, 'end': 17.12, 'text': 'ответил на письмо с извинениями.'}, raw[2]],
                         'words': [source_word(1., 2., 'Предыдущая реплика.'), source_word(3.37, 3.89, 'Не'),
                                   source_word(14.7, 15.24, 'ответил'), source_word(15.24, 15.36, 'на'),
                                   source_word(15.36, 15.78, 'письмо'), source_word(15.78, 15.9, 'с'),
                                   source_word(15.9, 17.12, 'извинениями.'),
                                   source_word(17.7, 19.12, 'Пора прощаться с роднёй.')]}
        self.correct_words = [(13.7, 14.54, 'Клиент'), (14.54, 14.7, 'не'), (14.7, 15.24, 'ответил'),
                              (15.24, 15.36, 'на'), (15.36, 15.78, 'письмо'),
                              (15.78, 15.9, 'с'), (15.9, 17.12, 'извинениями.')]
        self.model = SimpleNamespace(transcribe=MagicMock())

    def tearDown(self):
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root)

    def decode(self, words=None, probability=.95):
        decoded = focused_segment(words or self.correct_words, probability=probability)
        self.model.transcribe.return_value = (iter([decoded]), None)
        return inference.repair_transcript(self.samples, self.original, self.model)

    def test_wrong_negation_timestamp_repaired_and_missing_client_restored(self):
        before = copy.deepcopy(self.original)
        result = self.decode()
        self.assertEqual(self.original, before, 'Repair must not mutate a saved input object')
        self.assertEqual(result['repair_version'], 1)
        self.assertEqual(result['repair_log'][0]['status'], 'accepted')
        self.assertEqual(result['raw_segments'][1]['text'], 'Клиент не ответил на письмо с извинениями.')
        self.assertEqual(result['raw_segments'][1]['start'], 13.7)
        self.assertEqual([word['start'] for word in result['words'] if word['text'].lower() == 'не'], [14.54])
        self.assertEqual(result['repair_originals'][0]['segment'], self.original['raw_segments'][1])
        self.assertEqual(result['words'][0], self.original['words'][0])
        self.assertEqual(result['words'][-1], self.original['words'][-1])
        self.assertEqual(result['language'], 'ru')
        self.assertEqual(result['elapsed_seconds'], 123.)
        call = self.model.transcribe.call_args
        self.assertFalse(call.kwargs['vad_filter'])
        self.assertEqual(call.kwargs['language'], 'ru')
        self.assertTrue(call.kwargs['word_timestamps'])
        self.assertLessEqual(len(call.args[0]), 35 * 16000)

    def test_hallucinated_or_low_confidence_replacement_is_rejected(self):
        for words, probability in [([(13.7, 14.5, 'Совершенно'), (14.5, 15.5, 'другая'), (15.5, 17.12, 'история.')], .95),
                                   (self.correct_words, .49)]:
            with self.subTest(probability=probability):
                result = self.decode(words, probability)
                self.assertEqual(result['repair_log'][0]['status'], 'rejected')
                self.assertEqual(result['words'], self.original['words'])
                self.assertEqual(result['raw_segments'], self.original['raw_segments'])
                self.assertEqual(result['repair_originals'], [])

    def test_already_repaired_transcript_is_idempotent_without_decoding(self):
        result = self.decode()
        self.model.transcribe.reset_mock()
        again = inference.repair_transcript(self.samples, result, self.model)
        self.assertEqual(again, result)
        self.model.transcribe.assert_not_called()

    def test_new_words_are_center_bounded_and_clamped_to_original_interval_and_duration(self):
        extra = [(1.6, 2., 'Соседнее.'), *self.correct_words[:-1],
                 (16.9, 17.2, 'извинениями.'), (17.7, 18.2, 'Следующее.')]
        result = self.decode(extra)
        self.assertEqual(result['repair_log'][0]['status'], 'accepted')
        self.assertEqual(result['raw_segments'][1]['end'], 17.12)
        self.assertNotIn('Соседнее.', [word['text'] for word in result['words']])
        self.assertNotIn('Следующее.', [word['text'] for word in result['words']])
        self.assertTrue(all(0 <= word['start'] < word['end'] <= 34 for word in result['words']))
        self.assertEqual(result['words'][0], self.original['words'][0])
        self.assertEqual(result['words'][-1], self.original['words'][-1])

    def test_only_first_two_unfinished_words_trigger_large_gap_repair(self):
        for prefix, detected in [(['Не'], True), (['Клиент', 'не'], True),
                                 (['Этот', 'клиент', 'не'], False), (['Нет.'], False)]:
            value = {'segments': [{'start': 0, 'end': 20, 'text': 'example'}],
                     'words': [source_word(i, i + .2, text) for i, text in enumerate(prefix)] +
                              [source_word(10, 11, 'ответил'), source_word(11, 12, 'на'), source_word(12, 13, 'письмо')]}
            with self.subTest(prefix=prefix):
                self.assertEqual(bool(inference.repair_candidates(value)), detected)

    def test_repair_only_cpu_fallback_is_atomic_and_runtime_failure_preserves_old_file(self):
        self.destination.write_text(json.dumps(self.original, ensure_ascii=False), encoding='utf-8')
        gpu = SimpleNamespace(transcribe=MagicMock(side_effect=RuntimeError('CUDA out of memory')))
        cpu = SimpleNamespace(transcribe=MagicMock(return_value=(iter([focused_segment(self.correct_words)]), None)))
        with patch('app.inference._setup'), patch('app.inference._load_model', side_effect=[gpu, cpu]) as load, contextlib.redirect_stdout(io.StringIO()):
            repaired = inference.repair_only(self.audio, self.destination)
        self.assertEqual([call.args[0] for call in load.call_args_list], ['cuda', 'cpu'])
        self.assertEqual(repaired['device'], 'cpu')
        self.assertIn('CPU int8', repaired['warning'])
        self.assertEqual(json.loads(self.destination.read_text('utf-8')), repaired)
        with patch('app.inference._setup'), patch('app.inference._load_model') as load:
            self.assertEqual(inference.repair_only(self.audio, self.destination), repaired)
            load.assert_not_called()
        original_bytes = json.dumps(self.original, ensure_ascii=False).encode('utf-8')
        self.destination.write_bytes(original_bytes)
        failed = SimpleNamespace(transcribe=MagicMock(side_effect=RuntimeError('CPU model failure')))
        with patch('app.inference._setup'), patch('app.inference._load_model', side_effect=[gpu, failed]):
            with self.assertRaisesRegex(RuntimeError, 'CPU model failure'):
                inference.repair_only(self.audio, self.destination)
        self.assertEqual(self.destination.read_bytes(), original_bytes)
        self.assertFalse(self.destination.with_suffix('.partial').exists())

    def test_full_transcription_repairs_before_publishing_on_same_loaded_model(self):
        original = self.original['raw_segments'][1]
        old_words = [(word['start'], word['end'], word['text']) for word in self.original['words']
                     if original['start'] <= (word['start'] + word['end']) / 2 <= original['end']]
        full = focused_segment(old_words, window_start=0)
        full.start, full.end = original['start'], original['end']
        self.model.transcribe.side_effect = [(iter([full]), None),
                                            (iter([focused_segment(self.correct_words)]), None)]
        with patch('app.inference._setup'), patch('app.inference._load_model', return_value=self.model) as load, contextlib.redirect_stdout(io.StringIO()):
            result = inference.transcribe(self.audio, self.destination)
        load.assert_called_once_with('cuda')
        self.assertEqual([call.kwargs['vad_filter'] for call in self.model.transcribe.call_args_list], [True, False])
        self.assertEqual(result['raw_segments'][0]['text'], 'Клиент не ответил на письмо с извинениями.')
        self.assertEqual(json.loads(self.destination.read_text('utf-8')), result)
        self.assertEqual(result['repair_version'], 1)


if __name__ == '__main__':
    unittest.main()
