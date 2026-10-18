"""Frozen finishing renderer ownership; authored adapters except explicit media test."""
import copy
from pathlib import Path
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import finishing_render as renderer
from app.content_identity import file_sha256
from app.finishing import FinishProfile
from app.finishing_commands import CommandError, FinishingCommands
from app.json_store import atomic_json
from app.media import EXPORT_VALIDATION_VERSION


@pytest.fixture
def frozen(tmp_path):
    root = tmp_path
    job = str(uuid.uuid4())
    directory = root/'data/jobs'/job
    directory.mkdir(parents=True)
    source = root/'source.mp4'
    source.write_bytes(b'Authored source identity; no decoder used in adapter tests')
    atomic_json(directory/'source.json', {'path': str(source)})
    atomic_json(directory/'probe.json', {'audio_stream': 1})
    parts = [{'index': i, 'duration': 1.5, 'layout': 'cinema',
              'cuts': [{'start': (i-1)*2., 'end': (i-1)*2.+1.5}],
              'subtitles': [{'start': .2, 'end': .8, 'text': f'Original caption {i}'}]}
             for i in (1, 2)]
    plan = {'source': {'duration': 5}, 'parts': parts}
    atomic_json(directory/'plan.json', plan)
    profile = FinishProfile().model_dump()
    profile['video']['layout'] = 'cinema'
    profile['audio']['enabled'] = False
    manager = SimpleNamespace(root=root, job_dir=lambda value: directory)
    contract = {'version': 1, 'code_sha256': 'a'*64}
    raw = {'streams': [{'codec_type': 'video', 'width': 320, 'height': 180},
                       {'codec_type': 'audio'}, {'codec_type': 'audio'}]}
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.inspect_media', return_value=raw):
        payload = renderer.freeze_command(manager, job, [1, 2], profile)
    store = FinishingCommands(root)
    command = store.submit(job, file_sha256(source), 'export',
        {'part_indices': [1, 2], 'settings': profile}, lambda: payload)
    return root, directory, source, profile, plan, store, command, contract


def authored_render(captured, *, fail_index=None, receipt=True):
    def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
        captured.append((copy.deepcopy(part), copy.deepcopy(probe), kwargs))
        if part['index'] == fail_index:
            raise RuntimeError('Authored interruption on second part')
        output.mkdir(parents=True, exist_ok=True)
        video = output/f"part_{part['index']:03}.mp4"
        video.write_bytes(b'Authored private media; not decoded '+str(part['index']).encode())
        video.with_suffix('.srt').write_text(part['subtitles'][0]['text'], encoding='utf-8')
        if receipt:
            kwargs['on_validated']({'full_decode_version': EXPORT_VALIDATION_VERSION,
                'video_sha256': file_sha256(video), 'subtitles_sha256': file_sha256(video.with_suffix('.srt'))})
        return video
    return render


def test_freeze_preserves_original_audio_selection_and_exact_caption_ownership(frozen):
    _, _, _, _, _, _, command, _ = frozen
    saved = command['frozen']
    assert saved['audio_stream'] == saved['probe']['audio_stream'] == 1
    assert saved['probe']['width'] == 320
    assert type(saved['profile']['subtitles']['x']) is float
    assert set(saved['caption_revisions']) == {'1', '2'}
    assert all(len(value['target_id']) == 64 for value in saved['caption_revisions'].values())


def test_legacy_cut_without_focus_uses_the_same_held_center_as_empty_focus():
    from app.media import crop_expressions
    assert crop_expressions({'start': 1, 'end': 2}, 320, 180) == crop_expressions(
        {'start': 1, 'end': 2, 'focus': []}, 320, 180)


def test_render_never_looks_up_today_plan_source_profile_or_assets(frozen):
    root, directory, _, profile, plan, store, command, contract = frozen
    profile['video']['brightness'] = 140
    plan['parts'][0]['subtitles'][0]['text'] = 'Changed after submission'
    atomic_json(directory/'plan.json', plan)
    atomic_json(directory/'source.json', {'path': 'different source'})
    attempt = store.begin_attempt(command)['attempt_id']
    captured = []
    forbidden = AssertionError('Mutable resolution forbidden during execution')
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch.object(renderer, 'effective_plan', side_effect=forbidden), \
         patch('app.studio_render._source', side_effect=forbidden), \
         patch('app.studio_render._effective_part', side_effect=forbidden), \
         patch('app.finishing_avatar.resolve_avatar', side_effect=forbidden), \
         patch('app.music.pick_track_for_part', side_effect=forbidden), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=authored_render(captured)):
        renderer.render_command(root, command['operation_id'], attempt, lambda *args: None, lambda: False)
    assert captured[0][0]['subtitles'][0]['text'] == 'Original caption 1'
    assert captured[0][2]['finishing']['video']['brightness'] == 100
    assert store._runtime(command)[1]['status'] == 'completed'


def test_restart_reuses_first_committed_part_by_reference_without_copying(frozen):
    root, _, _, _, _, store, command, contract = frozen
    first_attempt = store.begin_attempt(command)['attempt_id']
    captured = []
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=authored_render(captured, fail_index=2)):
        with pytest.raises(RuntimeError, match='Authored interruption'):
            renderer.render_command(root, command['operation_id'], first_attempt, lambda *args: None, lambda: False)
    first = store.part_receipt(command, 1)
    store.update_attempt(command, first_attempt, status='interrupted')
    restarted = FinishingCommands(root)
    next_attempt = restarted.begin_attempt(command)['attempt_id']
    captured.clear()
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('shutil.copy2', side_effect=AssertionError('No media copying on resume')), \
         patch('app.media.render_part', side_effect=authored_render(captured)):
        renderer.render_command(root, command['operation_id'], next_attempt, lambda *args: None, lambda: False)
    assert [part['index'] for part, _, _ in captured] == [2]
    assert restarted.part_receipt(command, 1) == first
    assert restarted.part_receipt(command, 2)['attempt_id'] == next_attempt
    assert restarted._runtime(command)[1]['status'] == 'completed'


@pytest.mark.parametrize('failure', ['source_changed', 'renderer_changed', 'missing_decode_receipt'])
def test_changed_inputs_or_missing_real_validation_cannot_complete(frozen, failure):
    root, _, source, _, _, store, command, contract = frozen
    if failure == 'source_changed':
        source.write_bytes(b'Changed source')
    if failure == 'renderer_changed':
        contract = {'version': 1, 'code_sha256': 'b'*64}
    attempt = store.begin_attempt(command)['attempt_id']
    captured = []
    with patch.object(renderer, 'render_contract', return_value=contract), \
         patch('app.media.choose_encoder', return_value='authored'), \
         patch('app.media.render_part', side_effect=authored_render(captured, receipt=False)):
        with pytest.raises(CommandError):
            renderer.render_command(root, command['operation_id'], attempt, lambda *args: None, lambda: False)
    assert store._runtime(command)[1]['status'] != 'completed'
    assert store.part_receipt(command, 1) is None
    assert len(captured) == (1 if failure == 'missing_decode_receipt' else 0)
