"""Finishing HTTP contracts without workers, inference or generated media."""
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.finishing import create_finishing_router


@pytest.fixture
def api():
    manager = SimpleNamespace(mutex=threading.RLock())
    app = FastAPI()
    app.state.manager = manager
    app.include_router(create_finishing_router())
    with TestClient(app) as client:
        yield client, manager


@pytest.mark.parametrize('kind,body', [
    ('exports', {'part_indices': [1], 'settings': None}),
    ('previews', {'part_index': 1, 'from': 0, 'duration': 5, 'settings': None}),
])
def test_exact_replay_precedes_mutable_preflight(api, kind, body):
    client, manager = api
    operation_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    identifier = ('ex_' if kind == 'exports' else 'pv_') + uuid.uuid4().hex
    state = {('export_id' if kind == 'exports' else 'preview_id'): identifier,
             'status': 'interrupted', 'operation_id': operation_id, 'resumable': True}
    with patch('app.studio_render.replay_render', return_value=state, create=True) as replay, \
            patch('app.finishing._checked_render_job', side_effect=AssertionError('current plan touched')), \
            patch('app.finishing._stored_profile', side_effect=AssertionError('current profile touched')), \
            patch('app.finishing._check_avatar', side_effect=AssertionError('current avatar touched')), \
            patch('app.studio_render.submit_render', side_effect=AssertionError('duplicate command')):
        response = client.post(f'/api/jobs/{job_id}/{kind}', json={**body, 'operation_id': operation_id})
    assert response.status_code == 202, response.text
    assert response.json() == state
    replay.assert_called_once_with(manager, job_id, kind[:-1], operation_id, body)


@pytest.mark.parametrize('kind,body', [('exports', {'part_indices': [1]}), ('previews', {'part_index': 1})])
@pytest.mark.parametrize('invalid', ['NOT-A-UUID', '00000000000000000000000000000000', 'AAAAAAAA-0000-4000-8000-000000000000'])
def test_noncanonical_operation_uuid_is_rejected_before_dispatch(api, kind, body, invalid):
    client, _ = api
    with patch('app.studio_render.replay_render', create=True) as replay:
        response = client.post(f'/api/jobs/{uuid.uuid4()}/{kind}', json={**body, 'operation_id': invalid})
    assert response.status_code == 422
    replay.assert_not_called()


@pytest.mark.parametrize('kind,body', [('exports', {'part_indices': [1]}), ('previews', {'part_index': 1})])
def test_operation_conflict_is_409_and_does_not_run_preflight(api, kind, body):
    client, _ = api
    with patch('app.studio_render.replay_render', side_effect=ValueError('operation conflict'), create=True), \
            patch('app.finishing._checked_render_job', side_effect=AssertionError('current plan touched')):
        response = client.post(f'/api/jobs/{uuid.uuid4()}/{kind}', json={**body, 'operation_id': str(uuid.uuid4())})
    assert response.status_code == 409
    assert response.json()['detail'] == 'operation conflict'


@pytest.mark.parametrize('explicit_settings', [None, {}])
def test_preview_original_request_retains_requested_duration_and_settings_marker(api, explicit_settings):
    client, manager = api
    job_id, operation_id = str(uuid.uuid4()), str(uuid.uuid4())
    profile = {'video': {'layout': 'cinema'}}
    state = {'preview_id': 'pv_' + uuid.uuid4().hex, 'status': 'queued',
             'operation_id': operation_id, 'resumable': True}
    with patch('app.studio_render.replay_render', return_value=None, create=True) as replay, \
            patch('app.finishing._checked_render_job', return_value=({}, {'parts': [{'index': 1, 'duration': 3.5}]}, 'episode')), \
            patch('app.finishing._stored_profile', return_value=profile) as stored, \
            patch('app.finishing._check_avatar'), \
            patch('app.studio_render.submit_render', return_value=state) as submit:
        response = client.post(f'/api/jobs/{job_id}/previews', json={
            'part_index': 1, 'from': 2, 'duration': 5, 'settings': explicit_settings, 'operation_id': operation_id})
    assert response.status_code == 202, response.text
    assert submit.call_args.args[:3] == (manager, job_id, [1])
    assert submit.call_args.kwargs['preview'] == (1, 2, 1.5)
    original = submit.call_args.kwargs['original_request']
    assert original['from'] == 2 and original['duration'] == 5
    assert 'operation_id' not in original
    assert replay.call_args.args[-1] == original
    assert original['settings'] is None if explicit_settings is None else isinstance(original['settings'], dict)
    assert stored.call_count == (1 if explicit_settings is None else 0)
    assert response.json()['operation_id'] == operation_id
    assert response.json()['resumable'] is True


