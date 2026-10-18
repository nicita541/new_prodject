from __future__ import annotations

import threading
import shutil
import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from app import config
from app.jobs import BusyError, DamagedJobError, HEARTBEAT_STALE_SECONDS, JobManager, WorkerProcess
from app.json_store import atomic_json, read_json


def deepseek_stub(status=None, connection=None):
    # Never import the real client's private settings or contact its API.
    module = ModuleType("app.deepseek")
    module.begin_attempt = Mock(return_value={'attempt': 2, 'charged_ceiling_usd': '0'})
    module.public_status = Mock(return_value=status if status is not None else {
        "configured": True, "budget_usd": None, "charged_ceiling_usd": "0",
        "remaining_usd": "0.06", "model": "deepseek-flash"})
    module.check_connection = Mock(return_value=connection if connection is not None else {
        "available": True, "balance_infos": [{"currency": "USD", "total_balance": "0.06"}],
        "model": "deepseek-flash", "vision_supported": False})
    return module


class FakeWorker:
    instances = []
    def __init__(self, directory):
        self.directory = directory
        self.done = threading.Event()
        self.terminated = False
        self.closed = False
        self.instances.append(self)
    def poll(self):
        return 0 if self.done.is_set() else None
    def wait(self):
        self.done.wait()
        return 1 if self.terminated else 0
    def terminate_tree(self):
        self.terminated = True
        self.done.set()
    def close(self):
        self.closed = True


