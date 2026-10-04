import json
import copy
from contextlib import contextmanager
import uuid
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import FFMPEG, FFPROBE, TEMP
from app.media import choose_encoder, crop_expressions, crop_position, crop_size, inspect_media, render_part, run_command, validate_export
from app.pipeline import run_job


@contextmanager
def workspace_directory(prefix="media_test_"):
    # Keep diagnostic media inside the project and avoid mkdtemp's restricted ACL.
    path = TEMP / (prefix + uuid.uuid4().hex)
    path.mkdir()
    yield str(path)


class CropTests(unittest.TestCase):
    def test_shot_boundary_jumps_at_boundary_while_reply_focus_remains_smooth(self):
        cut = {"start": 10, "end": 15, "focus": [
            {"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
            {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.9, "hard_cut": True},
            {"time": 14, "x": 0.1, "y": 0.5, "confidence": 0.9, "hard_cut": False}]}
        expression, _ = crop_expressions(cut, 64, 36)
        def position(time):
            return eval(expression.replace("if(", "choose("), {"__builtins__": {}},
                        {"t": time, "choose": lambda condition, a, b: a if condition else b,
                         "lt": lambda a, b: a < b, "clip": lambda a, low, high: min(max(a, low), high)})
        self.assertEqual(position(1.9999), 0)
        self.assertEqual(position(2), 44)
        self.assertEqual(position(2.0001), 44)
        self.assertEqual(position(3.75), 44)
        self.assertAlmostEqual(position(3.875), 22)
        self.assertEqual(position(4), 0)

    def test_wide_and_tall_images_clamp(self):
        for width, height in [(1920, 1080), (600, 1600)]:
            cw, ch = crop_size(width, height)
            self.assertLess(abs(cw / ch - 9 / 16), 0.004)
            self.assertEqual(crop_position(-1, -1, width, height), (0, 0))
            self.assertEqual(crop_position(2, 2, width, height), (width - cw, height - ch))

    def test_motion_preserves_finalized_low_confidence_anchors(self):
        cut = {"start": 10, "end": 20, "focus": [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.8},
                                                      {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.1},
                                                      {"time": 14, "x": 0.7, "y": 0.5, "confidence": 0.8}]}
        x, _ = crop_expressions(cut, 1920, 1080)
        self.assertIn("4.000000", x)
        self.assertIn("2.000000", x)
        self.assertIn("3-2*", x)

    def test_missing_focus_uses_center(self):
        self.assertEqual(crop_expressions({"start": 10, "end": 20, "focus": []}, 1920, 1080),
                         ("657.0000", "0.0000"))

    def test_speaker_focus_holds_then_moves_in_quarter_second(self):
        cut = {"start": 0, "end": 12, "focus": [{"time": 0, "x": 0.1, "y": 0.5, "confidence": 0.9},
                                                     {"time": 10, "x": 0.9, "y": 0.5, "confidence": 0.9}]}
        x, _ = crop_expressions(cut, 1920, 1080)
        self.assertIn("t-9.750000", x)
        self.assertIn("/0.250000", x)

    def test_validation_rejects_overlength_and_wrong_geometry(self):
        info = {"format": {"duration": "91"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080,
                    "height": 1920, "avg_frame_rate": "30/1"}, {"codec_type": "audio", "codec_name": "aac"}]}
        with workspace_directory() as directory:
            path = Path(directory) / "output.mp4"
            path.write_bytes(b"x" * 2000)
            with patch("app.media.inspect_media", return_value=info):
                with self.assertRaises(ValueError):
                    validate_export(path, 90, Path(directory))


@unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), "Portable FFmpeg has not been installed")
class MediaIntegrationTests(unittest.TestCase):
    def test_cinema_preserves_both_source_edges_and_outputs_valid_portrait(self):
        import numpy as np
        import cv2
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / 'wide.mp4'
            run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         "color=red:s=320x180:r=30:d=1,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill",
                         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], base)
            part = {'index': 1, 'duration': .8, 'layout': 'cinema', 'caption_style': 'accent',
                    'subtitles': [], 'cuts': [{'start': 0, 'end': .8, 'focus': []}]}
            output = render_part(source, part, {'width': 320, 'height': 180}, base / 'output', base / 'work', 'libx264')
            video = cv2.VideoCapture(str(output))
            try:
                ok, frame = video.read()
                self.assertTrue(ok)
                left = np.mean(frame[900:1000, 20:80], axis=(0, 1))
                right = np.mean(frame[900:1000, 1000:1060], axis=(0, 1))
                self.assertGreater(left[2], left[0] + 100)
                self.assertGreater(right[0], right[2] + 100)
            finally:
                video.release()

    def _focus_luminance(self, focus, sample_frames=(10, 21, 41)):
        # Three wide vertical bands identify the source area actually selected
        # by FFmpeg. Sample well after each anchor, avoiding transition frames.
        cut = {"start": 10, "end": 15, "focus": focus}
        x, y = crop_expressions(cut, 64, 36)
        cw, ch = crop_size(64, 36)
        with workspace_directory() as directory:
            base = Path(directory)
            output = base / "crop.gray"
            source = "nullsrc=s=64x36:r=10:d=4.3,format=gray,geq=lum='if(lt(X,21),32,if(lt(X,43),128,224))'"
            select = "+".join(f"eq(n,{frame})" for frame in sample_frames)
            filters = f"crop={cw}:{ch}:x='{x}':y='{y}',select='{select}'"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", source,
                         "-vf", filters, "-fps_mode", "passthrough", "-pix_fmt", "gray",
                         "-threads", "1", "-f", "rawvideo", str(output)], base)
            pixels = output.read_bytes()
            self.assertEqual(len(pixels), len(sample_frames) * cw * ch)
            center = ch // 2 * cw + cw // 2
            return [pixels[frame * cw * ch + center] for frame in range(len(sample_frames))]

    def test_two_shot_crop_never_pans_toward_unseen_next_shot(self):
        focus = [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
                 {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.9, "hard_cut": True}]
        # t=1.9 still sees the old composition; t=2.0 and later see the new one.
        self.assertEqual(self._focus_luminance(focus, (19, 20, 21)), [32, 224, 224])

    def test_new_shot_center_reset_survives_confident_neighbor_anchors(self):
        focus = [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
                 {"time": 12, "x": 0.5, "y": 0.5, "confidence": 0.0},
                 {"time": 14, "x": 0.9, "y": 0.5, "confidence": 0.9}]
        self.assertEqual(self._focus_luminance(focus), [32, 128, 224])

    def test_all_uncertain_focus_anchors_preserve_resolved_positions(self):
        focus = [{"time": 10, "x": 0.5, "y": 0.5, "confidence": 0.0},
                 {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.1},
                 {"time": 14, "x": 0.1, "y": 0.5, "confidence": 0.0}]
        self.assertEqual(self._focus_luminance(focus), [128, 224, 32])

    def test_two_cuts_cyrillic_path_and_original_audio(self):
        with workspace_directory(prefix="монтаж с пробелами ") as directory:
            base = Path(directory)
            source = base / "Серия — два говорящих ' [проверка].mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            part = {"index": 1, "duration": 2, "cuts": [
                {"start": 0, "end": 1, "focus": [{"time": 0, "x": 0.2, "y": 0.5, "confidence": 0.9},
                                                      {"time": 0.8, "x": 0.8, "y": 0.5, "confidence": 0.9}]},
                {"start": 2, "end": 3, "focus": [{"time": 2, "x": 0.8, "y": 0.5, "confidence": 0.9}]}],
                "subtitles": [{"start": 0.1, "end": 0.8, "text": "Привет, мир!"}, {"start": 1.1, "end": 1.9, "text": "Второй персонаж."}]}
            result = render_part(source, part, {"width": 640, "height": 360}, base / "output", base / "work", "libx264")
            self.assertTrue(result.is_file())
            self.assertTrue(result.with_suffix(".srt").is_file())
            self.assertFalse((base / "work" / "part_001.partial.mp4").exists())
            metadata = validate_export(result, 2, base)
            self.assertLessEqual(abs(metadata["duration"] - 2), 0.05)

    def test_cancelled_command_does_not_start(self):
        with workspace_directory() as directory:
            with self.assertRaises(InterruptedError):
                run_command([str(FFMPEG), "-version"], Path(directory), lambda: True)

    def test_cancellation_terminates_running_process(self):
        with workspace_directory() as directory:
            started = time.monotonic()
            with self.assertRaises(InterruptedError):
                run_command([str(FFMPEG), "-v", "error", "-re", "-f", "lavfi", "-i",
                             "color=size=128x128:rate=30", "-t", "30", "-f", "null", "-"],
                            Path(directory), lambda: time.monotonic() - started > 0.5)
            self.assertLess(time.monotonic() - started, 5)

    def test_fractional_frame_cuts_do_not_accumulate_audio_drift(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "fractional.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=160x90:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            cuts = [{"start": i * 0.31, "end": i * 0.31 + 0.21,
                     "focus": [{"time": i * 0.31, "x": 0.5, "y": 0.5, "confidence": 0.9}]} for i in range(10)]
            part = {"index": 1, "duration": 2.1, "cuts": cuts, "subtitles": []}
            result = render_part(source, part, {"width": 160, "height": 90}, base / "output", base / "work", "libx264")
            info = inspect_media(result, base)
            streams = {s["codec_type"]: s for s in info["streams"]}
            self.assertLess(abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])), 0.04)
            self.assertLess(abs(float(info["format"]["duration"]) - 2.1), 0.04)

    def test_exact_ninety_seconds_exports_without_overflow(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "ninety.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=160x90:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "90", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            part = {"index": 1, "duration": 90, "cuts": [{"start": 0, "end": 90,
                    "focus": [{"time": 0, "x": 0.5, "y": 0.5, "confidence": 0.9}]}], "subtitles": []}
            result = render_part(source, part, {"width": 160, "height": 90}, base / "output", base / "work", choose_encoder(base))
            self.assertLessEqual(validate_export(result, 90, base)["duration"], 90)


