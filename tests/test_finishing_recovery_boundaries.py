"""POST recovery and input mutation boundaries, using authored media adapters.

The adapters declare test validation receipts; these tests do not decode media.
"""
import copy
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import finishing_render as renderer
from app import studio_render
from app.content_identity import file_sha256
from app.finishing import FinishProfile, create_finishing_router
from app.finishing_commands import CommandError
from app.finishing_execution import FinishingExecution
from app.json_store import atomic_json, read_json
from tests.test_finishing_render import authored_render, frozen as frozen_fixture


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def managed(tmp_path):
    manager = SimpleNamespace(root=tmp_path, mutex=threading.RLock(), active=None,
                              shutdown_requested=False, closed=False, busy=lambda: False)
    # The command is persisted after this already-running scheduler's startup.
    execution = FinishingExecution(manager, autostart=False, validate=Mock())
    manager.finishing_execution = execution
    original = frozen_fixture.__wrapped__(tmp_path)
    root, directory, source, profile, plan, store, initial, contract = original
    # Persist the same typed profile representation produced by the HTTP input
    # model, rather than bypassing its numeric coercions through fixture defaults.
    profile = FinishProfile.model_validate(profile).model_dump()
    payload = {**initial['frozen'], 'profile': profile}
    command = store.submit(initial['job_id'], initial['source_sha256'], 'export',
        {'part_indices': [1, 2], 'settings': profile}, lambda: payload)
    data = root, directory, source, profile, plan, store, command, contract
    manager.job_dir = lambda identifier: tmp_path/'data/jobs'/identifier
    manager.get = lambda identifier: {'id': identifier, 'status': 'completed'}
    app = FastAPI()
    app.state.manager = manager
    app.include_router(create_finishing_router())
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield manager, client, data
    finally:
        execution.stop()


def interrupted_submission(manager, data, failure):
    root, _, _, profile, _, store, command, _ = data
    if failure == 'reserved':
        operation = store._operation(command['operation_id'])
        atomic_json(operation, {**read_json(operation), 'state': 'reserved'})
        directory = store.task_directory(command['job_id'], command['kind'], command['task_id'])
        (directory/'command.json').unlink()
    elif failure == 'index_failure':
        operation = str(uuid.uuid4())
        with patch.object(renderer, 'freeze_command', return_value=copy.deepcopy(command['frozen'])), \
             patch.object(studio_render, '_index_command', side_effect=OSError('Authored index write failure')):
            with pytest.raises(OSError, match='Authored index write failure'):
                studio_render.submit_render(manager, command['job_id'], [1, 2], profile,
                                           operation_id=operation)
        command = store.load(operation)
        assert manager.finishing_execution.status(command)['status'] == 'queued'
    else:
        assert failure == 'committed'
    assert not (root/'finishing/exports-index'/(command['task_id']+'.json')).exists()
    return command


@pytest.mark.parametrize('failure', ['reserved', 'committed', 'index_failure'])
def test_exact_post_repairs_lost_submission_then_get_is_readonly(managed, failure):
    manager, client, data = managed
    root, _, source, profile, _, store, _, _ = data
    command = interrupted_submission(manager, data, failure)
    prior_state = store._runtime(command)[1]
    before_get = snapshot(root)
    # Missing materialization/index remains a read error; GET never repairs it.
    response = client.get('/api/exports/'+command['task_id'])
    assert response.status_code >= 400
    assert snapshot(root) == before_get
    # Exact intent survives an unavailable current source and mutable preflight.
    source.unlink()
    forbidden = AssertionError('POST replay must not resolve current settings/source')
    with patch('app.finishing._checked_render_job', side_effect=forbidden), \
         patch('app.finishing._stored_profile', side_effect=forbidden), \
         patch('app.finishing._check_avatar', side_effect=forbidden), \
         patch.object(renderer, 'freeze_command', side_effect=forbidden):
        response = client.post(f"/api/jobs/{command['job_id']}/exports", json={
            'part_indices': [1, 2], 'settings': profile, 'operation_id': command['operation_id']})
    assert response.status_code == 202, response.text
    state = response.json()
    assert state['export_id'] == command['task_id']
    assert state['operation_id'] == command['operation_id']
    assert state['status'] == 'queued'
    assert store.load(command['operation_id']) == command
    assert manager.finishing_execution.commands[command['operation_id']] == command
    assert read_json(root/'finishing/exports-index'/(command['task_id']+'.json')) == {
        'source_job_id': command['job_id'], 'operation_id': command['operation_id']}
    if prior_state:
        assert state['attempt_id'] == prior_state['attempt_id']
    durable = snapshot(root)
    response = client.get('/api/exports/'+command['task_id'])
    assert response.status_code == 200, response.text
    assert response.json()['attempt_id'] == state['attempt_id']
    assert snapshot(root) == durable


