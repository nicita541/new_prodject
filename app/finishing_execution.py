"""Manager-owned durable finishing queue and its owned child processes.

Commands and attempt state are authoritative; the in-memory queue is only an
index. Restart never infers missing parameters or resumes an interrupted render.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from app.file_lock import BusyError
from app.finishing_commands import CommandError, FinishingCommands, StaleAttempt

LOGGER = logging.getLogger(__name__)
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
HEARTBEAT_STALE_SECONDS = 30.0
MAX_PENDING_FINISHING_TASKS = 3


class FinishingExecution:
    def __init__(self, manager, *, worker_factory=None, validate=None,
                 autostart=True, poll_seconds=.2, clock=time.monotonic):
        self.manager = manager
        self.root = Path(manager.root).resolve()
        self.store = FinishingCommands(self.root)
        self.mutex = manager.mutex
        self.worker_factory = worker_factory
        self.validate = validate
        self.clock = clock
        self.poll_seconds = poll_seconds
        self.commands = {}
        self.damaged = {}
        self.active = None
        self.closed = False
        self.wake = threading.Event()
        self.thread = None
        with self.mutex:
            self._recover()
        if autostart:
            self.thread = threading.Thread(target=self._run, daemon=True,
                                           name='finishing-execution')
            self.thread.start()

    def _recover(self):
        directory = self.store._path('finishing/operations')
        for path in sorted(directory.glob('*.json')):
            operation = path.stem
            try:
                receipt = self.store._receipt(operation)
                if receipt is None or receipt['state'] == 'deleted':
                    continue
                command = self.store.recover(operation)
                self.commands[operation] = command
                _, state = self.store._runtime(command)
                if state is None:
                    self.store.begin_attempt(command)
                elif state['status'] == 'running':
                    self.store.update_attempt(command, state['attempt_id'],
                        status='cancelled' if self._cancel_marker(command, state['attempt_id']).exists()
                        else 'interrupted', progress=state['progress'])
            except (CommandError, OSError, ValueError):
                self.damaged[operation] = 'Unreadable finishing operation; original records preserved'
                LOGGER.error('Finishing recovery isolated an unreadable operation',
                    extra={'operation_id': operation, 'action': 'finishing_record_damaged'})

    def _load(self, value):
        operation = value['operation_id'] if isinstance(value, dict) else value
        command = self.store.load(operation)
        if command is None:
            raise CommandError('Unknown finishing operation')
        if isinstance(value, dict) and command != value:
            raise CommandError('Finishing command differs from immutable operation')
        return command

    def _state(self, command):
        return self.store._runtime(command)[1]

    def _pending(self):
        result = []
        for operation, command in tuple(self.commands.items()):
            if operation in self.damaged:
                continue
            try:
                receipt = self.store._receipt(operation)
                if receipt is not None and receipt['state'] == 'deleted':
                    # The manager tombstones before its deletion transaction
                    # drops this index. A tombstone is intentional deletion,
                    # never a newly damaged command that blocks forget_job.
                    continue
                self._load(command)
                state = self._state(command)
                if state and state['status'] in {'queued', 'running'}:
                    result.append((command, state))
            except (CommandError, OSError, ValueError):
                self.damaged[operation] = 'Unreadable finishing operation; original records preserved'
        return sorted(result, key=lambda item: (item[0]['created_at'], item[0]['operation_id']))

    def _capacity(self, *, replacing=None):
        if self.closed or getattr(self.manager, 'shutdown_requested', False):
            raise BusyError('Finishing execution is stopping')
        pending = self._pending()
        live = self.active and self.active['command']['operation_id'] != replacing and all(
                                   command['operation_id'] != self.active['command']['operation_id']
                                   for command, _ in pending)
        if len(pending) + bool(live) >= MAX_PENDING_FINISHING_TASKS:
            raise BusyError('Finishing queue already has one active and two waiting tasks')

    def submit(self, command):
        with self.mutex:
            command = self._load(command)
            state = self._state(command)
            if state is not None:
                self.commands[command['operation_id']] = command
                return self.status(command)
            self._capacity()
            self.store.begin_attempt(command)
            self.commands[command['operation_id']] = command
            self.wake.set()
            return self.status(command)

    def _validate(self, command):
        self.store.verify_assets(command)
        if self.validate is not None:
            self.validate(self.root, command)
        else:
            from app.finishing_render import validate_command
            validate_command(self.root, command)

    def resume(self, operation_id):
        with self.mutex:
            command = self._load(operation_id)
            state = self._state(command)
            if not state or state['status'] not in {'interrupted', 'failed', 'cancelled'}:
                raise CommandError('Only an interrupted, failed or cancelled finishing task can resume')
            self._capacity(replacing=operation_id)
            self._validate(command)
            if self.active and self.active['command']['operation_id'] == operation_id:
                # A failed/cancelled worker can still be unwinding. Its attempt
                # is already fenced, but its owned descendants must stop before
                # another attempt may use the same command's files.
                self._drain(self.active, terminate=True)
                self.active = None
            self.store.begin_attempt(command)
            self.commands[operation_id] = command
            self.wake.set()
            return self.status(command)

    def _directory(self, command, attempt):
        directory = self.store.task_directory(command['job_id'], command['kind'], command['task_id'])
        return self.store._owned(directory/'attempts'/attempt)

    def _finish(self, command, attempt, status):
        state = self._state(command)
        if state is None:
            raise CommandError('Finishing attempt disappeared before terminal reconciliation')
        if state and state['attempt_id'] == attempt and state['status'] not in TERMINAL:
            try:
                self.store.update_attempt(command, attempt, status=status, progress=state['progress'])
            except StaleAttempt:
                pass

    def _isolate(self, command):
        self.commands[command['operation_id']] = command
        self.damaged[command['operation_id']] = 'Unreadable finishing operation; original records preserved'

    def _cancel_marker(self, command, attempt):
        return self.store._owned(self._directory(command, attempt)/'.cancel')

    def _settle(self, active, status, *, terminate=False):
        """Stop the owned tree, then reconcile durable state before releasing it.

        Busy operation locks are transient. Keep the drained owner so another
        observation retries the exact terminal transition, never another render.
        Permanently unreadable state is preserved under known job ownership.
        """
        active['terminal_requested'] = status
        if terminate:
            active['terminate_requested'] = True
        if not active.get('drained'):
            try:
                self._drain(active, terminate=terminate)
                active['drained'] = True
            except Exception:
                LOGGER.exception('Could not drain owned finishing process tree')
                return False
        try:
            self._finish(active['command'], active['attempt'], status)
        except BusyError:
            return False
        except (CommandError, OSError, ValueError):
            self._isolate(active['command'])
            LOGGER.exception('Finishing terminal state is damaged; preserving known job ownership')
        return True

    def cancel(self, operation_id):
        with self.mutex:
            active = self.active if self.active and self.active['command']['operation_id'] == operation_id else None
            if active:
                command = active['command']
                try:
                    # This owned marker is independent of the operation lock;
                    # publish cancellation before waiting for a receipt writer.
                    self._cancel_marker(command, active['attempt']).touch()
                except (CommandError, OSError, ValueError):
                    LOGGER.exception('Could not publish finishing cancellation marker')
                if self._settle(active, 'cancelled', terminate=True):
                    self.active = None
            else:
                command = self._load(operation_id)
                state = self._state(command)
                if state is None:
                    raise CommandError('Finishing operation has not been scheduled')
                if state['status'] not in TERMINAL:
                    self._cancel_marker(command, state['attempt_id']).touch()
                    try:
                        self._finish(command, state['attempt_id'], 'cancelled')
                    except BusyError:
                        pass  # The queued marker is reconciled before any launch.
                    except (CommandError, OSError, ValueError):
                        self._isolate(command)
                        raise
            self.wake.set()
            return self.status(command)

    def _observe(self, active):
        from app.json_store import read_json
        try:
            record = read_json(self.store._owned(active['directory']/'worker-heartbeat.json'))
            pid = getattr(getattr(active['worker'], 'process', None), 'pid', None)
            if (isinstance(record, dict) and record.get('version') == 1
                    and record.get('attempt_id') == active['attempt']
                    and type(record.get('pid')) is int and record['pid'] == pid
                    and type(record.get('sequence')) is int and record['sequence'] > active['sequence']
                    and isinstance(record.get('heartbeat_at'), str)):
                active.update(sequence=record['sequence'], last_seen=self.clock())
        except (OSError, ValueError, UnicodeError):
            pass

    def status(self, command):
        """Read-only projection. Never repairs, schedules or adopts a process."""
        with self.mutex:
            command = self._load(command)
            state = self._state(command)
            if state is None:
                return None
            result = dict(state)
            from app.json_store import read_json
            try:
                details = read_json(self.store._owned(self._directory(command, state['attempt_id'])/'progress.json'), {})
                if (isinstance(details, dict) and details.get('attempt_id') == state['attempt_id']
                        and details.get('command_hash') == command['command_hash']):
                    result.update({key: details[key][:1000] for key in ('phase', 'message', 'error')
                                   if isinstance(details.get(key), str)})
            except (OSError, ValueError, UnicodeError):
                pass
            if self.active and self.active['command']['operation_id'] == command['operation_id']:
                active = self.active
                # Observation mutates only in-memory health, never durable state.
                self._observe(active)
                elapsed = max(0., self.clock()-active['last_seen'])
                result['worker_health'] = {
                    'status': 'reconciling' if active.get('drained') else 'stale' if elapsed >= HEARTBEAT_STALE_SECONDS else (
                        'healthy' if active['sequence'] >= 0 else 'starting'),
                    'seconds_since_heartbeat': round(elapsed, 1)}
                if active.get('terminal_requested') == 'cancelled' and state['status'] not in TERMINAL:
                    result.update(phase='cancelling', message='Owned worker stopped; saving cancellation'
                                  if active.get('drained') else 'Stopping owned finishing worker')
            return result

    def owns_job(self, job_id):
        with self.mutex:
            pending = self._pending()
            return (bool(self.active and self.active['command']['job_id'] == job_id)
                    or any(command['job_id'] == job_id for command, _ in pending)
                    or any(operation in self.damaged and command['job_id'] == job_id
                           for operation, command in self.commands.items()))

    def busy(self):
        with self.mutex:
            return bool(self.active or self._pending())

    def forget_job(self, job_id):
        """Drop only the in-memory index after the manager deletes a job.

        Files and operation tombstones belong to the manager's deletion
        transaction; this method never removes either.
        """
        with self.mutex:
            if self.owns_job(job_id):
                raise BusyError('Finishing tasks still own this job')
            for operation, command in tuple(self.commands.items()):
                if command['job_id'] == job_id:
                    self.commands.pop(operation)
                    self.damaged.pop(operation, None)

    def _drain(self, active, *, terminate=False):
        worker = active['worker']
        if worker is None:
            return
        if not terminate and worker.poll() is None:
            raise BusyError('Owned finishing worker is still running')
        try:
            if terminate or worker.poll() is not None:
                if terminate:
                    worker.terminate_tree()
                else:
                    worker.wait()
            if worker.poll() is None:
                raise BusyError('Owned finishing worker did not stop')
        finally:
            worker.close()

    def tick(self):
        """One scheduler observation, exposed for deterministic fault tests."""
        with self.mutex:
            if self.closed:
                return
            if self.active:
                active = self.active
                code = active['worker'].poll() if active['worker'] is not None else 1
                if code is None and not active.get('terminate_requested'):
                    self._observe(active)
                    return
                status = active.get('terminal_requested')
                if status is None:
                    try:
                        cancelled = self._cancel_marker(active['command'], active['attempt']).exists()
                    except (CommandError, OSError, ValueError):
                        self._isolate(active['command'])
                        cancelled = False
                    status = 'cancelled' if cancelled else ('failed' if code else 'interrupted')
                if not self._settle(active, status, terminate=bool(active.get('terminate_requested'))):
                    return
                self.active = None
            if getattr(self.manager, 'active', None) or getattr(self.manager, 'shutdown_requested', False):
                return
            for command, state in self._pending():
                if state['status'] != 'queued':
                    continue
                attempt = state['attempt_id']
                try:
                    directory = self._directory(command, attempt)
                    cancel_marked = self._cancel_marker(command, attempt).exists()
                except (CommandError, OSError, ValueError):
                    self._isolate(command)
                    continue
                if cancel_marked:
                    try:
                        self._finish(command, attempt, 'cancelled')
                    except BusyError:
                        return
                    except (CommandError, OSError, ValueError):
                        self._isolate(command)
                    continue
                running = False
                try:
                    self._validate(command)
                    self.store.update_attempt(command, attempt, status='running')
                    running = True
                    factory = self.worker_factory
                    if factory is None:
                        from app.jobs import WorkerProcess
                        factory = WorkerProcess
                    worker = factory(directory, command=[sys.executable, '-B', '-m',
                        'app.finishing_worker', '--root', str(self.root), '--operation',
                        command['operation_id'], '--attempt', attempt, '--directory', str(directory)])
                    self.active = {'worker': worker, 'command': command, 'attempt': attempt,
                                   'directory': directory, 'sequence': -1, 'last_seen': self.clock()}
                    break
                except BusyError:
                    if not running:
                        return
                    self.active = {'worker': None, 'command': command, 'attempt': attempt,
                                   'directory': directory, 'sequence': -1, 'last_seen': self.clock(), 'drained': True}
                    if self._settle(self.active, 'failed'):
                        self.active = None
                    return
                except Exception:
                    pending = {'worker': None, 'command': command, 'attempt': attempt,
                               'directory': directory, 'sequence': -1, 'last_seen': self.clock(), 'drained': True}
                    if not self._settle(pending, 'failed'):
                        self.active = pending
                        return
                    LOGGER.exception('Finishing worker could not start', extra={
                        'operation_id': command['operation_id'], 'action': 'finishing_worker_start_failed'})

    def _run(self):
        while not self.closed:
            try:
                self.tick()
            except Exception:
                LOGGER.exception('Finishing scheduler observation failed')
            self.wake.wait(self.poll_seconds)
            self.wake.clear()

    def stop(self, timeout=10):
        drained = True
        with self.mutex:
            self.closed = True
            if self.active:
                active = self.active
                status = active.get('terminal_requested', 'interrupted')
                if status == 'interrupted':
                    try:
                        self.store._owned(active['directory']/'.interrupt').touch()
                    except (CommandError, OSError, ValueError):
                        LOGGER.exception('Could not persist finishing interruption marker')
                drained = self._settle(active, status, terminate=True)
                if drained:
                    self.active = None
            self.wake.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=max(0, timeout))
        return drained and (self.thread is None or not self.thread.is_alive())
