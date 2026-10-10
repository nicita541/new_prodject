"""Persistent source registry and a single, cancellable background worker."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from app import config

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
LOGGER = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # A browser/read on Windows may briefly hold the old file handle.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


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


class BusyError(RuntimeError):
    pass


class InstanceLock:
    """OS-backed lock; a crashed server automatically releases ownership."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            self.stream.close()
            raise BusyError("Приложение уже запущено в другом окне") from None

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


class WorkerProcess:
    """Own a child tree without enumerating or killing unrelated processes.

    Windows: the worker waits for a start marker before importing the pipeline;
    assign it to a kill-on-close Job Object before allowing grandchildren.
    POSIX: children share a new process group.
    """
    def __init__(self, job_dir: Path):
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
                [sys.executable, "-m", "app.worker", "--job", job_dir.name], **kwargs)
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
        self.closed = False
        self.sources = read_json(self.data / "sources.json", {})
        try:
            self._recover()
        except BaseException:
            self.lock.close()
            raise

    def _recover(self):
        for path in self.jobs.glob("*/job.json"):
            job = read_json(path)
            if job and job["status"] in {"queued", "running"}:
                job.update(status="interrupted", message="Обработка прервана. Можно продолжить.",
                           updated_at=now(), cancel_requested=False)
                atomic_json(path, job)

    def list_sources(self) -> list[dict]:
        with self.mutex:
            sources_path = self.data / "sources.json"
            on_disk = read_json(sources_path, {})
            if isinstance(on_disk, dict):
                self.sources.update(on_disk)
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
            job = read_json(path)
            if not job:
                raise KeyError(identifier)
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
            return job

    def list_jobs(self) -> list[dict]:
        return sorted((self.get(path.parent.name) for path in self.jobs.glob("*/job.json")),
                      key=lambda item: item["created_at"], reverse=True)

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

    def delete_job(self, identifier: str) -> dict:
        with self.mutex:
            validate_id(identifier)
            if self.active and self.active[0] == identifier:
                raise BusyError("Нельзя удалить выполняющееся задание")
            if self.finishing_tasks.get(identifier, 0):
                raise BusyError("Нельзя удалить задание во время предпросмотра или экспорта")
            directory = self.job_dir(identifier)
            if not directory.is_dir():
                raise KeyError(identifier)
            # Never report success if Windows locks or permissions prevent removal.
            shutil.rmtree(directory)
            self._drop_finishing_export_index(identifier)
            self.pending_states.pop(identifier, None)
            return {"id": identifier, "deleted": True}

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
                if jid == active_id or self.finishing_tasks.get(jid, 0):
                    continue
                data = read_json(path)
                if not data or data.get("status") not in TERMINAL:
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
                        shutil.rmtree(directory)
                    except OSError:
                        LOGGER.exception("Cannot prune job %s", jid)
                    else:
                        self._drop_finishing_export_index(jid)
                        pruned.append(jid)
                else:
                    remaining_jobs.append((jid, created_at, mtime, directory))

            # Prune excess count beyond max_jobs
            excess = max(0, len(remaining_jobs) - max_jobs) if max_jobs is not None else 0
            if excess > 0:
                for jid, _, _, directory in remaining_jobs[:excess]:
                    try:
                        shutil.rmtree(directory)
                    except OSError:
                        LOGGER.exception("Cannot prune job %s", jid)
                    else:
                        self._drop_finishing_export_index(jid)
                        pruned.append(jid)

            return {"pruned_count": len(pruned), "pruned_ids": pruned,
                    "remaining_terminal": len(terminal_jobs) - len(pruned)}

    def busy(self) -> bool:
        with self.mutex:
            # Keep ownership until the watcher has closed the job object/log.
            return self.active is not None

    @staticmethod
    def _check_analysis_provider(provider: str) -> None:
        if provider not in {"local", "deepseek", "hybrid", "deepseek_plan", "local_flash_story"}:
            raise ValueError("Неизвестный способ анализа")
        # Hybrid always has a local path; remote availability is evaluated
        # only when the pipeline actually needs an optional fallback.
        if provider in {"local", "hybrid"}:
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
               layout: str = "portrait", caption_style: str = "classic", episode_id: str | None = None) -> dict:
        with self.mutex:
            from .editing import validate_options
            options = validate_options(layout, caption_style)
            if episode_id is not None:
                validate_id(episode_id)
            self._assert_available()
            self._check_analysis_provider(analysis_provider)
            source = self.source(source_id)
            identifier = str(uuid.uuid4())
            directory = self.jobs / identifier
            directory.mkdir()
            atomic_json(directory / "source.json", source)
            atomic_json(directory / "analysis-settings.json", {"provider": analysis_provider})
            atomic_json(directory / "render-settings.json", options)
            job = {"id": identifier, "source_name": source["name"], "status": "queued",
                   "stage": "queued", "progress": 0.0, "message": "Ожидание запуска",
                   "created_at": now(), "updated_at": now(), "error": None,
                   "outputs": [], "cancel_requested": False, "analysis_provider": analysis_provider,
                   **options}
            if episode_id is not None:
                job['episode_id'] = episode_id
            atomic_json(directory / "job.json", job)
            return self._start(job)

    def _assert_available(self):
        if self.closed:
            raise BusyError("Приложение завершает работу")
        if self.active is not None:
            raise BusyError("Сейчас обрабатывается другая серия")
        # Finishing jobs also consume FFmpeg, CPU, memory and source files.
        # Do not start a fresh analysis while any preview/export is active.
        if any(self.finishing_tasks.values()):
            raise BusyError("Дождитесь завершения предпросмотра или экспорта")

    def _start(self, job: dict) -> dict:
        directory = self.job_dir(job["id"])
        (directory / ".cancel").unlink(missing_ok=True)
        job.update(status="running", error=None, outputs=[], cancel_requested=False,
                   message="Запуск обработки", updated_at=now())
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
        LOGGER.info("Worker process launched", extra={"job_id": job["id"],
                     "action": "worker_launched", "status": "running",
                     "detail_log": f"data/jobs/{job['id']}/worker.log"})
        threading.Thread(target=self._watch, args=(job["id"], child), daemon=True).start()
        return self.get(job["id"])

    def _watch(self, identifier: str, child):
        try:
            code = child.wait()
            LOGGER.log(logging.INFO if code == 0 else logging.ERROR,
                       "Worker exited with code %s", code,
                       extra={"job_id": identifier, "action": "worker_exit", "code": code,
                              "detail_log": f"data/jobs/{identifier}/worker.log"})
            with self.mutex:
                if self.closed or not self.active or self.active[1] is not child:
                    return
                job = self.get(identifier)
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

    def cancel(self, identifier: str) -> dict:
        with self.mutex:
            job = self.get(identifier)
            if job["status"] in TERMINAL:
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
            job = read_json(self.job_dir(identifier) / "job.json")
            if job["status"] != "completed":
                job.update(status="cancelled", cancel_requested=True, error=None,
                           message="Обработка отменена. Сохранённые этапы можно продолжить.", updated_at=now())
                try:
                    atomic_json(self.job_dir(identifier) / "job.json", job)
                except OSError:
                    self.pending_states[identifier] = dict(job)
                    LOGGER.exception("Отмена выполнена, но не удалось сохранить статус задания %s", identifier)
            return job

    def retry(self, identifier: str) -> dict:
        with self.mutex:
            self._assert_available()
            job = self.get(identifier)
            if job["status"] not in {"failed", "interrupted", "cancelled"}:
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
            if job.get('analysis_provider') in {'deepseek', 'deepseek_plan', 'hybrid', 'local_flash_story'}:
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
            if self.closed:
                return
            self.closed = True
            try:
                if self.active:
                    identifier, child = self.active
                    try:
                        child.terminate_tree()
                        job = self.get(identifier)
                        if job["status"] not in TERMINAL:
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
        try:
            from .studio_render import stop_finishing_tasks
            if not stop_finishing_tasks(self, timeout=12):
                LOGGER.warning("Не все экспорты завершились при закрытии")
        finally:
            self.lock.close()