@pytest.mark.parametrize('failure', ['reserved', 'committed', 'index_failure'])
def test_conflicting_post_does_not_materialize_enroll_or_reindex(managed, failure):
    manager, client, data = managed
    root, _, _, profile, _, store, _, _ = data
    command = interrupted_submission(manager, data, failure)
    before = snapshot(root)
    before_commands = copy.deepcopy(manager.finishing_execution.commands)
    with patch.object(renderer, 'freeze_command', side_effect=AssertionError('conflict must not freeze')):
        response = client.post(f"/api/jobs/{command['job_id']}/exports", json={
            'part_indices': [2, 1], 'settings': profile, 'operation_id': command['operation_id']})
    assert response.status_code == 409, response.text
    assert snapshot(root) == before
    assert manager.finishing_execution.commands == before_commands
    assert store._receipt(command['operation_id'])['command'] == command


@pytest.mark.parametrize('failure', ['reserved', 'committed'])
@pytest.mark.parametrize('conflicting', [False, True])
def test_preview_replay_preserves_requested_and_clamped_interval(managed, failure, conflicting):
    manager, client, data = managed
    root, _, source, profile, _, store, initial, _ = data
    payload = copy.deepcopy(initial['frozen'])
    payload['plan']['parts'] = payload['plan']['parts'][:1]
    payload['caption_revisions'] = {'1': payload['caption_revisions']['1']}
    payload['resolved_music'] = {'1': None}
    payload['preview'] = {'part_index': 1, 'from': .5, 'duration': 1.}
    request = {'part_index': 1, 'from': .5, 'duration': 5., 'settings': profile}
    command = store.submit(initial['job_id'], initial['source_sha256'], 'preview', request, lambda: payload)
    if failure == 'reserved':
        operation = store._operation(command['operation_id'])
        atomic_json(operation, {**read_json(operation), 'state': 'reserved'})
        directory = store.task_directory(command['job_id'], 'preview', command['task_id'])
        (directory/'command.json').unlink()
    before = snapshot(root)
    get_path = f"/api/jobs/{command['job_id']}/previews/{command['task_id']}"
    response = client.get(get_path)
    assert response.status_code >= 400 if failure == 'reserved' else response.status_code == 200
    assert snapshot(root) == before
    assert command['operation_id'] not in manager.finishing_execution.commands
    if not conflicting:
        source.unlink()
    before = snapshot(root)
    forbidden = AssertionError('Preview replay must not resolve mutable inputs')
    body = {**request, 'operation_id': command['operation_id']}
    if conflicting:
        # Both durations would clamp to the same actual window. The original
        # request must nevertheless remain distinct and conflict before writes.
        body['duration'] = 4.
    with patch('app.finishing._checked_render_job', side_effect=forbidden), \
         patch('app.finishing._stored_profile', side_effect=forbidden), \
         patch('app.finishing._check_avatar', side_effect=forbidden), \
         patch.object(renderer, 'freeze_command', side_effect=forbidden):
        response = client.post(f"/api/jobs/{command['job_id']}/previews", json=body)
    if conflicting:
        assert response.status_code == 409, response.text
        assert snapshot(root) == before
        assert command['operation_id'] not in manager.finishing_execution.commands
    else:
        assert response.status_code == 202, response.text
        assert response.json()['preview_id'] == command['task_id']
        assert response.json()['status'] == 'queued'
        recovered = store.load(command['operation_id'])
        assert recovered == command
        assert recovered['request']['preview']['duration'] == 5.
        assert recovered['frozen']['preview']['duration'] == 1.
        before = snapshot(root)
        assert client.get(get_path).status_code == 200
        assert snapshot(root) == before


