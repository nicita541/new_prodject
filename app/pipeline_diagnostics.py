"""Append-only source decision audit, independent of model/checkpoint storage."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time
import uuid

from .media_probe import atomic_json, load_json


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()
                if not re.search(r'api.?key|token|password|secret|authorization', str(k), re.I)}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'(?i)(Bearer\s+|sk-)[A-Za-z0-9_.-]+', '[redacted]', value)
    return value


class Diagnostics:
    def __init__(self, job_dir: Path):
        self.path = Path(job_dir) / 'diagnostics' / 'pipeline'
        self.path.mkdir(parents=True, exist_ok=True)
        run_path = self.path / 'run.json'
        self.run_id = load_json(run_path).get('run_id') if run_path.exists() else uuid.uuid4().hex
        if not run_path.exists():
            self.write('run.json', {'run_id': self.run_id, 'status': 'analysis'})

    def write(self, name, value):
        atomic_json(self.path / name, _clean(value))

    def append(self, name, value):
        record = {'time': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                  'run_id': self.run_id, **_clean(value)}
        with (self.path / name).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')

    def event(self, stage, action, **fields):
        self.append('timeline.jsonl', {'stage': stage, 'action': action, **fields})

    def start(self, **fields):
        self.run_id = uuid.uuid4().hex
        self.write('run.json', {'run_id': self.run_id, 'status': 'running', **fields})
        self.write('summary.json', {})
        self.write('warnings.json', [])
        self.event('pipeline', 'start', **fields)

    @contextmanager
    def stage(self, stage, **fields):
        started = time.monotonic()
        self.event(stage, 'start', **fields)
        try:
            yield
        except Exception as error:
            self.event(stage, 'exception', error_type=type(error).__name__, error=str(error), **fields)
            raise
        finally:
            self.event(stage, 'end', elapsed_seconds=round(time.monotonic() - started, 6), **fields)

    def summary(self, **fields):
        target = self.path / 'summary.json'
        current = load_json(target) if target.exists() else {}
        self.write('summary.json', {**current, **fields})

    def warning(self, stage, reason, **fields):
        target = self.path / 'warnings.json'
        current = load_json(target) if target.exists() else []
        record = {'run_id': self.run_id, 'stage': stage, 'reason': reason, **fields}
        self.write('warnings.json', [*current, record])
        self.event(stage, 'warning', reason=reason, **fields)