def test_export_submit_preserves_none_marker_and_conflict_mapping(api):
    client, manager = api
    operation_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    with patch('app.studio_render.replay_render', return_value=None, create=True), \
            patch('app.finishing._checked_render_job', return_value=({}, {'parts': [{'index': 1}]}, 'episode')), \
            patch('app.finishing._stored_profile', return_value={'video': {}}), \
            patch('app.finishing._check_avatar'), \
            patch('app.studio_render.submit_render', side_effect=ValueError('late conflict')) as submit:
        response = client.post(f'/api/jobs/{job_id}/exports', json={'part_indices': [1], 'operation_id': operation_id})
    assert response.status_code == 409
    assert submit.call_args.kwargs == {'operation_id': operation_id, 'original_request': {'part_indices': [1], 'settings': None}}


@pytest.mark.parametrize('kind', ['export', 'preview'])
@pytest.mark.parametrize('action', ['resume', 'cancel'])
def test_controls_delegate_owner_and_return_public_state(api, kind, action):
    client, manager = api
    job_id = str(uuid.uuid4())
    identifier = ('ex_' if kind == 'export' else 'pv_') + uuid.uuid4().hex
    path = f'/api/exports/{identifier}/{action}' if kind == 'export' else f'/api/jobs/{job_id}/previews/{identifier}/{action}'
    state = {'status': 'queued' if action == 'resume' else 'cancelled', 'resumable': True}
    with patch('app.studio_render.control_task', return_value=state, create=True) as control:
        response = client.post(path)
    assert response.status_code == 200, response.text
    assert response.json() == state
    if kind == 'export':
        control.assert_called_once_with(manager, identifier, action)
    else:
        control.assert_called_once_with(manager, identifier, action, job_id=job_id)


def test_nonresumable_legacy_control_returns_conflict(api):
    client, _ = api
    with patch('app.studio_render.control_task', side_effect=ValueError('legacy non-resumable'), create=True):
        response = client.post('/api/exports/ex_' + uuid.uuid4().hex + '/resume')
    assert response.status_code == 409


def test_task_list_delegates_readonly_owner_query(api):
    client, manager = api
    job_id = str(uuid.uuid4())
    state = [{'export_id': 'ex_' + uuid.uuid4().hex, 'status': 'interrupted', 'resumable': True}]
    with patch('app.studio_render.list_tasks', return_value=state, create=True) as listing:
        response = client.get(f'/api/jobs/{job_id}/finishing-tasks')
    assert response.status_code == 200
    assert response.json() == state
    listing.assert_called_once_with(manager, job_id)


@pytest.mark.parametrize('kind,name', [('export', 'part_001.mp4'), ('export', 'part_001.srt'), ('preview', 'part_001.mp4')])
def test_stream_uses_receipt_resolver_not_assumed_output_directory(api, kind, name):
    client, manager = api
    job_id = str(uuid.uuid4())
    identifier = ('ex_' if kind == 'export' else 'pv_') + uuid.uuid4().hex
    path = f'/api/exports/{identifier}/files/{name}' if kind == 'export' else f'/api/jobs/{job_id}/previews/{identifier}.mp4'
    validated_reference = Path('F:/new_prodject/temp/validated-prior-attempt/' + name)
    state = {'status': 'completed', 'files': [{'name': 'part_001.mp4'}]}
    with patch('app.studio_render.task_status', return_value=state), \
            patch('app.studio_render.resolve_task_file', return_value=validated_reference, create=True) as resolve, \
            patch('app.http_media.ranged_file', return_value={'served': True}) as ranged:
        response = client.get(path)
    assert response.status_code == 200, response.text
    if kind == 'export':
        resolve.assert_called_once_with(manager, identifier, name)
        assert ranged.call_args.kwargs == {'as_attachment': False}
    else:
        resolve.assert_called_once_with(manager, identifier, name, job_id=job_id)
    assert ranged.call_args.args[0] == validated_reference


def test_stream_rejects_receipt_integrity_failure(api):
    client, _ = api
    with patch('app.studio_render.task_status', return_value={'status': 'completed', 'files': [{'name': 'part_001.mp4'}]}), \
            patch('app.studio_render.resolve_task_file', side_effect=HTTPException(409, 'artifact changed'), create=True), \
            patch('app.http_media.ranged_file') as ranged:
        response = client.get('/api/exports/ex_' + uuid.uuid4().hex + '/files/part_001.mp4')
    assert response.status_code == 409
    ranged.assert_not_called()
