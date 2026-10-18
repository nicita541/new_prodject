"""One pipeline execution per process; all model memory dies with this process."""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from app import config
from app.json_store import atomic_json, now, read_json
from app.jobs import contained, validate_id


class WorkerHeartbeat:
    """Process liveness only; never rewrites progress or user job state."""
    def __init__(self, directory: Path, attempt_id: str | None, *, interval=2.0):
        self.directory = directory
        self.attempt_id = attempt_id
        self.interval = interval
        self.sequence = 0
        self.stopped = threading.Event()
        self.thread = None
        self.failed = False

    def _publish(self):
        self.sequence += 1
        try:
            atomic_json(self.directory / "worker-heartbeat.json", {
                "version": 1, "attempt_id": self.attempt_id, "pid": os.getpid(),
                "sequence": self.sequence, "heartbeat_at": now()})
        except OSError:
            # A transient full disk/lock must not change an inference outcome.
            if not self.failed:
                logging.getLogger("app.worker").warning("Не удалось сохранить heartbeat задания",
                    extra={"job_id": self.directory.name, "run_id": self.attempt_id,
                           "action": "worker_heartbeat_write_failed"})
            self.failed = True
        else:
            self.failed = False

    def start(self):
        # Legacy standalone worker fixtures can lack an attempt ID. Production
        # JobManager creates a new one before every owned process starts.
        try:
            if not isinstance(self.attempt_id, str) or uuid.UUID(self.attempt_id).hex != self.attempt_id:
                return
        except ValueError:
            return
        self._publish()
        self.thread = threading.Thread(target=self._run, daemon=True, name="worker-heartbeat")
        self.thread.start()

    def _run(self):
        while not self.stopped.wait(self.interval):
            self._publish()

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    config.setup_environment()
    from app.run_logging import configure_logging
    configure_logging("studio")
    logger = logging.getLogger("app.worker")
    directory = contained(config.JOBS / validate_id(args.job), config.JOBS)
    # Parent assigns our process to its Windows Job Object before opening gate.
    for _ in range(300):
        if (directory / ".start").exists():
            break
        time.sleep(0.1)
    else:
        return 2
    def cancelled():
        return (directory / ".cancel").exists()
    def save(**changes):
        job = read_json(directory / "job.json")
        job.update(changes, updated_at=now())
        atomic_json(directory / "job.json", job)
    def report(stage: str, progress: float, message: str):
        if cancelled():
            raise InterruptedError("Обработка отменена")
        value = max(0.0, min(1.0, float(progress)))
        save(stage=stage, progress=value, message=message, progress_updated_at=now())
        logger.info("Pipeline progress: %s %.1f%% %s", stage, value * 100, message,
                    extra={"job_id": directory.name, "stage": stage,
                           "progress": round(value, 4), "action": "progress"})
    from app.antigravity_exchange import AnalysisPending
    runner = None
    heartbeat = WorkerHeartbeat(directory, read_json(directory / "job.json", {}).get("attempt_id"))
    try:
        heartbeat.start()
        selected_provider = read_json(directory / 'analysis-settings.json', {}).get('provider',
                            read_json(directory / 'job.json', {}).get('analysis_provider', 'local'))
        manual_provider = selected_provider == 'antigravity_manual'
        if manual_provider and read_json(directory / 'antigravity' / 'automation.json', {}).get('enabled'):
            atomic_json(directory / 'antigravity' / 'exchange.json', {'status': 'preparing', 'updated_at': now()})
        logger.info("Worker started", extra={"job_id": directory.name, "action": "job_start"})
        from app.antigravity_runner import ManagedRunner
        runner = ManagedRunner(directory,cancelled)
        runner.start()
        if manual_provider and read_json(directory/'antigravity/automation.json', {}).get('managed') is True:
            from app.antigravity_quota import wait_for_quota, QuotaRecoveryBlocked
            try:
                wait_for_quota(directory, cancelled)
            except QuotaRecoveryBlocked as error:
                raise AnalysisPending(str(error)) from error
        from app.pipeline import run_job
        outputs = run_job(directory, report, cancelled)
        if cancelled():
            raise InterruptedError("Обработка отменена")
        for name in outputs:
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Недопустимое имя результата")
            if not contained(directory / "output" / name, directory / "output").is_file():
                raise ValueError("Готовый результат отсутствует")
        response = read_json(directory/'feedback-result.json', {})
        processing = read_json(directory/'processing-settings.json', {})
        message = response.get('reply') if response.get('status') == 'completed' else (
            'План готов. Видео не экспортировалось.' if processing.get('mode') == 'plan_only' else 'Шортсы готовы')
        save(status="completed", stage="completed", progress=1.0, outputs=outputs,
             message=message, error=None)
        logger.info("Worker completed", extra={"job_id": directory.name, "action": "job_complete",
                                                "status": "completed"})
        return 0
    except AnalysisPending as pending:
        stage = read_json(directory / 'job.json').get('stage', 'analyze')
        save(status="waiting_analysis", stage=stage, waiting_stage=stage, error=None,
             message=str(pending), cancel_requested=False)
        logger.info("Manual analysis pending", extra={"job_id": directory.name,
                    "action": "manual_analysis_wait", "status": "waiting_analysis"})
        return 0
    except InterruptedError:
        logger.warning("Worker cancelled", extra={"job_id": directory.name, "action": "job_cancel",
                                                  "status": "cancelled"})
        save(status="cancelled", cancel_requested=True, error=None, message="Обработка отменена")
        return 0
    except Exception as error:
        logger.exception("Worker failed", extra={"job_id": directory.name, "action": "job_failure",
                                                 "status": "failed"})
        save(status="failed", error=str(error), message="Обработка завершилась с ошибкой")
        return 1
    finally:
        if runner is not None:
            try:
                runner.close()
            except Exception:
                logger.exception('Не удалось завершить собственный процесс обмена Antigravity')
        heartbeat.close()


if __name__ == "__main__":
    raise SystemExit(main())
