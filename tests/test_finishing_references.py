"""Same-job immutable media references using authored bytes, never a decoder.

The adapter declares fake validation receipts to exercise storage boundaries;
these fixtures do not claim actual media or model acceptance.
"""
import copy
import os
import uuid
from unittest.mock import patch

import pytest

from app import finishing_render as renderer
from app.content_identity import digest, file_sha256
from app.finishing_commands import CommandError, FinishingCommands
from app.json_store import atomic_json, read_json
from test_finishing_render import authored_render, frozen  # Shared full frozen-profile fixture.


def clone(frozen, change=None, *, job=None):
    root, _, _, _, _, store, original, _ = frozen
    saved = copy.deepcopy(original['frozen'])
    if change:
        change(saved)
    return store.submit(job or original['job_id'], saved['source']['sha256'], 'export',
        {'part_indices': [part['index'] for part in saved['plan']['parts']], 'settings': saved['profile']},
        lambda: saved, operation_id=str(uuid.uuid4()))


def render(frozen, command):
    root, _, _, _, _, store, _, _ = frozen
    attempt = store.begin_attempt(command)['attempt_id']
    captured = []
    with patch.object(renderer, 'render_contract', return_value=command['frozen']['render_contract']), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=authored_render(captured)), \
         patch('shutil.copy2', side_effect=AssertionError('References must not copy media')):
        renderer.render_command(root, command['operation_id'], attempt, lambda *args: None, lambda: False)
    return attempt, captured


def pointer_path(store, command, index=1):
    return store.task_directory(command['job_id'], command['kind'], command['task_id'])/'parts'/f'part_{index:03}.json'


def running(store, command):
    attempt = store.begin_attempt(command)['attempt_id']
    store.update_attempt(command, attempt, status='running')
    return attempt


def test_equivalent_new_operation_reuses_exact_origin_bytes_without_render_or_copy(frozen):
    _, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    original_receipts = {index: store.part_receipt(original, index) for index in (1, 2)}
    def bookkeeping_only(saved):
        saved['publication_revision'] = 'b'*64
        saved['source_plan_digest'] = 'c'*64
        saved['caption_revisions']['1']['revision'] += 1
        saved['caption_revisions']['1']['target_id'] = 'd'*64
        saved['profile']['subtitles']['safe_guides'] = not saved['profile']['subtitles'].get('safe_guides', False)
    command = clone(frozen, bookkeeping_only)
    attempt, captured = render(frozen, command)
    assert not captured
    assert store._runtime(command)[1]['status'] == 'completed'
    for index in (1, 2):
        assert store.part_receipt(command, index) == original_receipts[index]
        pointer = read_json(pointer_path(store, command, index))
        assert pointer['version'] == 2
        assert pointer['origin_operation_id'] == original['operation_id']
        assert pointer['origin_receipt_id'] == digest(original_receipts[index])
    directory = store.task_directory(command['job_id'], command['kind'], command['task_id'])
    assert not (directory/'attempts'/attempt/'output').exists()


def test_changed_caption_renders_only_affected_part_and_preserves_other_reference(frozen):
    _, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    def changed(saved):
        saved['plan']['parts'][0]['subtitles'][0]['text'] = 'New exact authored caption'
        saved['caption_revisions']['1']['revision'] += 1
    command = clone(frozen, changed)
    attempt, captured = render(frozen, command)
    assert [part['index'] for part, _, _ in captured] == [1]
    assert store.part_receipt(command, 1)['attempt_id'] == attempt
    assert store.part_receipt(command, 2) == store.part_receipt(original, 2)
    assert read_json(pointer_path(store, command, 2))['version'] == 2


@pytest.mark.parametrize('damage', ['video', 'subtitles', 'receipt', 'pointer'])
def test_corrupt_old_media_or_receipt_is_rejected_as_cache_and_rerendered(frozen, damage):
    root, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    record = store.part_receipt(original, 1)
    if damage in ('video', 'subtitles'):
        path = root/record[damage]['path']
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1])+data[1:])  # Same length, different identity.
    elif damage == 'receipt':
        pointer = read_json(pointer_path(store, original))
        directory = store.task_directory(original['job_id'], original['kind'], original['task_id'])
        path = directory/'receipts'/(pointer['receipt_id']+'.json')
        atomic_json(path, {**read_json(path), 'full_decode_version': -1})
    else:
        path = pointer_path(store, original)
        atomic_json(path, {**read_json(path), 'receipt_id': 'f'*64})
    with pytest.raises(CommandError):
        store.part_receipt(original, 1)
    command = clone(frozen)
    attempt, captured = render(frozen, command)
    assert [part['index'] for part, _, _ in captured] == [1]
    assert store.part_receipt(command, 1)['attempt_id'] == attempt
    assert store.part_receipt(command, 2) == store.part_receipt(original, 2)


def test_alias_at_old_artifact_path_cannot_approve_a_new_reference(frozen):
    root, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    record = store.part_receipt(original, 1)
    video = root/record['video']['path']
    target = root/'authored-alias-target.mp4'
    video.replace(target)
    try:
        os.symlink(target, video)
    except OSError as error:
        pytest.skip(f'Environment cannot create file symlink: {type(error).__name__}')
    with pytest.raises(CommandError):
        store.part_receipt(original, 1)
    command = clone(frozen)
    attempt, captured = render(frozen, command)
    assert [part['index'] for part, _, _ in captured] == [1]
    assert store.part_receipt(command, 1)['attempt_id'] == attempt