class PipelineCheckpointTests(unittest.TestCase):
    def test_shorter_retry_archives_only_obsolete_owned_exports_after_success(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "source.mp4"
            source.write_bytes(b"unchanged")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            original = {"probe": {"duration": 200, "width": 640, "height": 360, "has_audio": True},
                        "transcript": {"words": [], "segments": []}, "shots": [],
                        "events": [{"id": "a", "start": 0, "end": 200, "kind": "story", "importance": 4}]}
            shorter = copy.deepcopy(original)
            shorter["events"][0]["selected_ranges"] = [{"start": 0, "end": 20}]
            def render(source, part, probe, output, work, encoder, cancelled):
                path = output / f"part_{part['index']:03}.mp4"
                path.write_bytes(b"rendered" * 1000)
                path.with_suffix(".srt").write_text("subtitles", encoding="utf-8")
                return path
            with patch("app.analysis.analyze", side_effect=[original, shorter, shorter]), \
                    patch("app.pipeline.choose_encoder", return_value="libx264"), \
                    patch("app.pipeline.render_part", side_effect=render) as renderer, \
                    patch("app.pipeline.validate_export"):
                run_job(base, lambda *a: None, lambda: False)
                old_plan = json.loads((base / "output" / "plan.json").read_text(encoding="utf-8"))
                unrelated = base / "output" / "part_999.mp4"
                unrelated.write_bytes(b"user file")
                renderer.side_effect = InterruptedError("cancelled")
                with self.assertRaises(InterruptedError):
                    run_job(base, lambda *a: None, lambda: False)
                self.assertFalse((base / "previous_exports").exists())
                self.assertTrue((base / "output" / "part_003.mp4").is_file())
                renderer.side_effect = render
                outputs = run_job(base, lambda *a: None, lambda: False)
            self.assertEqual(outputs, ["part_001.mp4", "part_001.srt"])
            self.assertEqual(sorted(p.name for p in (base / "output").glob("*.mp4")),
                             ["part_001.mp4", "part_999.mp4"])
            archive = next((base / "previous_exports").iterdir())
            self.assertEqual(json.loads((archive / "plan.json").read_text(encoding="utf-8")), old_plan)
            self.assertEqual(sorted(p.name for p in archive.glob("*.mp4")), ["part_002.mp4", "part_003.mp4"])
            self.assertTrue((archive / "part_002.srt").is_file())
            self.assertTrue((archive / "part_003.checkpoint.json").is_file())
            self.assertEqual(unrelated.read_bytes(), b"user file")

    def test_resume_reuses_only_valid_output_and_changed_subtitles_rebuild(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "исходная серия.mp4"
            source.write_bytes(b"source")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            analysis = {"probe": {"duration": 5, "width": 640, "height": 360, "has_audio": True},
                        "transcript": {"words": [], "segments": []}, "shots": [],
                        "events": [{"id": "a", "start": 0, "end": 5, "kind": "story", "importance": 4}]}
            def fake_render(source, part, probe, output, work, encoder, cancelled):
                path = output / "part_001.mp4"
                path.write_bytes(b"rendered" * 1000)
                path.with_suffix(".srt").write_text("original subtitles", encoding="utf-8")
                return path
            with patch("app.analysis.analyze", return_value=analysis), patch("app.pipeline.choose_encoder", return_value="libx264"), \
                    patch("app.pipeline.render_part", side_effect=fake_render) as renderer, patch("app.pipeline.validate_export"):
                outputs = run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(outputs, ["part_001.mp4", "part_001.srt"])
                run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(renderer.call_count, 1)
                (base / "output" / "part_001.srt").write_text("tampered", encoding="utf-8")
                run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(renderer.call_count, 2)

    def test_cancel_before_analysis_preserves_job(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "input.mp4"
            source.write_bytes(b"source")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            with patch("app.analysis.analyze") as analyzer:
                with self.assertRaises(InterruptedError):
                    run_job(base, lambda *args: None, lambda: True)
                analyzer.assert_not_called()
