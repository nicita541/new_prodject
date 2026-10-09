import json
import os
import random
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.config import FFMPEG, FFPROBE, TEMP
from app.media import inspect_media, render_part, run_command
from app.pipeline import _validated_cached_render
from app.music import (DEFAULT_CONFIG, list_tracks, load_config, load_settings,
                       music_library_identity, pick_track, pick_track_for_part,
                       save_settings, validate_config)


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

    def test_pick_track_for_part_per_part(self):
        with workspace_directory() as directory:
            (directory / "a.mp3").write_bytes(b"a")
            (directory / "b.mp3").write_bytes(b"b")
            config = {
                "enabled": True,
                "volume": 0.15,
                "mode": "per_part",
                "part_tracks": {"1": "b.mp3", "2": "none", "3": "a.mp3"},
            }
            track1 = pick_track_for_part(directory, config, part_index=1)
            self.assertEqual(track1.name, "b.mp3")
            track2 = pick_track_for_part(directory, config, part_index=2)
            self.assertIsNone(track2)
            track3 = pick_track_for_part(directory, config, part_index=3)
            self.assertEqual(track3.name, "a.mp3")

    def test_replacing_track_with_same_name_size_and_timestamp_changes_fingerprint(self):
        with workspace_directory() as directory:
            song = directory / "song.mp3"
            song.write_bytes(b"original")
            before = music_library_identity(directory)
            stat = song.stat()
            song.write_bytes(b"modified")
            os.utime(song, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            after = music_library_identity(directory)
            self.assertEqual(before[0]["name"], after[0]["name"])
            self.assertNotEqual(before, after)

    def test_pick_track_for_part_random_per_part_is_stable(self):
        with workspace_directory() as directory:
            for name in ("a.mp3", "b.mp3", "c.mp3"):
                (directory / name).write_bytes(b"x")
            config = {"enabled": True, "volume": 0.15, "mode": "random_per_part"}
            track1 = pick_track_for_part(directory, config, part_index=1)
            track1_again = pick_track_for_part(directory, config, part_index=1)
            self.assertEqual(track1.name, track1_again.name)


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

    def test_simultaneous_settings_writes_leave_valid_json(self):
        with workspace_directory() as directory:
            settings_path = directory / "settings" / "music.json"
            with patch("app.music.MUSIC_SETTINGS", settings_path):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    values = list(executor.map(lambda i: save_settings({"volume": i / 20}), range(20)))
                saved = load_settings()
                self.assertIn(saved, values)
                self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["music"], saved)
                self.assertEqual(list(settings_path.parent.glob("*.tmp")), [])

    def test_load_settings_prefers_runtime_file(self):
        with workspace_directory() as directory:
            runtime = directory / "runtime.json"
            runtime.write_text(json.dumps({"music": {"enabled": False, "volume": 0.5}}), encoding="utf-8")
            with patch("app.music.MUSIC_SETTINGS", runtime), \
                    patch("app.music.MUSIC_CONFIG", directory / "missing.json"):
                config = load_settings()
                self.assertFalse(config["enabled"])
                self.assertEqual(config["volume"], 0.5)


