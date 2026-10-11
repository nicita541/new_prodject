"""Manual transport boundaries: no cloud calls, preserved inputs, strict imports."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.antigravity_exchange import (AnalysisPending, ManualVision, PROVIDER,
    import_result, packet_dir, preserve_provider_checkpoints, snapshot)
from app.config import STORY_MODEL
from app.jobs import JobManager, atomic_json
from app.server import create_app
from tests.test_jobs import FakeWorker


SCHEMA = {'type': 'object', 'properties': {'keep_units': {
    'type': 'array', 'items': {'type': 'string', 'enum': ['u1', 'u2']}, 'uniqueItems': True}},
    'required': ['keep_units'], 'additionalProperties': False}


def session(directory, **options):
    directory.mkdir(exist_ok=True)
    atomic_json(directory / 'analysis.meta.json', {'source': 'source-sha', 'version': 16})
    atomic_json(directory / 'probe.json', {'duration': 120})
    (directory / 'evidence.jpg').write_bytes(b'original-page')
    return ManualVision(directory, lambda: False, **options)


def prepare(vision, prompt='CURRENT u1 u2; PREVIOUS and NEXT are context only'):
    with pytest.raises(AnalysisPending):
        vision.query(prompt, vision.job_dir / 'evidence.jpg', schema=SCHEMA)
    return snapshot(vision.job_dir)['packets'][-1]['id']


def envelope(answer):
    return json.dumps({'status': 'SUCCESS', 'structured_output': answer,
        'duration_seconds': 2.5, 'usage': {'input_tokens': 12, 'output_tokens': 4, 'total_tokens': 16}}).encode()


def test_export_import_resume_uses_same_packet_and_native_contract(tmp_path):
    vision = session(tmp_path)
    identifier = prepare(vision)
    request = json.loads((packet_dir(tmp_path, identifier) / 'request.json').read_text())
    assert request['prompt'].startswith('CURRENT')
    assert request['schema'] == SCHEMA
    assert request['source']['source'] == 'source-sha'
    assert request['source_duration'] == 120
    assert (packet_dir(tmp_path, identifier) / request['images'][0]).read_bytes() == b'original-page'
    result = import_result(tmp_path, identifier, envelope({'keep_units': ['u1']}))
    assert result['usage']['total_tokens'] == 16
    with patch('subprocess.Popen', side_effect=AssertionError('must never start CLI/model')):
        for _ in range(2):
            assert vision.query(request['prompt'], tmp_path / 'evidence.jpg', schema=SCHEMA) == {'keep_units': ['u1']}
    assert len(snapshot(tmp_path)['packets']) == 1


@pytest.mark.parametrize('answer', [{'keep_units': ['invented']}, {'keep_units': ['u1', 'u1']},
    {'keep_units': 'u1'}, {'keep_units': ['u1'], 'unexpected': True}])
def test_schema_rejects_unknown_ids_duplicates_types_and_extras(tmp_path, answer):
    identifier = prepare(session(tmp_path))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, envelope(answer))
    assert snapshot(tmp_path)['packets'][0]['status'] == 'error'


@pytest.mark.parametrize('raw', [b'{broken', b'{"status":"ERROR"}',
    b'{"status":"SUCCESS","structured_output":{"keep_units":[],"keep_units":[]}}',
    b'{"status":"SUCCESS","structured_output":{"keep_units":[]},"duration_seconds":NaN}'])
def test_strict_json_and_failed_envelopes_are_never_answers(tmp_path, raw):
    identifier = prepare(session(tmp_path))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, raw)


def test_bad_replacement_keeps_accepted_cache(tmp_path):
    identifier = prepare(session(tmp_path))
    import_result(tmp_path, identifier, envelope({'keep_units': ['u1']}))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, b'{}')
    assert snapshot(tmp_path)['packets'][0]['status'] == 'ready'


def test_request_identity_changes_with_context_and_images(tmp_path):
    vision = session(tmp_path)
    first = prepare(vision)
    prepare(vision, 'Different neighboring context')
    (tmp_path / 'evidence.jpg').write_bytes(b'changed-page')
    prepare(vision)
    assert len(snapshot(tmp_path)['packets']) == 3
    (packet_dir(tmp_path, first) / 'page_000.jpg').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Изображения'):
        import_result(tmp_path, first, envelope({'keep_units': ['u1']}))


def test_rejects_outside_images_and_packet_paths(tmp_path):
    vision = session(tmp_path / 'job')
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(b'outside')
    with pytest.raises(ValueError):
        vision.query('prompt', outside, schema=SCHEMA)
    with pytest.raises(ValueError):
        packet_dir(vision.job_dir, '../../outside')


def test_import_rejects_stale_source_and_out_of_bounds_times(tmp_path):
    vision = session(tmp_path)
    schema = {'type': 'object', 'properties': {'start': {'type': 'number'},
              'end': {'type': 'number'}}, 'required': ['start', 'end'], 'additionalProperties': False}
    with pytest.raises(AnalysisPending):
        vision.query('Existing ranges only', schema=schema)
    identifier = snapshot(tmp_path)['packets'][0]['id']
    for answer in ({'start': -1, 'end': 1}, {'start': 2, 'end': 1}, {'start': 1, 'end': 121}):
        with pytest.raises(ValueError):
            import_result(tmp_path, identifier, envelope(answer))
    atomic_json(tmp_path / 'analysis.meta.json', {'source': 'another-source'})
    with pytest.raises(ValueError, match='Исходник'):
        import_result(tmp_path, identifier, envelope({'start': 0, 'end': 1}))


def test_cli_generation_schema_preserves_strict_backend_contract():
    from app.antigravity_exchange import cli_schema
    schema = {'type': 'object', 'properties': {'number': {'type': 'number', 'enum': [0, .5, 1]},
        'flag': {'type': 'boolean', 'enum': [True]}, 'id': {'type': 'string', 'enum': ['u1']}}}
    converted = cli_schema(schema)
    assert 'enum' not in converted['properties']['number']
    assert 'enum' not in converted['properties']['flag']
    assert converted['properties']['id']['enum'] == ['u1']
    assert schema['properties']['flag']['enum'] == [True]


def test_cancel_does_not_export_packet(tmp_path):
    vision = session(tmp_path)
    vision.cancelled = lambda: True
    with pytest.raises(InterruptedError) as caught:
        vision.query('prompt')
    assert not isinstance(caught.value, AnalysisPending)
    assert not snapshot(tmp_path)['packets']


def test_import_rejects_contradictory_and_incomplete_native_story_selection(tmp_path):
    vision = session(tmp_path)
    units = {'type': 'array', 'items': {'type': 'string', 'enum': ['u1', 'u2']}}
    schema = {'type': 'object', 'properties': {'keep_units': units, 'preserve_silent_units': units,
        'omit_units': {'type': 'array', 'items': {'type': 'object'}}}}
    with pytest.raises(AnalysisPending):
        vision.query('native selection', schema=schema)
    identifier = snapshot(tmp_path)['packets'][0]['id']
    omission = {'unit': 'u1', 'reason': 'waiting', 'reaction_or_humor': False}
    for answer in ({'keep_units': ['u1'], 'preserve_silent_units': [], 'omit_units': [omission]},
                   {'keep_units': ['u1'], 'preserve_silent_units': [], 'omit_units': []}):
        with pytest.raises(ValueError):
            import_result(tmp_path, identifier, envelope(answer))
    answer = {'keep_units': ['u2'], 'preserve_silent_units': [], 'omit_units': [omission]}
    assert import_result(tmp_path, identifier, envelope(answer))['status'] == 'ready'


def test_switch_restores_qwen_checkpoints_and_keeps_factual_data(tmp_path):
    for name in ('transcript.json', 'scenes.json', 'story-events.json'):
        atomic_json(tmp_path / name, {'original': name})
    (tmp_path / 'visual').mkdir()
    (tmp_path / 'visual/evidence.jpg').write_bytes(b'perception')
    preserve_provider_checkpoints(tmp_path, 'local', PROVIDER)
    atomic_json(tmp_path / 'story-events.json', {'manual': True})
    preserve_provider_checkpoints(tmp_path, PROVIDER, 'local')
    assert json.loads((tmp_path / 'story-events.json').read_text()) == {'original': 'story-events.json'}
    assert json.loads((tmp_path / 'transcript.json').read_text()) == {'original': 'transcript.json'}
    assert (tmp_path / 'visual/evidence.jpg').read_bytes() == b'perception'


def test_only_manual_9b_routed_and_other_providers_unchanged(tmp_path):
    from app.analysis import vision_session, provider_identity
    with patch('app.analysis._native_vision_session', return_value='native') as native:
        assert vision_session(tmp_path, lambda: False, PROVIDER) == 'native'
        assert native.call_args.args[2] == 'local'
        assert isinstance(vision_session(tmp_path, lambda: False, PROVIDER, model=STORY_MODEL), ManualVision)
        for provider in ('local', 'deepseek', 'deepseek_plan', 'hybrid'):
            assert vision_session(tmp_path, lambda: False, provider) == 'native'
            assert native.call_args.args[2] == provider
    assert provider_identity('local') == {'provider': 'local'}


def test_existing_control_failure_recognizes_pending_without_degrading():
    from app.scene_understanding import _control_failure
    assert _control_failure(AnalysisPending('waiting'))


def test_worker_persists_waiting_state_without_marking_cancelled(tmp_path):
    from app import config
    from app.worker import main
    import uuid
    identifier = str(uuid.uuid4())
    directory = tmp_path / identifier
    directory.mkdir()
    (directory / '.start').touch()
    atomic_json(directory / 'job.json', {'id': identifier, 'status': 'running', 'outputs': []})
    with patch.object(config, 'JOBS', tmp_path), patch('sys.argv', ['worker', '--job', identifier]), \
            patch('app.pipeline.run_job', side_effect=AnalysisPending('waiting for packet')):
        assert main() == 0
    job = json.loads((directory / 'job.json').read_text())
    assert job['status'] == job['stage'] == 'waiting_analysis'
    assert job['cancel_requested'] is False
    assert job['error'] is None


def test_api_manual_import_mode_retry_and_busy_guards(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'media')
    manager = JobManager(tmp_path, worker_factory=FakeWorker)
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        imported = manager.list_sources()[0]
        job = manager.create(imported['id'])
        identifier = job['id']
        prefix = '/api/jobs/' + identifier
        assert client.post(prefix + '/analysis-provider', json={'provider': PROVIDER}).status_code == 409
        manager.cancel(identifier)
        assert client.post(prefix + '/analysis-provider', json={'provider': PROVIDER}).status_code == 200
        directory = manager.job_dir(identifier)
        packet = prepare(session(directory))
        accepted = client.post(prefix + '/antigravity/' + packet + '/import',
            content=envelope({'keep_units': ['u2']}), headers={'content-type': 'application/json'})
        assert accepted.status_code == 200, accepted.text
        assert client.get(prefix + '/antigravity').json()['packets'][0]['status'] == 'ready'
        assert client.post(prefix + '/antigravity/prepare').status_code == 200
        assert client.post(prefix + '/antigravity/' + packet + '/import', content=b'{}').status_code == 409
        manager.cancel(identifier)
        assert client.post(prefix + '/analysis-provider', json={'provider': 'local'}).status_code == 200
        assert manager.get(identifier)['analysis_provider'] == 'local'
