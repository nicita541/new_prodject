"""Durable scheduler fault tests. Authored source bytes are never decoded."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

from app.config import TEMP, ROOT
from app.file_lock import BusyError, InstanceLock
from app.finishing_commands import CommandError, FinishingCommands, StaleAttempt
from app.finishing_execution import FinishingExecution, HEARTBEAT_STALE_SECONDS
from app.json_store import atomic_json, read_json


CHILD = r'''
import builtins, sys, time, types, subprocess
from pathlib import Path
directory = Path(sys.argv[-1])
mode = sys.argv[1]
module = types.ModuleType('app.finishing_render')
def render(root, operation, attempt, report, cancelled):
    (directory/'render-entered').write_text('entered', encoding='utf-8')
    report('render', .2, 'Authored test renderer; no media decoded')
    if mode == 'error':
        raise RuntimeError('secret-test-value-must-not-enter-public-status')
    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(120)'])
    (directory/'descendant.pid').write_text(str(child.pid), encoding='ascii')
    while not cancelled():
        time.sleep(.05)
    raise InterruptedError('authored cancellation')
module.render_command = render
sys.modules['app.finishing_render'] = module
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ('app.finishing_render', 'finishing_render'):
        if not (directory/'.start').is_file():
            raise AssertionError('renderer import before owned start gate')
        (directory/'render-imported').write_text('imported', encoding='ascii')
    if name in ('app.jobs', 'app.vision', 'app.deepseek', 'app.pipeline'):
        raise AssertionError('finishing worker imported forbidden module '+name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from app.finishing_worker import main
raise SystemExit(main(sys.argv[2:]))
'''


class FakeWorker:
    def __init__(self, directory, *, command):
        self.directory, self.command = directory, command
        self.code, self.terminated, self.closed = None, False, False
        self.process = SimpleNamespace(pid=8173)

    def poll(self):
        return self.code

    def wait(self):
        assert self.code is not None
        return self.code

    def terminate_tree(self):
        self.terminated = True
        self.code = 1

    def close(self):
        self.closed = True


class FinishingExecutionTests(unittest.TestCase):
    def setUp(self):
        self.root = TEMP/('finishing-execution-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.job = str(uuid.uuid4())
        source = self.root/'data/imports/source.mp4'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'authored source fixture, not media')
        self.sha = hashlib.sha256(source.read_bytes()).hexdigest()
        self.payload = {
            'source': {'path': 'data/imports/source.mp4', 'sha256': self.sha},
            'plan': {'parts': [{'index': 1, 'duration': 3.,
                               'cuts': [{'start': 1., 'end': 4.}], 'subtitles': []}]},
            'source_plan_digest': '1'*64, 'publication_revision': '2'*64,
            'audio_stream': 0, 'probe': {'width': 640, 'height': 360, 'audio_stream': 0},
            'profile': {}, 'preview': None,
            'caption_revisions': {'1': {'target_id': '3'*64, 'revision': 0}},
            'assets': [], 'resolved_music': {'1': None},
            'render_contract': {'version': 1, 'code_sha256': '4'*64}}
        self.manager = SimpleNamespace(root=self.root, mutex=threading.RLock(), active=None,
                                       shutdown_requested=False, closed=False)
        self.store = FinishingCommands(self.root)
        self.workers = []
        self.validate = Mock()
        self.runtimes = []
        self.instant = 1.
        self.execution = self.runtime()

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.stop()
        self.root.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.root)

    def factory(self, directory, *, command):
        worker = FakeWorker(directory, command=command)
        self.workers.append(worker)
        return worker

    def runtime(self, **kwargs):
        runtime = FinishingExecution(self.manager, worker_factory=self.factory,
            validate=self.validate, autostart=False, clock=lambda: self.instant, **kwargs)
        self.runtimes.append(runtime)
        return runtime

    def command(self, *, job=None):
        return self.store.submit(job or self.job, self.sha, 'export', {'part_indices': [1]},
            lambda: copy.deepcopy(self.payload), operation_id=str(uuid.uuid4()))

    def attempt_dir(self, command, attempt=None):
        if attempt is None:
            attempt = self.store._runtime(command)[1]['attempt_id']
        return self.store.task_directory(command['job_id'], command['kind'], command['task_id'])/'attempts'/attempt

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_one_active_two_waiting_and_exact_replay_before_full_or_stopping(self):
        commands = [self.command() for _ in range(4)]
        states = [self.execution.submit(command) for command in commands[:3]]
        self.execution.tick()
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(self.execution.status(commands[0])['status'], 'running')
        with self.assertRaises(BusyError):
            self.execution.submit(commands[3])
        self.manager.shutdown_requested = True
        replay = self.execution.submit(commands[1])
        self.assertEqual(replay['attempt_id'], states[1]['attempt_id'])
        self.validate.assert_called_once()

    def test_frozen_command_exactness_and_asset_changes_fail_before_launch(self):
        command = self.command()
        changed = copy.deepcopy(command)
        changed['frozen']['profile']['today'] = True
        with self.assertRaises(CommandError):
            self.execution.submit(changed)
        self.execution.submit(command)
        (self.root/'data/imports/source.mp4').write_bytes(b'changed')
        self.execution.tick()
        self.assertEqual(self.execution.status(command)['status'], 'failed')
        self.assertFalse(self.workers)

    def test_validation_failure_isolated_and_next_task_starts(self):
        first, second = self.command(), self.command()
        self.execution.submit(first)
        self.execution.submit(second)
        self.validate.side_effect = [CommandError('incompatible frozen renderer'), None]
        self.execution.tick()
        self.assertEqual(self.execution.status(first)['status'], 'failed')
        self.assertEqual(self.execution.status(second)['status'], 'running')
        self.assertEqual(len(self.workers), 1)

    def test_worker_creation_failure_fences_attempt_without_blocking_following_task(self):
        first, second = self.command(), self.command()
        for command in (first, second):
            self.execution.submit(command)
        self.execution.worker_factory = Mock(side_effect=[OSError('cannot start'), self.factory(
            self.attempt_dir(second), command=['authored'])])
        self.execution.tick()
        self.assertEqual(self.execution.status(first)['status'], 'failed')
        self.assertEqual(self.execution.status(second)['status'], 'running')

    def test_clean_exit_without_completion_receipts_is_interrupted_and_nonzero_failed(self):
        for code, status in ((0, 'interrupted'), (1, 'failed')):
            with self.subTest(code=code):
                command = self.command()
                self.execution.submit(command)
                self.execution.tick()
                worker = self.execution.active['worker']
                worker.code = code
                self.execution.tick()
                self.assertEqual(self.execution.status(command)['status'], status)
                self.assertTrue(worker.closed)
                self.assertIsNone(self.execution.active)

    def test_actual_process_exit_observed_even_with_fresh_heartbeat(self):
        command = self.command()
        state = self.execution.submit(command)
        self.execution.tick()
        atomic_json(self.attempt_dir(command)/'worker-heartbeat.json', {
            'version': 1, 'attempt_id': state['attempt_id'], 'pid': 8173,
            'sequence': 1, 'heartbeat_at': 'authored current heartbeat'})
        self.workers[-1].code = 7
        self.execution.tick()
        self.assertEqual(self.execution.status(command)['status'], 'failed')

    def test_exited_child_retains_owner_across_terminal_lock_timeout_then_reconciles(self):
        first, second = self.command(), self.command()
        for command in (first, second):
            self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        worker.code = 1
        with patch.object(self.execution.store, 'update_attempt', side_effect=BusyError('authored lock timeout')):
            self.execution.tick()
            self.execution.tick()
            self.assertIs(self.execution.active['worker'], worker)
            self.assertTrue(self.execution.active['drained'])
            self.assertTrue(worker.closed)
            self.assertEqual(self.store._runtime(first)[1]['status'], 'running')
            self.assertEqual(len(self.workers), 1)
            self.assertTrue(self.execution.owns_job(self.job))
        self.execution.tick()
        self.assertEqual(self.execution.status(first)['status'], 'failed')
        self.assertEqual(self.execution.active['command'], second)
        self.assertEqual(len(self.workers), 2)

    def test_cancel_marks_and_stops_tree_before_waiting_for_locked_terminal_write(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        marker = self.attempt_dir(command)/'.cancel'
        def blocked(*args, **kwargs):
            self.assertTrue(marker.is_file())
            self.assertTrue(worker.terminated and worker.closed)
            raise BusyError('authored lock timeout')
        with patch.object(self.execution.store, 'update_attempt', side_effect=blocked):
            result = self.execution.cancel(command['operation_id'])
            self.assertEqual(result['status'], 'running')
            self.assertEqual(result['phase'], 'cancelling')
            self.assertIs(self.execution.active['worker'], worker)
            self.execution.tick()
            self.assertIsNotNone(self.execution.active)
        self.execution.tick()
        self.assertEqual(self.execution.status(command)['status'], 'cancelled')
        self.assertIsNone(self.execution.active)
        self.assertFalse(self.execution.busy())

    def test_queued_cancel_marker_prevents_launch_after_write_timeout(self):
        command = self.command()
        self.execution.submit(command)
        with patch.object(self.execution.store, 'update_attempt', side_effect=BusyError('authored lock timeout')):
            self.execution.cancel(command['operation_id'])
            self.execution.tick()
            self.assertEqual(self.execution.status(command)['status'], 'queued')
            self.assertFalse(self.workers)
            self.assertTrue(self.execution.owns_job(self.job))
        self.execution.tick()
        self.assertEqual(self.execution.status(command)['status'], 'cancelled')
        self.assertFalse(self.workers)

    def test_stop_timeout_retains_drained_owner_and_later_stop_retries_terminal_write(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        with patch.object(self.execution.store, 'update_attempt', side_effect=BusyError('authored lock timeout')):
            self.assertFalse(self.execution.stop(timeout=.1))
            self.assertTrue(worker.terminated and worker.closed)
            self.assertIsNotNone(self.execution.active)
            self.assertTrue(self.execution.owns_job(self.job))
            self.assertEqual(self.store._runtime(command)[1]['status'], 'running')
        self.assertTrue(self.execution.stop(timeout=.1))
        self.assertEqual(self.execution.status(command)['status'], 'interrupted')
        self.assertIsNone(self.execution.active)

    def test_failed_explicit_kill_retains_owner_and_next_tick_retries_owned_tree_stop(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        terminate = worker.terminate_tree
        attempts = []
        def flaky():
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError('authored temporary terminate failure')
            terminate()
        worker.terminate_tree = flaky
        status = self.execution.cancel(command['operation_id'])
        self.assertEqual(status['status'], 'running')
        self.assertIs(self.execution.active['worker'], worker)
        self.execution.tick()
        self.assertEqual(len(attempts), 2)
        self.assertTrue(worker.terminated)
        self.assertEqual(self.execution.status(command)['status'], 'cancelled')
        self.assertIsNone(self.execution.active)

    def test_disk_failure_protects_known_job_but_does_not_deadlock_unrelated_queue(self):
        first = self.command()
        second = self.command(job=str(uuid.uuid4()))
        for command in (first, second):
            self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        worker.code = 1
        original = self.execution.store.update_attempt
        def broken(command, *args, **kwargs):
            if command['operation_id'] == first['operation_id']:
                raise OSError('authored disk failure')
            return original(command, *args, **kwargs)
        with patch.object(self.execution.store, 'update_attempt', side_effect=broken):
            self.execution.tick()
        self.assertTrue(worker.closed)
        self.assertIn(first['operation_id'], self.execution.damaged)
        self.assertTrue(self.execution.owns_job(first['job_id']))
        self.assertEqual(self.execution.active['command'], second)
        with self.assertRaises(BusyError):
            self.execution.forget_job(first['job_id'])

    def test_real_operation_lock_released_in_background_allows_cancel_to_persist(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        lock = InstanceLock(self.root/'finishing/operations/.locks'/(command['operation_id']+'.lock'))
        released = threading.Event()
        def release():
            time.sleep(.12)
            lock.close()
            released.set()
        thread = threading.Thread(target=release)
        thread.start()
        try:
            result = self.execution.cancel(command['operation_id'])
            self.assertTrue(released.is_set())
            self.assertEqual(result['status'], 'cancelled')
            self.assertTrue(worker.terminated and worker.closed)
            self.assertIsNone(self.execution.active)
        finally:
            thread.join(timeout=2)
            lock.close()

    def test_real_operation_lock_timeout_keeps_owner_until_next_observation(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        self.workers[-1].code = 1
        self.execution.store.lock_timeout = .03
        lock = InstanceLock(self.root/'finishing/operations/.locks'/(command['operation_id']+'.lock'))
        try:
            self.execution.tick()
            self.assertIsNotNone(self.execution.active)
            self.assertTrue(self.execution.active['drained'])
            self.assertEqual(self.store._runtime(command)[1]['status'], 'running')
        finally:
            lock.close()
        self.execution.tick()
        self.assertEqual(self.execution.status(command)['status'], 'failed')
        self.assertFalse(self.execution.busy())

    def test_heartbeat_requires_owned_pid_attempt_and_increasing_sequence(self):
        command = self.command()
        state = self.execution.submit(command)
        self.execution.tick()
        path = self.attempt_dir(command)/'worker-heartbeat.json'
        base = {'version': 1, 'attempt_id': state['attempt_id'], 'pid': 8173,
                'sequence': 1, 'heartbeat_at': 'authored'}
        for changes in ({'pid': 19}, {'attempt_id': uuid.uuid4().hex}, {'sequence': True}):
            atomic_json(path, {**base, **changes})
            self.assertEqual(self.execution.status(command)['worker_health']['status'], 'starting')
        atomic_json(path, base)
        self.assertEqual(self.execution.status(command)['worker_health']['status'], 'healthy')
        self.instant += HEARTBEAT_STALE_SECONDS+1
        self.assertEqual(self.execution.status(command)['worker_health']['status'], 'stale')
        self.assertFalse(self.workers[-1].terminated)
        atomic_json(path, {**base, 'sequence': 2})
        self.assertEqual(self.execution.status(command)['worker_health']['status'], 'healthy')

    def test_status_reads_never_repair_schedule_or_rewrite_and_reject_stale_details(self):
        command = self.command()
        state = self.execution.submit(command)
        path = self.attempt_dir(command)/'progress.json'
        atomic_json(path, {'attempt_id': uuid.uuid4().hex, 'command_hash': command['command_hash'],
                           'phase': 'wrong owner'})
        before = self.snapshot()
        for _ in range(3):
            self.assertNotIn('phase', self.execution.status(command))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.workers)
        self.validate.assert_not_called()
        atomic_json(path, {'attempt_id': state['attempt_id'], 'command_hash': command['command_hash'],
                           'phase': 'render', 'message': {'not': 'a string'}, 'error': None})
        self.assertEqual(self.execution.status(command)['phase'], 'render')
        self.assertNotIn('message', self.execution.status(command))

    def test_cancel_queued_never_starts_and_cancel_running_kills_owned_worker(self):
        first, second = self.command(), self.command()
        for command in (first, second):
            self.execution.submit(command)
        self.execution.cancel(second['operation_id'])
        self.execution.tick()
        worker = self.workers[-1]
        self.execution.cancel(first['operation_id'])
        self.assertTrue(worker.terminated and worker.closed)
        self.execution.tick()
        self.assertEqual(len(self.workers), 1)
        self.assertFalse(self.execution.busy())
        self.assertEqual(self.execution.status(second)['status'], 'cancelled')

    def test_explicit_cancel_still_stops_owned_tree_if_runtime_record_is_corrupt(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        directory = self.store.task_directory(command['job_id'], command['kind'], command['task_id'])
        (directory/'runtime.json').write_bytes(b'{damaged')
        with self.assertRaises(CommandError):
            self.execution.cancel(command['operation_id'])
        self.assertTrue(worker.terminated and worker.closed)
        self.assertIsNone(self.execution.active)

    def test_stop_still_joins_and_kills_when_attempt_record_was_corrupted(self):
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        worker = self.workers[-1]
        directory = self.store.task_directory(command['job_id'], command['kind'], command['task_id'])
        (directory/'runtime.json').write_bytes(b'{damaged')
        self.assertTrue(self.execution.stop())
        self.assertTrue(worker.terminated and worker.closed)
        self.assertEqual((directory/'runtime.json').read_bytes(), b'{damaged')
        self.assertIsNone(self.execution.active)

    def test_resume_is_explicit_and_previous_attempt_cannot_publish_after_restart(self):
        command = self.command()
        first = self.execution.submit(command)
        self.execution.tick()
        self.execution.stop()
        restarted = self.runtime()
        self.assertEqual(restarted.status(command)['status'], 'interrupted')
        restarted.tick()
        self.assertEqual(len(self.workers), 1)
        second = restarted.resume(command['operation_id'])
        self.assertNotEqual(first['attempt_id'], second['attempt_id'])
        self.assertEqual(second['status'], 'queued')
        with self.assertRaises(StaleAttempt):
            self.store.update_attempt(command, first['attempt_id'], status='running')
        restarted.tick()
        self.assertEqual(len(self.workers), 2)

    def test_resume_drains_lingering_terminal_worker_and_counts_replaced_slot_once(self):
        commands = [self.command() for _ in range(3)]
        for command in commands:
            self.execution.submit(command)
        self.execution.tick()
        first, worker = commands[0], self.workers[-1]
        attempt = self.execution.status(first)['attempt_id']
        self.store.update_attempt(first, attempt, status='failed')
        self.assertTrue(self.execution.owns_job(self.job))
        self.assertTrue(self.execution.busy())
        resumed = self.execution.resume(first['operation_id'])
        self.assertEqual(resumed['status'], 'queued')
        self.assertTrue(worker.terminated and worker.closed)
        self.assertIsNone(self.execution.active)

    def test_live_terminal_worker_still_occupies_capacity(self):
        commands = [self.command() for _ in range(4)]
        for command in commands[:3]:
            self.execution.submit(command)
        self.execution.tick()
        state = self.execution.status(commands[0])
        self.store.update_attempt(commands[0], state['attempt_id'], status='failed')
        with self.assertRaises(BusyError):
            self.execution.submit(commands[3])

    def test_resume_validates_frozen_assets_and_does_not_requeue_running_or_completed(self):
        command = self.command()
        self.execution.submit(command)
        with self.assertRaises(CommandError):
            self.execution.resume(command['operation_id'])
        self.execution.cancel(command['operation_id'])
        before = self.store._runtime(command)[1]
        (self.root/'data/imports/source.mp4').unlink()
        with self.assertRaises(CommandError):
            self.execution.resume(command['operation_id'])
        self.assertEqual(self.store._runtime(command)[1], before)

    def test_recovery_queues_reserved_exact_bytes_and_marks_lost_running_interrupted(self):
        reserved, lost, queued = [self.command() for _ in range(3)]
        receipt_path = self.root/'finishing/operations'/(reserved['operation_id']+'.json')
        receipt = read_json(receipt_path)
        atomic_json(receipt_path, {**receipt, 'state': 'reserved'})
        reserved_dir = self.store.task_directory(reserved['job_id'], reserved['kind'], reserved['task_id'])
        (reserved_dir/'command.json').unlink()
        state = self.store.begin_attempt(lost)
        self.store.update_attempt(lost, state['attempt_id'], status='running', progress=.34)
        queued_state = self.store.begin_attempt(queued)
        restarted = self.runtime()
        self.assertEqual(self.store.load(reserved['operation_id']), reserved)
        self.assertEqual(restarted.status(lost)['status'], 'interrupted')
        self.assertEqual(restarted.status(queued)['attempt_id'], queued_state['attempt_id'])
        restarted.tick()
        expected = sorted((reserved, queued), key=lambda command: (command['created_at'], command['operation_id']))[0]
        self.assertEqual(restarted.active['command'], expected)

    def test_recovery_retains_cancel_intention_and_protects_known_corrupt_owner(self):
        cancelled, corrupt = self.command(), self.command()
        state = self.store.begin_attempt(cancelled)
        self.store.update_attempt(cancelled, state['attempt_id'], status='running')
        (self.attempt_dir(cancelled)/'.cancel').touch()
        self.store.begin_attempt(corrupt)
        directory = self.store.task_directory(corrupt['job_id'], corrupt['kind'], corrupt['task_id'])
        (directory/'runtime.json').write_bytes(b'{original damaged bytes')
        restarted = self.runtime()
        self.assertEqual(restarted.status(cancelled)['status'], 'cancelled')
        self.assertIn(corrupt['operation_id'], restarted.damaged)
        self.assertTrue(restarted.owns_job(corrupt['job_id']))
        restarted.tick()
        self.assertFalse(self.workers)
        self.assertFalse(restarted.busy())
        self.assertEqual((directory/'runtime.json').read_bytes(), b'{original damaged bytes')

    def test_recovery_isolates_damaged_operation_without_rewriting_and_skips_tombstone(self):
        command, deleted = self.command(), self.command()
        self.store.tombstone(deleted['operation_id'], job_id=self.job)
        damaged = self.root/'finishing/operations'/(str(uuid.uuid4())+'.json')
        damaged.write_bytes(b'{broken operation')
        restarted = self.runtime()
        self.assertEqual(damaged.read_bytes(), b'{broken operation')
        self.assertIn(damaged.stem, restarted.damaged)
        restarted.tick()
        self.assertEqual(restarted.active['command'], command)
        self.assertNotIn(deleted['operation_id'], restarted.commands)

    def test_job_ownership_protects_waiting_and_damaged_known_attempts(self):
        first = self.command()
        second = self.command(job=str(uuid.uuid4()))
        for command in (first, second):
            self.execution.submit(command)
        self.assertTrue(self.execution.owns_job(second['job_id']))
        directory = self.store.task_directory(second['job_id'], second['kind'], second['task_id'])
        (directory/'runtime.json').write_bytes(b'null')
        self.execution._pending()
        self.assertTrue(self.execution.owns_job(second['job_id']))
        self.assertFalse(self.execution.owns_job(str(uuid.uuid4())))

    def test_analysis_owns_worker_slot_and_stop_preserves_waiting_tasks(self):
        command = self.command()
        state = self.execution.submit(command)
        self.manager.active = {'authored': 'analysis worker'}
        self.execution.tick()
        self.assertFalse(self.workers)
        self.manager.active = None
        self.execution.tick()
        self.manager.closed = True
        self.assertTrue(self.execution.stop(timeout=.1))
        self.assertTrue(self.workers[-1].terminated)
        self.assertEqual(self.execution.status(command)['status'], 'interrupted')
        with self.assertRaises(BusyError):
            self.execution.submit(self.command())
        self.assertEqual(self.execution.submit(command)['attempt_id'], state['attempt_id'])

    def test_forget_only_terminal_job_index_without_deleting_command_or_receipt(self):
        command = self.command()
        self.execution.submit(command)
        with self.assertRaises(BusyError):
            self.execution.forget_job(self.job)
        self.execution.cancel(command['operation_id'])
        self.store.tombstone(command['operation_id'], job_id=self.job)
        before = self.snapshot()
        self.execution.forget_job(self.job)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn(command['operation_id'], self.execution.commands)

    def wait_until(self, callback, *, seconds=8):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if callback():
                return
            time.sleep(.03)
        self.fail('Owned test child did not reach expected state before deadline')

    @staticmethod
    def alive(pid):
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if not handle:
                return False
            try:
                return kernel.WaitForSingleObject(handle, 0) == 258
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            status = Path('/proc')/str(pid)/'stat'
            return not status.exists() or status.read_text().split()[2] != 'Z'
        except ProcessLookupError:
            return False

    def test_real_child_waits_for_gate_and_sanitizes_private_render_error(self):
        command = self.command()
        state = self.execution.submit(command)
        self.store.update_attempt(command, state['attempt_id'], status='running')
        directory = self.attempt_dir(command)
        args = [sys.executable, '-B', '-c', CHILD, 'error', '--root', str(self.root),
                '--operation', command['operation_id'], '--attempt', state['attempt_id'],
                '--directory', str(directory)]
        with (directory/'gate-test.log').open('wb') as output:
            process = subprocess.Popen(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
            try:
                time.sleep(.3)
                self.assertIsNone(process.poll())
                self.assertFalse((directory/'render-imported').exists())
                self.assertFalse((directory/'render-entered').exists())
                (directory/'.start').touch()
                self.assertEqual(process.wait(timeout=10), 1)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        self.assertTrue((directory/'render-imported').exists())
        self.assertTrue((directory/'render-entered').exists())
        status = self.execution.status(command)
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(status['error'], 'Не удалось создать видео. Подробности в локальном журнале экспорта.')
        self.assertNotIn('secret-test-value', str(status))
        self.assertIn('secret-test-value', (directory/'gate-test.log').read_text(encoding='utf-8'))

    def test_real_owned_worker_cancel_kills_its_descendant_and_releases_slot(self):
        from app.jobs import WorkerProcess
        real_workers = []
        def factory(directory, *, command):
            args = [sys.executable, '-B', '-c', CHILD, 'descendant', *command[4:]]
            worker = WorkerProcess(directory, command=args)
            real_workers.append(worker)
            return worker
        self.execution.worker_factory = factory
        command = self.command()
        self.execution.submit(command)
        self.execution.tick()
        directory = self.attempt_dir(command)
        self.wait_until(lambda: (directory/'descendant.pid').is_file())
        descendant = int((directory/'descendant.pid').read_text(encoding='ascii'))
        worker = real_workers[0]
        self.assertTrue(self.alive(descendant))
        self.assertIsNone(worker.poll())
        self.wait_until(lambda: self.execution.status(command)['worker_health']['status'] == 'healthy')
        result = self.execution.cancel(command['operation_id'])
        self.assertEqual(result['status'], 'cancelled')
        self.wait_until(lambda: not self.alive(descendant))
        self.assertIsNotNone(worker.poll())
        self.assertFalse(self.execution.busy())


if __name__ == '__main__':
    unittest.main()
