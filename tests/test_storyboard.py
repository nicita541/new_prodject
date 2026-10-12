"""Regression coverage for collages labeling stale cached frames as new times."""
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.vision import storyboard
from app.config import TEMP


class StoryboardCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP / ("storyboard_test_" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.source = self.directory / "Русская серия с пробелами.mp4"
        self.source.write_bytes(b"A-source")
        self.collage = self.directory / "event_0000.jpg"
        self.commands = []

    @staticmethod
    def color(timestamp, source):
        return (35 + round(timestamp * 10) % 180, source.read_bytes()[0], 60)

    def extract_frame(self, command, log, cancelled, timeout=3600):
        timestamp = float(command[command.index("-ss") + 1])
        source = Path(command[command.index("-i") + 1])
        destination = Path(command[-1])
        self.commands.append({"timestamp": timestamp, "source": source, "destination": destination})
        # Pillow stands in for FFmpeg and makes each frame's real timestamp
        # observable in the generated collage, without invoking a decoder/model.
        Image.new("RGB", (480, 270), self.color(timestamp, source)).save(destination, quality=96)

    def render(self, start=0, end=10, source=None):
        # These cache tests mock JPEG extraction and do not need a valid video
        # container; source-bound probing has separate FFmpeg integration tests.
        with patch("app.media.video_frame_bounds", return_value=(0.0, 100.0)), \
                patch("app.vision.run_process", side_effect=self.extract_frame):
            return storyboard(source or self.source, start, end, [], {"words": [], "segments": []},
                              self.collage, lambda: False)

    def assert_collage_has_actual_frames(self, timestamps, source=None):
        source = source or self.source
        with Image.open(self.collage) as collage:
            for index, timestamp in enumerate(timestamps):
                # Sample the image center, away from captions and JPEG boundaries.
                pixel = collage.getpixel(((index % 2) * 480 + 240, (index // 2) * 294 + 159))
                expected = self.color(timestamp, source)
                self.assertTrue(all(abs(actual - target) <= 4 for actual, target in zip(pixel, expected)),
                                f"Frame {index + 1} claims {timestamp}s but contains {pixel}, expected {expected}")

    def test_same_source_and_timestamps_reuse_extracted_frames(self):
        first = self.render()
        extracted = len(self.commands)
        second = self.render()
        self.assertEqual(second, first)
        self.assertEqual(len(self.commands), extracted)
        self.assert_collage_has_actual_frames(second)

    def test_shifted_window_extracts_new_frames_under_same_event_name(self):
        first = self.render()
        extracted = len(self.commands)
        shifted = self.render(start=1, end=11)
        self.assertFalse(set(first) & set(shifted))
        self.assertEqual([command["timestamp"] for command in self.commands[extracted:]], shifted)
        self.assert_collage_has_actual_frames(shifted)

    def test_shared_absolute_timestamp_is_reused_when_panel_index_changes(self):
        first = self.render(start=0, end=10)
        extracted = len(self.commands)
        wider = self.render(start=0, end=20)
        shared = set(first) & set(wider)
        self.assertTrue(shared)
        self.assertNotEqual(first.index(5.0), wider.index(5.0))
        self.assertEqual([command["timestamp"] for command in self.commands[extracted:]],
                         [timestamp for timestamp in wider if timestamp not in shared])
        self.assert_collage_has_actual_frames(wider)

    def test_source_mtime_change_invalidates_same_timestamp_frames(self):
        first = self.render()
        extracted = len(self.commands)
        stat = self.source.stat()
        # Same name and length; changing content + mtime must not reuse old pixels.
        self.source.write_bytes(b"Z-source")
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        current = self.render()
        self.assertEqual(current, first)
        self.assertEqual(len(self.commands) - extracted, len(current))
        self.assert_collage_has_actual_frames(current)

    def test_source_size_change_invalidates_even_when_mtime_is_preserved(self):
        first = self.render()
        extracted = len(self.commands)
        stat = self.source.stat()
        self.source.write_bytes(b"A-longer-source")
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        current = self.render()
        self.assertEqual(current, first)
        self.assertEqual(len(self.commands) - extracted, len(current))
        self.assert_collage_has_actual_frames(current)

    def test_different_source_path_invalidates_even_when_size_mtime_match(self):
        first = self.render()
        extracted = len(self.commands)
        stat = self.source.stat()
        other_source = self.directory / "Другая серия.mp4"
        other_source.write_bytes(self.source.read_bytes())
        os.utime(other_source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        current = self.render(source=other_source)
        self.assertEqual(current, first)
        new_commands = self.commands[extracted:]
        self.assertEqual(len(new_commands), len(current))
        self.assertTrue(all(command["source"] == other_source for command in new_commands))
        self.assert_collage_has_actual_frames(current, other_source)
