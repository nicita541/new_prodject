"""Persistent source registry and a single, cancellable background worker."""
from __future__ import annotations

from app.json_store import atomic_json, read_json, now
from app.content_identity import digest as content_digest
from app.file_lock import BusyError, InstanceLock

import ctypes
import copy
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from app import config

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "waiting_analysis"}
LOGGER = logging.getLogger(__name__)
HEARTBEAT_STALE_SECONDS = 30.0
WORKER_POLL_SECONDS = 0.2


class DamagedJobError(ValueError):
    """A saved user record is unreadable; never replace it with empty state."""


def contained(path: Path, root: Path) -> Path:
    result = path.resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Путь находится за пределами папки проекта")
    return result


def validate_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise KeyError(value) from None
    if str(parsed) != value:
        raise KeyError(value)
    return value


class SubmissionConflict(BusyError):
    """An operation ID cannot create another job or change its original command."""


class WorkerProcess:
    """Own a child tree without enumerating or killing unrelated processes.

    Windows: the worker waits for a start marker before importing the pipeline;
    assign it to a kill-on-close Job Object before allowing grandchildren.
    POSIX: children share a new process group.
    """
    def __init__(self, job_dir: Path, *, command: list[str] | None = None):
        self.process = None
        self.handle = None
        self.log = (job_dir / "worker.log").open("ab")
        start = job_dir / ".start"
        start.unlink(missing_ok=True)
        kwargs = {"cwd": str(config.ROOT), "stdin": subprocess.DEVNULL,
                  "stdout": self.log, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(
                command or [sys.executable, "-m", "app.worker", "--job", job_dir.name], **kwargs)
            if os.name == "nt":
                self._assign_windows_job()
            start.touch()
        except BaseException:
            if self.process:
                self.process.kill()
                self.process.wait()
            self.close()
            raise

    def _assign_windows_job(self):
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                        ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t),
                        ("PeakJob", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(self.handle, int(self.process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self):
        return self.process.poll()

    def wait(self):
        return self.process.wait()

    def terminate_tree(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
        elif self.process and self.process.poll() is None:
            if os.name != "nt":
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                self.process.terminate()
        if self.process:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait()

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        self.log.close()


class JobManager:
    def __init__(self, root: Path | None = None, worker_factory: Callable = WorkerProcess):
        self.root = (root or config.ROOT).resolve()
        self.data = contained(self.root / "data", self.root)
        self.jobs = contained(self.data / "jobs", self.root)
        self.imports = contained(self.data / "imports", self.root)
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.imports.mkdir(parents=True, exist_ok=True)
        self.lock = InstanceLock(self.data / ".server.lock")
        self.mutex = threading.RLock()
        self.worker_factory = worker_factory
        self.active = None
        # Active finishing previews/exports also own files under a job directory.
        self.finishing_tasks: dict[str, int] = {}
        self.pending_states = {}
        self.damaged_jobs: dict[str, str] = {}
        self._worker_observation = None
        self.closed = False
        self._resources_closed = False
        self.finishing_execution = None
        self.shutdown_requested = False
        self.sources = read_json(self.data / "sources.json", {})
        try:
            self._recover()
            from .finishing_execution import FinishingExecution
            self.finishing_execution = FinishingExecution(self)
            from .studio_render import recover_legacy_finishing
            recover_legacy_finishing(self)
        except BaseException:
            if self.finishing_execution is not None:
                self.finishing_execution.stop()
            self.lock.close()
            raise

    def _recover(self):
        self._recover_submissions()
        for path in self.jobs.glob("*/job.json"):
            try:
                job = self._read_job(path.parent.name)
            except (DamagedJobError, KeyError):
                continue
            if job and job["status"] in {"queued", "running"}:
                job.update(status="interrupted", message="Обработка прервана. Можно продолжить.",
                           updated_at=now(), cancel_requested=False)
                atomic_json(path, job)

    def _submission_path(self, operation_id: str) -> Path:
        try:
            validate_id(operation_id)
        except KeyError:
            raise ValueError('operation_id должен быть UUID в канонической записи') from None
        return contained(self.data / 'job-operations' / (operation_id + '.json'), self.data)

    def _read_submission(self, operation_id: str) -> dict | None:
        path = self._submission_path(operation_id)
        try:
            receipt = read_json(path)
            if receipt is None and not path.exists():
                return None
            if (not isinstance(receipt, dict) or receipt.get('version') != 1
                    or receipt.get('operation_id') != operation_id
                    or receipt.get('state') not in {'reserved', 'committed', 'deleted'}
                    or not isinstance(receipt.get('request'), dict)
                    or not isinstance(receipt.get('files'), dict)
                    or not isinstance(receipt.get('job'), dict)):
                raise ValueError()
            snapshot = {key: value for key, value in receipt.items() if key not in {'state', 'snapshot_sha256'}}
            if receipt.get('snapshot_sha256') != content_digest(snapshot):
                raise ValueError()
            identifier = validate_id(receipt['job_id'])
            job, request, files = receipt['job'], receipt['request'], receipt['files']
            request_fields = {'source_id', 'analysis_provider', 'layout', 'caption_style',
                              'episode_id', 'processing_mode', 'reuse_job_id', 'economy_mode'}
            required = {'source.json', 'analysis-settings.json', 'render-settings.json', 'processing-settings.json'}
            allowed = required | {'editorial-settings.json', 'planning-preferences.json', 'speech-handle-overrides.json', 'story-objective.json'}
            absent = receipt.get('absent_settings', [])
            if (set(request)-{'story_objective'} != request_fields or not required.issubset(files) or not set(files).issubset(allowed)
                    or not isinstance(absent, list) or any(not isinstance(name, str) for name in absent)
                    or not set(absent).issubset(allowed - required) or set(absent).intersection(files)
                    or job.get('id') != identifier or job.get('operation_id') != operation_id
                    or job.get('episode_id') != request.get('episode_id')
                    or job.get('source_id') != request.get('source_id')
                    or job.get('status') != 'queued'
                    or not isinstance(job.get('created_at'), str)
                    or not isinstance(job.get('source_name'), str)
                    or not isinstance(files['source.json'], dict)
                    or not isinstance(files['source.json'].get('name'), str)
                    or not all(isinstance(files[name], dict) for name in required)):
                raise ValueError()
            contained(Path(files['source.json']['path']), self.root)
            previous = files['processing-settings.json'].get('reuse_job_id')
            if previous is not None:
                validate_id(previous)
                if previous == identifier:
                    raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise SubmissionConflict('Квитанция операции повреждена. Она сохранена; новое задание не создано.') from None
        return receipt

    def _recover_submissions(self):
        # Recovery never starts a worker. Incomplete creation is made visible
        # under its reserved ID and requires an explicit ordinary retry.
        for path in (self.data / 'job-operations').glob('*.json'):
            try:
                receipt = self._read_submission(path.stem)
                if receipt and receipt['state'] == 'reserved':
                    self._materialize_submission(receipt, recovered=True)
            except (OSError, ValueError, KeyError, RuntimeError):
                LOGGER.error('Не удалось восстановить создание задания; квитанция сохранена',
                             extra={'action': 'job_submission_recovery_failed', 'status': 'interrupted'})

    def _write_job_inputs(self, directory: Path, files: dict, *, absent_settings=(), owner_episode_id=None) -> None:
        from .processing import inherit_checkpoints
        files = copy.deepcopy(files)
        processing = files['processing-settings.json']
        previous = processing.get('reuse_job_id')
        copied = []
        if previous is not None:
            previous_directory = self.job_dir(previous)
            if not (previous_directory / 'job.json').is_file():
                raise SubmissionConflict('Задание с исходными контрольными точками недоступно. Квитанция сохранена.')
            from .checkpoint_lineage import link
            from .processing import source_digest
            link(previous_directory, directory, source_sha256=source_digest(Path(files['source.json']['path'])),
                 episode_id=owner_episode_id)
            copied = inherit_checkpoints(previous_directory, directory,
                                         plan_only=processing['mode'] == 'plan_only')
        processing['inherited_files'] = copied
        # Settings were captured before the reservation, not read again from
        # a possibly edited episode or ancestor during crash recovery.
        for name in absent_settings:
            (directory / name).unlink(missing_ok=True)
        for name, value in files.items():
            atomic_json(directory / name, value)

    def _materialize_submission(self, receipt: dict, *, recovered: bool) -> dict:
        identifier = receipt['job_id']
        directory = self.job_dir(identifier)
        if (directory / 'job.json').exists():
            job = self._read_job(identifier)
            if (job.get('operation_id') != receipt['operation_id']
                    or job.get('source_id') != receipt['request']['source_id']
                    or job.get('episode_id') != receipt['request']['episode_id']):
                raise SubmissionConflict('Зарезервированное задание принадлежит другой операции.')
        else:
            if receipt['state'] != 'reserved':
                raise SubmissionConflict('Задание этой операции удалено или недоступно. Повторный запуск не выполнен.')
            directory.mkdir(exist_ok=True)
            self._write_job_inputs(directory, receipt['files'], absent_settings=receipt.get('absent_settings', []),
                                   owner_episode_id=receipt['job'].get('episode_id'))
            job = copy.deepcopy(receipt['job'])
            if recovered:
                job.update(status='interrupted', updated_at=now(),
                           message='Создание задания восстановлено. Можно продолжить обработку.')
            atomic_json(directory / 'job.json', job)
        if receipt['state'] == 'reserved':
            atomic_json(self._submission_path(receipt['operation_id']), {**receipt, 'state': 'committed'})
        return job

    def _existing_submission(self, operation_id: str, request: dict) -> dict | None:
        receipt = self._read_submission(operation_id)
        if receipt is None:
            return None
        if content_digest(receipt['request']) != content_digest(request):
            raise SubmissionConflict('operation_id уже использован для другого исходника, настроек или серии.')
        if receipt['state'] == 'deleted':
            raise SubmissionConflict('Задание этой операции удалено. Повторный запуск не выполнен.')
        job = self._materialize_submission(receipt, recovered=True)
        return self.get(job['id'])

    def _read_job(self, identifier: str) -> dict:
        path = self.job_dir(identifier) / "job.json"
        try:
            missing = object()
            job = read_json(path, missing)
            if job is missing:
                raise KeyError(identifier)
            if (not isinstance(job, dict) or job.get("id") != identifier
                    or job.get("status") not in TERMINAL | {"queued", "running"}
                    or not isinstance(job.get("created_at"), str)
                    or not isinstance(job.get("source_name"), str)
                    or not isinstance(job.get("outputs", []), list)
                    or any(not isinstance(name, str) for name in job.get("outputs", []))):
                raise ValueError("Invalid job record")
        except (OSError, ValueError, TypeError) as error:
            # Log only the exception type, never the contents of a damaged file.
            reason = type(error).__name__
            if self.damaged_jobs.get(identifier) != reason:
                LOGGER.error("Повреждена запись задания %s; исходный job.json сохранён (%s)",
                             identifier, reason, extra={"job_id": identifier,
                             "action": "job_record_damaged", "status": "damaged"})
            self.damaged_jobs[identifier] = reason
            raise DamagedJobError("Повреждена запись задания. Исходный job.json сохранён; "
                                  "остальные задания доступны.") from None
        self.damaged_jobs.pop(identifier, None)
        return job

    def list_sources(self, *, discover=True) -> list[dict]:
        with self.mutex:
            sources_path = self.data / "sources.json"
            on_disk = read_json(sources_path, {})
            if isinstance(on_disk, dict):
                self.sources.update(on_disk)
            if not discover:
                result = []
                for identifier, record in self.sources.items():
                    try:
                        path = contained(Path(record['path']), self.root)
                        if path.is_file():
                            result.append({'id': identifier, 'name': record.get('name', path.name),
                                           'size': path.stat().st_size})
                    except (ValueError, KeyError, OSError):
                        continue
                return sorted(result, key=lambda item: item['name'])
            by_path = {record["path"]: identifier for identifier, record in self.sources.items()}
            candidates = list(self.root.iterdir()) + list(self.imports.glob("*/*"))
            result = []
            changed = False
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.lower() not in {".mp4", ".mkv"}:
                    continue
                try:
                    resolved = contained(candidate, self.root)
                except ValueError:
                    continue
                resolved_str = str(resolved)
                identifier = by_path.get(resolved_str)
                if not identifier:
                    identifier = str(uuid.uuid4())
                    by_path[resolved_str] = identifier
                    changed = True
                record = self.sources.get(identifier)
                if not record:
                    record = {"path": resolved_str, "name": candidate.name}
                    self.sources[identifier] = record
                    changed = True
                elif record.get("path") != resolved_str:
                    record["path"] = resolved_str
                    changed = True
                result.append({"id": identifier, "name": record.get("name", candidate.name), "size": resolved.stat().st_size})
            if changed or not sources_path.is_file():
                atomic_json(sources_path, self.sources)
            return sorted(result, key=lambda item: item["name"])

    def register_import(self, path: Path, original_name: str) -> dict:
        with self.mutex:
            sources_path = self.data / "sources.json"
            on_disk = read_json(sources_path, {})
            if isinstance(on_disk, dict):
                self.sources.update(on_disk)
            path = contained(path, self.imports)
            identifier = str(uuid.uuid4())
            self.sources[identifier] = {"path": str(path), "name": original_name}
            atomic_json(sources_path, self.sources)
            return {"id": identifier, "name": original_name, "size": path.stat().st_size}

    def source(self, identifier: str) -> dict:
        validate_id(identifier)
        record = self.sources.get(identifier)
        if not record:
            raise KeyError(identifier)
        path = contained(Path(record["path"]), self.root)
        if not path.is_file() or path.suffix.lower() not in {".mp4", ".mkv"}:
            raise KeyError(identifier)
        if path.parent != self.root and not path.is_relative_to(self.imports.resolve()):
            raise KeyError(identifier)
        return {"path": str(path), "name": record["name"]}

    def job_dir(self, identifier: str) -> Path:
        return contained(self.jobs / validate_id(identifier), self.jobs)

    def get(self, identifier: str) -> dict:
        with self.mutex:
            path = self.job_dir(identifier) / "job.json"
            job = self._read_job(identifier)
            owned = self.active is not None and self.active[0] == identifier
            if not owned and identifier in self.pending_states:
                job = dict(self.pending_states[identifier])
                try:
                    atomic_json(path, job)
                except OSError:
                    LOGGER.exception("Не удалось сохранить фактический статус задания %s", identifier)
                else:
                    self.pending_states.pop(identifier, None)
                return job
            if not owned and job["status"] in {"queued", "running"}:
                job.update(status="interrupted", cancel_requested=False, updated_at=now(),
                           message="Рабочий процесс завершён без сохранения статуса. Можно продолжить.")
                try:
                    atomic_json(path, job)
                except OSError:
                    # Return the actual process state even while storage is
                    # unavailable. A later read retries persisting recovery.
                    LOGGER.exception("Не удалось сохранить восстановленный статус задания %s", identifier)
            if owned:
                job = {**job, "worker_health": self._observe_worker(identifier, self.active[1])}
            return job

    def list_jobs(self) -> list[dict]:
        jobs = []
        for path in self.jobs.glob("*/job.json"):
            try:
                jobs.append(self.get(path.parent.name))
            except (DamagedJobError, KeyError):
                continue
        return sorted(jobs, key=lambda item: item["created_at"], reverse=True)

    def _observe_worker(self, identifier: str, child) -> dict | None:
        """Observe only our current process; stale heartbeat is not a kill policy.

        A long model request may have no progress while its heartbeat advances.
        A missing heartbeat can also mean blocked storage/native Python code, so
        it is diagnostic and leaves explicit cancellation to the owned tree.
        """
        if not self.active or self.active != (identifier, child):
            return None
        observation = self._worker_observation
        if observation is None:
            return None
        process = getattr(child, "process", None)
        pid = getattr(process, "pid", None)
        if pid is None:
            return {"status": "unavailable", "process_alive": child.poll() is None,
                    "attempt_id": observation["attempt_id"]}
        stamp = time.monotonic()
        reason = "missing"
        try:
            record = read_json(self.job_dir(identifier) / "worker-heartbeat.json")
            if record is not None:
                reason = "invalid"
                if (isinstance(record, dict) and record.get("version") == 1
                        and record.get("attempt_id") == observation["attempt_id"]
                        and type(record.get("pid")) is int and record["pid"] == pid
                        and type(record.get("sequence")) is int and record["sequence"] > 0
                        and isinstance(record.get("heartbeat_at"), str)):
                    reason = None
                    if record["sequence"] > observation["sequence"]:
                        observation.update(sequence=record["sequence"], last_seen=stamp,
                                           heartbeat_at=record["heartbeat_at"])
        except (OSError, ValueError, TypeError):
            reason = "unreadable"
        elapsed = max(0.0, stamp - observation["last_seen"])
        status = ("stale" if elapsed >= HEARTBEAT_STALE_SECONDS else
                  "healthy" if observation["sequence"] else "starting")
        if status != observation.get("status"):
            if status == "stale" or observation.get("status") == "stale":
                LOGGER.log(logging.WARNING if status == "stale" else logging.INFO,
                           "Worker heartbeat: %s", status,
                           extra={"job_id": identifier, "run_id": observation["attempt_id"],
                                  "action": "worker_heartbeat_" + status, "status": status})
            observation["status"] = status
        return {"status": status, "process_alive": child.poll() is None,
                "attempt_id": observation["attempt_id"],
                "last_heartbeat_at": observation.get("heartbeat_at"),
                "seconds_since_heartbeat": round(elapsed, 1), "heartbeat_issue": reason}

    def _drop_finishing_export_index(self, job_id: str) -> None:
        """Remove only orphaned registry entries after a job was removed.

        The registry contains pointers to isolated exports in the deleted job
        directory. Never delete other jobs' entries or active task folders.
        """
        directory = self.root / "finishing" / "exports-index"
        if not directory.is_dir():
            return
        for path in directory.glob("ex_*.json"):
            try:
                record = read_json(path, {})
                if isinstance(record, dict) and record.get("source_job_id") == job_id:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                LOGGER.exception("Cannot inspect/remove old export registry entry %s", path.name)

    def _checkpoint_dependents(self, identifier):
        from .checkpoint_lineage import dependents
        references = set(dependents(self.jobs, identifier))
        # A process may stop between durable submission reservation and writing
        # the child's lineage pointer. Preserve its intended ancestor too.
        for path in (self.data / 'job-operations').glob('*.json'):
            try:
                receipt = self._read_submission(path.stem)
            except (ValueError, SubmissionConflict):
                continue
            if (receipt and receipt['state'] == 'reserved'
                    and receipt['files']['processing-settings.json'].get('reuse_job_id') == identifier):
                references.add(receipt['job_id'])
        return references

    def _retire_finishing_commands(self, identifier):
        """Tombstone exact finishing intentions before removing their job files."""
        from .finishing_commands import FinishingCommands, CommandError
        store = FinishingCommands(self.root)
        commands = {}
        directory = self.job_dir(identifier)
        for kind in ('previews', 'exports'):
            for path in (directory/'finishing'/kind).glob('*/command.json'):
                saved = store._read(path)
                command = store._command(saved, expected={'job_id': identifier})
                if store.load(command['operation_id'], job_id=identifier) != command:
                    raise CommandError('Finishing command is missing its operation receipt')
                commands[command['operation_id']] = command
        for path in store._path('finishing/operations').glob('*.json'):
            try:
                receipt = store._receipt(path.stem)
            except (ValueError, OSError):
                continue
            if receipt and receipt['state'] != 'deleted' and receipt['command']['job_id'] == identifier:
                commands[path.stem] = receipt['command']
        retired = []
        try:
            for operation in commands:
                path = store._operation(operation)
                receipt = store._receipt(operation)
                store.tombstone(operation, job_id=identifier)
                retired.append((path, receipt))
        except BaseException:
            for path, receipt in reversed(retired):
                atomic_json(path, receipt)
            raise
        return retired

    def delete_job(self, identifier: str) -> dict:
        with self.mutex:
            validate_id(identifier)
            if self.active and self.active[0] == identifier:
                raise BusyError("Нельзя удалить выполняющееся задание")
            if self.finishing_tasks.get(identifier, 0) or self.finishing_execution.owns_job(identifier):
                raise BusyError("Нельзя удалить задание во время предпросмотра или экспорта")
            directory = self.job_dir(identifier)
            if not directory.is_dir():
                raise KeyError(identifier)
            if self._checkpoint_dependents(identifier):
                raise BusyError('Задание используется потомками как источник контрольных точек')
            # Keep a tombstone even for an interrupted reservation whose
            # job.json was never published. A retry must not resurrect it.
            retired = []
            try:
                retired.extend(self._retire_finishing_commands(identifier))
                for path in (self.data / 'job-operations').glob('*.json'):
                    try:
                        receipt = self._read_submission(path.stem)
                    except (ValueError, SubmissionConflict):
                        continue
                    if receipt and receipt['job_id'] == identifier:
                        atomic_json(path, {**receipt, 'state': 'deleted'})
                        retired.append((path, receipt))
                # Never report success if Windows locks or permissions prevent removal.
                shutil.rmtree(directory)
            except BaseException:
                for path, receipt in retired:
                    try:
                        atomic_json(path, receipt)
                    except OSError:
                        LOGGER.error('Не удалось восстановить квитанцию после ошибки удаления задания',
                                     extra={'job_id': identifier, 'action': 'job_submission_restore_failed'})
                raise
            self._drop_finishing_export_index(identifier)
            self.finishing_execution.forget_job(identifier)
            self.pending_states.pop(identifier, None)
            return {"id": identifier, "deleted": True}

    @staticmethod
    def _has_resumable_work(directory: Path) -> bool:
        """Protect recoverable hours of media/AI work from bulk pruning.

        Users can explicitly delete any stopped job. The automated/bulk prune
        must not silently discard checkpoints or already rendered Shorts from
        failed, interrupted or cancelled jobs.
        """
        for name in ("audio.wav", "transcript.json", "shots.json", "scenes.json",
                     "events.json", "story-events.json", "analysis-final.json", "plan.json"):
            if (directory / name).is_file():
                return True
        for folder, pattern in (("visual", "*.checkpoint.json"),
                                ("visual", "event_*.json"),
                                ("story_refinement", "*.json"),
                                ("render", "part_*.json"),
                                ("output", "part_*.mp4")):
            if any((directory / folder).glob(pattern)):
                return True
        return False

    def prune_jobs(self, max_jobs: int = 50, max_age_days: int | None = 30) -> dict:
        # Validate before inspecting or deleting user exports. Negative values
        # would otherwise silently select every completed job for deletion.
        if (max_jobs is not None and
                (type(max_jobs) is not int or max_jobs < 0)):
            raise ValueError("max_jobs должно быть неотрицательным целым числом")
        if (max_age_days is not None and
                (type(max_age_days) is not int or max_age_days < 0)):
            raise ValueError("max_age_days должно быть неотрицательным целым числом")
        with self.mutex:
            active_id = self.active[0] if self.active else None
            terminal_jobs = []
            now_ts = time.time()
            cutoff_ts = (now_ts - max_age_days * 86400) if max_age_days is not None else None

            for path in self.jobs.glob("*/job.json"):
                jid = path.parent.name
                if (jid == active_id or self.finishing_tasks.get(jid, 0)
                        or self.finishing_execution.owns_job(jid) or self._checkpoint_dependents(jid)):
                    continue
                try:
                    data = self._read_job(jid)
                except (DamagedJobError, KeyError):
                    continue
                if not data or data.get("status") not in TERMINAL:
                    continue
                if (data.get("status") in {"failed", "interrupted", "cancelled"}
                        and self._has_resumable_work(path.parent)):
                    # Retain checkpoints so retry() can continue this exact
                    # job ID without redoing expensive paid/model analysis.
                    continue
                created_at = data.get("created_at") or ""
                mtime = path.stat().st_mtime
                terminal_jobs.append((jid, created_at, mtime, path.parent))

            # Sort oldest first by created_at / mtime
            terminal_jobs.sort(key=lambda item: (item[1], item[2]))

            pruned = []
            # Prune jobs older than max_age_days
            remaining_jobs = []
            for jid, created_at, mtime, directory in terminal_jobs:
                if cutoff_ts is not None and mtime < cutoff_ts:
                    try:
                        self.delete_job(jid)
                    except (OSError, BusyError, ValueError):
                        LOGGER.exception("Cannot prune job %s", jid)
                    else:
                        pruned.append(jid)
                else:
                    remaining_jobs.append((jid, created_at, mtime, directory))

            # Prune excess count beyond max_jobs
            excess = max(0, len(remaining_jobs) - max_jobs) if max_jobs is not None else 0
            if excess > 0:
                for jid, _, _, directory in remaining_jobs[:excess]:
                    try:
                        self.delete_job(jid)
                    except (OSError, BusyError, ValueError):
                        LOGGER.exception("Cannot prune job %s", jid)
                    else:
                        pruned.append(jid)

            return {"pruned_count": len(pruned), "pruned_ids": pruned,
                    "remaining_terminal": len(terminal_jobs) - len(pruned)}

    def busy(self) -> bool:
        with self.mutex:
            # Keep ownership until the watcher has closed the job object/log.
            return self.active is not None

    @staticmethod
    def _check_analysis_provider(provider: str) -> None:
        if provider not in {"local", "deepseek", "hybrid", "deepseek_plan", "local_flash_story", "local_fast_story", "local_flash_story_budgeted", "antigravity_manual"}:
            raise ValueError("Неизвестный способ анализа")
        # Hybrid always has a local path; remote availability is evaluated
        # only when the pipeline actually needs an optional fallback.
        if provider in {"local", "hybrid", "local_fast_story", "antigravity_manual"}:
            return
        try:
            from app.deepseek import public_status
            state = public_status()
            configured = state.get("configured") is True
        except Exception:
            # Client failures may contain credentials; never expose their text.
            raise ValueError("Не удалось проверить локальные настройки DeepSeek") from None
        if not configured:
            raise ValueError("DeepSeek не настроен. Доступен локальный анализ.")

    def create(self, source_id: str, analysis_provider: str = "local",
               layout: str = "portrait", caption_style: str = "classic", episode_id: str | None = None,
               processing_mode: str = "full", reuse_job_id: str | None = None,
               correction_request: dict | None = None, economy_mode: bool = True,
               operation_id: str | None = None, preflight: Callable | None = None,
               story_objective: dict | None = None) -> dict:
        with self.mutex:
            from .processing import validate_mode, cached_analysis, source_digest
            request = {'source_id': source_id, 'analysis_provider': analysis_provider,
                       'layout': layout, 'caption_style': caption_style, 'episode_id': episode_id,
                       'processing_mode': processing_mode, 'reuse_job_id': reuse_job_id,
                       'economy_mode': economy_mode}
            from .story_objective import validate_objective
            objective = validate_objective(story_objective)
            if story_objective is not None:
                request['story_objective'] = objective
            if operation_id is not None:
                if correction_request is not None:
                    raise ValueError('Замечания используют собственный идентификатор операции')
                existing = self._existing_submission(operation_id, request)
                if existing is not None:
                    return existing
            if type(economy_mode) is not bool:
                raise ValueError('Экономный режим должен быть включён или выключен')
            validate_mode(processing_mode)
            from .editing import validate_options
            options = validate_options(layout, caption_style)
            if episode_id is not None:
                validate_id(episode_id)
            self._assert_available()
            if preflight is not None:
                preflight()
            if processing_mode != 'plan_only':
                self._check_analysis_provider(analysis_provider)
            source = self.source(source_id)
            previous = None
            if processing_mode != 'full':
                candidates = [self.get(reuse_job_id)] if reuse_job_id else self.list_jobs()
                digest = source_digest(Path(source['path']))
                legacy_owners = read_json(self.data/'library.json', {}).get('legacy_jobs', {})
                for candidate in candidates:
                    old_dir = self.job_dir(candidate['id'])
                    old_source = read_json(old_dir / 'source.json', {})
                    candidate_owner = candidate.get('episode_id', legacy_owners.get(candidate['id']))
                    same_owner = (candidate_owner == episode_id if episode_id else
                                  candidate.get('episode_id') is None)
                    if not same_owner or old_source.get('path') != source['path']:
                        if reuse_job_id:
                            raise ValueError('Задание кэша принадлежит другой серии или исходнику')
                        continue
                    if candidate['status'] not in TERMINAL:
                        continue
                    try:
                        if read_json(old_dir / 'analysis.meta.json', {}).get('source') != digest:
                            continue
                        if processing_mode == 'plan_only':
                            if (candidate.get('analysis_provider', 'local') != analysis_provider
                                    or candidate.get('layout', 'portrait') != layout):
                                continue
                            cached_analysis(old_dir, Path(source['path']))
                    except (ValueError, OSError, TypeError):
                        continue
                    previous = candidate
                    break
                if processing_mode == 'plan_only' and previous is None:
                    raise ValueError('Нет подходящего сохранённого анализа. Сначала выполните полный монтаж или обновление по изменениям.')
            identifier = str(uuid.uuid4())
            directory = self.jobs / identifier
            previous_settings = read_json(self.job_dir(previous['id']) / 'analysis-settings.json', {}) if previous else {}
            if previous and processing_mode == 'plan_only':
                economy_mode = previous_settings.get('economy_mode', True)
            # Preserve supplied transcript provenance, never manual exchange state.
            analysis_settings = {key: previous_settings[key] for key in
                                 ('transcript_mode', 'transcript_source_sha256') if key in previous_settings}
            previous_processing = read_json(self.job_dir(previous['id'])/'processing-settings.json', {}) if previous else {}
            response_cache_jobs = previous_processing.get('response_cache_jobs', [])
            if previous and previous_processing.get('mode') == 'full':
                response_cache_jobs = [previous['id'], *response_cache_jobs]
            files = {'source.json': source,
                'analysis-settings.json': {**analysis_settings, 'provider': analysis_provider, 'economy_mode': economy_mode},
                'render-settings.json': options,
                'story-objective.json': objective,
                'processing-settings.json': {
                'mode': processing_mode, 'reuse_job_id': previous['id'] if previous else None,
                'response_cache_jobs': response_cache_jobs, 'inherited_files': []}}
            absent_settings = []
            if previous:
                for name in ('editorial-settings.json', 'planning-preferences.json', 'speech-handle-overrides.json'):
                    path = self.job_dir(previous['id']) / name
                    if path.is_file():
                        files[name] = read_json(path)
                    else:
                        absent_settings.append(name)
            job = {"id": identifier, "source_name": source["name"], "status": "queued",
                   "stage": "queued", "progress": 0.0, "message": "Ожидание запуска",
                   "created_at": now(), "updated_at": now(), "error": None,
                   "outputs": [], "cancel_requested": False, "analysis_provider": analysis_provider, "economy_mode": economy_mode,
                   'processing_mode': processing_mode,
                   'reuse_job_id': previous['id'] if previous else None, **options}
            job['story_objective'] = objective
            if episode_id is not None:
                job['episode_id'] = episode_id
            if operation_id is not None:
                job.update(operation_id=operation_id, source_id=source_id)
                receipt = {'version': 1, 'operation_id': operation_id, 'job_id': identifier,
                           'state': 'reserved', 'request': request, 'files': files,
                           'absent_settings': absent_settings, 'job': job}
                receipt['snapshot_sha256'] = content_digest({key: value for key, value in receipt.items() if key != 'state'})
                atomic_json(self._submission_path(operation_id), receipt)
                return self._start(self._materialize_submission(receipt, recovered=False))
            directory.mkdir()
            self._write_job_inputs(directory, files, owner_episode_id=episode_id)
            if correction_request is not None:
                job['feedback_parent_job_id'] = correction_request['parent_job_id']
                job['feedback_operation_id'] = correction_request['operation_id']
                atomic_json(directory/'correction-request.json', correction_request)
                from .processing import cached_analysis
                atomic_json(directory/'correction-base-analysis.json', cached_analysis(directory, Path(source['path'])))
                atomic_json(directory/'correction-base-plan.json', read_json(directory/'plan.json'))
                journal = self.job_dir(correction_request['parent_job_id'])/'feedback'/(
                    validate_id(correction_request['operation_id'])+'.json')
                atomic_json(journal, {**correction_request, 'job_id': identifier, 'created_at': now()})
            atomic_json(directory / "job.json", job)
            return self._start(job)

    def create_feedback(self, identifier: str, operation_id: str, text: str,
                        part_index: int, source_time: float | None = None) -> dict:
        with self.mutex:
            from .processing import cached_analysis
            from .review_feedback import validate_request, digest, history
            directory = self.job_dir(identifier)
            parent = self.get(identifier)
            if parent['status'] != 'completed':
                raise ValueError('Замечание можно отправить к завершённому монтажу')
            operation_id = validate_id(operation_id)
            plan = read_json(directory/'plan.json')
            if not isinstance(plan, dict) or not plan.get('parts'):
                raise ValueError('Сохранённый план монтажа не найден')
            request = {**validate_request(text, part_index, source_time, plan),
                       'operation_id': operation_id, 'parent_job_id': identifier}
            journal = directory/'feedback'/(operation_id+'.json')
            existing = read_json(journal)
            if existing is not None:
                if any(existing.get(key) != value for key, value in request.items()):
                    raise ValueError('Идентификатор замечания уже использован для другого запроса')
                return self.get(existing['job_id'])
            self._assert_available()
            catalog = read_json(self.data/'library.json', {})
            owner = parent.get('episode_id') or catalog.get('legacy_jobs', {}).get(identifier)
            episode = catalog.get('episodes', {}).get(owner, {})
            project = catalog.get('projects', {}).get(episode.get('project_id'), {})
            if episode.get('archived_at') or project.get('archived_at'):
                raise ValueError('Сначала восстановите серию или проект из корзины')
            source = read_json(directory/'source.json')
            source_id = next((i for i, row in self.sources.items() if row['path'] == source['path']), None)
            if source_id is None:
                raise ValueError('Исходник этого монтажа больше не зарегистрирован')
            registered = self.source(source_id)
            analysis = cached_analysis(directory, Path(registered['path']))
            from .planner import validate_plan
            validate_plan(plan, analysis)
            from .processing import source_digest
            request.update(base_analysis_digest=digest(analysis), base_plan_digest=digest(plan),
                           source_sha256=source_digest(Path(source['path'])))
            request['context_messages'] = [{'text': item['text'][:300], 'reply': item['reply'][:300],
                                            'part_index': item['part_index']}
                                           for item in history(self, identifier)['messages'][-4:]]
            return self.create(source_id, parent.get('analysis_provider', 'local'),
                parent.get('layout', 'portrait'), parent.get('caption_style', 'classic'),
                episode_id=owner, processing_mode='incremental',
                reuse_job_id=identifier, correction_request=request)

    def _assert_available(self):
        if self.closed or self.shutdown_requested:
            raise BusyError("Приложение завершает работу")
        if self.active is not None:
            raise BusyError("Сейчас обрабатывается другая серия")
        # Finishing jobs also consume FFmpeg, CPU, memory and source files.
        # Do not start a fresh analysis while any preview/export is active.
        if any(self.finishing_tasks.values()) or self.finishing_execution.busy():
            raise BusyError("Дождитесь завершения предпросмотра или экспорта")

    def _start(self, job: dict) -> dict:
        directory = self.job_dir(job["id"])
        from .antigravity_runner import configure_default
        configure_default(directory,job.get('analysis_provider','local'))
        (directory / ".cancel").unlink(missing_ok=True)
        job.pop("worker_health", None)
        job.update(status="running", error=None, outputs=[], cancel_requested=False,
                   message="Запуск обработки", updated_at=now(), attempt_id=uuid.uuid4().hex,
                   progress_updated_at=None)
        atomic_json(directory / "job.json", job)
        self.pending_states.pop(job["id"], None)
        try:
            child = self.worker_factory(directory)
        except Exception as error:
            job.update(status="failed", error=str(error), message="Не удалось запустить обработку",
                       updated_at=now())
            atomic_json(directory / "job.json", job)
            return job
        self.active = (job["id"], child)
        self._worker_observation = {"attempt_id": job["attempt_id"], "sequence": 0,
                                    "last_seen": time.monotonic()}
        LOGGER.info("Worker process launched", extra={"job_id": job["id"],
                     "action": "worker_launched", "status": "running",
                     "detail_log": f"data/jobs/{job['id']}/worker.log"})
        threading.Thread(target=self._watch, args=(job["id"], child), daemon=True).start()
        return self.get(job["id"])

    def _watch(self, identifier: str, child):
        try:
            while child.poll() is None:
                with self.mutex:
                    if self.closed or not self.active or self.active[1] is not child:
                        return
                    self._observe_worker(identifier, child)
                time.sleep(WORKER_POLL_SECONDS)
            code = child.wait()
            LOGGER.log(logging.INFO if code == 0 else logging.ERROR,
                       "Worker exited with code %s", code,
                       extra={"job_id": identifier, "action": "worker_exit", "code": code,
                              "detail_log": f"data/jobs/{identifier}/worker.log"})
            with self.mutex:
                if self.closed or not self.active or self.active[1] is not child:
                    return
                job = self.get(identifier)
                job.pop("worker_health", None)
                if job["status"] not in TERMINAL:
                    requested = (self.job_dir(identifier) / ".cancel").exists()
                    job.update(status="cancelled" if requested else "failed", updated_at=now(),
                               cancel_requested=requested,
                               message="Обработка отменена" if requested else "Рабочий процесс завершился с ошибкой",
                               error=None if requested else f"Рабочий процесс завершился (код {code})")
                    atomic_json(self.job_dir(identifier) / "job.json", job)
        except Exception:
            LOGGER.exception("Не удалось сохранить завершение задания %s", identifier)
        finally:
            with self.mutex:
                try:
                    child.close()
                except Exception:
                    LOGGER.exception("Не удалось закрыть ресурсы задания %s", identifier)
                finally:
                    # An old watcher must never clear a newer retry's worker.
                    if self.active and self.active[1] is child:
                        self.active = None

    def cancel(self, identifier: str, *, stop_terminal=False) -> dict:
        with self.mutex:
            damaged = None
            try:
                job = self.get(identifier)
            except DamagedJobError as error:
                if not self.active or self.active[0] != identifier:
                    raise
                # A damaged record must not make its still-owned process
                # impossible to stop. Preserve the file after draining it.
                damaged, job = error, None
            if job is not None and job["status"] in TERMINAL and (not stop_terminal or job['status'] == 'completed'):
                return job
            try:
                (self.job_dir(identifier) / ".cancel").touch()
            except OSError:
                LOGGER.exception("Не удалось записать маркер отмены задания %s", identifier)
            if self.active and self.active[0] == identifier:
                child = self.active[1]
                try:
                    child.terminate_tree()
                finally:
                    try:
                        child.close()
                    except Exception:
                        LOGGER.exception("Не удалось закрыть ресурсы задания %s", identifier)
                    finally:
                        if self.active and self.active[1] is child:
                            self.active = None
            # No child writes after terminate_tree returns.
            if damaged is not None:
                raise damaged
            job = self._read_job(identifier)
            if job["status"] != "completed":
                job.update(status="cancelled", cancel_requested=True, error=None,
                           message="Обработка отменена. Сохранённые этапы можно продолжить.", updated_at=now())
                try:
                    atomic_json(self.job_dir(identifier) / "job.json", job)
                except OSError:
                    self.pending_states[identifier] = dict(job)
                    LOGGER.exception("Отмена выполнена, но не удалось сохранить статус задания %s", identifier)
            return job

    def change_analysis_provider(self, identifier: str, provider: str, *, resume=False, remember=None) -> dict:
        """Stop only the owned worker before banking/switching and optional resume."""
        with self.mutex:
            job = self.get(identifier)
            if job['status'] == 'completed':
                raise BusyError('Готовое задание менять нельзя; создайте новое обновление')
            if self.closed or self.shutdown_requested:
                raise BusyError('Приложение завершает работу')
            if self.active and self.active[0] != identifier:
                raise BusyError('Сейчас обрабатывается другая серия')
            if any(self.finishing_tasks.values()) or self.finishing_execution.busy():
                raise BusyError('Дождитесь завершения предпросмотра или экспорта')
            if not resume and job['status'] not in TERMINAL:
                raise BusyError('Сначала остановите обработку или выберите переключение с продолжением')
            # A missing key/unsupported destination cannot cancel healthy work.
            self._check_analysis_provider(provider)
            directory = self.job_dir(identifier)
            if resume:
                source = read_json(directory / 'source.json', {})
                if not source.get('path') or not contained(Path(source['path']), self.root).is_file():
                    raise ValueError('Исходная серия больше недоступна')
            old = job.get('analysis_provider', 'local')
            if old == provider:
                if resume and job['status'] in TERMINAL and self.active and self.active[0] == identifier:
                    self.cancel(identifier, stop_terminal=True)
                return self.retry(identifier) if resume and job['status'] in TERMINAL else job
            if job['status'] not in TERMINAL or (self.active and self.active[0] == identifier):
                job = self.cancel(identifier, stop_terminal=True)
                # Completion can race the request; never mutate a finished run.
                if job['status'] == 'completed':
                    raise BusyError('Монтаж уже завершён; создайте новое обновление')
            from .antigravity_exchange import preserve_provider_checkpoints
            preserve_provider_checkpoints(directory, old, provider)
            from .analysis_continuation import enable_continuation
            enable_continuation(directory, old, provider)
            settings = read_json(directory / 'analysis-settings.json', {})
            atomic_json(directory / 'analysis-settings.json', {**settings, 'provider': provider})
            job.update(analysis_provider=provider, provider_wait=None, error=None,
                       updated_at=now(), message='Способ анализа изменён. Сохранённые этапы доступны для продолжения.')
            atomic_json(directory / 'job.json', job)
            if remember is not None:
                remember()
            return self.retry(identifier) if resume else job

    def change_analysis_economy(self, identifier: str, enabled: bool, *, resume=False, remember=None) -> dict:
        """Change pass policy only after draining this job's owned worker."""
        with self.mutex:
            if type(enabled) is not bool:
                raise ValueError('Экономный режим должен быть включён или выключен')
            job = self.get(identifier)
            if job['status'] == 'completed' or job.get('processing_mode') == 'plan_only':
                raise BusyError('Режим проверок меняется только для незавершённого анализа')
            if self.closed or self.shutdown_requested:
                raise BusyError('Приложение завершает работу')
            if self.active and self.active[0] != identifier:
                raise BusyError('Сейчас обрабатывается другая серия')
            if any(self.finishing_tasks.values()) or self.finishing_execution.busy():
                raise BusyError('Дождитесь завершения предпросмотра или экспорта')
            if job['status'] not in TERMINAL and not resume:
                raise BusyError('Сначала остановите обработку или выберите продолжение')
            directory = self.job_dir(identifier)
            if not Path(read_json(directory / 'source.json')['path']).is_file():
                raise ValueError('Исходное видео недоступно')
            if resume:
                self._check_analysis_provider(job.get('analysis_provider', 'local'))
            if job['status'] not in TERMINAL or (self.active and self.active[0] == identifier):
                job = self.cancel(identifier, stop_terminal=True)
                if job['status'] == 'completed':
                    raise BusyError('Монтаж уже завершён')
            settings = read_json(directory / 'analysis-settings.json', {})
            atomic_json(directory / 'analysis-settings.json', {**settings, 'economy_mode': enabled})
            from .analysis_continuation import enable_continuation
            provider = job.get('analysis_provider', 'local')
            enable_continuation(directory, provider, provider)
            job.update(economy_mode=enabled, updated_at=now(),
                       message='Экономный режим включён.' if enabled else 'Включены все проверки.')
            atomic_json(directory / 'job.json', job)
            if remember is not None:
                remember()
            return self.retry(identifier) if resume else job

    def retry(self, identifier: str) -> dict:
        with self.mutex:
            self._assert_available()
            job = self.get(identifier)
            if job["status"] not in {"failed", "interrupted", "cancelled", "waiting_analysis"}:
                raise BusyError("Продолжить можно только отменённую или прерванную обработку")
            try:
                self._check_analysis_provider(job.get("analysis_provider", "local"))
            except ValueError:
                # A completed story can still be rendered/reviewed locally.
                # The cloud adapter remains halted if a changed source/cache
                # actually needs a new request; this never bypasses billing.
                directory = self.job_dir(identifier)
                if (job.get('analysis_provider') not in {'deepseek', 'deepseek_plan'} or
                        not (directory / 'story-events.json').is_file()):
                    raise
            source = read_json(self.job_dir(identifier) / "source.json")
            if not source or not contained(Path(source["path"]), self.root).is_file():
                raise ValueError("Исходная серия больше недоступна")
            if job.get('analysis_provider') in {'deepseek', 'deepseek_plan', 'hybrid', 'local_flash_story',
                                              'local_flash_story_budgeted', 'antigravity_manual'}:
                from .deepseek import begin_attempt
                begin_attempt(self.job_dir(identifier))
            return self._start(job)

    def reset_attempt_budget(self, identifier: str) -> dict:
        with self.mutex:
            self._assert_available()
            job = self.get(identifier)
            if job['status'] not in TERMINAL:
                raise BusyError('Сбросить лимит можно после остановки обработки')
            from .deepseek import begin_attempt
            return begin_attempt(self.job_dir(identifier))

    def close(self):
        with self.mutex:
            if self._resources_closed:
                return True
            self.closed = True
            try:
                if self.active:
                    identifier, child = self.active
                    try:
                        child.terminate_tree()
                        job = self.get(identifier)
                        if job["status"] not in TERMINAL:
                            job.pop("worker_health", None)
                            job.update(status="interrupted", message="Приложение закрыто. Можно продолжить.", updated_at=now())
                            atomic_json(self.job_dir(identifier) / "job.json", job)
                    except Exception:
                        LOGGER.exception("Не удалось сохранить закрытие задания %s", identifier)
                    finally:
                        try:
                            child.close()
                        except Exception:
                            LOGGER.exception("Не удалось закрыть ресурсы задания %s", identifier)
                        finally:
                            self.active = None
            finally:
                pass
        # Finishing worker cleanup acquires manager.mutex, so join only
        # after releasing the lock held above.
        from .studio_render import stop_finishing_tasks
        if not stop_finishing_tasks(self, timeout=12):
            # Keep exclusive server ownership until the old process tree and
            # durable terminal state have been reconciled. close() may retry.
            LOGGER.warning("Не все экспорты завершились при закрытии; блокировка приложения сохранена")
            return False
        self.lock.close()
        self._resources_closed = True
        return True
