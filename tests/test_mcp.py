"""Real MCP protocol plus isolated backend, replay, targeting and security checks."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
import jsonschema
import pytest

from app.content_identity import digest
from app.json_store import atomic_json
from app.mcp_contract import MCPError, ReplayJournal, redact
from app.mcp_product import Product
from app.mcp_runtime import OUTPUT_SCHEMA
from devtools.mcp_dev import Development
from devtools.mcp_readers import Readers

ROOT = Path(__file__).resolve().parents[1]
IDS = [str(uuid.uuid4()) for _ in range(6)]


def run(coro): return asyncio.run(coro)


@pytest.fixture
def backend(tmp_path):
    from app.jobs import JobManager
    from app.server import create_app
    from fastapi.testclient import TestClient
    from tests.test_jobs import FakeWorker
    manager = JobManager(tmp_path, worker_factory=FakeWorker)
    application = create_app(manager)
    lifecycle = TestClient(application, base_url='http://127.0.0.1:8765')
    lifecycle.__enter__()
    workspace = hashlib.sha256(str(tmp_path.resolve()).casefold().encode()).hexdigest()[:20]
    with patch('app.server.server_identity', return_value={'application': 'kadr-studio', 'workspace': workspace, 'backend': 'test', 'ui': 'test'}):
        product = Product(tmp_path, transport=httpx.ASGITransport(app=application), expected_backend='test')
        yield product, application, manager
        run(product.close())
        lifecycle.__exit__(None, None, None)
        manager.close()


def call(service, name, **arguments):
    result = run(service.registry.invoke(service.registry.prefix + name, arguments))
    jsonschema.validate(result, OUTPUT_SCHEMA)
    return result


def project_episode(backend):
    product, application, manager = backend
    project = call(product, 'create_project', title='Actual test project', operation_id='create-project')['data']
    episode = call(product, 'create_episode', project_id=project['id'], operation_id='create-episode')['data']['result']
    return {'project_id': project['id'], 'episode_id': episode['id']}


def test_product_create_replay_and_conflict(backend):
    product, app, manager = backend
    first = call(product, 'create_project', title='Project', operation_id='same-operation')
    again = call(product, 'create_project', title='Project', operation_id='same-operation')
    assert first == again and first['ok']
    assert len(app.state.library.data['projects']) == 1
    saved = call(product, 'get_operation', operation_id='same-operation')
    assert saved['ok'] and saved['data']['state'] == 'done'
    conflict = call(product, 'create_project', title='Other', operation_id='same-operation')
    assert conflict['error']['code'] == 'operation_conflict'
    assert call(product, 'create_project', title='Missing ID')['error']['code'] == 'invalid_arguments'


def test_settings_revision_is_checked_under_backend_owner(backend):
    product, app, manager = backend
    ids = project_episode(backend)
    video = manager.root / 'video.mp4'
    video.write_bytes(b'isolated test only; no decoder runs')
    source_id = str(uuid.uuid4())
    manager.sources[source_id] = {'path': str(video), 'name': video.name}
    values = dict(source_id=source_id, analysis_provider='local', layout='cinema', caption_style='accent')
    before = call(product, 'get_settings', **ids)['data']
    saved = call(product, 'update_settings', **ids, **values, revision=before['revision'], operation_id='save-settings')
    assert saved['ok']
    # Studio changes the same owner directly; MCP must not overwrite it.
    app.state.library.save_episode(ids['episode_id'], source_id, {k: v for k, v in values.items() if k != 'source_id'} | {'layout': 'portrait'})
    stale = call(product, 'update_settings', **ids, **values, revision=saved['data']['revision'], operation_id='stale-settings')
    assert stale['error']['details']['http_status'] == 409
    assert app.state.library._episode(ids['episode_id'])['settings']['layout'] == 'portrait'


def test_mcp_uses_existing_worker_and_validates_target(backend):
    product, app, manager = backend
    ids = project_episode(backend)
    path = manager.root / 'source.mp4'
    path.write_bytes(b'isolated')
    source_id = str(uuid.uuid4())
    manager.sources[source_id] = {'path': str(path), 'name': path.name}
    app.state.library.save_episode(ids['episode_id'], source_id, {'analysis_provider': 'local', 'layout': 'cinema', 'caption_style': 'accent'})
    with patch('app.config.readiness', return_value={'ready': True, 'missing': []}):
        first = call(product, 'start_job', **ids, operation_id='start-once')
        assert first['ok'], first
        job_id = first['data']['result']['id']
        same = call(product, 'start_job', **ids, operation_id='start-once')
        assert same == first
        assert len(manager.list_jobs()) == 1
        wrong = call(product, 'cancel_job', **ids | {'episode_id': IDS[0]}, job_id=job_id, operation_id='wrong-cancel')
        assert wrong['error']['code'] == 'ownership_mismatch'
        assert manager.busy()
        assert call(product, 'cancel_job', **ids, job_id=job_id, operation_id='right-cancel')['ok']


def test_read_only_catalog_does_not_register_video_or_create_artifacts(backend):
    product, app, manager = backend
    (manager.root / 'unregistered.mp4').write_bytes(b'not registered')
    before = {str(p.relative_to(manager.root)): p.stat().st_mtime_ns for p in manager.root.rglob('*') if p.is_file()}
    assert call(product, 'list_sources')['data']['total'] == 0
    assert call(product, 'list_projects')['ok']
    after = {str(p.relative_to(manager.root)): p.stat().st_mtime_ns for p in manager.root.rglob('*') if p.is_file()}
    assert before == after
    assert not (manager.root / 'data/mcp').exists()


@pytest.mark.parametrize('name,arguments', [
    ('get_job_status', {'project_id': '../a', 'episode_id': IDS[0], 'job_id': IDS[1]}),
    ('list_projects', {'limit': 1000}), ('list_projects', {'unknown': 1}),
    ('create_project', {'title': 'x', 'operation_id': '../escape'}),
])
def test_strict_arguments(backend, name, arguments):
    assert call(backend[0], name, **arguments)['error']['code'] == 'invalid_arguments'


def test_stale_and_wrong_backend_refuse_mutations(backend):
    product, app, manager = backend
    product.expected_backend = 'new version'
    assert call(product, 'create_project', title='x', operation_id='stale-version')['error']['code'] == 'stale_backend'
    product.expected_workspace = 'other workspace'
    assert call(product, 'get_app_status')['error']['code'] == 'wrong_backend'
    assert not app.state.library.data['projects']


@pytest.mark.parametrize('url', ['https://127.0.0.1:8765', 'http://example.com', 'http://user:pass@localhost', 'http://localhost/path', 'http://localhost?x=y'])
def test_remote_backend_not_allowed(url, tmp_path):
    with pytest.raises(ValueError): Product(tmp_path, url)


def test_backend_failure_is_specific_and_does_not_retry(tmp_path):
    calls = []
    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b'bad json')
    product = Product(tmp_path, transport=httpx.MockTransport(response))
    assert call(product, 'get_app_status')['error']['code'] == 'backend_invalid_response'
    assert calls == ['/api/studio/identity']
    run(product.close())


def test_ambiguous_replay_is_not_relaunched(tmp_path):
    journal = ReplayJournal(tmp_path / 'operations')
    calls = []
    async def action():
        calls.append(1)
        raise MCPError('backend_unavailable', 'Disconnected after dispatch')
    with pytest.raises(MCPError): run(journal.execute('operation', 'start', {}, action))
    with pytest.raises(MCPError, match='прерван'): run(journal.execute('operation', 'start', {}, action))
    assert calls == [1]


def test_cancelled_protocol_request_keeps_accepted_mutation(tmp_path):
    async def exercise():
        journal = ReplayJournal(tmp_path / 'operations')
        gate, entered = asyncio.Event(), asyncio.Event()
        async def action():
            entered.set()
            await gate.wait()
            return {'job_id': IDS[0]}
        request = asyncio.create_task(journal.execute('operation', 'start', {}, action))
        await entered.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError): await request
        gate.set()
        await journal.drain()
        assert (await journal.execute('operation', 'start', {}, action))['job_id'] == IDS[0]
    run(exercise())


def test_concurrent_clients_cannot_execute_same_operation_twice(tmp_path):
    async def exercise():
        first, second = ReplayJournal(tmp_path / 'operations'), ReplayJournal(tmp_path / 'operations')
        gate, entered = asyncio.Event(), asyncio.Event()
        count = 0
        async def action():
            nonlocal count
            count += 1
            entered.set()
            await gate.wait()
            return {'accepted': True}
        running = asyncio.create_task(first.execute('operation', 'start', {}, action))
        await entered.wait()
        with pytest.raises(MCPError, match='уже выполняется'):
            await second.execute('operation', 'start', {}, action)
        gate.set()
        assert await running == {'accepted': True}
        assert await second.execute('operation', 'start', {}, action) == {'accepted': True}
        assert count == 1
    run(exercise())


def fixture_job(tmp_path):
    directory = tmp_path / 'data/jobs' / IDS[0]
    directory.mkdir(parents=True)
    atomic_json(directory / 'job.json', {'id': IDS[0], 'status': 'failed', 'stage': 'story', 'error': 'Specific failure'})
    return directory


def test_dev_reads_are_isolated_and_do_not_create_diagnostics(tmp_path):
    directory = fixture_job(tmp_path)
    dev = Development(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))
    assert call(dev, 'get_error_report', job_id=IDS[0])['data']['saved_error'] == 'Specific failure'
    assert call(dev, 'get_stage_events', job_id=IDS[0])['data']['available'] is False
    assert call(dev, 'get_metrics', job_id=IDS[0])['data']['timings'] is None
    assert before == sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))
    assert not (directory / 'diagnostics').exists()
    run(dev.close())


def test_dev_corrupt_json_and_path_escape_are_explicit(tmp_path):
    directory = fixture_job(tmp_path)
    (directory / 'timings.json').write_text('{ broken', encoding='utf-8')
    dev = Development(tmp_path)
    assert call(dev, 'get_metrics', job_id=IDS[0])['error']['code'] == 'corrupt_json'
    assert call(dev, 'inspect_checkpoint', job_id=IDS[0], artifact='../../settings.json')['error']['code'] == 'path_denied'
    assert call(dev, 'get_decision', filename='../../private.md')['error']['code'] == 'path_denied'
    assert call(dev, 'run_check', check='powershell')['error']['code'] == 'invalid_arguments'
    run(dev.close())


def test_dev_search_and_ast_coverage(tmp_path):
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app/logic.py').write_text('def target():\n    pass\n\ndef caller():\n    return target()\n', encoding='utf-8')
    dev = Development(tmp_path)
    assert call(dev, 'search_code', query='target')['data']['total'] == 2
    assert call(dev, 'find_symbol', symbol='target')['data']['items'][0]['line'] == 1
    result = call(dev, 'get_callers', symbol='target')['data']
    assert result['items'][0]['line'] == 5 and 'dynamic' in result['coverage']
    run(dev.close())


def test_jsonl_byte_cursor_and_incomplete_row(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_bytes(b'{"stage":"a"}\n{"stage":"b"}\n{"unfinished":')
    readers = Readers(tmp_path)
    first = readers.jsonl(path, limit=1)
    second = readers.jsonl(path, first['next_cursor'], limit=1)
    assert first['items'][0]['record']['stage'] == 'a'
    assert second['items'][0]['record']['stage'] == 'b'
    third = readers.jsonl(path, second['next_cursor'])
    assert not third['items'] and third['next_cursor'] == second['next_cursor']


def test_secret_redaction_preserves_token_counts():
    value = redact({'access_token': 'sensitive', 'refresh_token': 'sensitive2', 'total_tokens': 120,
        'nested': [{'message': 'authorization=Bearer abcdefghijkl', 'api_key': 'secretvalue'}]})
    encoded = json.dumps(value)
    assert 'sensitive' not in encoded and 'abcdefghijkl' not in encoded and 'secretvalue' not in encoded
    assert value['total_tokens'] == 120


def test_packet_reader_redacts_multiline_json(tmp_path):
    directory = fixture_job(tmp_path) / 'antigravity/packets/packet'
    directory.mkdir(parents=True)
    (directory / 'request.json').write_text('{"api_key":\n"secretvalue", "purpose":"story"}', encoding='utf-8')
    dev = Development(tmp_path)
    result = call(dev, 'get_model_request', job_id=IDS[0], request_id='packet')
    assert result['ok'] and 'secretvalue' not in json.dumps(result)
    run(dev.close())


def test_benchmark_resource_lease_refuses_running_studio(tmp_path):
    from app.jobs import InstanceLock
    from devtools.mcp_tasks import Tasks
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'isolated')
    lock = InstanceLock(tmp_path / 'data/.server.lock')
    tasks = Tasks(tmp_path)
    try:
        with pytest.raises(MCPError, match='закрытом Studio'):
            run(tasks.submit({'kind': 'benchmark', 'benchmark_id': IDS[0], 'source': str(video),
                'duration': 120, 'start_seconds': 0, 'timeout_seconds': 60, 'prepare_only': True}, 60))
        assert not (tmp_path / 'temp/mcp-tasks').exists()
    finally: lock.close()


def test_finishing_captions_and_async_render_delegate_to_existing_owner(backend):
    product, app, manager = backend
    ids = project_episode(backend)
    job_id = str(uuid.uuid4())
    directory = manager.job_dir(job_id)
    directory.mkdir(parents=True)
    atomic_json(directory / 'job.json', {'id': job_id, 'episode_id': ids['episode_id'],
        'source_id': IDS[2], 'source_name': 'source.mp4', 'created_at': '2026-10-13T00:00:00Z',
        'status': 'completed', 'stage': 'completed', 'progress': 1, 'outputs': []})
    atomic_json(directory / 'plan.json', {'source': {'duration': 12}, 'parts': [
        {'index': 1, 'duration': 6, 'cuts': [{'start': 1, 'end': 7, 'focus': []}], 'subtitles': []}]})
    original = (directory / 'plan.json').read_bytes()
    target = {**ids, 'job_id': job_id}
    profile = call(product, 'get_finishing', **ids)['data']['result']
    from app.finishing import FinishProfile
    fields = FinishProfile.model_fields
    values = {k: v for k, v in profile.items() if k in fields}
    values['video']['zoom'] = 112
    saved = call(product, 'update_finishing', **ids, profile=values, revision=profile['revision'], operation_id='finish-once')
    assert saved['ok'], saved
    stale = call(product, 'update_finishing', **ids, profile=values, revision=profile['revision'], operation_id='finish-stale')
    assert stale['error']['details']['http_status'] == 409
    cues = [{'start': .2, 'end': 1.2, 'text': 'Real saved caption'}]
    assert call(product, 'update_captions', **target, part_index=1, cues=cues, revision=0, operation_id='caption-once')['ok']
    assert call(product, 'get_captions', **target, part_index=1)['data']['result']['cues'] == cues
    invalid = call(product, 'update_captions', **target, part_index=1,
        cues=[{'start': 5.0, 'end': 8.0, 'text': 'Outside part'}], revision=1, operation_id='invalid-cues')
    assert invalid['error']['details']['http_status'] == 422
    with patch('app.studio_render.submit_render', return_value={'task_id': 'accepted', 'preview_id': 'pv_' + 'a' * 32, 'status': 'queued'}) as render:
        assert call(product, 'create_preview', **target, settings={'part_index': 1, 'from': .5, 'duration': 2.0}, operation_id='preview-once')['ok']
        assert call(product, 'start_export', **target, settings={'part_indices': [1]}, operation_id='export-once')['ok']
        assert render.call_count == 2
    assert (directory / 'plan.json').read_bytes() == original


def test_restore_archive_and_invalid_import_path(backend):
    product, app, manager = backend
    ids = project_episode(backend)
    assert call(product, 'archive_episode', **ids, operation_id='archive-episode')['ok']
    assert call(product, 'restore_episode', **ids, operation_id='restore-episode')['ok']
    assert call(product, 'archive_project', project_id=ids['project_id'], operation_id='archive-project')['ok']
    assert call(product, 'restore_project', project_id=ids['project_id'], operation_id='restore-project')['ok']
    rejected = call(product, 'import_video', filename='../source.mp4', operation_id='invalid-import')
    assert rejected['error']['code'] == 'path_denied'


def test_readers_reject_symlink_escape(tmp_path):
    inside, outside = tmp_path / 'workspace', tmp_path / 'private'
    inside.mkdir()
    outside.mkdir()
    (outside / 'timings.json').write_text('{"secret":"hidden"}', encoding='utf-8')
    directory = inside / 'data/jobs' / IDS[0]
    directory.mkdir(parents=True)
    atomic_json(directory / 'job.json', {'id': IDS[0]})
    try: (directory / 'timings.json').symlink_to(outside / 'timings.json')
    except OSError: pytest.skip('Symlinks not permitted on this host')
    with pytest.raises(MCPError, match='за пределами'): Readers(inside).artifact(IDS[0], 'timings.json')


def test_checkpoint_catalog_and_local_request_index_use_actual_records(tmp_path):
    directory = fixture_job(tmp_path)
    atomic_json(directory / 'events.meta.json', {'signature': 'real-signature'})
    (directory / 'model-performance.jsonl').write_text('{"event":"request_start","id":"request1","stage":"story"}\n', encoding='utf-8')
    dev = Development(tmp_path)
    catalog = call(dev, 'inspect_checkpoint', job_id=IDS[0])['data']
    assert any(i['identity_fields'] == {'signature': 'real-signature'} for i in catalog['items'])
    indexed = call(dev, 'list_model_requests', job_id=IDS[0], source='local')['data']
    assert indexed['items'][0]['record']['id'] == 'request1'
    detail = call(dev, 'get_model_request', job_id=IDS[0], request_id='request1', source='local')['data']
    assert detail['items'] and detail['prompt_available'] is False
    run(dev.close())


def test_benchmark_first_run_is_fresh_and_within_workspace(tmp_path):
    from devtools.mcp_tasks import command
    video = tmp_path / 'source.mp4'
    video.write_bytes(b'isolated; no media run')
    args = command(tmp_path, {'kind': 'benchmark', 'benchmark_id': IDS[0], 'source': str(video),
        'duration': 120, 'start_seconds': 1.0, 'timeout_seconds': 30, 'prepare_only': False})
    assert '--resume' not in args and '--prepare-only' not in args
    assert str(tmp_path / 'temp/mcp-benchmarks' / IDS[0]) in args


@pytest.mark.parametrize('module,prefix,tool,arguments', [
    ('app.mcp_server', 'kadr_', 'kadr_list_projects', {'limit': 999}),
    ('devtools.mcp_server', 'kadr_dev_', 'kadr_dev_find_symbol', {'symbol': 'digest', 'limit': 3}),
])
def test_actual_stdio_sdk_handshake_and_tool_isolation(module, prefix, tool, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=['-B', '-m', module], cwd=ROOT,
            env={**os.environ, 'TEMP': str(ROOT / 'temp'), 'TMP': str(ROOT / 'temp'), 'PYTHONIOENCODING': 'utf-8'})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name in {'kadr', 'kadr-dev'}
                catalog = await session.list_tools()
                assert len(catalog.tools) >= 30
                assert all(t.name.startswith(prefix) and (prefix != 'kadr_' or not t.name.startswith('kadr_dev_')) for t in catalog.tools)
                for item in catalog.tools: jsonschema.Draft202012Validator.check_schema(item.inputSchema)
                response = await session.call_tool(tool, arguments)
                assert response.structuredContent is not None
                jsonschema.validate(response.structuredContent, OUTPUT_SCHEMA)
                if prefix == 'kadr_': assert response.isError and response.structuredContent['error']['code'] == 'invalid_arguments'
                else: assert not response.isError and response.structuredContent['data']['items']
                wrong = await session.call_tool('kadr_dev_get_architecture' if prefix == 'kadr_' else 'kadr_create_project', {})
                assert wrong.isError and wrong.structuredContent['error']['code'] == 'unknown_tool'
                resources = await session.list_resources()
                assert len(resources.resources) == 1
                resource = await session.read_resource(resources.resources[0].uri)
                assert json.loads(resource.contents[0].text)['schema_version'] == 1
    run(exercise())
