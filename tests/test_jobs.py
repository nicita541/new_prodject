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
from types import ModuleType
from unittest.mock import Mock, patch

from app import config
from app.jobs import BusyError, JobManager, WorkerProcess, atomic_json, read_json


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
    def test_default_analysis_remains_local_without_reading_deepseek_settings(self):
        client = deepseek_stub()
        with patch.dict(sys.modules, {"app.deepseek": client}):
            job = self.manager.create(self.source_id)
        self.assertEqual(job["analysis_provider"], "local")
        self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "analysis-settings.json"), {"provider": "local"})
        client.public_status.assert_not_called()
        client.check_connection.assert_not_called()

    def test_explicit_deepseek_selection_persists_and_retry_rechecks_balance(self):
        client = deepseek_stub()
        with patch.dict(sys.modules, {"app.deepseek": client}):
            job = self.manager.create(self.source_id, "deepseek")
            self.assertEqual(job["analysis_provider"], "deepseek")
            self.assertEqual(read_json(self.manager.job_dir(job["id"]) / "analysis-settings.json"), {"provider": "deepseek"})
            self.manager.cancel(job["id"])
            client.public_status.return_value["remaining_usd"] = "0"
            with self.assertRaisesRegex(ValueError, "Баланс не подтверждён"):
                self.manager.retry(job["id"])
            self.assertFalse(self.manager.busy())
            self.assertEqual(self.manager.get(job["id"])["status"], "cancelled")
            client.public_status.return_value["remaining_usd"] = "0.004"
            self.assertEqual(self.manager.retry(job["id"])["analysis_provider"], "deepseek")
            client.begin_attempt.assert_called_once_with(self.manager.job_dir(job['id']))
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
                    self.assertEqual(read_json(directory / "analysis-settings.json"), {"provider": "hybrid"})
                    self.manager.cancel(job["id"])
                    # Recovery must retain the chosen provider across a server restart.
                    self.manager.close()
                    self.manager = JobManager(self.root, FakeWorker)
                    retried = self.manager.retry(job["id"])
                    self.assertEqual(retried["analysis_provider"], "hybrid")
                    self.assertEqual(retried["status"], "running")
                    self.assertEqual(read_json(directory / "analysis-settings.json"), {"provider": "hybrid"})
                    self.manager.cancel(job["id"])
                client.public_status.assert_not_called()
                client.check_connection.assert_not_called()

    def test_deepseek_plan_persists_and_rechecks_verified_balance_on_retry(self):
        client = deepseek_stub()
        with patch.dict(sys.modules, {"app.deepseek": client}):
            job = self.manager.create(self.source_id, "deepseek_plan")
            self.assertEqual(job["analysis_provider"], "deepseek_plan")
            directory = self.manager.job_dir(job["id"])
            self.assertEqual(read_json(directory / "analysis-settings.json"), {"provider": "deepseek_plan"})
            self.manager.cancel(job["id"])
            client.public_status.return_value["remaining_usd"] = "0"
            with self.assertRaisesRegex(ValueError, "Баланс не подтверждён"):
                self.manager.retry(job["id"])
            self.assertFalse(self.manager.busy())
            client.public_status.return_value["remaining_usd"] = "0.04"
            self.assertEqual(self.manager.retry(job["id"])["analysis_provider"], "deepseek_plan")
        client.check_connection.assert_not_called()

    def test_deepseek_plan_without_configured_positive_balance_creates_nothing(self):
        for status in ({"configured": False, "remaining_usd": "0.04"},
                       {"configured": True, "remaining_usd": "0"},
                       {"configured": True, "remaining_usd": "NaN"}):
            with self.subTest(status=status), patch.dict(sys.modules, {"app.deepseek": deepseek_stub(status)}):
                with self.assertRaises(ValueError):
                    self.manager.create(self.source_id, "deepseek_plan")
                self.assertEqual(list(self.manager.jobs.iterdir()), [])

    def test_unconfigured_or_exhausted_deepseek_has_no_job_side_effects(self):
        for status in ({"configured": False, "remaining_usd": "0.01"},
                       {"configured": True, "remaining_usd": "0"},
                       {"configured": True, "remaining_usd": "-0.001"},
                       {"configured": True, "remaining_usd": "NaN"}):
            with self.subTest(status=status), patch.dict(sys.modules, {"app.deepseek": deepseek_stub(status)}):
                with self.assertRaises(ValueError):
                    self.manager.create(self.source_id, "deepseek")
        with self.assertRaises(ValueError):
            self.manager.create(self.source_id, "unexpected")
        self.assertEqual(list(self.manager.jobs.iterdir()), [])
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
        self.source = self.root / ("Серия с длинным русским именем и пробелами " * 4 + ".mp4")
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


if __name__ == "__main__":
    unittest.main()
