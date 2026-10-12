"""Whitelist development tasks, isolated output and existing process-tree ownership."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

from app.jobs import WorkerProcess, InstanceLock, BusyError
from app.json_store import atomic_json
from app.mcp_contract import MCPError, resolve_under
from devtools.mcp_readers import Readers

CHECKS = {
    'python': ('Python regression suite', ['python', '-m', 'pytest', '-q', 'tests']),
    'mcp': ('MCP integration and security tests', ['python', '-m', 'pytest', '-q', 'tests/test_mcp.py']),
    'studio_test': ('Studio transport/render tests', ['node', 'frontend/scripts/check-studio.mjs']),
    'studio_lint': ('Studio lint', ['node', 'frontend/scripts/check-studio.mjs', '--lint']),
}


def command(root, specification):
    if specification['kind'] == 'check':
        name = specification['check']
        if name not in CHECKS: raise ValueError('Check not allowlisted')
        parts = CHECKS[name][1]
        executable = root / ('tools/python/python.exe' if parts[0] == 'python' else 'tools/node/node.exe')
        return [str(executable), *parts[1:]]
    if specification['kind'] == 'benchmark':
        directory = resolve_under(resolve_under(root, 'temp/mcp-benchmarks'), specification['benchmark_id'])
        source = resolve_under(root, specification['source'])
        if source.suffix.lower() not in {'.mp4', '.mkv'} or not source.is_file(): raise ValueError('Invalid registered video')
        duration = specification['duration']
        start = specification['start_seconds']
        if duration not in {120, 180} or not 0 <= start <= 86400: raise ValueError('Invalid benchmark range')
        parts = [str(root / 'tools/python/python.exe'), '-m', 'scripts.benchmark_local_pipeline',
            '--source', str(source), '--directory', str(directory), '--start-seconds', str(start),
            '--durations', str(duration), '--timeout-seconds', str(specification['timeout_seconds'])]
        if specification['prepare_only']: parts.append('--prepare-only')
        return parts
    raise ValueError('Unknown task kind')


class Tasks:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.readers = Readers(root)
        self.tasks, self.watchers = {}, set()
        self.cancelled = set()

    async def submit(self, specification, timeout_seconds):
        if len(self.tasks) >= 2:
            raise MCPError('checks_busy', 'Уже выполняются две проверки этого MCP-сеанса')
        # Validate executable and all supplied paths before creating any files.
        command(self.root, specification)
        identifier = str(uuid.uuid4())
        directory = resolve_under(self.root, 'temp/mcp-tasks/' + identifier)
        lease = None
        if specification['kind'] == 'benchmark':
            # This OS lock is the exact lock acquired by JobManager at startup.
            # No race between a running benchmark and starting Studio.
            try: lease = InstanceLock(resolve_under(self.root, 'data/.server.lock'))
            except BusyError:
                raise MCPError('backend_busy', 'Короткий benchmark запускается при закрытом Studio, чтобы не конкурировать с продуктовым worker. MCP не останавливает Studio автоматически') from None
        try:
            directory.mkdir(parents=True)
            atomic_json(directory / 'specification.json', specification)
            worker = WorkerProcess(directory, command=[str(self.root / 'tools/python/python.exe'),
                '-m', 'devtools.task_worker', '--directory', str(directory)])
        except BaseException:
            if lease: lease.close()
            raise
        self.tasks[identifier] = (worker, lease)
        state = {'task_id': identifier, 'status': 'running', 'specification': specification,
                 'timeout_seconds': timeout_seconds}
        atomic_json(directory / 'state.json', state)
        watcher = asyncio.create_task(self._watch(identifier, state, timeout_seconds))
        self.watchers.add(watcher)
        watcher.add_done_callback(self.watchers.discard)
        return state

    async def _watch(self, identifier, state, timeout):
        worker, lease = self.tasks[identifier]
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while worker.poll() is None:
                if asyncio.get_running_loop().time() >= deadline:
                    worker.terminate_tree()
                    state.update(status='timed_out', exit_code=worker.poll())
                    break
                await asyncio.sleep(.25)
            else:
                state.update(status='cancelled' if identifier in self.cancelled else
                    'completed' if worker.poll() == 0 else 'failed', exit_code=worker.poll())
        except asyncio.CancelledError:
            worker.terminate_tree()
            state.update(status='cancelled', exit_code=worker.poll())
            raise
        finally:
            worker.close()
            if lease: lease.close()
            self.tasks.pop(identifier, None)
            self.cancelled.discard(identifier)
            atomic_json(self.root / 'temp/mcp-tasks' / identifier / 'state.json', state)

    async def close(self):
        for watcher in list(self.watchers): watcher.cancel()
        await asyncio.gather(*self.watchers, return_exceptions=True)

    async def result(self, task_id, offset=0, limit=30):
        directory = resolve_under(self.root, 'temp/mcp-tasks/' + task_id)
        state = self.readers.json(directory / 'state.json')
        if state is None: raise MCPError('not_found', 'Проверка не найдена')
        if state['status'] == 'running' and task_id not in self.tasks:
            state = {**state, 'status': 'interrupted', 'message': 'Задача принадлежала завершившемуся MCP-сеансу; автоматический повтор не выполняется'}
        return {'state': state, 'log': self.readers.text(directory / 'worker.log', offset, limit)}

    async def cancel(self, task_id):
        task = self.tasks.get(task_id)
        if task is None: raise MCPError('not_running', 'Нет активной проверки этого MCP-сеанса')
        self.cancelled.add(task_id)
        task[0].terminate_tree()
        return {'task_id': task_id, 'cancel_requested': True}
