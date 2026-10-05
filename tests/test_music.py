import json
import random
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.config import FFMPEG, FFPROBE, TEMP
from app.media import inspect_media, render_part, run_command
from app.music import (DEFAULT_CONFIG, list_tracks, load_config, load_settings,
                       pick_track, save_settings, validate_config)


@contextmanager
def workspace_directory(prefix="music_test_"):
    path = TEMP / (prefix + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        pass


class ConfigTests(unittest.TestCase):
    def test_defaults_when_file_missing(self):
        with workspace_directory() as directory:
            self.assertEqual(load_config(directory / "config.json"), DEFAULT_CONFIG)

    def test_reads_music_section(self):
        with workspace_directory() as directory:
            path = directory / "config.json"
            path.write_text(json.dumps({"music": {"enabled": False, "volume": 0.25,
                                                  "fade_in": False, "fade_out": True}}),
                            encoding="utf-8")
            config = load_config(path)
            self.assertFalse(config["enabled"])
            self.assertEqual(config["volume"], 0.25)
            self.assertFalse(config["fade_in"])
            self.assertTrue(config["fade_out"])

    def test_rejects_volume_above_one(self):
        with self.assertRaises(ValueError):
            validate_config({"volume": 1.5})

    def test_rejects_non_boolean_enabled(self):
        with self.assertRaises(ValueError):
            validate_config({"enabled": "yes"})

    def test_rejects_non_string_track(self):
        with self.assertRaises(ValueError):
            validate_config({"track": 5})

    def test_ignores_unknown_keys(self):
        config = validate_config({"volume": 0.3, "unknown": 1})
        self.assertEqual(config["volume"], 0.3)
        self.assertNotIn("unknown", config)


class TrackTests(unittest.TestCase):
    def test_disabled_returns_none(self):
        with workspace_directory() as directory:
            (directory / "song.mp3").write_bytes(b"x")
            self.assertIsNone(pick_track(directory, {"enabled": False, "volume": 0.15}))

    def test_empty_folder_returns_none(self):
        with workspace_directory() as directory:
            self.assertIsNone(pick_track(directory, {"enabled": True, "volume": 0.15}))

    def test_missing_folder_returns_none(self):
        self.assertIsNone(pick_track(TEMP / "music_does_not_exist",
                                     {"enabled": True, "volume": 0.15}))

    def test_ignores_unsupported_files(self):
        with workspace_directory() as directory:
            (directory / "song.mp3").write_bytes(b"a")
            (directory / "readme.txt").write_bytes(b"b")
            (directory / "cover.jpg").write_bytes(b"c")
            self.assertEqual([p.name for p in list_tracks(directory)], ["song.mp3"])

    def test_picks_random_track_among_many(self):
        with workspace_directory() as directory:
            for name in ("a.mp3", "b.wav", "c.flac"):
                (directory / name).write_bytes(b"x")
            track = pick_track(directory, {"enabled": True, "volume": 0.15}, random.Random(0))
            self.assertIn(track.name, {"a.mp3", "b.wav", "c.flac"})

    def test_list_tracks_sorted(self):
        with workspace_directory() as directory:
            (directory / "b.mp3").write_bytes(b"x")
            (directory / "a.wav").write_bytes(b"x")
            self.assertEqual([p.name for p in list_tracks(directory)], ["a.wav", "b.mp3"])

    def test_pick_track_honors_configured_track(self):
        with workspace_directory() as directory:
            (directory / "a.mp3").write_bytes(b"a")
            (directory / "b.mp3").write_bytes(b"b")
            track = pick_track(directory, {"enabled": True, "volume": 0.15, "track": "b.mp3"})
            self.assertEqual(track.name, "b.mp3")

    def test_pick_track_falls_back_to_random_when_track_missing(self):
        with workspace_directory() as directory:
            (directory / "a.mp3").write_bytes(b"a")
            track = pick_track(directory, {"enabled": True, "volume": 0.15, "track": "gone.mp3"},
                               random.Random(0))
            self.assertEqual(track.name, "a.mp3")


class SettingsPersistenceTests(unittest.TestCase):
    def test_save_and_load_settings_roundtrip(self):
        with workspace_directory() as directory:
            settings_path = directory / "settings" / "music.json"
            with patch("app.music.MUSIC_SETTINGS", settings_path):
                saved = save_settings({"enabled": False, "volume": 0.3, "track": "song.mp3"})
                self.assertFalse(saved["enabled"])
                self.assertEqual(saved["volume"], 0.3)
                self.assertEqual(load_settings(), saved)
                self.assertTrue(settings_path.is_file())

    def test_load_settings_prefers_runtime_file(self):
        with workspace_directory() as directory:
            runtime = directory / "runtime.json"
            runtime.write_text(json.dumps({"music": {"enabled": False, "volume": 0.5}}), encoding="utf-8")
            with patch("app.music.MUSIC_SETTINGS", runtime), \
                    patch("app.music.MUSIC_CONFIG", directory / "missing.json"):
                config = load_settings()
                self.assertFalse(config["enabled"])
                self.assertEqual(config["volume"], 0.5)


class BackgroundMusicFilterTests(unittest.TestCase):
    def _part(self):
        return {"index": 1, "duration": 2.0, "layout": "portrait", "caption_style": "classic",
                "subtitles": [], "cuts": [{"start": 0, "end": 2.0, "focus": []}]}

    def _render(self, directory, background_music):
        base = Path(directory)
        source = base / "source.mp4"
        source.write_bytes(b"source")
        captured = {}

        def fake_run(argv, cwd, cancelled=lambda: False, timeout=None):
            captured["argv"] = [str(a) for a in argv]
            Path(argv[-1]).write_bytes(b"x" * 2000)
            return ""

        with patch("app.media.run_command", side_effect=fake_run), \
                patch("app.media.validate_export", return_value={"duration": 2.0}), \
                patch("app.media.write_ass", side_effect=lambda path, *a, **k: path.write_text("")), \
                patch("app.media.write_srt", side_effect=lambda path, *a, **k: path.write_text("")):
            render_part(source, self._part(), {"width": 320, "height": 180}, base / "output",
                        base / "work", "libx264", background_music=background_music)
        script = (base / "work" / "render.ffscript").read_text(encoding="utf-8")
        return captured["argv"], script

    def test_music_adds_mix_while_keeping_voice(self):
        with workspace_directory() as directory:
            music = Path(directory) / "song.mp3"
            music.write_bytes(b"music")
            argv, script = self._render(directory, {"path": music, "volume": 0.15,
                                                    "fade_in": True, "fade_out": True})
            self.assertIn("-stream_loop", argv)
            self.assertIn(str(music.resolve()), argv)
            self.assertIn("concat=n=1:v=0:a=1[audio]", script)
            self.assertIn("[audio][music]amix=inputs=2:duration=first:normalize=0", script)
            self.assertIn("alimiter=level=false:limit=0.95", script)
            self.assertIn("volume=0.150000", script)
            self.assertIn("afade=t=in", script)
            self.assertIn("afade=t=out", script)
            self.assertIn("[mixed]", argv)

    def test_no_music_keeps_original_audio_path(self):
        with workspace_directory() as directory:
            argv, script = self._render(directory, None)
            self.assertNotIn("amix", script)
            self.assertNotIn("volume=", script)
            self.assertNotIn("alimiter", script)
            self.assertIn("[audio]", argv)
            self.assertNotIn("[mixed]", argv)


@unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), "Portable FFmpeg has not been installed")
class BackgroundMusicIntegrationTests(unittest.TestCase):
    def test_short_music_loops_and_fades_to_match_part(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "source.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                         "color=size=160x90:rate=30", "-f", "lavfi", "-i",
                         "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            music = base / "music.wav"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                         "sine=frequency=660:sample_rate=48000", "-t", "0.5",
                         "-c:a", "pcm_s16le", str(music)], base)
            part = {"index": 1, "duration": 2.0,
                    "cuts": [{"start": 0, "end": 2.0,
                              "focus": [{"time": 0, "x": 0.5, "y": 0.5, "confidence": 0.9}]}],
                    "subtitles": []}
            result = render_part(source, part, {"width": 160, "height": 90}, base / "output",
                                 base / "work", "libx264",
                                 background_music={"path": music, "volume": 0.15,
                                                   "fade_in": True, "fade_out": True})
            info = inspect_media(result, base)
            streams = {s["codec_type"]: s for s in info["streams"]}
            self.assertLess(abs(float(info["format"]["duration"]) - 2.0), 0.15)
            self.assertLess(abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])), 0.15)


