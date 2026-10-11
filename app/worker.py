"""One pipeline execution per process; all model memory dies with this process."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from app import config
from app.jobs import atomic_json, contained, now, read_json, validate_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    config.setup_environment()
    from app.run_logging import configure_logging
    import logging
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
        save(stage=stage, progress=value, message=message)
        logger.info("Pipeline progress: %s %.1f%% %s", stage, value * 100, message,
                    extra={"job_id": directory.name, "stage": stage,
                           "progress": round(value, 4), "action": "progress"})
    from app.antigravity_exchange import AnalysisPending
    try:
        if read_json(directory / 'antigravity' / 'automation.json', {}).get('enabled'):
            atomic_json(directory / 'antigravity' / 'exchange.json', {'status': 'preparing', 'updated_at': now()})
        logger.info("Worker started", extra={"job_id": directory.name, "action": "job_start"})
        from app.pipeline import run_job
        outputs = run_job(directory, report, cancelled)
        if cancelled():
            raise InterruptedError("Обработка отменена")
        for name in outputs:
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Недопустимое имя результата")
            if not contained(directory / "output" / name, directory / "output").is_file():
                raise ValueError("Готовый результат отсутствует")
        save(status="completed", stage="completed", progress=1.0, outputs=outputs,
             message="Шортсы готовы", error=None)
        logger.info("Worker completed", extra={"job_id": directory.name, "action": "job_complete",
                                                "status": "completed"})
        return 0
    except AnalysisPending as pending:
        stage = read_json(directory / 'job.json').get('stage', 'waiting_analysis') if read_json(
            directory / 'antigravity/automation.json', {}).get('enabled') else 'waiting_analysis'
        save(status="waiting_analysis", stage=stage, error=None,
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


if __name__ == "__main__":
    raise SystemExit(main())
