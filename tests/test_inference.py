"""ASR regression checks run without loading a model or touching a GPU."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import unittest
import uuid
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app import config, inference


def word(start, end, text):
    return SimpleNamespace(start=start, end=end, word=text, probability=.98765)


def segment(start, end, text, words):
    return SimpleNamespace(start=start, end=end, text=text, words=words,
                           no_speech_prob=.1, avg_logprob=-.2)


class InferenceTests(unittest.TestCase):
    def setUp(self):
        # Windows 3.12 tempfile mode 0700 is unreadable by this sandbox; keep
        # inherited project ACLs, and keep every generated fixture in TEMP.
        self.root = config.TEMP / ("inference_" + uuid.uuid4().hex)
        self.root.mkdir()
        self.audio = self.root / "Русское аудио с пробелами.wav"
        self.destination = self.root / "transcript.json"
        self.write_audio()
        self.factory = MagicMock()
        self.patchers = [patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=self.factory)})]
        if os.name == "nt":
            self.patchers.append(patch("app.inference.os.add_dll_directory", return_value=SimpleNamespace(close=lambda: None)))
        for patcher in self.patchers:
            patcher.start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        for patcher in reversed(self.patchers):
            patcher.stop()
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root)

    def write_audio(self, *, channels=1, width=2, rate=16000):
        with wave.open(str(self.audio), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(b"\0" * channels * width * rate)  # exactly one second

    def assert_no_output(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix(".partial").exists())

    def test_cuda_iteration_oom_retries_complete_cpu_transcript_with_same_local_model(self):
        leaked = segment(0, .1, "Недописанная GPU реплика", [word(0, .1, "GPU")])
        complete = [segment(.1, .8, " Привет, мир! ", [word(.1, .3, " Привет, "), word(.4, .8, " мир! ")])]
        def interrupted():
            yield leaked
            raise RuntimeError("CUDA out of memory during segment decoding")
        gpu = SimpleNamespace(transcribe=MagicMock(return_value=(interrupted(), None)))
        cpu = SimpleNamespace(transcribe=MagicMock(return_value=(iter(complete), None)))
        self.factory.side_effect = [gpu, cpu]
        result = inference.transcribe(self.audio, self.destination)
        self.assertEqual(result["device"], "cpu")
        self.assertIn("CUDA out of memory", result["warning"])
        self.assertIn("CPU int8", result["warning"])
        self.assertEqual(result["segments"], [{"start": .1, "end": .8, "text": "Привет, мир!"}])
        self.assertEqual(result["words"], [
            {"start": .1, "end": .3, "text": "Привет,", "probability": .988},
            {"start": .4, "end": .8, "text": "мир!", "probability": .988},
        ])
        self.assertEqual(len(self.factory.call_args_list), 2)
        cuda_call, cpu_call = self.factory.call_args_list
        self.assertEqual(cuda_call.args, cpu_call.args)
        self.assertEqual(cpu_call.args, (str(config.ASR_MODEL),))
        for call in (cuda_call, cpu_call):
            self.assertTrue(call.kwargs["local_files_only"])
        self.assertEqual(cuda_call.kwargs["device"], "cuda")
        self.assertEqual(cpu_call.kwargs["device"], "cpu")
        self.assertEqual(cpu_call.kwargs["compute_type"], "int8")
        samples = gpu.transcribe.call_args.args[0]
        self.assertIs(cpu.transcribe.call_args.args[0], samples)
        self.assertIsInstance(samples, np.ndarray)
        self.assertEqual(samples.dtype, np.float32)
        self.assertEqual(len(samples), 16000)
        for model in (gpu, cpu):
            self.assertEqual(model.transcribe.call_args.kwargs["language"], "ru")
            self.assertTrue(model.transcribe.call_args.kwargs["word_timestamps"])
        self.assertEqual(json.loads(self.destination.read_text("utf-8")), result)
        self.assertFalse(self.destination.with_suffix(".partial").exists())

    def test_non_16k_mono_pcm16_and_malformed_audio_fail_without_output(self):
        for parameters in ({"rate": 8000}, {"channels": 2}, {"width": 1}):
            with self.subTest(parameters=parameters):
                self.write_audio(**parameters)
                with self.assertRaisesRegex(ValueError, "16kHz mono PCM16"):
                    inference.transcribe(self.audio, self.destination)
                self.assert_no_output()
        self.audio.write_bytes(b"not a wave file")
        with self.assertRaises((wave.Error, EOFError)):
            inference.transcribe(self.audio, self.destination)
        self.assert_no_output()
        self.factory.assert_not_called()

    def test_boundary_words_clamp_to_source_end_and_zero_length_words_are_omitted(self):
        speech = [segment(-.5, 1.7, " Граница серии ", [
            word(-.1, .2, "Начало"), word(.9, 1.25, "конец"),
            word(1.1, 1.4, "за пределами"), word(.4, .4, "нулевое"), word(.2, .3, "  ")])]
        self.factory.return_value = SimpleNamespace(transcribe=MagicMock(return_value=(iter(speech), None)))
        result = inference.transcribe(self.audio, self.destination)
        self.assertEqual(result["device"], "cuda")
        self.assertIsNone(result["warning"])
        self.assertEqual(result["segments"], [{"start": 0, "end": 1, "text": "Граница серии"}])
        self.assertEqual([(entry["start"], entry["end"], entry["text"]) for entry in result["words"]],
                         [(0, .2, "Начало"), (.9, 1, "конец")])

    def test_progress_streams_real_source_positions_before_complete_transcript(self):
        observed = []
        def stream():
            yield segment(0, .3, 'Первый', [word(0, .3, 'Первый')])
            observed.append(json.loads((self.root / 'asr-progress.json').read_text('utf-8')))
            self.assertFalse(self.destination.exists())
            yield segment(.4, .8, 'Второй', [word(.4, .8, 'Второй')])
        self.factory.return_value = SimpleNamespace(transcribe=MagicMock(return_value=(stream(), None)))
        inference.transcribe(self.audio, self.destination)
        self.assertEqual(observed[0]['fraction'], .3)
        complete = json.loads((self.root / 'asr-progress.json').read_text('utf-8'))
        self.assertEqual((complete['phase'], complete['fraction']), ('completed', 1.0))

    def test_gpu_and_cpu_iteration_failure_publish_neither_complete_nor_partial_transcript(self):
        def failed_cpu():
            yield segment(0, .5, "Не завершено", [word(0, .5, "Нет")])
            raise RuntimeError("CPU model decoding failed")
        gpu = SimpleNamespace(transcribe=MagicMock(side_effect=RuntimeError("CUDA out of memory")))
        cpu = SimpleNamespace(transcribe=MagicMock(return_value=(failed_cpu(), None)))
        self.factory.side_effect = [gpu, cpu]
        with self.assertRaisesRegex(RuntimeError, "CPU model decoding failed"):
            inference.transcribe(self.audio, self.destination)
        self.assert_no_output()

    def test_model_failure_leaves_existing_checkpoint_unchanged(self):
        self.destination.write_text('{"previous": "checkpoint"}', encoding="utf-8")
        self.factory.side_effect = [RuntimeError("CUDA unavailable"), RuntimeError("CPU unavailable")]
        with self.assertRaisesRegex(RuntimeError, "CPU unavailable"):
            inference.transcribe(self.audio, self.destination)
        self.assertEqual(self.destination.read_text("utf-8"), '{"previous": "checkpoint"}')
        self.assertFalse(self.destination.with_suffix(".partial").exists())


if __name__ == "__main__":
    unittest.main()