class MusicApiTests(unittest.TestCase):
    def test_get_and_put_music_settings(self):
        from fastapi.testclient import TestClient
        from app.jobs import JobManager
        from app.server import create_app
        with workspace_directory() as directory:
            base = Path(directory)
            music_dir = base / "music"
            music_dir.mkdir()
            (music_dir / "a.mp3").write_bytes(b"a")
            (music_dir / "b.wav").write_bytes(b"b")
            settings_path = base / "settings" / "music.json"
            with patch("app.music.MUSIC_SETTINGS", settings_path), \
                    patch("app.music.MUSIC_CONFIG", base / "missing.json"), \
                    patch("app.config.MUSIC", music_dir):
                client = TestClient(create_app(JobManager(root=base)), base_url="http://127.0.0.1:8765")
                data = client.get("/api/music").json()
                self.assertTrue(data["enabled"])
                self.assertEqual(data["tracks"], ["a.mp3", "b.wav"])
                self.assertIsNone(data["track"])
                updated = client.put("/api/music", json={"enabled": False, "volume": 0.25, "track": "b.wav"}).json()
                self.assertFalse(updated["enabled"])
                self.assertEqual(updated["volume"], 0.25)
                self.assertEqual(updated["track"], "b.wav")
                again = client.get("/api/music").json()
                self.assertFalse(again["enabled"])
                self.assertEqual(again["volume"], 0.25)
                self.assertEqual(again["track"], "b.wav")