@pytest.fixture
def frozen(tmp_path):
    return frozen_fixture.__wrapped__(tmp_path)


def command_with_asset(data, role):
    root, _, source, _, _, store, initial, _ = data
    payload = copy.deepcopy(initial['frozen'])
    if role == 'source':
        path = source
    else:
        path = root/'finishing/assets'/('track.mp3' if role == 'music' else 'avatar.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('Authored '+role+' identity; no decoder used').encode())
        sha = file_sha256(path)
        payload['assets'].append({'role': role, 'path': path.relative_to(root).as_posix(), 'sha256': sha})
        if role == 'music':
            payload['profile']['audio']['enabled'] = True
            payload['resolved_music'] = {str(i): {'asset_sha256': sha, 'volume': .1} for i in (1, 2)}
        else:
            payload['profile']['video']['avatar_style'] = 'image'
    command = store.submit(initial['job_id'], initial['source_sha256'], 'export',
        {'part_indices': [1, 2], 'settings': payload['profile']}, lambda: payload)
    return command, path


@pytest.mark.parametrize('role', ['source', 'music', 'avatar'])
@pytest.mark.parametrize('changed_part', [1, 2])
def test_input_mutation_during_fresh_render_cannot_commit_that_part(frozen, role, changed_part):
    root, _, _, _, _, store, _, contract = frozen
    command, asset = command_with_asset(frozen, role)
    attempt = store.begin_attempt(command)['attempt_id']
    captured = []
    adapter = authored_render(captured)

    def mutate_during_render(source, part, *args, **kwargs):
        if part['index'] == changed_part:
            asset.write_bytes(b'Ordinary edit while renderer is executing')
        return adapter(source, part, *args, **kwargs)

    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=mutate_during_render):
        with pytest.raises(CommandError, match='bytes changed'):
            renderer.render_command(root, command['operation_id'], attempt, lambda *args: None, lambda: False)
    assert store._runtime(command)[1]['status'] != 'completed'
    assert store.part_receipt(command, changed_part) is None
    assert store.part_receipt(command, 2) is None
    if changed_part == 2:
        assert store.part_receipt(command, 1) is not None
    assert [part['index'] for part, _, _ in captured] == list(range(1, changed_part+1))


@pytest.mark.parametrize('role', ['source', 'music', 'avatar'])
def test_reuse_only_run_rechecks_mutated_inputs_before_completion(frozen, role):
    root, _, _, _, _, store, _, contract = frozen
    origin, asset = command_with_asset(frozen, role)
    origin_attempt = store.begin_attempt(origin)['attempt_id']
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=authored_render([])):
        renderer.render_command(root, origin['operation_id'], origin_attempt, lambda *args: None, lambda: False)
    command = store.submit(origin['job_id'], origin['source_sha256'], 'export',
        {'part_indices': [1, 2], 'settings': origin['frozen']['profile']}, lambda: origin['frozen'])
    attempt = store.begin_attempt(command)['attempt_id']
    reused = []

    def report(stage, progress, message):
        assert stage == 'reusing'
        reused.append(progress)
        if progress == 1:
            asset.write_bytes(b'Ordinary edit after the last existing artifact was reused')

    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', side_effect=AssertionError('reuse must not acquire encoder')), \
         patch('app.media.render_part', side_effect=AssertionError('reuse must not render')):
        with pytest.raises(CommandError, match='bytes changed'):
            renderer.render_command(root, command['operation_id'], attempt, report, lambda: False)
    assert reused == [.5, 1]
    assert store._runtime(command)[1]['status'] != 'completed'
    assert store._runtime(origin)[1]['status'] == 'completed'
    # References still point at genuine earlier authored receipts; no new media
    # is created under the new attempt, and no changed-input completion exists.
    for index in (1, 2):
        assert store.part_receipt(command, index) == store.part_receipt(origin, index)
    directory = store.task_directory(command['job_id'], 'export', command['task_id'])
    assert not (directory/'attempts'/attempt/'output').exists()
