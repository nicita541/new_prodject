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
        save(stage=stage, progress=max(0.0, min(1.0, float(progress))), message=message)
    try:
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
        return 0
    except InterruptedError:
        save(status="cancelled", cancel_requested=True, error=None, message="Обработка отменена")
        return 0
    except Exception as error:
        save(status="failed", error=str(error), message="Обработка завершилась с ошибкой")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