class RenderCacheTests(unittest.TestCase):
    def test_valid_cached_video_preserves_recorded_music_track(self):
        with workspace_directory() as directory:
            mp4 = directory / "part_001.mp4"
            mp4.write_bytes(b"existing encoded video")
            subtitle = mp4.with_suffix(".srt")
            subtitle.write_text("subtitles", encoding="utf-8")
            checkpoint = directory / "part_001.json"
            stat = mp4.stat()
            checkpoint.write_text(json.dumps({
                "fingerprint": "same-run",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "srt_hash": __import__("hashlib").sha256(subtitle.read_bytes()).hexdigest(),
                "music_track": "song.mp3", "encoder": "libx264"
            }), encoding="utf-8")
            with patch("app.pipeline.validate_export") as validate:
                saved = _validated_cached_render(mp4, checkpoint, "same-run",
                                                 {"duration": 2.0}, directory, lambda: False)
            self.assertEqual(saved["music_track"], "song.mp3")
            validate.assert_called_once()

    def test_cache_validation_cancellation_is_not_swallowed(self):
        with workspace_directory() as directory:
            import hashlib
            mp4 = directory / "part_001.mp4"
            mp4.write_bytes(b"encoded")
            subtitle = mp4.with_suffix(".srt")
            subtitle.write_text("subtitles")
            checkpoint = directory / "part_001.json"
            stat = mp4.stat()
            checkpoint.write_text(json.dumps({
                "fingerprint": "same-run",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "srt_hash": hashlib.sha256(subtitle.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            with patch("app.pipeline.validate_export", side_effect=InterruptedError("cancel")):
                with self.assertRaises(InterruptedError):
                    _validated_cached_render(mp4, checkpoint, "same-run",
                                             {"duration": 2.0}, directory, lambda: False)

    def test_non_object_or_truncated_cache_is_a_miss(self):
        with workspace_directory() as directory:
            mp4 = directory / "part_001.mp4"
            mp4.write_bytes(b"encoded")
            mp4.with_suffix(".srt").write_text("subtitles")
            checkpoint = directory / "part_001.json"
            with patch("app.pipeline.validate_export") as validate:
                for broken in ("[]", '{"fingerprint":', 'null', 'true'):
                    with self.subTest(broken=broken):
                        checkpoint.write_text(broken, encoding="utf-8")
                        self.assertIsNone(_validated_cached_render(
                            mp4, checkpoint, "same-run", {"duration": 2.0},
                            directory, lambda: False))
            validate.assert_not_called()


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

    def test_nvenc_error_falls_back_to_cpu_without_losing_background_music(self):
        with workspace_directory() as directory:
            source = directory / "source.mp4"
            source.write_bytes(b"source")
            track = directory / "music.wav"
            track.write_bytes(b"audio")
            calls = []

            def fake_run(argv, cwd, cancelled=lambda: False, timeout=None):
                calls.append([str(arg) for arg in argv])
                if "h264_nvenc" in argv:
                    raise RuntimeError("GPU encoder unavailable")
                Path(argv[-1]).write_bytes(b"x" * 2000)
                return ""

            with patch("app.media.run_command", side_effect=fake_run), \
                    patch("app.media.validate_export", return_value={"duration": 2.0}), \
                    patch("app.media.write_ass", side_effect=lambda path, *a, **k: path.write_text("")), \
                    patch("app.media.write_srt", side_effect=lambda path, *a, **k: path.write_text("")):
                render_part(source, self._part(), {"width": 320, "height": 180},
                            directory / "output", directory / "work", "h264_nvenc",
                            background_music={"path": track, "volume": 0.15})
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("-stream_loop" in argv for argv in calls))
            self.assertIn("libx264", calls[-1])
            self.assertIn("amix=inputs=2", (directory / "work" / "render.ffscript").read_text(encoding="utf-8"))
            metadata = json.loads((directory / "work" / "render-info.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["encoder"], "libx264")

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

    def test_put_music_settings_with_modes_and_per_part(self):
        from fastapi.testclient import TestClient
        from app.jobs import JobManager
        from app.server import create_app
        with workspace_directory() as directory:
            base = Path(directory)
            music_dir = base / "music"
            music_dir.mkdir()
            (music_dir / "x.mp3").write_bytes(b"x")
            settings_path = base / "settings" / "music.json"
            with patch("app.music.MUSIC_SETTINGS", settings_path), \
                    patch("app.music.MUSIC_CONFIG", base / "missing.json"), \
                    patch("app.config.MUSIC", music_dir):
                client = TestClient(create_app(JobManager(root=base)), base_url="http://127.0.0.1:8765")
                updated = client.put("/api/music", json={
                    "enabled": True,
                    "volume": 0.15,
                    "mode": "per_part",
                    "part_tracks": {"1": "x.mp3", "2": "none"},
                }).json()
                self.assertEqual(updated["mode"], "per_part")
                self.assertEqual(updated["part_tracks"], {"1": "x.mp3", "2": "none"})
                get_res = client.get("/api/music").json()
                self.assertEqual(get_res["mode"], "per_part")
                self.assertEqual(get_res["part_tracks"], {"1": "x.mp3", "2": "none"})


