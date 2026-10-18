"""Studio Edition endpoint regressions. Uses a disposable project and fake media."""
import json
import logging
import os
import shutil
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.jobs import JobManager
from app.json_store import atomic_json
from app.server import create_app
from app.studio_render import slice_part
from tests.test_jobs import FakeWorker


class AuthoredFinishingWorker:
    """Thread-backed process protocol, exercising the real worker entry point.

    This adapter proves scheduler/command/receipt behavior, not OS process
    ownership or media decoding. Real-process and real-FFmpeg tests live apart.
    """
    def __init__(self, directory, *, command):
        self.directory, self.code = directory, None
        self.process = SimpleNamespace(pid=os.getpid())
        self.logger = logging.getLogger('app.finishing_worker')
        self.handler = logging.FileHandler(directory/'worker.log', encoding='utf-8')
        self.logger.addHandler(self.handler)
        (directory/'.start').touch()
        self.thread = threading.Thread(target=self._run, args=(command[4:],), daemon=True)
        self.thread.start()

    def _run(self, argv):
        from app.finishing_worker import main
        try:
            self.code = main(argv)
        except BaseException:
            self.logger.exception('Authored worker adapter failed')
            self.code = 1

    def poll(self):
        return self.code

    def wait(self):
        self.thread.join(5)
        assert not self.thread.is_alive(), 'Authored worker did not drain'
        return self.code

    def terminate_tree(self):
        (self.directory/'.cancel').touch()
        self.wait()

    def close(self):
        self.wait()
        self.logger.removeHandler(self.handler)
        self.handler.close()


@contextmanager
def authored_finishing(manager, render=None):
    """Real immutable command executor with deliberately authored fake media."""
    from app.content_identity import file_sha256
    from app.media import EXPORT_VALIDATION_VERSION
    execution = manager.finishing_execution
    previous_factory = execution.worker_factory
    workers = []

    def factory(directory, *, command):
        worker = AuthoredFinishingWorker(directory, command=command)
        workers.append(worker)
        return worker

    def media(source, part, probe, output, work, encoder, cancelled, **kwargs):
        if render is None:
            output.mkdir(parents=True, exist_ok=True)
            video = output/f"part_{part['index']:03}.mp4"
            video.write_bytes(b'Authored presentation, not decoded media')
        else:
            video = render(source, part, probe, output, work, encoder, cancelled, **kwargs)
        if not video.with_suffix('.srt').exists():
            video.with_suffix('.srt').write_text('Authored subtitles, not decoded media', encoding='utf-8')
        # Explicitly AUTHORED receipt for fake bytes. This adapter does not
        # attest to actual full decoding; it exercises the ownership/hash gate.
        kwargs['on_validated']({'full_decode_version': EXPORT_VALIDATION_VERSION,
            'video_sha256': file_sha256(video),
            'subtitles_sha256': file_sha256(video.with_suffix('.srt'))})
        return video

    execution.worker_factory = factory
    with patch('app.studio_render._probe', return_value={'width': 640, 'height': 360, 'audio_stream': 0}), \
            patch('app.finishing_render.render_contract', return_value={'version': 1, 'code_sha256': 'd'*64}), \
            patch('app.config.setup_environment'), \
            patch('app.media.choose_encoder', return_value='authored_encoder') as encoder, \
            patch('app.media.render_part', side_effect=media) as renderer:
        try:
            yield renderer, encoder, workers
        finally:
            deadline = time.monotonic()+5
            while not execution.closed and (execution.active or execution._pending()) and time.monotonic() < deadline:
                execution.tick()
                time.sleep(.01)
            execution.worker_factory = previous_factory
            assert all(not worker.thread.is_alive() for worker in workers), 'Authored workers outlived their test scope'


