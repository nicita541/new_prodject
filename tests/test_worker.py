"""Owned worker liveness without inference, external requests or real media."""
import os
import shutil
import time
import unittest
import uuid
from unittest.mock import patch

from app import config
from app.json_store import atomic_json, read_json
from app.worker import WorkerHeartbeat


class WorkerHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.directory = config.TEMP / ('worker-heartbeat-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)

    def tearDown(self):
        self.directory.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_heartbeat_runs_independently_and_stops_without_changing_job_progress(self):
        attempt = uuid.uuid4().hex
        job_path = self.directory / 'job.json'
        atomic_json(job_path, {'attempt_id': attempt, 'progress': .25,
                              'updated_at': 'unchanged', 'progress_updated_at': 'unchanged'})
        original = job_path.read_bytes()
        heartbeat = WorkerHeartbeat(self.directory, attempt, interval=.01)
        try:
            heartbeat.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                record = read_json(self.directory / 'worker-heartbeat.json')
                if record['sequence'] >= 3:
                    break
                time.sleep(.01)
            self.assertGreaterEqual(record['sequence'], 3)
            self.assertEqual(record['attempt_id'], attempt)
            self.assertEqual(record['pid'], os.getpid())
            self.assertEqual(job_path.read_bytes(), original)
        finally:
            heartbeat.close()
        self.assertFalse(heartbeat.thread.is_alive())
        published = (self.directory / 'worker-heartbeat.json').read_bytes()
        time.sleep(.03)
        self.assertEqual((self.directory / 'worker-heartbeat.json').read_bytes(), published)

    def test_heartbeat_storage_failure_is_diagnostic_and_next_write_recovers(self):
        heartbeat = WorkerHeartbeat(self.directory, uuid.uuid4().hex)
        with patch('app.worker.atomic_json', side_effect=OSError('disk full')), \
                self.assertLogs('app.worker', level='WARNING') as logs:
            heartbeat._publish()
            heartbeat._publish()
        self.assertEqual(len(logs.records), 1)
        self.assertTrue(heartbeat.failed)
        heartbeat._publish()
        self.assertFalse(heartbeat.failed)
        self.assertEqual(read_json(self.directory / 'worker-heartbeat.json')['sequence'], 3)

    def test_legacy_worker_without_attempt_does_not_publish_unowned_heartbeat(self):
        for attempt in (None, 'invalid', str(uuid.uuid4())):
            heartbeat = WorkerHeartbeat(self.directory, attempt)
            heartbeat.start()
            self.assertIsNone(heartbeat.thread)
            self.assertFalse((self.directory / 'worker-heartbeat.json').exists())

    def test_worker_main_maintains_heartbeat_during_blocking_pipeline_and_stops_it(self):
        from app.worker import main
        identifier, attempt = str(uuid.uuid4()), uuid.uuid4().hex
        directory = self.directory / identifier
        directory.mkdir()
        (directory / '.start').touch()
        atomic_json(directory / 'job.json', {'id': identifier, 'status': 'running',
                    'attempt_id': attempt, 'analysis_provider': 'local'})
        heartbeats = []

        def pipeline(job_dir, report, cancelled):
            report('analyze', .25, 'Blocking fake inference')
            job_path = job_dir / 'job.json'
            before = job_path.read_bytes()
            self.assertTrue(read_json(job_path)['progress_updated_at'])
            first = read_json(job_dir / 'worker-heartbeat.json')['sequence']
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                current = read_json(job_dir / 'worker-heartbeat.json')
                if current['sequence'] > first:
                    break
                time.sleep(.01)
            self.assertGreater(current['sequence'], first)
            self.assertEqual(job_path.read_bytes(), before)
            self.assertFalse(cancelled())
            return []

        def heartbeat_factory(*args):
            result = WorkerHeartbeat(*args, interval=.01)
            heartbeats.append(result)
            return result

        with patch('sys.argv', ['worker', '--job', identifier]), \
                patch.object(config, 'JOBS', self.directory), \
                patch('app.run_logging.configure_logging'), \
                patch('app.antigravity_runner.ManagedRunner'), \
                patch('app.pipeline.run_job', side_effect=pipeline), \
                patch('app.worker.WorkerHeartbeat', side_effect=heartbeat_factory):
            self.assertEqual(main(), 0)
        self.assertEqual(read_json(directory / 'job.json')['status'], 'completed')
        self.assertFalse(heartbeats[0].thread.is_alive())
