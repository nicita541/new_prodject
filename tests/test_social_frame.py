"""Publication appearance, literal user text and render-only cache changes."""
import json
import shutil
import unittest
import uuid
from unittest.mock import patch

from PIL import Image
from pydantic import ValidationError

from app.config import TEMP
from app.finishing_profile import VideoFinish, load_video_finish, profile_path
from app.json_store import atomic_json
from app.media import render_part
from app.pipeline import run_job
from app.social_frame import geometry, write_card


class SocialFrameTests(unittest.TestCase):
    def setUp(self):
        self.root = TEMP / ("social-frame-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_profile_reads_are_bounded_to_workspace_and_text_is_literal(self):
        identifier = str(uuid.uuid4())
        path = profile_path(self.root, identifier)
        self.assertEqual(load_video_finish(self.root, identifier)["frame_style"], "plain")
        self.assertFalse(path.parent.exists(), "reading defaults must not create directories")
        video = VideoFinish(frame_style="social", channel_name="  Канал\nимя  ",
                            post_caption="x;[in]overlay=a:b,'\\%{eif:1}'").model_dump()
        atomic_json(path, {"video": video})
        self.assertEqual(load_video_finish(self.root, identifier), video)
        self.assertEqual(video["channel_name"], "Канал имя")
        with self.assertRaises(ValueError):
            profile_path(self.root, "../../secret")
        with self.assertRaises(ValidationError):
            VideoFinish(channel_name="x" * 61)
        with self.assertRaises(ValidationError):
            VideoFinish(card_variant="unknown")
        with self.assertRaises(ValidationError):
            VideoFinish(channel_handle="x" * 61)

    def test_card_keeps_whole_source_hole_transparent_without_invented_metadata(self):
        for variant, width, height in [(v, w, h) for v in ("compact", "post")
                                      for w, h in [(1920, 1080), (600, 1600), (800, 800)]]:
            with self.subTest(variant=variant, width=width, height=height):
                card = self.root / "card.png"
                box = write_card(card, width, height, {"channel_name": "", "post_caption": "", "card_variant": variant})
                with Image.open(card) as image:
                    self.assertEqual(image.size, (1080, 1920))
                    self.assertEqual(image.getpixel((540, box["y"] + box["height"] // 2))[3], 0)
                    self.assertEqual(image.getpixel((540, box["card_top"] + 5)),
                                     (20, 33, 42, 255) if variant == "post" else (8, 11, 15, 255))
                    self.assertEqual(box["y"], box["card_top"] + (400 if variant == "post" else 280))
                self.assertLessEqual(abs(box["width"] / box["height"] - width / height), .01)
                self.assertLessEqual(box["height"], 800)

    def test_user_text_never_enters_filters_and_music_input_index_remains_correct(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"test")
        text = "Подпись: [in];overlay=1:2,'\\%{eif:1}'"
        part = {"index": 1, "duration": 1.0, "layout": "portrait", "subtitles": [],
                "cuts": [{"start": 0, "end": 1, "focus": []}]}
        with patch("app.media.run_command", side_effect=InterruptedError("captured")) as command:
            with self.assertRaises(InterruptedError):
                render_part(source, part, {"width": 320, "height": 180}, self.root / "output",
                            self.root / "work", "libx264",
                            finishing={"video": {"frame_style": "social", "post_caption": text, "zoom": 160}},
                            background_music={"path": source, "volume": .1})
        filters = (self.root / "work" / "render.ffscript").read_text("utf-8")
        self.assertNotIn(text, filters)
        self.assertIn("[joined][1:v:0]overlay=0:0:shortest=1[carded]", filters)
        self.assertIn("[2:a:0]atrim=", filters)
        self.assertNotIn("scale=iw*1.6000", filters)
        self.assertIn("social-card.png", " ".join(command.call_args.args[0]))

    def test_first_export_uses_saved_card_and_caption_changes_reuse_plan(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"source")
        atomic_json(self.root / "source.json", {"path": str(source)})
        atomic_json(self.root / "job.json", {"episode_id": str(uuid.uuid4())})
        analysis = {"probe": {"duration": 5, "width": 640, "height": 360, "has_audio": True},
                    "transcript": {"words": [], "segments": []}, "shots": [],
                    "events": [{"id": "a", "start": 0, "end": 5, "kind": "story", "importance": 4}]}
        style = VideoFinish(frame_style="social", channel_name="Имя", post_caption="Первый").model_dump()
        def rendered(source, part, probe, output, work, encoder, cancelled, **kwargs):
            path = output / "part_001.mp4"
            path.write_bytes(b"valid-render" * 1000)
            path.with_suffix(".srt").write_text("captions", encoding="utf-8")
            return path
        with patch("app.analysis.analyze", return_value=analysis), \
             patch("app.pipeline.choose_encoder", return_value="libx264"), \
             patch("app.pipeline.render_part", side_effect=rendered) as renderer, \
             patch("app.pipeline.validate_export"), \
             patch("app.finishing_profile.load_video_finish", return_value=style):
            run_job(self.root, lambda *args: None, lambda: False)
            first = json.loads((self.root / "plan.json").read_text("utf-8"))
            self.assertEqual(renderer.call_args.kwargs["finishing"]["video"]["post_caption"], "Первый")
            run_job(self.root, lambda *args: None, lambda: False)
            self.assertEqual(renderer.call_count, 1)
            style["post_caption"] = "Изменённый"
            run_job(self.root, lambda *args: None, lambda: False)
            changed = json.loads((self.root / "plan.json").read_text("utf-8"))
            self.assertEqual(renderer.call_count, 2)
            self.assertEqual(first["fingerprint"], changed["fingerprint"])
            self.assertNotEqual(first["render_fingerprint"], changed["render_fingerprint"])
            style["card_variant"] = "post"
            style["channel_handle"] = "@имя"
            run_job(self.root, lambda *args: None, lambda: False)
            variant = json.loads((self.root / "plan.json").read_text("utf-8"))
            self.assertEqual(renderer.call_count, 3)
            self.assertEqual(first["fingerprint"], variant["fingerprint"])
            self.assertNotEqual(changed["render_fingerprint"], variant["render_fingerprint"])
            self.assertEqual(variant["render_video"]["channel_handle"], "@имя")
            style["frame_style"] = "plain"
            run_job(self.root, lambda *args: None, lambda: False)
            self.assertEqual(renderer.call_count, 4)
            self.assertIsNone(renderer.call_args.kwargs["finishing"])
