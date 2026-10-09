"""Studio Edition endpoint regressions. Uses a disposable project and fake media."""
import json
import shutil
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.jobs import JobManager, atomic_json
from app.server import create_app
from app.studio_render import slice_part
from tests.test_jobs import FakeWorker


class StudioApiTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP / ("studio-api-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source remains unchanged")
        self.manager = JobManager(self.root, FakeWorker)
        self.client = TestClient(create_app(self.manager), base_url="http://127.0.0.1:8765")
        self.client.__enter__()
        self.project_id = self.client.post("/api/projects", json={"title": "Studio demo"}).json()["id"]
        self.episode_id = self.client.post("/api/projects/" + self.project_id + "/episodes",
                                           json={"number": 1}).json()["id"]
        self.job_id = str(uuid.uuid4())
        self.directory = self.manager.job_dir(self.job_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.plan = {"source": {"duration": 15}, "parts": [
            {"index": 1, "duration": 6.0,
             "cuts": [{"start": 1, "end": 3, "focus": []},
                      {"start": 8, "end": 12, "focus": []}],
             "subtitles": [{"start": 0.4, "end": 1.3, "text": "Оригинал"}]},
            {"index": 2, "duration": 3.0,
             "cuts": [{"start": 12, "end": 15, "focus": []}], "subtitles": []}]}
        atomic_json(self.directory / "plan.json", self.plan)
        atomic_json(self.directory / "source.json", {"path": str(self.source)})
        atomic_json(self.directory / "job.json", {
            "id": self.job_id, "source_id": "test-source", "source_name": self.source.name,
            "episode_id": self.episode_id, "created_at": "2026-10-09T00:00:00Z",
            "updated_at": "2026-10-09T00:00:00Z",
            "status": "completed", "stage": "completed", "progress": 1.0,
            "outputs": ["part_001.mp4", "part_001.srt"]})
        output = self.directory / "output"
        output.mkdir(exist_ok=True)
        (output / "part_001.mp4").write_bytes(b"existing precious mp4")
        (output / "part_001.srt").write_bytes(b"existing srt")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root, ignore_errors=True)

    def test_finishing_profile_persists_and_validates_without_touching_analysis(self):
        path = "/api/episodes/" + self.episode_id + "/finishing"
        before = (self.directory / "plan.json").read_bytes()
        initial = self.client.get(path)
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()["video"]["zoom"], 100)
        doc = {key: value for key, value in initial.json().items()
               if key in {"version", "video", "subtitles", "audio", "part_overrides"}}
        doc["video"]["zoom"] = 117
        doc["subtitles"]["y"] = 62
        doc["part_overrides"]["1"] = {"style": {**doc["subtitles"], "color": "#aaddbb"}}
        saved = self.client.put(path, json=doc)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        self.assertEqual(self.client.get(path).json()["video"]["zoom"], 117)
        bad = dict(doc)
        bad["video"] = {**doc["video"], "zoom": 1000}
        self.assertEqual(self.client.put(path, json=bad).status_code, 422)
        self.assertEqual((self.directory / "plan.json").read_bytes(), before)

    def test_legacy_episode_captions_are_backed_up_not_shared_with_other_jobs(self):
        path = "/api/episodes/" + self.episode_id + "/finishing"
        saved = self.client.get(path).json()
        legacy = {key: value for key, value in saved.items()
                  if key in {"version", "video", "subtitles", "audio", "part_overrides", "revision"}}
        legacy["part_overrides"] = {"1": {"cues": [
            {"start": .1, "end": 2.0, "text": "СТАРАЯ ВЕРСИЯ"}]}}
        updated = self.client.put(path, json=legacy)
        self.assertEqual(updated.status_code, 200, updated.text)
        # Fresh clients never inherit unowned episode-wide caption text.
        self.assertIsNone(updated.json()["part_overrides"]["1"].get("cues"))
        profile = self.client.get(path).json()
        self.assertIsNone(profile["part_overrides"]["1"]["cues"])
        # A pre-existing legacy profile must be copied before cleanup.
        disk = self.manager.root / "finishing" / "episodes" / (self.episode_id + ".json")
        stored = json.loads(disk.read_text("utf-8"))
        stored["part_overrides"]["1"]["cues"] = [
            {"start": .3, "end": 2.0, "text": "РУЧНЫЕ ПРАВКИ"}]
        atomic_json(disk, stored)
        next_profile = {key: value for key, value in profile.items() if key != "episode_id"}
        second = self.client.put(path, json=next_profile)
        self.assertEqual(second.status_code, 200, second.text)
        backup_dir = disk.parent / "legacy-caption-backups"
        first_backup = backup_dir / (self.episode_id + "-r000000.json")
        backup = backup_dir / (self.episode_id + "-r000001.json")
        self.assertTrue(first_backup.is_file())
        self.assertEqual(json.loads(first_backup.read_text("utf-8"))[
            "part_overrides"]["1"]["cues"][0]["text"], "СТАРАЯ ВЕРСИЯ")
        self.assertTrue(backup.is_file())
        preserved = json.loads(backup.read_text("utf-8"))
        self.assertEqual(preserved["part_overrides"]["1"]["cues"][0]["text"], "РУЧНЫЕ ПРАВКИ")
        self.assertIsNone(self.client.get(path).json()["part_overrides"]["1"]["cues"])

    def test_finishing_profile_rejects_stale_revision_without_losing_changes(self):
        path = "/api/episodes/" + self.episode_id + "/finishing"
        original = self.client.get(path).json()
        first = {key: value for key, value in original.items()
                 if key in {"version", "video", "subtitles", "audio", "part_overrides", "revision"}}
        first["video"] = {**first["video"], "zoom": 110}
        saved = self.client.put(path, json=first)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        stale = {**first, "video": {**first["video"], "zoom": 130}}
        rejected = self.client.put(path, json=stale)
        self.assertEqual(rejected.status_code, 409, rejected.text)
        current = self.client.get(path).json()
        self.assertEqual(current["video"]["zoom"], 110)
        self.assertEqual(current["revision"], 1)
        next_profile = {**stale, "revision": 1}
        succeeded = self.client.put(path, json=next_profile)
        self.assertEqual(succeeded.status_code, 200, succeeded.text)
        self.assertEqual(succeeded.json()["revision"], 2)

    def test_caption_overrides_validate_bounds_revision_and_leave_original(self):
        path = "/api/jobs/" + self.job_id + "/parts/1/captions"
        self.assertEqual(self.client.get(path).json()["cues"][0]["text"], "Оригинал")
        before = (self.directory / "plan.json").read_bytes()
        data = {"part_index": 1, "revision": 0, "cues": [
            {"start": 0.0, "end": 2.5, "text": "НОВЫЙ ТЕКСТ"}]}
        saved = self.client.put(path, json=data)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        self.assertEqual(self.client.get(path).json()["cues"][0]["text"], "НОВЫЙ ТЕКСТ")
        self.assertEqual(self.client.put(path, json=data).status_code, 409)
        data["revision"] = 1
        data["cues"][0]["end"] = 100
        self.assertEqual(self.client.put(path, json=data).status_code, 422)
        self.assertEqual((self.directory / "plan.json").read_bytes(), before)

    def test_batch_save_preflights_all_caption_revisions_before_writing(self):
        profile = self.client.get("/api/episodes/" + self.episode_id + "/finishing").json()
        body = {"profile": {key: val for key, val in profile.items() if key != "episode_id"},
                "captions": [
                    {"part_index": 1, "revision": 0,
                     "cues": [{"start": 0, "end": 1, "text": "ПЕРВАЯ"}]},
                    {"part_index": 2, "revision": 0,
                     "cues": [{"start": 0, "end": 1, "text": "ВТОРАЯ"}]}]}
        path = "/api/jobs/" + self.job_id + "/finishing/state"
        first = self.client.put(path, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["profile"]["revision"], 1)
        self.assertEqual(len(first.json()["captions"]), 2)
        old_profile = (self.manager.root / "finishing" / "episodes" /
                       (self.episode_id + ".json")).read_bytes()
        old_caption = (self.directory / "finishing" / "captions_001.json").read_bytes()
        body["profile"]["revision"] = 1
        body["captions"][0]["revision"] = 1
        stale = self.client.put(path, json=body)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual((self.directory / "finishing" / "captions_001.json").read_bytes(), old_caption)
        self.assertEqual((self.manager.root / "finishing" / "episodes" /
                          (self.episode_id + ".json")).read_bytes(), old_profile)
        body["captions"][1]["revision"] = 1
        body["captions"][1]["cues"] = [{"start": 0, "end": 90, "text": "ВЫХОД ЗА КРАЙ"}]
        invalid = self.client.put(path, json=body)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual((self.directory / "finishing" / "captions_001.json").read_bytes(), old_caption)

    def test_batch_save_rolls_back_caption_files_on_profile_write_error(self):
        path = "/api/jobs/" + self.job_id + "/finishing/state"
        profile = self.client.get("/api/episodes/" + self.episode_id + "/finishing").json()
        data = {"profile": {key: val for key, val in profile.items() if key != "episode_id"},
                "captions": [{"part_index": 1, "revision": 0,
                               "cues": [{"start": 0, "end": 1, "text": "НЕ СОХРАНЯТЬ"}]}]}
        profile_path = self.manager.root / "finishing" / "episodes" / (self.episode_id + ".json")
        original_write = atomic_json
        def fail_profile(target, value):
            if Path(target) == profile_path:
                raise OSError("Disk full writing profile")
            return original_write(target, value)
        with patch("app.finishing.atomic_json", side_effect=fail_profile):
            with self.assertRaises(OSError):
                self.client.put(path, json=data)
        self.assertFalse((self.directory / "finishing" / "captions_001.json").exists())
        self.assertFalse(profile_path.exists())

    def test_finishing_never_substitutes_random_music_for_missing_selected_track(self):
        from app.studio_render import _music
        music_dir = self.root / "test-music"
        music_dir.mkdir(exist_ok=True)
        (music_dir / "available.mp3").write_bytes(b"dummy")
        audio = {"enabled": True, "volume": .15, "fade_in": 0, "fade_out": 0,
                 "ducking": False, "mode": "single", "track": "deleted.mp3",
                 "part_tracks": {}}
        with patch("app.studio_render.config.MUSIC", music_dir):
            with self.assertRaisesRegex(FileNotFoundError, "недоступен"):
                _music({"audio": audio}, 1, 2, self.plan["parts"][0])
            audio["track"] = "available.mp3"
            self.assertEqual(_music({"audio": audio}, 1, 2, self.plan["parts"][0])[
                "path"].name, "available.mp3")
            audio.update(mode="per_part", part_tracks={"1": "gone.wav"})
            with self.assertRaises(FileNotFoundError):
                _music({"audio": audio}, 1, 2, self.plan["parts"][0])
            audio["part_tracks"]["1"] = "none"
            self.assertIsNone(_music({"audio": audio}, 1, 2, self.plan["parts"][0]))
            audio["part_tracks"]["1"] = "available.mp3"
            self.assertEqual(_music({"audio": audio}, 1, 2, self.plan["parts"][0])[
                "path"].name, "available.mp3")

    def test_finishing_uses_same_russian_audio_track_as_initial_montage(self):
        from app.studio_render import _probe
        media = {"streams": [
            {"codec_type": "video", "width": 1280, "height": 720},
            {"codec_type": "audio", "tags": {"language": "ja"}},
            {"codec_type": "audio", "tags": {"language": "rus"}},
        ]}
        with patch("app.studio_render.inspect_media", return_value=media):
            self.assertEqual(_probe(self.source, self.root)["audio_stream"], 1)
            only_one = {"streams": [media["streams"][0], media["streams"][1]]}
            with patch("app.studio_render.inspect_media", return_value=only_one):
                self.assertEqual(_probe(self.source, self.root)["audio_stream"], 0)
            with self.assertRaisesRegex(ValueError, "обозначения русской"):
                with patch("app.studio_render.inspect_media", return_value={
                    "streams": [media["streams"][0], media["streams"][1],
                                {"codec_type": "audio", "tags": {"language": "en"}}]}):
                    _probe(self.source, self.root)

    def test_two_montages_of_same_episode_never_share_legacy_caption_text(self):
        from app.finishing import FinishProfile
        from app.studio_render import _effective_part
        profile = FinishProfile().model_dump()
        profile["part_overrides"]["1"] = {
            "cues": [{"start": 0.1, "end": 1.0, "text": "НЕ ТА ВЕРСИЯ"}]
        }
        # A fresh montage uses its plan even if the episode's shared profile
        # still contains an older montage's unsafely stored captions.
        current = _effective_part(self.manager, self.job_id, self.plan["parts"][0], profile)
        self.assertEqual(current["subtitles"][0]["text"], "Оригинал")
        # The current job's saved caption has precedence over legacy profile.
        captions = self.directory / "finishing" / "captions_001.json"
        atomic_json(captions, {"revision": 1, "part_index": 1, "job_id": self.job_id,
                               "cues": [{"start": .2, "end": 1.1, "text": "ТОЛЬКО ЭТО ЗАДАНИЕ"}]})
        updated = _effective_part(self.manager, self.job_id, self.plan["parts"][0], profile)
        self.assertEqual(updated["subtitles"][0]["text"], "ТОЛЬКО ЭТО ЗАДАНИЕ")
        another = str(uuid.uuid4())
        second = self.manager.job_dir(another)
        second.mkdir()
        second_part = {**self.plan["parts"][0], "subtitles": [
            {"start": 0, "end": 1, "text": "РЕПЛИКА НОВОГО МОНТАЖА"}]}
        other_result = _effective_part(self.manager, another, second_part, profile)
        self.assertEqual(other_result["subtitles"][0]["text"], "РЕПЛИКА НОВОГО МОНТАЖА")

    def test_short_preview_maps_output_seconds_to_source_cuts(self):
        part = slice_part(self.plan["parts"][0], 1.0, 4.0)
        self.assertAlmostEqual(part["duration"], 4.0)
        self.assertEqual(part["cuts"], [
            {"start": 2.0, "end": 3.0, "focus": []},
            {"start": 8.0, "end": 11.0, "focus": []}])
        self.assertEqual(part["subtitles"][0]["start"], 0)
        self.assertAlmostEqual(part["subtitles"][0]["end"], 0.3)

    def test_export_is_non_destructive_and_files_are_individually_addressed(self):
        original = (self.directory / "output" / "part_001.mp4").read_bytes()
        def fake_render(manager, job_id, part, profile, output, work, preview):
            output.mkdir(parents=True, exist_ok=True)
            path = output / ("part_%03d.mp4" % part["index"])
            path.write_bytes(b"new independent render")
            path.with_suffix(".srt").write_text("subtitle", encoding="utf-8")
            return path
        with patch("app.studio_render.render_finishing_part", side_effect=fake_render):
            request = self.client.post("/api/jobs/" + self.job_id + "/exports",
                                       json={"part_indices": [1]})
            self.assertEqual(request.status_code, 202, request.text)
            export_id = request.json()["export_id"]
            result = None
            for _ in range(100):
                result = self.client.get("/api/exports/" + export_id).json()
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.02)
            self.assertEqual(result["status"], "completed", result)
        file = result["files"][0]
        self.assertEqual(self.client.get(file["url"]).content, b"new independent render")
        self.assertEqual(self.client.get(file["subtitle_url"]).status_code, 200)
        self.assertEqual(self.client.get(file["url"], headers={"Range": "bytes=0-2"}).status_code, 206)
        self.assertEqual((self.directory / "output" / "part_001.mp4").read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), b"source remains unchanged")
        self.assertEqual(self.manager.get(self.job_id)["outputs"], ["part_001.mp4", "part_001.srt"])
        self.assertEqual(self.client.get("/api/exports/" + export_id + "/files/../job.json").status_code, 404)

    def test_legacy_completed_job_uses_migrated_library_episode(self):
        job_path = self.directory / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job.pop("episode_id")
        atomic_json(job_path, job)
        self.client.app.state.library.data["legacy_jobs"][self.job_id] = self.episode_id
        with patch("app.studio_render.submit_render",
                   return_value={"export_id": "ex_mock", "status": "queued"}):
            result = self.client.post("/api/jobs/" + self.job_id + "/exports",
                                      json={"part_indices": [1]})
        self.assertEqual(result.status_code, 202, result.text)

    def test_preview_is_isolated_and_validates_range(self):
        with patch("app.studio_render.render_finishing_part") as render:
            def fake_render(manager, job_id, part, profile, output, work, preview):
                output.mkdir(parents=True, exist_ok=True)
                file = output / "part_001.mp4"
                file.write_bytes(b"preview")
                return file
            render.side_effect = fake_render
            path = "/api/jobs/" + self.job_id + "/previews"
            self.assertEqual(self.client.post(path, json={"part_index": 1, "from": 6, "duration": 2}).status_code, 422)
            response = self.client.post(path, json={"part_index": 1, "from": 1, "duration": 3})
            self.assertEqual(response.status_code, 202, response.text)
            preview_id = response.json()["preview_id"]
            result = None
            for _ in range(100):
                result = self.client.get(path + "/" + preview_id).json()
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.02)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(self.client.get(result["url"]).content, b"preview")

    def test_music_import_rejects_invalid_windows_filenames(self):
        for name in ("CON.mp3", "AUX.wav", "bad?.mp3", "song|edit.wav", "bad<name.mp3"):
            with self.subTest(name=name):
                response = self.client.post("/api/music/import",
                                            files={"file": (name, b"audio", "audio/mpeg")})
                self.assertEqual(response.status_code, 422, response.text)

    def test_imported_music_is_streamed_only_from_allowlisted_folder(self):
        music = self.root / "music"
        music.mkdir()
        mock_probe = type("Result", (), {"stdout": json.dumps(
            {"streams": [{"codec_type": "audio"}], "format": {"duration": "2.0"}}).encode()})()
        fake_probe = self.root / "ffprobe.exe"
        fake_probe.write_bytes(b"fake")
        with patch("app.finishing.config.MUSIC", music), \
             patch("app.finishing.config.FFPROBE", fake_probe), \
             patch("app.finishing.subprocess.run", return_value=mock_probe):
            response = self.client.post("/api/music/import",
                                        files={"file": ("test.wav", b"small audio content", "audio/wav")})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["stored"], True)
            stream = self.client.get("/api/music/tracks/test.wav/stream",
                                     headers={"Range": "bytes=0-4"})
            self.assertEqual(stream.status_code, 206)
            self.assertEqual(stream.content, b"small")
            self.assertEqual(self.client.post("/api/music/import",
                files={"file": ("test.wav", b"duplicate", "audio/wav")}).status_code, 409)
            self.assertEqual(self.client.get("/api/music/tracks/missing.wav/stream").status_code, 404)


    def test_active_finishing_thread_owns_source_job_until_finished(self):
        import threading
        from app.studio_render import submit_render
        started = threading.Event()
        release = threading.Event()

        def block_render(*args, **kwargs):
            started.set()
            release.wait(timeout=5)

        from app.finishing import FinishProfile
        with patch("app.studio_render.run_export", side_effect=block_render):
            try:
                submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                              preview=(1, 0, 1))
                self.assertTrue(started.wait(timeout=2), "Finishing worker never started")
                self.assertEqual(self.manager.finishing_tasks.get(self.job_id), 1)
                from app.jobs import BusyError
                with self.assertRaisesRegex(BusyError, "предпросмотра или экспорта"):
                    self.manager._assert_available()
                response = self.client.delete("/api/jobs/" + self.job_id)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertTrue(self.directory.is_dir())
            finally:
                release.set()
            for _ in range(100):
                if not self.manager.finishing_tasks.get(self.job_id):
                    break
                time.sleep(0.01)
            self.assertFalse(self.manager.finishing_tasks.get(self.job_id))
            self.manager._assert_available()

    def test_finishing_queue_is_bounded_without_creating_rejected_files(self):
        import threading
        from app.finishing import FinishProfile
        from app.studio_render import submit_render, MAX_PENDING_FINISHING_TASKS
        started = threading.Event()
        release = threading.Event()

        def block_render(*args, **kwargs):
            started.set()
            release.wait(timeout=5)

        before = set((self.directory / "finishing" / "previews").glob("pv_*"))
        with patch("app.studio_render.run_export", side_effect=block_render):
            try:
                requests = [
                    submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                                  preview=(1, 0, 1))
                    for _ in range(MAX_PENDING_FINISHING_TASKS)
                ]
                self.assertTrue(started.wait(timeout=2))
                files_at_capacity = set((self.directory / "finishing" / "previews").glob("pv_*"))
                with self.assertRaisesRegex(RuntimeError, "Очередь экспорта заполнена"):
                    submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                                  preview=(1, 0, 1))
                self.assertEqual(files_at_capacity,
                                 set((self.directory / "finishing" / "previews").glob("pv_*")))
                self.assertEqual(len(files_at_capacity - before), MAX_PENDING_FINISHING_TASKS)
                self.assertEqual(self.manager.finishing_tasks[self.job_id],
                                 MAX_PENDING_FINISHING_TASKS)
            finally:
                release.set()
            for _ in range(200):
                if not self.manager.finishing_tasks.get(self.job_id):
                    break
                time.sleep(0.01)
            self.assertFalse(self.manager.finishing_tasks.get(self.job_id))

    def test_task_status_never_marks_just_completed_preview_interrupted(self):
        from app.studio_render import task_status
        identifier = "pv_" + uuid.uuid4().hex
        folder = self.directory / "finishing" / "previews" / identifier
        complete = {"preview_id": identifier, "source_job_id": self.job_id,
                    "status": "completed", "progress": 1.0,
                    "files": [{"part_index":1,"name":"part_001.mp4","duration":1.0}]}
        atomic_json(folder / "status.json", complete)
        stale = {**complete, "status": "running", "files": []}
        with patch("app.studio_render.read_json", side_effect=[stale, complete]) as reads:
            status = task_status(self.manager, identifier, self.job_id)
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(json.loads((folder / "status.json").read_text("utf-8")), complete)

    def test_restart_marks_orphaned_preview_interrupted_but_keeps_live_worker(self):
        from app.studio_render import task_status, _ACTIVE_TASKS, _TASKS_LOCK
        orphan = "pv_" + uuid.uuid4().hex
        orphan_folder = self.directory / "finishing" / "previews" / orphan
        atomic_json(orphan_folder / "status.json", {
            "preview_id": orphan, "source_job_id": self.job_id,
            "status": "queued", "progress": 0, "files": []})
        result = task_status(self.manager, orphan, self.job_id)
        self.assertEqual(result["status"], "interrupted")
        self.assertIn("перезапущен", result["error"])
        self.assertEqual(json.loads((orphan_folder / "status.json").read_text("utf-8"))["status"],
                         "interrupted")

        live = "pv_" + uuid.uuid4().hex
        live_folder = self.directory / "finishing" / "previews" / live
        atomic_json(live_folder / "status.json", {
            "preview_id": live, "source_job_id": self.job_id,
            "status": "running", "progress": .2, "files": []})
        with _TASKS_LOCK:
            _ACTIVE_TASKS.add(live)
        try:
            self.assertEqual(task_status(self.manager, live, self.job_id)["status"], "running")
        finally:
            with _TASKS_LOCK:
                _ACTIVE_TASKS.discard(live)


if __name__ == "__main__":
    unittest.main()