@pytest.mark.parametrize('field', ['music', 'avatar', 'source', 'probe', 'audio_stream', 'render_contract', 'video', 'subtitle_style'])
def test_changed_presentation_inputs_never_reuse_old_approved_part(frozen, field):
    root, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    def changed(saved):
        if field in ('music', 'avatar'):
            asset = root/(field+'.asset')
            asset.write_bytes(('new authored '+field).encode())
            sha = file_sha256(asset)
            saved['assets'].append({'role': field, 'path': asset.name, 'sha256': sha})
            if field == 'music':
                saved['resolved_music'] = {str(index): {'asset_sha256': sha, 'volume': .1} for index in (1, 2)}
        elif field == 'source':
            asset = root/'different-source.mp4'
            asset.write_bytes(b'different authored source')
            saved['source'] = {'path': asset.name, 'sha256': file_sha256(asset)}
        elif field == 'probe':
            saved['probe']['width'] += 2
        elif field == 'audio_stream':
            saved['probe']['audio_stream'] = saved['audio_stream'] = 0
        elif field == 'render_contract':
            saved['render_contract']['code_sha256'] = 'e'*64
        elif field == 'video':
            saved['profile']['video']['brightness'] += 1
        else:
            saved['profile']['subtitles']['font_size'] += 1
    command = clone(frozen, changed)
    attempt = running(store, command)
    for index in (1, 2):
        assert store.presentation_identity(command, index) != store.presentation_identity(original, index)
        assert renderer._reuse_part(store, command, attempt, index) is False
        assert store.part_receipt(command, index) is None
        with pytest.raises(CommandError):
            store.reference_part(command, attempt, index, original, index)


def test_foreign_job_with_identical_presentation_is_not_a_reuse_origin(frozen):
    _, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    command = clone(frozen, job=str(uuid.uuid4()))
    attempt = running(store, command)
    assert store.presentation_identity(command, 1) == store.presentation_identity(original, 1)
    with pytest.raises(CommandError, match='same job'):
        store.reference_part(command, attempt, 1, original, 1)
    assert renderer._reuse_part(store, command, attempt, 1) is False
    assert store.part_receipt(command, 1) is None


@pytest.mark.parametrize('field,value', [
    ('version', 2.0), ('command_hash', '0'*64), ('part_index', 2),
    ('origin_operation_id', str(uuid.uuid4())), ('origin_part_index', 2),
    ('origin_receipt_id', '0'*64), ('render_input_digest', '0'*64), ('presentation_sha256', '0'*64),
])
def test_reference_pointer_tampering_never_approves_artifact(frozen, field, value):
    _, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    command = clone(frozen)
    render(frozen, command)
    path = pointer_path(store, command)
    pointer = read_json(path)
    atomic_json(path, {**pointer, field: value})
    with pytest.raises(CommandError):
        store.part_receipt(command, 1)


def test_reference_chain_preserves_original_decode_receipt_and_cycle_fails_closed(frozen):
    _, _, _, _, _, store, original, _ = frozen
    render(frozen, original)
    first = clone(frozen)
    render(frozen, first)
    second = clone(frozen)
    attempt = running(store, second)
    expected = store.part_receipt(original, 1)
    assert store.reference_part(second, attempt, 1, first, 1) == expected
    assert store.part_receipt(second, 1) == expected
    first_path = pointer_path(store, first)
    pointer = read_json(first_path)
    atomic_json(first_path, {**pointer, 'origin_operation_id': second['operation_id']})
    with pytest.raises(CommandError, match='cycle'):
        store.part_receipt(second, 1)


@pytest.mark.parametrize('fail_removal', [False, True])
def test_job_deletion_retires_same_job_reference_graph_and_rolls_back_on_removal_failure(frozen, fail_removal):
    root, directory, _, _, _, store, original, _ = frozen
    render(frozen, original)
    command = clone(frozen)
    render(frozen, command)
    from app.jobs import JobManager
    manager = JobManager(root)
    try:
        # Both persisted attempts are completed; recovery must not schedule them.
        assert not manager.finishing_execution.owns_job(original['job_id'])
        paths = [store._operation(item['operation_id']) for item in (original, command)]
        before = [path.read_bytes() for path in paths]
        if fail_removal:
            with patch('app.jobs.shutil.rmtree', side_effect=PermissionError('authored locked directory')):
                with pytest.raises(PermissionError):
                    manager.delete_job(original['job_id'])
            assert directory.is_dir()
            assert [path.read_bytes() for path in paths] == before
            assert store.part_receipt(command, 1) == store.part_receipt(original, 1)
        else:
            assert manager.delete_job(original['job_id'])['deleted'] is True
            assert not directory.exists()
            assert all(read_json(path)['state'] == 'deleted' for path in paths)
            for item in (original, command):
                with pytest.raises(CommandError):
                    store.load(item['operation_id'])
    finally:
        manager.close()