class JobTests(unittest.TestCase):
    def test_startup_isolates_damaged_jobs_without_rewriting_originals(self):
        healthy = self.manager.create(self.source_id)
        self.manager.close()
        damaged = {}
        for content in (b'{"status":', b'null', b'[]',
                        b'{"id":"wrong","status":"running"}', b'\xff\xfe'):
            identifier = str(uuid.uuid4())
            directory = self.manager.job_dir(identifier)
            directory.mkdir()
            (directory / 'job.json').write_bytes(content)
            damaged[identifier] = content
        with self.assertLogs('app.jobs', level='ERROR') as messages:
            self.manager = JobManager(self.root, FakeWorker)
        damage_records = [item for item in messages.records
                          if getattr(item, 'action', None) == 'job_record_damaged']
        self.assertEqual(len(damage_records), len(damaged))
        self.assertEqual({job['id'] for job in self.manager.list_jobs()}, {healthy['id']})
        self.assertEqual(self.manager.get(healthy['id'])['status'], 'interrupted')
        for identifier, content in damaged.items():
            with self.assertRaisesRegex(DamagedJobError, 'Исходный job.json сохранён'):
                self.manager.get(identifier)
            self.assertEqual((self.manager.job_dir(identifier) / 'job.json').read_bytes(), content)
        self.assertEqual(set(self.manager.damaged_jobs), set(damaged))
        self.assertEqual(self.manager.retry(healthy['id'])['status'], 'running')

    def test_listing_isolates_new_corruption_and_recognizes_repaired_record(self):
        first = self.manager.create(self.source_id)
        self.manager.cancel(first['id'])
        path = self.manager.job_dir(first['id']) / 'job.json'
        original = path.read_bytes()
        second = self.manager.create(self.source_id)
        path.write_bytes(b'{"private_marker": "must-not-appear-in-diagnostic",')
        with self.assertLogs('app.jobs', level='ERROR') as messages:
            self.assertEqual([job['id'] for job in self.manager.list_jobs()], [second['id']])
        self.assertNotIn('private_marker', ' '.join(messages.output))
        self.assertIn(first['id'], self.manager.damaged_jobs)
        self.assertTrue(path.read_bytes().endswith(b','))
        path.write_bytes(original)
        self.assertEqual(len(self.manager.list_jobs()), 2)
        self.assertNotIn(first['id'], self.manager.damaged_jobs)

    def test_cancel_still_drains_owned_worker_if_its_record_is_damaged(self):
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        path = self.manager.job_dir(job['id']) / 'job.json'
        path.write_bytes(b'{broken')
        with self.assertLogs('app.jobs', level='ERROR'), self.assertRaises(DamagedJobError):
            self.manager.cancel(job['id'])
        self.assertTrue(child.terminated)
        self.assertTrue(child.closed)
        self.assertFalse(self.manager.busy())
        self.assertEqual(path.read_bytes(), b'{broken')

    def test_heartbeat_advances_without_progress_and_stale_does_not_kill(self):
        job = self.manager.create(self.source_id)
        with self.manager.mutex:
            child = self.manager.active[1]
            child.process = SimpleNamespace(pid=4123)
            path = self.manager.job_dir(job['id']) / 'job.json'
            original = path.read_bytes()
            heartbeat = path.with_name('worker-heartbeat.json')
            record = {'version': 1, 'attempt_id': job['attempt_id'], 'pid': child.process.pid,
                      'sequence': 1, 'heartbeat_at': '2026-10-15T00:00:00+00:00'}
            atomic_json(heartbeat, record)
            self.assertEqual(self.manager.get(job['id'])['worker_health']['status'], 'healthy')
            self.manager._worker_observation['last_seen'] -= HEARTBEAT_STALE_SECONDS + 1
            with self.assertLogs('app.jobs', level='WARNING'):
                health = self.manager.get(job['id'])['worker_health']
            self.assertEqual(health['status'], 'stale')
            self.assertTrue(health['process_alive'])
            self.assertFalse(child.terminated)
            atomic_json(heartbeat, {**record, 'sequence': 2})
            self.assertEqual(self.manager.get(job['id'])['worker_health']['status'], 'healthy')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.manager.get(job['id'])['updated_at'], job['updated_at'])

    def test_wrong_attempt_pid_and_malformed_heartbeat_cannot_refresh_liveness(self):
        job = self.manager.create(self.source_id)
        with self.manager.mutex:
            child = self.manager.active[1]
            child.process = SimpleNamespace(pid=4123)
            path = self.manager.job_dir(job['id']) / 'worker-heartbeat.json'
            record = {'version': 1, 'attempt_id': job['attempt_id'], 'pid': 4123,
                      'sequence': 1, 'heartbeat_at': '2099-01-01T00:00:00+00:00'}
            self.manager._worker_observation['last_seen'] -= HEARTBEAT_STALE_SECONDS + 1
            for value in ({**record, 'attempt_id': uuid.uuid4().hex},
                          {**record, 'pid': 9999}, {**record, 'sequence': True}, ['invalid']):
                atomic_json(path, value)
                health = self.manager.get(job['id'])['worker_health']
                self.assertEqual(health['status'], 'stale')
                self.assertEqual(self.manager._worker_observation['sequence'], 0)
            path.write_bytes(b'{broken')
            self.assertEqual(self.manager.get(job['id'])['worker_health']['heartbeat_issue'], 'unreadable')
            self.assertFalse(child.terminated)
            atomic_json(path, record)
            self.assertEqual(self.manager.get(job['id'])['worker_health']['status'], 'healthy')

    def test_retry_changes_attempt_and_old_watcher_cannot_own_new_worker(self):
        first = self.manager.create(self.source_id)
        previous = self.manager.active[1]
        self.manager.cancel(first['id'])
        retried = self.manager.retry(first['id'])
        self.assertNotEqual(first['attempt_id'], retried['attempt_id'])
        with self.manager.mutex:
            current = self.manager.active[1]
            current.process = SimpleNamespace(pid=4123)
            atomic_json(self.manager.job_dir(first['id']) / 'worker-heartbeat.json', {
                'version': 1, 'attempt_id': first['attempt_id'], 'pid': 4123,
                'sequence': 100, 'heartbeat_at': '2099-01-01T00:00:00+00:00'})
            self.assertEqual(self.manager.get(first['id'])['worker_health']['status'], 'starting')
            self.assertIsNone(self.manager._observe_worker(first['id'], previous))
            self.manager._watch(first['id'], previous)
            self.assertIs(self.manager.active[1], current)
            self.assertFalse(current.closed)
            self.assertFalse(current.terminated)

    def test_real_owned_child_heartbeat_is_visible_without_pipeline_progress(self):
        def factory(directory):
            script = ("from pathlib import Path; import time; "
                      "from app.worker import WorkerHeartbeat; "
                      "from app.json_store import read_json; "
                      f"directory=Path({str(directory)!r}); "
                      "gate=directory/'.start'; exec('while not gate.exists(): time.sleep(.01)'); "
                      "heartbeat=WorkerHeartbeat(directory, read_json(directory/'job.json')['attempt_id'], interval=.03); "
                      "heartbeat.start(); time.sleep(60)")
            return WorkerProcess(directory, command=[sys.executable, '-c', script])

        self.manager.worker_factory = factory
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                current = self.manager.get(job['id'])
                if current.get('worker_health', {}).get('status') == 'healthy':
                    break
                time.sleep(.02)
            self.assertEqual(current['worker_health']['status'], 'healthy')
            self.assertTrue(current['worker_health']['process_alive'])
            self.assertIsNone(current['progress_updated_at'])
            self.assertEqual(read_json(self.manager.job_dir(job['id']) / 'worker-heartbeat.json')['pid'],
                             child.process.pid)
        finally:
            self.manager.cancel(job['id'])
        self.assertIsNotNone(child.poll())

    def test_atomic_json_keeps_old_state_and_cleans_temporary_file_on_failure(self):
        path = self.root / 'atomic-state.json'
        atomic_json(path, {'value': 'old'})
        before = path.read_bytes()
        with patch('app.json_store.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                atomic_json(path, {'value': 'new'})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.atomic-state.json.*.tmp')), [])

    def test_atomic_json_retries_transient_windows_lock_and_preserves_encoding(self):
        import json
        from app.json_store import analysis_json, compact_json
        path = self.root / 'atomic-encoding.json'
        replace = os.replace
        with patch('app.json_store.os.replace', side_effect=[PermissionError('locked'), None]) as mocked, \
             patch('app.json_store.time.sleep') as sleep:
            # The successful attempt must actually publish the temporary file.
            def publish(source, destination):
                if mocked.call_count == 1:
                    raise PermissionError('locked')
                return replace(source, destination)
            mocked.side_effect = publish
            atomic_json(path, {'text': 'Кадр'})
        self.assertEqual(read_json(path), {'text': 'Кадр'})
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once_with(.01)
        value = {'text': 'Кадр', 'float': float('nan')}
        with self.assertRaises(ValueError):
            atomic_json(path, value)
        self.assertEqual(read_json(path), {'text': 'Кадр'})
        analysis_json(path, value)
        self.assertEqual(path.read_text('utf-8'), json.dumps(value, ensure_ascii=False, indent=2))
        compact_json(path, {'text': 'Кадр'})
        self.assertEqual(path.read_text('utf-8'), json.dumps({'text': 'Кадр'}, ensure_ascii=False))

    def test_concurrent_json_writers_publish_complete_records(self):
        from concurrent.futures import ThreadPoolExecutor
        path = self.root / 'atomic-concurrent.json'
        values = [{'index': index, 'payload': 'Кадр' * 2048} for index in range(16)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda value: atomic_json(path, value), values))
        self.assertIn(read_json(path), values)
        self.assertEqual(list(self.root.glob('.atomic-concurrent.json.*.tmp')), [])

    def test_default_analysis_remains_local_without_reading_deepseek_settings(self):
        client = deepseek_stub()
        with patch.dict(sys.modules, {"app.deepseek": client}):
            job = self.manager.create(self.source_id)
        self.assertEqual(job["analysis_provider"], "local")
        self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "analysis-settings.json"), {"provider": "local", "economy_mode": True})
        client.public_status.assert_not_called()
        client.check_connection.assert_not_called()

    def test_explicit_deepseek_selection_and_retry_ignore_money_status(self):
        client=deepseek_stub({'configured':True,'remaining_usd':'0'})
        with patch.dict(sys.modules, {'app.deepseek':client}):
            job=self.manager.create(self.source_id,'deepseek')
            self.assertEqual(job['analysis_provider'],'deepseek')
            self.manager.cancel(job['id'])
            client.public_status.return_value['remaining_usd']='NaN'
            self.assertEqual(self.manager.retry(job['id'])['analysis_provider'],'deepseek')
        client.check_connection.assert_not_called()

    def test_hybrid_create_and_retry_allow_unavailable_remote_without_settings_reads(self):
        for status in ({"configured": False, "remaining_usd": "0"},
                       {"configured": True, "remaining_usd": "0"}):
            with self.subTest(status=status):
                client = deepseek_stub(status)
                client.public_status.side_effect = RuntimeError("Remote settings unavailable")
                with patch.dict(sys.modules, {"app.deepseek": client}):
                    job = self.manager.create(self.source_id, "hybrid")
                    directory = self.manager.job_dir(job["id"])
                    self.assertEqual(job["analysis_provider"], "hybrid")
                    self.assertEqual(read_json(directory / "analysis-settings.json"), {"provider": "hybrid", "economy_mode": True})
                    self.manager.cancel(job["id"])
                    # Recovery must retain the chosen provider across a server restart.
                    self.manager.close()
                    self.manager = JobManager(self.root, FakeWorker)
                    retried = self.manager.retry(job["id"])
                    self.assertEqual(retried["analysis_provider"], "hybrid")
                    self.assertEqual(retried["status"], "running")
                    self.assertEqual(read_json(directory / "analysis-settings.json"), {"provider": "hybrid", "economy_mode": True})
                    self.manager.cancel(job["id"])
                client.public_status.assert_not_called()
                client.check_connection.assert_not_called()

    def test_deepseek_plan_persists_and_retries_without_balance(self):
        client=deepseek_stub({'configured':True,'remaining_usd':None})
        with patch.dict(sys.modules, {'app.deepseek':client}):
            job=self.manager.create(self.source_id,'deepseek_plan')
            directory=self.manager.job_dir(job['id'])
            self.assertEqual(read_json(directory/'analysis-settings.json'),{'provider':'deepseek_plan','economy_mode':True})
            self.manager.cancel(job['id'])
            self.assertEqual(self.manager.retry(job['id'])['analysis_provider'],'deepseek_plan')
        client.check_connection.assert_not_called()

    def test_unconfigured_deepseek_plan_creates_nothing(self):
        with patch.dict(sys.modules, {'app.deepseek':deepseek_stub({'configured':False,'remaining_usd':'100'})}):
            with self.assertRaises(ValueError):self.manager.create(self.source_id,'deepseek_plan')
        self.assertEqual(list(self.manager.jobs.iterdir()),[])

    def test_unconfigured_and_unknown_provider_have_no_job_side_effects(self):
        with patch.dict(sys.modules, {'app.deepseek':deepseek_stub({'configured':False})}):
            with self.assertRaises(ValueError):self.manager.create(self.source_id,'deepseek')
        with self.assertRaises(ValueError):self.manager.create(self.source_id,'unexpected')
        self.assertEqual(list(self.manager.jobs.iterdir()),[])
        self.assertFalse(self.manager.busy())

    def test_cancel_storage_failure_still_kills_tree_and_retains_actual_state(self):
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        with self.assertLogs("app.jobs", level="ERROR"), \
                patch("pathlib.Path.touch", side_effect=OSError("disk full")), \
                patch("app.jobs.atomic_json", side_effect=OSError("disk full")):
            cancelled = self.manager.cancel(job["id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertTrue(child.terminated)
            self.assertTrue(child.closed)
            self.assertFalse(self.manager.busy())
            self.assertEqual(self.manager.get(job["id"])["status"], "cancelled")
        self.assertEqual(self.manager.get(job["id"])["status"], "cancelled")
        self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "job.json")["status"], "cancelled")
        self.assertEqual(self.manager.retry(job["id"])["status"], "running")

    def test_watcher_storage_failure_releases_worker_and_recovers_for_retry(self):
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        with self.assertLogs("app.jobs", level="ERROR"), patch("app.jobs.atomic_json", side_effect=OSError("disk full")):
            child.done.set()
            for _ in range(100):
                if not self.manager.busy():
                    break
                time.sleep(0.01)
            self.assertFalse(self.manager.busy())
            self.assertTrue(child.closed)
            self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "job.json")["status"], "running")
        recovered = self.manager.get(job["id"])
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "job.json")["status"], "interrupted")
        self.assertEqual(self.manager.retry(job["id"])["status"], "running")

    def test_close_storage_failure_releases_process_and_instance_lock(self):
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        with self.assertLogs("app.jobs", level="ERROR"), patch("app.jobs.atomic_json", side_effect=OSError("disk full")):
            self.manager.close()
        self.assertTrue(child.terminated)
        self.assertTrue(child.closed)
        self.assertFalse(self.manager.busy())
        self.manager = JobManager(self.root, FakeWorker)
        self.assertEqual(self.manager.get(job["id"])["status"], "interrupted")

    def setUp(self):
        self.root = config.TEMP / ("jobs_" + uuid.uuid4().hex)
        self.root.mkdir()
        self.manager = JobManager(self.root, FakeWorker)
        # Linux limits UTF-8 filename components to 255 bytes; Windows uses
        # UTF-16 code units. Keep a long Cyrillic name on both platforms.
        repeats = 4 if os.name == "nt" else 2
        self.source = self.root / ("Серия с длинным русским именем и пробелами " * repeats + ".mp4")
        self.source.write_bytes(b"unchanged source")
        self.source_id = self.manager.list_sources()[0]["id"]
    def tearDown(self):
        self.manager.close()
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root)

    def test_single_job_cancel_retry_keeps_checkpoints_and_source(self):
        job = self.manager.create(self.source_id)
        first = self.manager.active[1]
        with self.assertRaises(BusyError):
            self.manager.create(self.source_id)
        checkpoint = self.manager.job_dir(job["id"]) / "transcript.json"
        atomic_json(checkpoint, {"words": [{"start": 1, "end": 2, "text": "Привет"}]})
        cancelled = self.manager.cancel(job["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(first.terminated)
        self.assertTrue((checkpoint.parent / ".cancel").exists())
        retried = self.manager.retry(job["id"])
        self.assertEqual(retried["id"], job["id"])
        self.assertEqual(retried["status"], "running")
        self.assertFalse((checkpoint.parent / ".cancel").exists())
        self.assertEqual(read_json(checkpoint)["words"][0]["text"], "Привет")
        self.assertEqual(self.source.read_bytes(), b"unchanged source")

    def test_restart_marks_running_interrupted_and_releases_instance_lock(self):
        job = self.manager.create(self.source_id)
        with self.assertRaises(BusyError):
            JobManager(self.root, FakeWorker)
        self.manager.close()
        self.manager = JobManager(self.root, FakeWorker)
        self.assertEqual(self.manager.get(job["id"])["status"], "interrupted")
        self.assertEqual(self.manager.retry(job["id"])["status"], "running")

    def test_stale_on_disk_running_job_is_recovered(self):
        job = self.manager.create(self.source_id)
        self.manager.close()
        path = self.manager.job_dir(job["id"]) / "job.json"
        job["status"] = "running"
        atomic_json(path, job)
        self.manager = JobManager(self.root, FakeWorker)
        self.assertEqual(self.manager.get(job["id"])["status"], "interrupted")

    def test_source_registry_stable_and_not_client_paths(self):
        self.assertEqual(self.manager.list_sources()[0]["id"], self.source_id)
        with self.assertRaises(KeyError):
            self.manager.create(str(self.source))
        with self.assertRaises(KeyError):
            self.manager.get("../source")
        with self.assertRaises(KeyError):
            self.manager.create(str(uuid.uuid4()))

    def test_unhandled_child_exit_becomes_failure(self):
        job = self.manager.create(self.source_id)
        child = self.manager.active[1]
        child.done.set()
        for _ in range(100):
            if not self.manager.busy():
                break
            time.sleep(.01)
        self.assertEqual(self.manager.get(job["id"])["status"], "failed")
        self.assertTrue(child.closed)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object ownership")
    def test_real_windows_job_object_kills_only_owned_children(self):
        import ctypes
        from ctypes import wintypes
        gate = self.root / ".start"
        child_record = self.root / "child.pid"
        script = ("from pathlib import Path; import time, subprocess, sys; "
                  f"gate=Path({str(gate)!r}); "
                  "exec('while not gate.exists(): time.sleep(.01)'); "
                  "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                  f"Path({str(child_record)!r}).write_text(str(child.pid)); time.sleep(60)")
        original_popen = subprocess.Popen
        def spawn(_command, **kwargs):
            return original_popen([sys.executable, "-c", script], **kwargs)
        worker = None
        child_handle = None
        # A sibling process is intentionally outside the Job Object.
        sibling = original_popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            with patch("app.jobs.subprocess.Popen", side_effect=spawn):
                worker = WorkerProcess(self.root)
            for _ in range(300):
                if child_record.is_file():
                    break
                time.sleep(.01)
            self.assertTrue(child_record.is_file(), "Worker never opened its start gate")
            child_handle = kernel.OpenProcess(0x00100000, False, int(child_record.read_text()))
            self.assertTrue(child_handle)
            worker.terminate_tree()
            self.assertIsNotNone(worker.poll())
            self.assertEqual(kernel.WaitForSingleObject(child_handle, 5000), 0)
            self.assertIsNone(sibling.poll(), "Unrelated sibling process was terminated")
        finally:
            if worker:
                worker.terminate_tree()
                worker.close()
            if child_handle:
                kernel.CloseHandle(child_handle)
            sibling.terminate()
            sibling.wait()

    def test_list_sources_does_not_write_if_unchanged(self):
        # Initial list writes sources.json
        sources_file = self.manager.data / "sources.json"
        self.assertTrue(sources_file.exists())
        # Subsequent list without changes should NOT write to disk
        with patch("app.jobs.atomic_json") as mock_atomic:
            self.manager.list_sources()
            mock_atomic.assert_not_called()

    def test_list_sources_incorporates_manual_edits(self):
        sources_file = self.manager.data / "sources.json"
        custom_id = str(uuid.uuid4())
        manual_record = {custom_id: {"path": str(self.source), "name": "Ручное имя.mp4"}}
        atomic_json(sources_file, manual_record)

        sources = self.manager.list_sources()
        found = [s for s in sources if s["id"] == custom_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "Ручное имя.mp4")

    def test_prune_rejects_invalid_limits_without_touching_jobs(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        marker = directory / "output" / "part_001.mp4"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b"do not delete")
        for kwargs in (
            {"max_jobs": -1},
            {"max_age_days": -1},
            {"max_jobs": True},
            {"max_age_days": 1.5},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.manager.prune_jobs(**kwargs)
                self.assertTrue(directory.is_dir())
                self.assertEqual(marker.read_bytes(), b"do not delete")

    def test_delete_job_and_prune_jobs(self):
        job = self.manager.create(self.source_id)
        # Cannot delete active running job
        with self.assertRaises(BusyError):
            self.manager.delete_job(job["id"])

        # Cancel job so it becomes terminal
        self.manager.cancel(job["id"])
        job_dir = self.manager.job_dir(job["id"])
        self.assertTrue(job_dir.is_dir())

        # Now delete_job succeeds
        res = self.manager.delete_job(job["id"])
        self.assertTrue(res["deleted"])
        self.assertFalse(job_dir.is_dir())

        # Test prune_jobs with multiple terminal jobs
        job1 = self.manager.create(self.source_id)
        self.manager.cancel(job1["id"])
        job2 = self.manager.create(self.source_id)
        self.manager.cancel(job2["id"])

        prune_res = self.manager.prune_jobs(max_jobs=1)
        self.assertEqual(prune_res["pruned_count"], 1)
        self.assertEqual(prune_res["remaining_terminal"], 1)

    def test_finishing_owner_blocks_job_deletion_and_prune(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        marker = directory / "output" / "part_001.mp4"
        marker.parent.mkdir(exist_ok=True)
        marker.write_bytes(b"valuable export")
        self.manager.finishing_tasks[job["id"]] = 1
        with self.assertRaises(BusyError):
            self.manager.delete_job(job["id"])
        result = self.manager.prune_jobs(max_jobs=0, max_age_days=0)
        self.assertEqual(result["pruned_count"], 0)
        self.assertEqual(marker.read_bytes(), b"valuable export")
        self.manager.finishing_tasks.pop(job["id"])
        # A stopped job with an exported MP4 is valuable resumable work.
        # Finishing ownership may end, but bulk prune must still preserve it.
        self.assertEqual(self.manager.prune_jobs(max_jobs=0)["pruned_count"], 0)
        self.assertEqual(marker.read_bytes(), b"valuable export")
        self.assertTrue(directory.is_dir())

    def test_job_deletion_and_prune_remove_only_matching_export_pointers(self):
        first = self.manager.create(self.source_id)
        self.manager.cancel(first["id"])
        second = self.manager.create(self.source_id)
        self.manager.cancel(second["id"])
        indices = self.root / "finishing" / "exports-index"
        a = indices / ("ex_" + "a" * 32 + ".json")
        b = indices / ("ex_" + "b" * 32 + ".json")
        atomic_json(a, {"source_job_id": first["id"]})
        atomic_json(b, {"source_job_id": second["id"]})
        self.manager.delete_job(first["id"])
        self.assertFalse(a.exists(), "deleted job's export pointer remains")
        self.assertTrue(b.exists(), "unrelated export pointer was removed")
        self.assertEqual(self.manager.prune_jobs(max_jobs=0)["pruned_count"], 1)
        self.assertFalse(b.exists(), "pruned job's export pointer remains")

    def test_delete_job_does_not_claim_success_when_removal_fails(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        with patch("app.jobs.shutil.rmtree", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.manager.delete_job(job["id"])
        self.assertTrue(directory.is_dir())

    def test_bulk_prune_keeps_cancelled_job_with_paid_or_local_checkpoints(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        partial = directory / "story_refinement" / "validated.json"
        partial.parent.mkdir(parents=True)
        partial.write_text('{"stage":"complete"}', encoding="utf-8")
        found = self.manager.prune_jobs(max_jobs=0, max_age_days=0)
        self.assertEqual(found["pruned_count"], 0)
        self.assertEqual(partial.read_text(encoding="utf-8"), '{"stage":"complete"}')
        self.assertEqual(self.manager.retry(job["id"])["status"], "running")
        self.manager.cancel(job["id"])

    def test_bulk_prune_does_not_erase_rendered_parts_of_interrupted_job(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        video = directory / "output" / "part_001.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"important existing rendered short")
        result = self.manager.prune_jobs(max_jobs=0, max_age_days=0)
        self.assertEqual(result["pruned_count"], 0)
        self.assertEqual(video.read_bytes(), b"important existing rendered short")
        self.manager.delete_job(job["id"])
        self.assertFalse(directory.exists())

    def test_prune_reports_only_successful_removals(self):
        job = self.manager.create(self.source_id)
        self.manager.cancel(job["id"])
        with patch("app.jobs.shutil.rmtree", side_effect=PermissionError("locked")):
            with self.assertLogs("app.jobs", level="ERROR"):
                result = self.manager.prune_jobs(max_jobs=0)
        self.assertEqual(result["pruned_count"], 0)
        self.assertEqual(result["pruned_ids"], [])
        self.assertEqual(result["remaining_terminal"], 1)
        self.assertTrue(self.manager.job_dir(job["id"]).is_dir())

    def test_setup_environment_idempotent(self):
        config.setup_environment()
        path1 = os.environ.get("PATH", "")
        config.setup_environment()
        path2 = os.environ.get("PATH", "")
        self.assertEqual(path1, path2)


if __name__ == "__main__":
    unittest.main()
