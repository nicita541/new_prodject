"""Separate developer MCP registry: inspection + explicit bounded local tasks."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from app.mcp_contract import ID, OP, TEXT, LIMIT, OFFSET, MCPError, Registry, ReplayJournal, page, resolve_under
from app.content_identity import digest
from app.run_logging import scrub
from app.studio_identity import backend_fingerprint
from devtools.mcp_readers import Readers
from devtools.mcp_tasks import Tasks, CHECKS

PAGING = {'offset': (OFFSET, 0), 'limit': (LIMIT, 30)}
JOB = {'job_id': (ID, ...)}
CURSOR = {'cursor': (Annotated[int, Field(ge=0)], 0), 'limit': (LIMIT, 30)}


class Development:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.readers, self.tasks = Readers(root), Tasks(root)
        self.journal = ReplayJournal(self.root / 'temp/mcp-operations', root=self.root)
        self.registry = Registry('kadr_dev_', self.journal)
        self._register()

    async def close(self):
        await self.journal.drain()
        await self.tasks.close()

    def _register(self):
        add = self.registry.add
        add('get_operation', 'Inspect development replay journal; never relaunch an uncertain task.', {'operation_id': (OP, ...)}, self.journal.inspect)
        add('get_architecture', 'Read the actual architecture/ownership documents.', {'document': (Literal['app/README.md', 'docs/ai/architecture.md', 'docs/audit/storage-and-modules.md'], 'app/README.md'), **PAGING}, self.architecture)
        for name, docs in [('search_code', False), ('search_docs', True), ('find_owner', True)]:
            async def search(query, offset=0, limit=30, docs=docs):
                return await asyncio.to_thread(self.readers.search, query, docs, offset, limit)
            add(name, 'Literal case-insensitive bounded search; paths and line numbers, no shell.', {'query': (TEXT, ...), **PAGING}, search)
        for name, callers in [('find_symbol', False), ('get_callers', True)]:
            async def symbols(symbol, offset=0, limit=30, callers=callers):
                return await asyncio.to_thread(self.readers.symbols, symbol, callers, offset, limit)
            add(name, 'Static Python AST lookup; dynamic/aliased coverage explicitly limited.', {'symbol': (TEXT, ...), **PAGING}, symbols)
        add('get_decision', 'Read an architecture decision by its actual filename.', {'filename': (TEXT, ...), **PAGING}, self.decision)
        add('get_log_tail', 'Read bounded worker log tail without changing the job.', JOB | {'lines': (LIMIT, 30)}, self.log_tail)
        add('get_stage_events', 'Read pipeline JSONL with byte cursor and optional stage filter.', JOB | CURSOR | {'stage': (TEXT | None, None)}, self.events)
        add('get_ui_diagnostics', 'Read recorded browser diagnostics; no job attribution is invented.', CURSOR | {'process_id': (OFFSET | None, None)}, self.ui_diagnostics)
        add('get_error_report', 'Report saved error and actual traceback/event evidence; no guessed cause.', JOB, self.error_report)
        add('inspect_checkpoint', 'List actual checkpoints or read a named allowlisted artifact; never repair it.', JOB | {'artifact': (TEXT, 'catalog'), **PAGING}, self.checkpoint)
        add('compare_identities', 'Explain differences between supplied identities; no cache mutation.', {'actual': (dict, ...), 'expected': (dict, ...)}, self.compare_identities)
        add('list_model_requests', 'Index persisted manual packets or real local model timing records.', JOB | PAGING | {'source': (Literal['packets', 'local'], 'packets'), 'cursor': (Annotated[int, Field(ge=0)], 0)}, self.requests)
        add('get_model_request', 'Read redacted packet artifact or local timing records; absent prompts remain absent.', JOB | {'request_id': (TEXT, ...), 'artifact': (Literal['request.json', 'result.json', 'schema.json', 'failure.json', 'reception.json'], 'request.json'), 'source': (Literal['packets', 'local'], 'packets'), 'cursor': (Annotated[int, Field(ge=0)], 0), **PAGING}, self.request)
        add('get_metrics', 'Read actual saved timings/performance/tokens; unknown values remain null.', JOB | CURSOR | {'token_cursor': (Annotated[int, Field(ge=0)], 0)}, self.metrics)
        add('compare_runs', 'Compare measured stage durations from two jobs.', {'job_id': (ID, ...), 'other_job_id': (ID, ...)}, self.compare_runs)
        for name in ('trace_source_unit', 'get_evidence', 'explain_selection'):
            async def trace(job_id, unit_id, offset=0, limit=30):
                return await asyncio.to_thread(self.readers.trace, job_id, unit_id, offset, limit)
            add(name, 'Find actual persisted ID evidence/selection/cuts; explicitly reports absent links.', JOB | {'unit_id': (TEXT, ...), **PAGING}, trace)
        add('validate_artifact', 'Run existing pure analysis/plan validator; no inference/recovery.', JOB | {'artifact': (Literal['analysis.json', 'analysis-final.json', 'plan.json'], ...)}, self.validate)
        add('list_checks', 'List the fixed local validation whitelist.', {}, self.checks)
        add('run_check', 'Start an isolated allowlisted check and return task ID. Disconnect cancels its child tree.',
            {'check': (Literal[tuple(CHECKS)], ...), 'timeout_seconds': (Annotated[int, Field(ge=1, le=900)], 300)}, self.run_check, mutating=True)
        add('get_check_result', 'Read an isolated check state and paged stdout/exit code.', {'task_id': (ID, ...), **PAGING}, self.tasks.result)
        add('cancel_check', 'Cancel only a development child tree owned by this MCP session.', {'task_id': (ID, ...)}, self.tasks.cancel, mutating=True)
        add('prepare_benchmark', 'Prepare a real 120/180s local benchmark from a registered workspace source. Requires closed Studio.',
            {'source_id': (ID, ...), 'start_seconds': (Annotated[float, Field(ge=0, le=86400)], 0.0), 'duration': (Literal[120, 180], 120)}, self.prepare_benchmark, mutating=True)
        add('start_benchmark', 'Start prepared local benchmark, isolated from product jobs; closed Studio resource lease required.',
            {'benchmark_id': (ID, ...), 'timeout_seconds': (Annotated[int, Field(ge=1, le=1800)], 1800)}, self.start_benchmark, mutating=True)
        add('get_benchmark', 'Read benchmark preparation/result state; no rerun.', {'benchmark_id': (ID, ...), **PAGING}, self.benchmark)
        add('get_workspace_status', 'Read Git branch/SHA/changed paths and on-disk backend fingerprint.', {}, self.workspace_status)
        add('get_diff', 'Read bounded redacted diff of a tracked allowlisted source/doc; no arbitrary Git options.',
            {'path': (TEXT, ...), 'base': (Literal['main', 'HEAD'], 'main'), **PAGING}, self.diff)

    async def architecture(self, document='app/README.md', offset=0, limit=30):
        return self.readers.document(document, offset, limit)

    async def decision(self, filename, offset=0, limit=30):
        path = 'docs/ai/decisions/' + filename
        return self.readers.document(path, offset, limit)

    async def log_tail(self, job_id, lines=30):
        path = resolve_under(self.readers.job(job_id), 'worker.log')
        if not path.is_file(): return {'available': False, 'lines': []}
        with path.open('rb') as stream:
            size = path.stat().st_size
            stream.seek(max(0, size - 128 * 1024))
            rows = scrub(stream.read(128 * 1024).decode('utf-8', errors='replace'), limit=128 * 1024).splitlines()
        return {'available': True, 'lines': rows[-lines:], 'tail_bytes': min(size, 128 * 1024)}

    async def events(self, job_id, cursor=0, limit=30, stage=None):
        return self.readers.jsonl(resolve_under(self.readers.job(job_id), 'diagnostics/pipeline/timeline.jsonl'), cursor, limit, stage)

    async def ui_diagnostics(self, cursor=0, limit=30, process_id=None):
        pointer = resolve_under(self.root, 'logs/LATEST.txt')
        if not pointer.is_file(): return {'available': False, 'message': 'Нет указателя текущего журнала Studio'}
        directory = resolve_under(self.root, pointer.read_text('utf-8-sig').strip())
        if not directory.is_relative_to(resolve_under(self.root, 'logs/studio')):
            return {'available': False, 'message': 'Последний журнал относится к тестам, а не Studio'}
        paths = sorted(directory.glob('events-*.jsonl'))
        if not paths: return {'available': False, 'message': 'Журнал событий не найден'}
        session = self.readers.json(directory / 'session.json') or {}
        identifier = process_id or session.get('created_by_pid')
        if type(identifier) is not int or not 0 < identifier <= 4294967295:
            return {'available': False, 'streams': [p.name for p in paths], 'message': 'Нет корректного PID создателя журнала; укажите process_id'}
        selected = directory / f"events-{identifier}.jsonl"
        return {**self.readers.jsonl(resolve_under(self.root, selected), cursor, limit, 'browser'),
                'streams': [p.name for p in paths],
                'job_attribution': 'Browser records may not contain job IDs; not inferred from the current screen'}

    async def error_report(self, job_id):
        job = self.readers.artifact(job_id, 'job.json')
        return {'job_id': job_id, 'saved_error': job.get('error'), 'saved_details': job.get('error_details'),
            'status': job.get('status'), 'stage': job.get('stage'), 'worker_tail': await self.log_tail(job_id, 30),
            'cause': 'Only saved error/traceback evidence; root cause has not been independently verified'}

    async def checkpoint(self, job_id, artifact='catalog', offset=0, limit=30):
        if artifact == 'catalog': return self.readers.checkpoints(job_id, offset, limit)
        value = self.readers.artifact(job_id, artifact)
        entries = [{'field': k, 'value': v} for k, v in value.items()] if isinstance(value, dict) else value if isinstance(value, list) else []
        return {'available': value is not None, 'artifact': artifact, 'identity': digest(value) if value is not None else None, **page(entries, offset, limit)}

    async def compare_identities(self, actual, expected):
        differences = []
        def visit(a, b, pointer=''):
            if isinstance(a, dict) and isinstance(b, dict):
                for k in sorted(a.keys() | b.keys()):
                    if k not in a or k not in b: differences.append({'field': pointer + '/' + k, 'actual': a.get(k), 'expected': b.get(k), 'missing': k not in a or k not in b})
                    else: visit(a[k], b[k], pointer + '/' + k)
            elif a != b: differences.append({'field': pointer, 'actual': a, 'expected': b})
        visit(actual, expected)
        return {'matches': not differences, 'differences': differences[:100], 'truncated': len(differences) > 100}

    async def requests(self, job_id, offset=0, limit=30, source='packets', cursor=0):
        if source == 'local':
            return {**self.readers.jsonl(self.readers.job(job_id) / 'model-performance.jsonl', cursor, limit),
                    'coverage': 'Measured request/startup records; raw local prompts/responses are not persisted here'}
        return {**page(self.readers.packets(job_id), offset, limit),
                'coverage': 'Persisted Antigravity packets; local/deepseek prompt bodies are not saved by token accounting; use get_metrics for measured calls'}

    async def request(self, job_id, request_id, artifact='request.json', offset=0, limit=30, source='packets', cursor=0):
        if source == 'local':
            value = self.readers.jsonl(self.readers.job(job_id) / 'model-performance.jsonl', cursor, 100)
            records = [item for item in value['items'] if isinstance(item['record'], dict) and item['record'].get('id') == request_id]
            return {**value, 'items': records[:limit], 'prompt_available': False, 'response_available': False,
                    'note': 'Continue with next_cursor when the request has not appeared in this page'}
        return self.readers.packet(job_id, request_id, artifact, offset, limit)

    async def metrics(self, job_id, cursor=0, limit=30, token_cursor=0):
        directory = self.readers.job(job_id)
        timings = self.readers.artifact(job_id, 'timings.json')
        if isinstance(timings, dict):
            timings = {k: v for k, v in timings.items() if k in {'run_id', 'status', 'elapsed_seconds',
                'stages_seconds', 'started_at', 'finished_at', 'error_type', 'render_workers', 'identity'}}
        tokens = resolve_under(self.root, directory / 'token-usage.jsonl')
        summary = None
        if tokens.is_file() and tokens.stat().st_size <= 32 * 1024 * 1024:
            from app.token_usage import summary as token_summary
            summary = token_summary(directory)
        return {'timings': timings,
            'performance': self.readers.jsonl(directory / 'model-performance.jsonl', cursor, limit),
            'tokens': self.readers.jsonl(tokens, token_cursor, limit), 'token_summary': summary,
            'resource_measurements': None, 'note': 'No CPU/GPU load is estimated from elapsed time'}

    async def compare_runs(self, job_id, other_job_id):
        a = self.readers.artifact(job_id, 'timings.json') or {}
        b = self.readers.artifact(other_job_id, 'timings.json') or {}
        left, right = a.get('stages_seconds', {}), b.get('stages_seconds', {})
        return {'jobs': [job_id, other_job_id], 'stages': [{'stage': k, 'seconds': left.get(k),
            'other_seconds': right.get(k), 'difference_seconds': left[k] - right[k] if k in left and k in right else None}
            for k in sorted(left.keys() | right.keys())], 'same_inputs': a.get('identity') == b.get('identity') if a.get('identity') and b.get('identity') else None}

    async def validate(self, job_id, artifact):
        from app.planner import validate_analysis, validate_plan
        value = self.readers.artifact(job_id, artifact)
        if value is None: raise MCPError('not_found', 'Артефакт не найден')
        try:
            if artifact == 'plan.json':
                analysis = self.readers.artifact(job_id, 'analysis.json')
                if analysis is None: raise MCPError('not_found', 'Для проверки плана отсутствует analysis.json')
                validate_plan(value, analysis)
            else: validate_analysis(value)
        except (ValueError, AssertionError, TypeError, KeyError) as error:
            return {'valid': False, 'artifact': artifact, 'violations': [str(error)], 'validator': 'app.planner'}
        return {'valid': True, 'artifact': artifact, 'validator': 'app.planner', 'scope': 'Pure schema/timing/plan invariants; no model-based quality inference'}

    async def checks(self):
        return {'checks': [{'id': k, 'description': v[0]} for k, v in CHECKS.items()]}

    async def run_check(self, check, timeout_seconds=300):
        return await self.tasks.submit({'kind': 'check', 'check': check}, timeout_seconds)

    async def prepare_benchmark(self, source_id, start_seconds=0.0, duration=120):
        # Registry is read directly; do not construct JobManager/migrate library.
        registry = self.readers.json(resolve_under(self.root, 'data/sources.json')) or {}
        source = registry.get(source_id)
        if not source: raise MCPError('not_found', 'Зарегистрированный источник не найден')
        source_path = source.get('path')
        if not isinstance(source_path, str): raise MCPError('invalid_source', 'У источника отсутствует проверенный путь')
        path = resolve_under(self.root, source_path)
        identifier = str(uuid.uuid4())
        spec = {'kind': 'benchmark', 'benchmark_id': identifier, 'source': str(path),
            'duration': duration, 'start_seconds': start_seconds, 'timeout_seconds': 1800, 'prepare_only': True}
        result = await self.tasks.submit(spec, 300)
        directory = resolve_under(self.root, 'temp/mcp-benchmarks/' + identifier)
        directory.mkdir(exist_ok=True, parents=True)
        from app.json_store import atomic_json
        atomic_json(directory / 'mcp.json', {'specification': spec, 'preparation_task_id': result['task_id']})
        return {'benchmark_id': identifier, 'task': result}

    async def start_benchmark(self, benchmark_id, timeout_seconds=1800):
        directory = resolve_under(self.root, 'temp/mcp-benchmarks/' + benchmark_id)
        record = self.readers.json(directory / 'mcp.json')
        if not record: raise MCPError('not_found', 'Benchmark не подготовлен')
        if record.get('run_task_id'): raise MCPError('already_started', 'Этот benchmark уже запускался; прочитайте его результат')
        preparation = await self.tasks.result(record['preparation_task_id'])
        if preparation['state']['status'] != 'completed': raise MCPError('not_ready', 'Подготовка benchmark не завершена успешно')
        spec = {**record['specification'], 'prepare_only': False, 'timeout_seconds': timeout_seconds}
        result = await self.tasks.submit(spec, timeout_seconds + 30)
        from app.json_store import atomic_json
        atomic_json(directory / 'mcp.json', {**record, 'run_task_id': result['task_id']})
        return {'benchmark_id': benchmark_id, 'task': result}

    async def benchmark(self, benchmark_id, offset=0, limit=30):
        directory = resolve_under(self.root, 'temp/mcp-benchmarks/' + benchmark_id)
        record = self.readers.json(directory / 'mcp.json')
        if not record: raise MCPError('not_found', 'Benchmark не найден')
        task = await self.tasks.result(record.get('run_task_id', record['preparation_task_id']), offset, limit)
        return {'benchmark_id': benchmark_id, 'task': task, 'results': self.readers.json(directory / 'fresh-results.json')}

    async def git(self, arguments):
        def execute():
            result = subprocess.run(['git', '--no-pager', *arguments], cwd=self.root,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name == 'nt' else 0)
            if result.returncode: raise MCPError('git_error', 'Команда чтения Git завершилась ошибкой')
            if len(result.stdout) > 3 * 1024 * 1024: raise MCPError('result_too_large', 'Git diff слишком велик; выберите меньший файл')
            return result.stdout.decode('utf-8', errors='replace')
        return await asyncio.to_thread(execute)

    async def workspace_status(self):
        return {'branch': (await self.git(['branch', '--show-current'])).strip(),
            'sha': (await self.git(['rev-parse', 'HEAD'])).strip(),
            'changed_files': (await self.git(['status', '--short', '--untracked-files=no'])).splitlines()[:100],
            'on_disk_backend': backend_fingerprint()}

    async def diff(self, path, base='main', offset=0, limit=30):
        candidate = resolve_under(self.root, path)
        approved = self.readers.source_files() + self.readers.source_files(True) + [self.root / 'app/README.md']
        if candidate not in approved: raise MCPError('path_denied', 'Diff разрешён только для кода/документации из whitelist')
        result = await self.git(['diff', '--no-ext-diff', '--no-textconv', base, '--', candidate.relative_to(self.root).as_posix()])
        return page(result.splitlines(), offset, limit)
