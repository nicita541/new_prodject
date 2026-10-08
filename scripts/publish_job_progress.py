"""Publish read-only stage counters through an already-mounted static directory.

Usage: tools/python/python.exe scripts/publish_job_progress.py --job UUID [--once]
This helper never imports a provider, starts a worker, or edits job.json.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.pycache_prefix = str(ROOT / 'cache' / 'pycache')
for _name in ('TEMP', 'TMP', 'TMPDIR'):
    os.environ[_name] = str(ROOT / 'temp')
sys.path.insert(0, str(ROOT))
from app.job_progress import ALIASES, STEPS, _read, stage_progress

TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
STATUSES = TERMINAL | {'queued', 'running'}


def _contained(path, root):
    value = Path(path).resolve()
    if not value.is_relative_to(root.resolve()):
        raise ValueError('Presentation path must stay inside the workspace')
    return value


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)


def publish_once(job_id, *, root=ROOT):
    """Return the sanitized snapshot, or None while the job file is unreadable."""
    if not isinstance(job_id, str) or str(uuid.UUID(job_id)) != job_id:
        raise ValueError('Expected a canonical job UUID')
    root = _contained(root, ROOT)
    directory = _contained(root / 'data' / 'jobs' / job_id, root)
    job_path = _contained(directory / 'job.json', root)
    job = _read(job_path)
    if (not isinstance(job, dict) or job.get('id') != job_id
            or not isinstance(job.get('status'), str) or job['status'] not in STATUSES
            or not isinstance(job.get('stage'), str)
            or job['stage'] not in {*STEPS, *ALIASES, 'queued', 'completed'}):
        return None
    try:
        updated = job['updated_at']
        if not isinstance(updated, str) or datetime.fromisoformat(updated.replace('Z', '+00:00')).tzinfo is None:
            return None
    except (KeyError, ValueError):
        return None
    snapshot = {'version': 1, 'job_id': job_id, 'status': job['status'], 'stage': job['stage'],
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'job_updated_at': updated,
                'stage_progress': stage_progress(job, directory)}
    destination = _contained(root / 'frontend' / 'dist' / 'assets' / 'job-progress' / (job_id + '.json'), root)
    _atomic(destination, snapshot)
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, help='Canonical job UUID')
    parser.add_argument('--once', action='store_true', help='Publish one snapshot and exit')
    args = parser.parse_args(argv)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        os.environ[name] = str(ROOT / 'temp')
    os.environ['PYTHONPYCACHEPREFIX'] = str(ROOT / 'cache' / 'pycache')
    while True:
        snapshot = publish_once(args.job)
        if snapshot:
            print(json.dumps({key: snapshot[key] for key in ('job_id', 'status', 'stage')},
                             ensure_ascii=False), flush=True)
        if args.once or snapshot and snapshot['status'] in TERMINAL:
            return 0
        time.sleep(3)


if __name__ == '__main__':
    raise SystemExit(main())
