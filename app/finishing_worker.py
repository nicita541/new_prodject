"""One immutable finishing command per process, without a JobManager or models."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import threading
import time
import uuid


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ('root', 'operation', 'attempt', 'directory'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    root, directory = Path(args.root).resolve(), Path(args.directory).resolve()
    if (not directory.is_relative_to(root) or directory == root
            or str(uuid.UUID(args.operation)) != args.operation
            or uuid.UUID(args.attempt).hex != args.attempt):
        raise ValueError('Invalid finishing process owner')
    # No application/render imports or descendants until the parent assigns its
    # owned process tree and opens the gate.
    for _ in range(300):
        if (directory/'.start').is_file():
            break
        time.sleep(.1)
    else:
        return 2
    from app.finishing_commands import FinishingCommands, StaleAttempt
    from app.json_store import atomic_json, now
    store = FinishingCommands(root)
    command = store.load(args.operation)
    if command is None:
        raise ValueError('Unknown finishing command')
    task = store.task_directory(command['job_id'], command['kind'], command['task_id'])
    if store._owned(task/'attempts'/args.attempt) != directory:
        raise ValueError('Finishing process directory differs from command owner')
    stopped = threading.Event()

    def cancelled():
        if (directory/'.cancel').exists() or (directory/'.interrupt').exists():
            return True
        _, state = store._runtime(command)
        return not state or state['attempt_id'] != args.attempt or state['status'] != 'running'

    def details(phase, message, error=None):
        atomic_json(store._owned(directory/'progress.json'), {
            'attempt_id': args.attempt, 'command_hash': command['command_hash'],
            'phase': phase, 'message': message, 'error': error, 'updated_at': now()})

    def report(stage, progress, message):
        if stage == 'completed':
            _, state = store._runtime(command)
            if state and state['attempt_id'] == args.attempt and state['status'] == 'completed':
                details(stage, message)
                return
            raise InterruptedError('Finishing completion belongs to another attempt')
        if cancelled():
            raise InterruptedError('Finishing cancelled or superseded')
        store.update_attempt(command, args.attempt, status='running', progress=float(progress))
        details(stage, message)

    def heartbeat():
        sequence = 0
        while not stopped.is_set():
            sequence += 1
            try:
                atomic_json(store._owned(directory/'worker-heartbeat.json'), {
                    'version': 1, 'attempt_id': args.attempt, 'pid': os.getpid(),
                    'sequence': sequence, 'heartbeat_at': now()})
            except OSError:
                pass  # A heartbeat storage error does not replace render state.
            stopped.wait(2)

    thread = threading.Thread(target=heartbeat, daemon=True, name='finishing-heartbeat')
    try:
        if cancelled():
            return 0
        thread.start()
        from app import config
        config.setup_environment()
        from app.finishing_render import render_command
        render_command(root, args.operation, args.attempt, report, cancelled)
        return 0
    except (InterruptedError, StaleAttempt):
        try:
            _, state = store._runtime(command)
            terminal = 'interrupted' if (directory/'.interrupt').exists() else 'cancelled'
            store.update_attempt(command, args.attempt, status=terminal,
                                 progress=state['progress'] if state else 0)
        except StaleAttempt:
            pass
        return 0
    except Exception as error:
        logging.getLogger(__name__).exception('Finishing worker failed')
        try:
            _, state = store._runtime(command)
            store.update_attempt(command, args.attempt, status='failed',
                                 progress=state['progress'] if state else 0)
            # API projections may expose this file. Arbitrary exception text
            # can contain source text, credentials or full private paths; the
            # traceback belongs only to the owned worker's private log.
            message = 'Не удалось создать видео. Подробности в локальном журнале экспорта.'
            details('failed', message, message)
        except StaleAttempt:
            pass
        return 1
    finally:
        stopped.set()
        if thread.ident is not None:
            thread.join(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
