"""Observe an owned local job and record actual stage transitions without secrets."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import JOBS
from app.jobs import atomic_json, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    args = parser.parse_args()
    job = JOBS/str(args.job)
    started = time.monotonic()
    observations = []
    last = None
    while True:
        try:
            state = json.loads((job/'job.json').read_text('utf-8'))
        except (OSError, ValueError):
            time.sleep(1)
            continue
        current = (state['status'], state['stage'], state['message'])
        if current != last:
            elapsed = round(time.monotonic()-started, 3)
            observations.append({'observed_at': now(), 'elapsed_seconds': elapsed,
                                 'status': current[0], 'stage': current[1], 'message': current[2]})
            print(f'{elapsed:.1f}s | {current[0]} | {current[1]} | {current[2]}', flush=True)
            last = current
            directory = job/'qa'
            directory.mkdir(exist_ok=True)
            atomic_json(directory/'runtime-observation.json', {'job':str(args.job),
                'note':'Observer started after job dispatch; factual audio/ASR reuse is recorded in review-origin.json.',
                'observations':observations})
        if state['status'] in ('completed','failed','cancelled','interrupted'):
            break
        time.sleep(3)


if __name__ == '__main__':
    main()
