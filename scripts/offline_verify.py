"""Repeat a completed job with external Python connections forbidden."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import JOBS
from app.pipeline import run_job

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    args = parser.parse_args()
    directory = JOBS / str(args.job)
    state = json.loads((directory / 'job.json').read_text('utf-8'))
    if state['status'] != 'completed':
        parser.error('Wait until the job has completed')
    original = socket.socket.connect
    attempts = []
    def local_connect(sock, address):
        host = address[0]
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = host.lower() == 'localhost'
        if not allowed:
            attempts.append(str(host))
            raise OSError('External network is forbidden during offline verification')
        return original(sock, address)
    socket.socket.connect = local_connect
    started = time.monotonic()
    try:
        files = run_job(directory, lambda stage, progress, message: print(message, flush=True), lambda: False)
    finally:
        socket.socket.connect = original
    report = {'mode': 'repeat_with_validated_checkpoints', 'external_python_connections_forbidden': True,
              'runtime_offline_flags': ['HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1', 'llama.cpp --offline'],
              'blocked_external_attempts': attempts, 'elapsed_seconds': round(time.monotonic() - started, 3),
              'files': files, 'note': 'Operating-system networking was not changed; cached analysis and verified exports were reused.'}
    (directory / 'offline-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    main()
