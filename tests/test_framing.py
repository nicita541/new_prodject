import copy
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.config import TEMP
from app.framing import FOCUS_SCHEMA, _FrameReader, _coordinates, _focus_prompt, focus_samples, refine_focus, temporal_times


def workspace_directory():
    path = TEMP / ("framing_" + uuid.uuid4().hex)
    path.mkdir()
    return path


class FakeReader:
    def __init__(self, *args):
        self.closed = False

    def frame(self, timestamp):
        return np.full((360, 640, 3), 100, dtype=np.uint8)

    def close(self):
        self.closed = True


class FakeVision:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.schemas = []

    def query(self, prompt, image, max_tokens, schema=None):
        self.calls.append((prompt, image, max_tokens))
        self.schemas.append(schema)
        return self.answers.pop(0)


def fixtures():
    events = [{"id": "early", "start": 0, "end": 10, "kind": "story", "importance": 1, "requires": [],
               "focus": [{"time": 0, "x": 0.5, "y": 0.5, "confidence": 0.9}]},
              {"id": "later", "start": 10, "end": 20, "kind": "story", "importance": 4, "requires": ["early"],
               "focus": [{"time": 10, "x": 0.5, "y": 0.5, "confidence": 0.9}]}]
    shots = [{"id": "s0", "start": 0, "end": 10}, {"id": "s1", "start": 10, "end": 20}]
    transcript = {"segments": [{"start": 0, "end": 4, "text": "Русская реплика."}, {"start": 10, "end": 14, "text": "Ответ."}],
                  "words": [{"start": 0.1, "end": 0.5, "text": "Русская"}, {"start": 10.1, "end": 10.5, "text": "Ответ"}]}
    return events, shots, transcript