class StudioApiTests(unittest.TestCase):
    def test_queued_export_snapshots_plan_captions_and_profile(self):
        from app.studio_render import submit_render
        from app.finishing import FinishProfile
        entered, release = threading.Event(), threading.Event()
        captured = []

        def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test gate timed out')
            captured.append((json.loads(json.dumps(part)), kwargs['finishing']['video']['brightness']))
            output.mkdir(parents=True, exist_ok=True)
            path = output / f"part_{part['index']:03d}.mp4"
            path.write_bytes(b'snapshot fixture')
            return path

        profile = FinishProfile().model_dump()
        with authored_finishing(self.manager, render):
            try:
                task = submit_render(self.manager, self.job_id, [1, 2], profile)
                self.assertTrue(entered.wait(2))
                response = self.client.put(f'/api/jobs/{self.job_id}/parts/1/captions', json={
                    'part_index': 1, 'revision': 0,
                    'cues': [{'start': .4, 'end': 1.3, 'text': 'Changed while queued'}]})
                self.assertEqual(response.status_code, 200, response.text)
                self.plan['parts'][0]['cuts'][0]['end'] = 2.5
                atomic_json(self.directory / 'plan.json', self.plan)
                profile['video']['brightness'] = 140
            finally:
                release.set()
            for _ in range(200):
                state = self.client.get('/api/exports/' + task['export_id']).json()
                if state['status'] not in ('queued', 'running'):
                    break
                time.sleep(.01)
        self.assertEqual(state['status'], 'completed', state)
        self.assertEqual(captured[0][0]['subtitles'][0]['text'], 'Оригинал')
        self.assertEqual(captured[0][0]['cuts'][0]['end'], 3)
        self.assertEqual(captured[0][1], 100)
        self.assertEqual(state['caption_revisions'], {'1': 0, '2': 0})
        self.assertNotIn('finishing_applied', self.client.get('/api/jobs/' + self.job_id).json())

    def test_corrupt_and_legacy_export_records_do_not_hide_valid_files_or_projects(self):
        from app.studio_render import plan_digest
        def record(state, registry=None):
            identifier = 'ex_' + uuid.uuid4().hex
            folder = self.directory / 'finishing/exports' / identifier
            (folder / 'output').mkdir(parents=True)
            (folder / 'output/part_001.mp4').write_bytes(b'isolated presentation')
            atomic_json(self.root / 'finishing/exports-index' / (identifier + '.json'),
                        {'source_job_id': self.job_id} if registry is None else registry)
            if isinstance(state, str):
                (folder / 'status.json').write_text(state, encoding='utf-8')
            else:
                atomic_json(folder / 'status.json', state)
            return identifier
        state = {'source_job_id': self.job_id, 'status': 'completed', 'created_at_ns': 10,
                 'source_plan_digest': plan_digest(self.plan),
                 'files': [{'part_index': 1, 'name': 'part_001.mp4', 'duration': 6}]}
        valid = record(state)
        legacy = record({k: v for k, v in state.items() if k != 'source_plan_digest'})
        record('{unfinished')
        record(state, registry=[])
        record({**state, 'created_at_ns': 'bad rank'})
        record({**state, 'files': [None, 'bad entry']})
        response = self.client.get('/api/jobs')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('/api/exports/' + valid + '/', response.json()[0]['files'][0]['url'])
        self.assertEqual(self.client.get(f'/api/exports/{legacy}/files/part_001.mp4').status_code, 200)
        self.plan['parts'][0]['cuts'][0]['end'] = 2.5
        atomic_json(self.directory / 'plan.json', self.plan)
        response = self.client.get('/api/jobs/' + self.job_id).json()
        self.assertNotIn('finishing_applied', response)
        self.assertIn('/api/jobs/', response['files'][0]['url'])

    def test_apply_export_accepts_more_than_fifty_supported_parts(self):
        self.plan['parts'] = [{**self.plan['parts'][0], 'index': i} for i in range(1, 52)]
        atomic_json(self.directory / 'plan.json', self.plan)
        indices = list(range(1, 52))
        with patch('app.studio_render.submit_render', return_value={'status': 'queued'}) as submit:
            response = self.client.post('/api/jobs/' + self.job_id + '/exports', json={'part_indices': indices})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(submit.call_args.args[2], indices)
            denied = self.client.post('/api/jobs/' + self.job_id + '/exports', json={'part_indices': list(range(1, 102))})
            self.assertEqual(denied.status_code, 422)

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

    def test_publication_frame_saves_real_text_and_old_profiles_remain_valid(self):
        path = "/api/episodes/" + self.episode_id + "/finishing"
        profile = self.client.get(path).json()
        self.assertEqual(profile["video"]["frame_style"], "plain")
        profile.pop("episode_id")
        before = (self.directory / "plan.json").read_bytes()
        profile["video"].update(frame_style="social", layout="cinema", card_variant="post", channel_handle="@канал",
                                channel_name="Мой канал", post_caption="Подпись: [x]; '100%' \\ текст")
        response = self.client.put(path, json=profile)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(path).json()["video"]["channel_name"], "Мой канал")
        self.assertEqual(self.client.get(path).json()["video"]["post_caption"], profile["video"]["post_caption"])
        self.assertEqual((self.directory / "plan.json").read_bytes(), before)
        invalid = {**profile, "video": {**profile["video"], "post_caption": "x" * 181}}
        self.assertEqual(self.client.put(path, json=invalid).status_code, 422)
        invalid["video"]["post_caption"] = "bad\x00text"
        self.assertEqual(self.client.put(path, json=invalid).status_code, 422)
        legacy = {**profile, "revision": 1, "video": {k: v for k, v in profile["video"].items()
                  if k not in {"frame_style", "card_variant", "channel_name", "channel_handle", "post_caption"}}}
        old = self.client.put(path, json=legacy)
        self.assertEqual(old.status_code, 200, old.text)
        self.assertEqual(old.json()["video"]["frame_style"], "plain")

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
        from app.finishing import FinishProfile
        from app.finishing_render import freeze_command
        from app.finishing_commands import CommandError
        music_dir = self.root / "music"
        music_dir.mkdir(exist_ok=True)
        (music_dir / "available.mp3").write_bytes(b"dummy")
        audio = {"enabled": True, "volume": .15, "fade_in": 0, "fade_out": 0,
                 "ducking": False, "mode": "single", "track": "deleted.mp3",
                 "part_tracks": {}}
        profile = FinishProfile().model_dump()
        profile['audio'] = audio
        def frozen_track():
            frozen = freeze_command(self.manager, self.job_id, [1], profile)
            track = frozen['resolved_music']['1']
            return None if track is None else next(Path(asset['path']).name for asset in frozen['assets']
                                                   if asset['sha256'] == track['asset_sha256'])
        with authored_finishing(self.manager):
            with self.assertRaisesRegex(CommandError, "недоступен"), patch('app.music.pick_track_for_part',
                    side_effect=AssertionError('missing selection must not choose a fallback')):
                frozen_track()
            audio["track"] = "available.mp3"
            self.assertEqual(frozen_track(), "available.mp3")
            audio.update(mode="per_part", part_tracks={"1": "gone.wav"})
            with self.assertRaises(CommandError):
                frozen_track()
            audio["part_tracks"]["1"] = "none"
            self.assertIsNone(frozen_track())
            audio["part_tracks"]["1"] = "available.mp3"
            self.assertEqual(frozen_track(), "available.mp3")

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
        def fake_render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            output.mkdir(parents=True, exist_ok=True)
            path = output / ("part_%03d.mp4" % part["index"])
            path.write_bytes(b"new independent render")
            path.with_suffix(".srt").write_text("subtitle", encoding="utf-8")
            return path
        with authored_finishing(self.manager, fake_render):
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
        # Ready playback and copying use the rendered presentation, even on a
        # fresh GET, without rewriting the base output or the montage plan.
        public = self.client.get('/api/jobs/' + self.job_id).json()
        self.assertEqual(public['files'][0]['url'], file['url'])
        self.assertTrue(public['finishing_applied'])
        self.assertNotIn('_path', public['files'][0])
        self.assertIn('/api/jobs/', public['base_files'][0]['url'])
        destination = self.root / 'saved'
        destination.mkdir()
        copied = self.client.post('/api/jobs/' + self.job_id + '/save-videos',
                                  json={'all': True, 'destination': str(destination)})
        self.assertEqual(copied.status_code, 200, copied.text)
        self.assertEqual((destination / 'part_001.mp4').read_bytes(), b'new independent render')

    def test_repeat_apply_reuses_unchanged_parts_and_caption_edit_renders_only_its_part(self):
        def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            output.mkdir(parents=True, exist_ok=True)
            path = output / f"part_{part['index']:03}.mp4"
            path.write_bytes(b'new presentation')
            path.with_suffix('.srt').write_text('\n'.join(c['text'] for c in part['subtitles']), encoding='utf-8')
            # FFmpeg reports progress within a part, not only after it ends.
            kwargs['on_progress'](.4)
            return path
        def apply(settings=None):
            body = {'part_indices': [1, 2]}
            if settings:
                body['settings'] = settings
            response = self.client.post('/api/jobs/' + self.job_id + '/exports', json=body)
            self.assertEqual(response.status_code, 202, response.text)
            for _ in range(100):
                result = self.client.get('/api/exports/' + response.json()['export_id']).json()
                if result['status'] not in ('queued', 'running'):
                    break
                time.sleep(.01)
            self.assertEqual(result['status'], 'completed', result)
            return result
        with authored_finishing(self.manager, render) as (renderer, encoder, _):
            apply()
            self.assertEqual(renderer.call_count, 2)
            self.assertEqual(encoder.call_count, 1)
            reused = apply()
            self.assertEqual(renderer.call_count, 2, 'unchanged apply must not encode anything')
            self.assertEqual(encoder.call_count, 1)
            self.assertEqual(reused['completed_parts'], 2)
            captions = self.directory / 'finishing/captions_001.json'
            atomic_json(captions, {'revision': 1, 'cues': [{'start': .1, 'end': 1, 'text': 'Edited first'}]})
            apply()
            self.assertEqual(renderer.call_count, 3)
            self.assertEqual(renderer.call_args.args[1]['index'], 1)
            settings = self.client.get('/api/episodes/' + self.episode_id + '/finishing').json()
            settings.pop('episode_id'); settings.pop('revision')
            settings['video']['blur'] += 1
            apply(settings)
            self.assertEqual(renderer.call_count, 5, 'a global visual change affects both parts')
            # Input identity alone cannot bless a damaged previously rendered MP4.
            damaged = self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url']
            from app.studio_render import resolve_task_file
            export_id = damaged.split('/')[3]
            resolve_task_file(self.manager, export_id, 'part_001.mp4').write_bytes(b'damaged')
            apply(settings)
            self.assertEqual(renderer.call_count, 6, 'a corrupted cached presentation must be rebuilt')

    def test_failed_partial_export_and_changed_plan_never_replace_ready_shorts(self):
        from app.studio_render import submit_render, _locate_task
        from app.finishing import FinishProfile
        original = self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url']
        def fail_second(source, part, probe, output, work, encoder, cancelled, **kwargs):
            if part['index'] == 2:
                raise RuntimeError('authored render failure')
            output.mkdir(parents=True, exist_ok=True)
            path = output / 'part_001.mp4'
            path.write_bytes(b'partial render')
            return path
        with authored_finishing(self.manager, fail_second):
            task = submit_render(self.manager, self.job_id, [1, 2], FinishProfile().model_dump())
            for _ in range(100):
                status = self.client.get('/api/exports/' + task['export_id']).json()
                if status['status'] not in ('queued', 'running'):
                    break
                time.sleep(.02)
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(len(status['files']), 1, 'validated partial work remains available for resume')
        self.assertEqual(self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url'], original)
        _, folder = _locate_task(self.manager, task['export_id'])
        # Legacy status JSON cannot complete an immutable managed operation.
        atomic_json(folder/'status.json', {**status, 'status': 'completed'})
        self.assertEqual(self.client.get('/api/exports/' + task['export_id']).json()['status'], 'failed')
        self.assertEqual(self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url'], original)
        with authored_finishing(self.manager):
            task = submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump())
            for _ in range(150):
                if self.client.get('/api/exports/' + task['export_id']).json()['status'] == 'completed':
                    break
                time.sleep(.01)
        self.assertIn('/api/exports/', self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url'])
        changed = json.loads(json.dumps(self.plan))
        changed['parts'][0]['cuts'][0]['end'] = 2.5
        atomic_json(self.directory / 'plan.json', changed)
        self.assertEqual(self.client.get('/api/jobs/' + self.job_id).json()['files'][0]['url'], original)

    def test_avatar_upload_is_canonical_owned_and_supports_profile_and_preview(self):
        from PIL import Image
        import io
        data = io.BytesIO()
        Image.new('RGB', (180, 120), '#ef4835').save(data, format='JPEG')
        endpoint = '/api/episodes/' + self.episode_id
        uploaded = self.client.post(endpoint + '/finishing/avatar', files={'file': ('photo.jpg', data.getvalue(), 'image/jpeg')})
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        asset = uploaded.json()
        delivered = self.client.get(asset['url'])
        self.assertEqual(delivered.headers['content-type'], 'image/png')
        with Image.open(io.BytesIO(delivered.content)) as decoded:
            self.assertEqual(decoded.size, (512, 512))
            self.assertEqual(decoded.format, 'PNG')
        profile = self.client.get(endpoint + '/finishing').json()
        profile.pop('episode_id')
        profile['video'].update(frame_style='social', avatar_style='image', avatar_id=asset['avatar_id'])
        saved = self.client.put(endpoint + '/finishing', json=profile)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get(endpoint + '/avatars/star.png').status_code, 200)
        other = self.client.post('/api/projects/' + self.project_id + '/episodes', json={'number': 2}).json()['id']
        self.assertEqual(self.client.get('/api/episodes/' + other + '/avatars/' + asset['avatar_id'] + '.png').status_code, 404)
        other_profile = self.client.get('/api/episodes/' + other + '/finishing').json()
        other_profile.pop('episode_id')
        other_profile['video'] = profile['video']
        self.assertEqual(self.client.put('/api/episodes/' + other + '/finishing', json=other_profile).status_code, 422)
        for contents in (b'not an image', b'x' * (4 * 1024 * 1024 + 1)):
            rejected = self.client.post(endpoint + '/finishing/avatar', files={'file': ('bad.png', contents, 'image/png')})
            self.assertIn(rejected.status_code, (413, 422))

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
        def fake_render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            output.mkdir(parents=True, exist_ok=True)
            file = output / "part_001.mp4"
            file.write_bytes(b"preview")
            return file
        with authored_finishing(self.manager, fake_render):
            path = "/api/jobs/" + self.job_id + "/previews"
            self.assertEqual(self.client.post(path, json={"part_index": 1, "from": 6, "duration": 2}).status_code, 422)
            response = self.client.post(path, json={"part_index": 1, "from": 1, "duration": 3})
            self.assertEqual(response.status_code, 202, response.text)
            preview_id = response.json()["preview_id"]
            result = None
            for _ in range(100):
                polled = self.client.get(path + "/" + preview_id)
                self.assertEqual(polled.status_code, 200, polled.text)
                result = polled.json()
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


    def test_active_finishing_operation_owns_source_job_until_finished(self):
        from app.studio_render import submit_render
        started = threading.Event()
        release = threading.Event()

        def block_render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Authored test render timed out')
            output.mkdir(parents=True, exist_ok=True)
            path = output/f"part_{part['index']:03}.mp4"
            path.write_bytes(b'owned authored preview')
            return path

        from app.finishing import FinishProfile
        with authored_finishing(self.manager, block_render):
            try:
                submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                              preview=(1, 0, 1))
                self.assertTrue(started.wait(timeout=2), "Finishing worker never started")
                self.assertTrue(self.manager.finishing_execution.owns_job(self.job_id))
                from app.jobs import BusyError
                with self.assertRaises(BusyError):
                    self.manager._assert_available()
                with self.assertRaises(BusyError):
                    self.manager.create('not-read-while-finishing')
                self.assertEqual(self.manager.prune_jobs(max_jobs=0, max_age_days=None)['pruned_ids'], [])
                response = self.client.delete("/api/jobs/" + self.job_id)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertTrue(self.directory.is_dir())
            finally:
                release.set()
            for _ in range(100):
                self.manager.finishing_execution.tick()
                if not self.manager.finishing_execution.owns_job(self.job_id):
                    break
                time.sleep(0.01)
            self.assertFalse(self.manager.finishing_execution.owns_job(self.job_id))
            self.manager._assert_available()

    def test_finishing_queue_is_bounded_without_creating_rejected_files(self):
        from app.finishing import FinishProfile
        from app.studio_render import submit_render, MAX_PENDING_FINISHING_TASKS
        started = threading.Event()
        release = threading.Event()

        def block_render(source, part, probe, output, work, encoder, cancelled, **kwargs):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Authored test render timed out')
            output.mkdir(parents=True, exist_ok=True)
            path = output/f"part_{part['index']:03}.mp4"
            path.write_bytes(b'queued authored preview')
            return path

        before = set((self.directory / "finishing" / "previews").glob("pv_*"))
        with authored_finishing(self.manager, block_render):
            try:
                requests = [
                    submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                                  preview=(1, 0, 1))
                    for _ in range(MAX_PENDING_FINISHING_TASKS)
                ]
                self.assertTrue(started.wait(timeout=2))
                files_at_capacity = set((self.directory / "finishing" / "previews").glob("pv_*"))
                receipts_at_capacity = set((self.root/'finishing/operations').glob('*.json'))
                from app.file_lock import BusyError
                with self.assertRaises(BusyError), patch('app.finishing_render.freeze_command',
                        side_effect=AssertionError('rejected command inspected mutable media')):
                    submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                                  preview=(1, 0, 1))
                self.assertEqual(files_at_capacity,
                                 set((self.directory / "finishing" / "previews").glob("pv_*")))
                self.assertEqual(len(files_at_capacity - before), MAX_PENDING_FINISHING_TASKS)
                self.assertEqual(receipts_at_capacity, set((self.root/'finishing/operations').glob('*.json')))
                self.assertEqual(len(self.manager.finishing_execution._pending()), MAX_PENDING_FINISHING_TASKS)
            finally:
                release.set()
            for _ in range(200):
                self.manager.finishing_execution.tick()
                if not self.manager.finishing_execution.owns_job(self.job_id):
                    break
                time.sleep(0.01)
            self.assertFalse(self.manager.finishing_execution.owns_job(self.job_id))

    def test_close_requests_cancellation_and_drains_render_tasks(self):
        from app.studio_render import submit_render
        from app.finishing import FinishProfile
        started = threading.Event()
        def wait_until_cancelled(source, part, probe, output, work, encoder, cancelled, **kwargs):
            started.set()
            while not cancelled():
                time.sleep(.02)
            raise InterruptedError('Authored worker observed cancellation')
        with authored_finishing(self.manager, wait_until_cancelled) as (_, _, workers):
            state = submit_render(self.manager, self.job_id, [1], FinishProfile().model_dump(),
                                  preview=(1, 0, 1))
            self.assertTrue(started.wait(2))
            self.manager.close()
            self.assertIsNone(self.manager.finishing_execution.active)
            self.assertTrue(all(not worker.thread.is_alive() for worker in workers))
            from app.finishing_commands import FinishingCommands
            store = FinishingCommands(self.root)
            command = store.load(state['operation_id'])
            self.assertEqual(store._runtime(command)[1]['status'], 'interrupted')
            self.assertTrue((self.directory/'finishing/previews'/state['preview_id']/'command.json').is_file())

    def test_task_status_never_marks_just_completed_preview_interrupted(self):
        from app.studio_render import task_status
        identifier = "pv_" + uuid.uuid4().hex
        folder = self.directory / "finishing" / "previews" / identifier
        complete = {"preview_id": identifier, "source_job_id": self.job_id,
                    "status": "completed", "progress": 1.0,
                    "files": [{"part_index":1,"name":"part_001.mp4","duration":1.0}]}
        atomic_json(folder / "status.json", complete)
        before = (folder/'status.json').read_bytes()
        with patch("app.studio_render.read_json", return_value=complete) as reads:
            status = task_status(self.manager, identifier, self.job_id)
        self.assertEqual(reads.call_count, 1, 'status must project one read without repair')
        self.assertEqual(status["status"], "completed")
        self.assertEqual((folder/'status.json').read_bytes(), before)

    def test_startup_marks_legacy_orphan_interrupted_and_get_remains_read_only(self):
        from app.studio_render import task_status, recover_legacy_finishing
        orphan = "pv_" + uuid.uuid4().hex
        orphan_folder = self.directory / "finishing" / "previews" / orphan
        atomic_json(orphan_folder / "status.json", {
            "preview_id": orphan, "source_job_id": self.job_id,
            "status": "queued", "progress": 0, "files": []})
        before = (orphan_folder/'status.json').read_bytes()
        self.assertEqual(task_status(self.manager, orphan, self.job_id)['status'], 'queued')
        self.assertEqual((orphan_folder/'status.json').read_bytes(), before)
        # This is the actual startup recovery entry point, invoked explicitly
        # after authoring old records instead of making a GET mutate them.
        recover_legacy_finishing(self.manager)
        result = task_status(self.manager, orphan, self.job_id)
        self.assertEqual(result["status"], "interrupted")
        self.assertFalse(result['resumable'])
        self.assertIn("точные параметры", result["error"])
        self.assertEqual(json.loads((orphan_folder / "status.json").read_text("utf-8"))["status"],
                         "interrupted")

        live = "pv_" + uuid.uuid4().hex
        live_folder = self.directory / "finishing" / "previews" / live
        atomic_json(live_folder / "status.json", {
            "preview_id": live, "source_job_id": self.job_id,
            "status": "running", "progress": .2, "files": []})
        before = (live_folder/'status.json').read_bytes()
        self.assertEqual(task_status(self.manager, live, self.job_id)["status"], "running")
        self.assertEqual((live_folder/'status.json').read_bytes(), before,
                         'GET cannot infer orphanhood from an absent legacy thread registry')
        recover_legacy_finishing(self.manager)
        self.assertEqual(task_status(self.manager, live, self.job_id)['status'], 'interrupted')


    def test_failed_preview_writes_private_diagnostic_without_leaking_absolute_paths(self):
        private_details = "FFmpeg failure at C:/private/source/anime.mkv"
        def fail(*args, **kwargs):
            raise RuntimeError(private_details)
        with authored_finishing(self.manager, fail):
            response = self.client.post(
                "/api/jobs/" + self.job_id + "/previews",
                json={"part_index": 1, "from": 0, "duration": 2})
            self.assertEqual(response.status_code, 202, response.text)
            preview_id = response.json()["preview_id"]
            state = None
            for _ in range(120):
                state = self.client.get(
                    "/api/jobs/" + self.job_id + "/previews/" + preview_id).json()
                if state["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
        self.assertEqual(state["status"], "failed", state)
        self.assertNotIn("C:/private", json.dumps(state))
        private_log = (self.directory / "finishing" / "previews" / preview_id /
                       'attempts' / state['attempt_id'] / 'worker.log')
        self.assertIn(private_details, private_log.read_text("utf-8"))
        self.assertEqual((self.directory / "output" / "part_001.mp4").read_bytes(),
                         b"existing precious mp4")


if __name__ == "__main__":
    unittest.main()