class FramingTests(unittest.TestCase):
    def prepare(self):
        # These fixed-response fixtures isolate cache/fallback/cancellation
        # behavior. Periodic refreshes are covered separately with the default
        # four-second limit and a real refine_focus invocation below.
        sampling = patch("app.framing.MAX_SAMPLE_INTERVAL", 1000.0)
        sampling.start()
        self.addCleanup(sampling.stop)
        directory = workspace_directory()
        source = directory / "Серия с пробелами.mp4"
        source.write_bytes(b"fixture source")
        (directory / "analysis.meta.json").write_text(json.dumps({"source": "test-source", "version": 2}), encoding="utf-8")
        return directory, source

    def test_reply_uses_word_midpoint_but_boundary_time_and_deduplicates_shot(self):
        events, shots, transcript = fixtures()
        sample = focus_samples(events[0], transcript, shots)
        original_samples = [entry for entry in sample if not entry.get("periodic")]
        self.assertEqual(len(original_samples), 1)
        self.assertEqual(sample[0]["time"], 0)
        self.assertAlmostEqual(sample[0]["sample_time"], 0.3)
        self.assertTrue(sample[0]["reply"])

    def test_important_silent_shots_are_sampled_without_transcript(self):
        events, shots, _ = fixtures()
        samples = focus_samples({**events[0], "end": 20}, {"words": [], "segments": []}, shots)
        initial = [sample for sample in samples if not sample.get("periodic")]
        self.assertEqual([s["time"] for s in initial], [0, 10])
        self.assertEqual([s["sample_time"] for s in initial], [0.25, 10.25])

    def test_long_silent_shot_refreshes_with_maximum_four_second_gap(self):
        event = {"start": 0, "end": 19, "selected_ranges": [{"start": 2, "end": 8}, {"start": 12, "end": 19}]}
        shots = [{"id": "same-plan", "start": 0, "end": 25}]
        samples = focus_samples(event, {"words": [], "segments": []}, shots)
        self.assertTrue(any(sample.get("periodic") for sample in samples))
        for left, right in ((2, 8), (12, 19)):
            selected = [sample for sample in samples if left <= sample["time"] < right]
            boundaries = [left, *[sample["time"] for sample in selected], right]
            self.assertTrue(all(end - start <= 4 + 1e-6 for start, end in zip(boundaries, boundaries[1:])))
            self.assertTrue(all(left <= sample["sample_time"] < right for sample in selected))
        self.assertTrue(all(sample["time"] < 8 or sample["time"] >= 12 for sample in samples))
        self.assertTrue(all(sample["shot_id"] == "same-plan" and not sample.get("hardcut") for sample in samples))

    def test_periodic_refresh_preserves_reply_priority_and_shot_boundaries(self):
        event = {"start": 0, "end": 14}
        shots = [{"id": "first", "start": 0, "end": 7}, {"id": "second", "start": 7, "end": 14}]
        transcript = {"segments": [{"start": 0, "end": 1, "text": "Первая."}, {"start": 7, "end": 8, "text": "Ответ."}],
                      "words": [{"start": .1, "end": .5, "text": "Первая."}, {"start": 7.1, "end": 7.5, "text": "Ответ."}]}
        samples = focus_samples(event, transcript, shots)
        self.assertEqual([sample["time"] for sample in samples if sample["reply"]], [0, 7])
        self.assertEqual(len({sample["time"] for sample in samples}), len(samples))
        for sample in samples:
            shot = next(shot for shot in shots if shot["id"] == sample["shot_id"])
            self.assertTrue(shot["start"] <= sample["time"] <= sample["sample_time"] < shot["end"])
            self.assertTrue(all(shot["start"] <= time < shot["end"] for time in temporal_times(sample, event, shots)))

    def test_silent_action_prompt_and_default_periodic_refinement(self):
        self.assertIn("MAIN VISIBLE ACTION", _focus_prompt({"phrase": ""}))
        self.assertIn("visible_speaker=false", _focus_prompt({"phrase": ""}))
        speech = _focus_prompt({"phrase": "Настоящая реплика."})
        self.assertIn("Compare mouth motion", speech)
        self.assertIn("Настоящая реплика.", speech)
        directory, source = self.prepare()
        event = {"id": "action", "start": 0, "end": 10, "kind": "story", "importance": 4, "requires": []}
        shots = [{"id": "long-silent", "start": 0, "end": 10}]
        answer = {"x": .6, "y": .5, "confidence": .95, "visible_speaker": False}
        vision = FakeVision([copy.deepcopy(answer) for _ in range(3)])
        with patch("app.framing.MAX_SAMPLE_INTERVAL", 4.0), patch("app.framing._FrameReader", return_value=FakeReader()):
            result = refine_focus(source, {"fps": 30}, {"segments": [], "words": []}, shots, [event],
                                  directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(len(result[0]["focus"]), 3)
        self.assertTrue(all("MAIN VISIBLE ACTION" in prompt for prompt, _, _ in vision.calls))
        self.assertFalse(result[0]["focus_warnings"])

    def test_selected_ranges_only_sample_retained_material(self):
        events, shots, transcript = fixtures()
        event = {**events[0], "selected_ranges": [{"start": 3, "end": 6}]}
        samples = focus_samples(event, transcript, shots)
        self.assertTrue(all(3 <= s["time"] < 6 and 3 <= s["sample_time"] < 6 for s in samples))

    def test_bad_coordinates_reject_pixel_values_and_outside_normalized_range(self):
        self.assertEqual(_coordinates({"x": 0, "y": 1, "confidence": 1}), {"x": 0, "y": 1, "confidence": 1})
        for raw in [{"x": 120, "y": 200, "confidence": 0.9},
                    {"x": -0.2, "y": 0.5, "confidence": 0.9},
                    {"x": 0.2, "y": 1.2, "confidence": 0.9},
                    {"x": 0.2, "y": 0.5, "confidence": 2}]:
            with self.assertRaises(ValueError):
                _coordinates(raw)
        for value in (float("nan"), float("inf"), True, "0.2", None):
            with self.assertRaises(ValueError):
                _coordinates({"x": value, "y": 0.5, "confidence": 0.8})

    def test_dependencies_refined_and_new_shot_uncertainty_uses_current_subject(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        original = copy.deepcopy(events)
        reader = FakeReader()
        vision = FakeVision([{"x": 0.35, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                             {"x": 0.8, "y": 0.5, "confidence": 0.2, "visible_speaker": False},
                             {"x": 0.65, "y": 0.4, "confidence": 0.85, "visible_speaker": False}])
        with patch("app.framing._FrameReader", return_value=reader):
            result = refine_focus(source, {"fps": 30}, transcript, shots, events, directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(events, original)
        self.assertEqual(result[0]["focus"][0]["x"], 0.35)
        self.assertEqual(result[1]["focus"][0]["x"], 0.65)
        self.assertTrue(result[1]["focus"][0]["main_fallback"])
        self.assertNotIn("held", result[1]["focus"][0])
        self.assertTrue(result[1]["focus_warnings"])
        self.assertTrue(reader.closed)
        for prompt, image, max_tokens in vision.calls:
            decoded = cv2.imdecode(np.frombuffer(image.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertIn(decoded.shape[:2], [(810, 480), (270, 480)])
            self.assertEqual(max_tokens, 120)
            if decoded.shape[0] == 810:
                self.assertIn("consecutive", prompt)
                self.assertIn("WITHIN ONE", prompt)
            else:
                self.assertIn("CURRENT single frame", prompt)
        self.assertTrue(all(schema is FOCUS_SCHEMA for schema in vision.schemas))

    def test_cached_focus_needs_matching_identity_and_valid_coordinates(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        answers = [{"x": 0.3, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                   {"x": 0.7, "y": 0.4, "confidence": 0.9, "visible_speaker": True}]
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            first = FakeVision(answers)
            refine_focus(source, {"fps": 30}, transcript, shots, events, directory, first, lambda *a: None, lambda: False)
            second = FakeVision([])
            refine_focus(source, {"fps": 30}, transcript, shots, events, directory, second, lambda *a: None, lambda: False)
            self.assertEqual(len(second.calls), 0)
            # A different source identity invalidates every focus checkpoint.
            (directory / "analysis.meta.json").write_text(json.dumps({"source": "changed-source", "version": 2}), encoding="utf-8")
            third = FakeVision(answers)
            refine_focus(source, {"fps": 30}, transcript, shots, events, directory, third, lambda *a: None, lambda: False)
            self.assertEqual(len(third.calls), 2)
            for checkpoint in (directory / "focus").glob("*.json"):
                value = json.loads(checkpoint.read_text(encoding="utf-8"))
                value["focus"][0]["x"] = float("nan")
                checkpoint.write_text(json.dumps(value), encoding="utf-8")
            fourth = FakeVision(answers)
            refine_focus(source, {"fps": 30}, transcript, shots, events, directory, fourth, lambda *a: None, lambda: False)
            self.assertEqual(len(fourth.calls), 2)

    def test_temporal_sequence_never_crosses_a_shot_or_selected_cut(self):
        event = {"start": 0, "end": 10, "selected_ranges": [{"start": 3, "end": 6}]}
        shots = [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 4, "end": 10}]
        before_change = temporal_times({"sample_time": 3.95}, event, shots)
        self.assertEqual(len(before_change), 3)
        self.assertTrue(all(3 <= timestamp < 4 for timestamp in before_change))
        before_cut = temporal_times({"sample_time": 5.95}, event, shots)
        self.assertTrue(all(4 <= timestamp < 6 for timestamp in before_cut))
        ordinary = temporal_times({"sample_time": 4.5}, event, shots)
        self.assertEqual(ordinary, [4.5, 4.62, 4.75])

    def test_actual_model_projector_and_profile_change_invalidate_focus_cache(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        answers = [{"x": 0.3, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                   {"x": 0.7, "y": 0.4, "confidence": 0.9, "visible_speaker": True}]
        model_a, model_b = directory / "model-a.gguf", directory / "model-b.gguf"
        projector_a, projector_b = directory / "projector-a.gguf", directory / "projector-b.gguf"
        for path in (model_a, model_b, projector_a, projector_b):
            path.write_bytes(b"same-sized model fixture")
        def invoke(model, projector, thinking=False, cached=False):
            vision = FakeVision([] if cached else copy.deepcopy(answers))
            vision.model, vision.projector = model, projector
            vision.thinking, vision.gpu_layers, vision.cpu_projector = thinking, 99, False
            refine_focus(source, {"fps": 30}, transcript, shots, events, directory,
                         vision, lambda *a: None, lambda: False)
            self.assertEqual(len(vision.calls), 0 if cached else 2)
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            invoke(model_a, projector_a)
            invoke(model_a, projector_a, cached=True)
            invoke(model_b, projector_a)
            invoke(model_b, projector_a, cached=True)
            invoke(model_b, projector_b)
            invoke(model_b, projector_b, thinking=True)
            invoke(model_b, projector_b, thinking=True, cached=True)

    def test_confident_listener_requires_current_main_subject_geometry(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        vision = FakeVision([{"x": 0.35, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                             {"x": 0.8, "y": 0.5, "confidence": 0.99, "visible_speaker": False},
                             {"x": 0.75, "y": 0.5, "confidence": 0.9, "visible_speaker": False}])
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            result = refine_focus(source, {"fps": 30}, transcript, shots, events, directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(result[1]["focus"][0]["x"], 0.75)
        self.assertTrue(result[1]["focus"][0]["main_fallback"])
        self.assertTrue(result[1]["focus_warnings"])

    def test_uncertainty_without_previous_subject_uses_actual_center(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        vision = FakeVision([{"x": 0.95, "y": 0.05, "confidence": 0.2, "visible_speaker": False},
                             {"x": 200, "y": 120, "confidence": 0.9, "visible_speaker": False},
                             {"x": 0.7, "y": 0.4, "confidence": 0.9, "visible_speaker": True}])
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            result = refine_focus(source, {"fps": 30}, transcript, shots, events, directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(result[0]["focus"][0], {"time": 0, "x": 0.5, "y": 0.5, "confidence": 0.0})
        self.assertIn("центральный фокус", result[0]["focus_warnings"][0])

    def test_same_shot_and_same_selection_can_hold_previous_visible_subject(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        events = [{**events[0], "importance": 4}]
        transcript["segments"].append({"start": 3, "end": 5, "text": "Еще реплика."})
        transcript["segments"] = sorted([s for s in transcript["segments"] if s["start"] < 10], key=lambda s: s["start"])
        transcript["words"] = [transcript["words"][0], {"start": 3.1, "end": 3.5, "text": "Еще"}]
        vision = FakeVision([{"x": 0.35, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                             {"x": 0.9, "y": 0.5, "confidence": 0.3, "visible_speaker": False}])
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            result = refine_focus(source, {"fps": 30}, transcript, shots, events, directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(len(vision.calls), 2)
        self.assertEqual(result[0]["focus"][1]["x"], 0.35)
        self.assertTrue(result[0]["focus"][1]["held"])

    def test_same_shot_different_cut_does_not_hold_previous_focus(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        events = [{**events[0], "importance": 4, "selected_ranges": [{"start": 0, "end": 2}, {"start": 3, "end": 6}]}]
        transcript = {"segments": [{"start": 0, "end": 1, "text": "Один"}, {"start": 3, "end": 5, "text": "Два"}],
                      "words": [{"start": 0.1, "end": 0.5, "text": "Один"}, {"start": 3.1, "end": 3.5, "text": "Два"}]}
        vision = FakeVision([{"x": 0.35, "y": 0.4, "confidence": 0.9, "visible_speaker": True},
                             {"x": 0.9, "y": 0.5, "confidence": 0.3, "visible_speaker": False},
                             {"x": 0.75, "y": 0.4, "confidence": 0.9, "visible_speaker": False}])
        with patch("app.framing._FrameReader", side_effect=lambda *a: FakeReader()):
            result = refine_focus(source, {"fps": 30}, transcript, shots, events, directory, vision, lambda *a: None, lambda: False)
        self.assertEqual(len(vision.calls), 3)
        self.assertEqual(result[0]["focus"][1]["x"], 0.75)
        self.assertTrue(result[0]["focus"][1]["main_fallback"])

    def test_schema_prevents_pixel_coordinates_and_missing_focus_fields(self):
        self.assertEqual(set(FOCUS_SCHEMA["required"]), {"x", "y", "confidence", "visible_speaker"})
        self.assertFalse(FOCUS_SCHEMA["additionalProperties"])
        for key in ("x", "y", "confidence"):
            values = FOCUS_SCHEMA["properties"][key]["enum"]
            self.assertEqual(values, [index / 20 for index in range(21)])
            self.assertIn(0.55, values)
            self.assertNotIn(100, values)
        self.assertEqual(FOCUS_SCHEMA["properties"]["visible_speaker"], {"type": "boolean"})

    def test_cancellation_closes_video_decoder(self):
        directory, source = self.prepare()
        events, shots, transcript = fixtures()
        reader = FakeReader()
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls > 1
        with patch("app.framing._FrameReader", return_value=reader):
            with self.assertRaises(InterruptedError):
                refine_focus(source, {}, transcript, shots, events, directory, FakeVision([]), lambda *a: None, cancelled)
        self.assertTrue(reader.closed)

    def test_actual_single_video_decoder_handles_unicode_source_and_seeks(self):
        directory = workspace_directory()
        source = directory / "Русское видео с пробелами.avi"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 30, (320, 180))
        self.assertTrue(writer.isOpened())
        for index in range(60):
            writer.write(np.full((180, 320, 3), index * 3, dtype=np.uint8))
        writer.release()
        reader = _FrameReader(source, {"fps": 30}, lambda: False)
        try:
            first, middle, back = reader.frame(0.1), reader.frame(1.5), reader.frame(0.3)
            self.assertEqual(first.shape[:2], (180, 320))
            self.assertGreater(float(middle.mean()), float(first.mean()) + 70)
            self.assertLess(float(back.mean()), float(middle.mean()) - 70)
            tail = reader.frame(2.01)
            self.assertGreater(float(tail.mean()), float(middle.mean()))
        finally:
            reader.close()
