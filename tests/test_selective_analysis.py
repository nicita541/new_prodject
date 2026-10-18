"""Selective scope mechanics; mocked semantics are never model-quality proof."""
import copy
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.selective_analysis import qualify_episode_map, resolve_scope, _technical_failures
from tests.test_selection_gate import accepted


def inputs():
    scenes = [{'id': f's{i}', 'start': i*10, 'end': (i+1)*10} for i in range(4)]
    windows = [{'id': f'w{i}', 'scene_id': f's{i}', 'start': i*10, 'end': i*10+5} for i in range(4)]
    episode_map = {'authority': 'hypothesis_only', 'windows': windows, 'coverage': [w['id'] for w in windows],
                   'hypotheses': [{'id': 'h', 'window_ids': ['w0', 'w3'], 'prerequisite_window_ids': ['w0']}]}
    return scenes, episode_map


def test_scope_union_and_original_neighbors_and_immutability():
    scenes, episode_map = inputs()
    before = copy.deepcopy((scenes, episode_map))
    scope = resolve_scope(scenes, episode_map)
    assert scope['event_ids'] == {'s0': 'event_0000', 's3': 'event_0003'}
    assert scope['context_scenes']['s0']['next']['id'] == 's1'
    assert scope['context_scenes']['s3']['previous']['id'] == 's2'
    assert scope['analyzed_ranges'] == [{'start': 0, 'end': 10}, {'start': 30, 'end': 40}]
    scope['scenes'][0]['start'] = 99
    assert (scenes, episode_map) == before


@pytest.mark.parametrize('field', ['window_ids', 'prerequisite_window_ids'])
def test_unknown_hypothesis_reference_fails_closed(field):
    scenes, episode_map = inputs()
    episode_map['hypotheses'][0][field] = ['invented']
    with pytest.raises(ValueError, match='unknown'):
        resolve_scope(scenes, episode_map)


def test_overlapping_windows_process_original_owner_once_and_expand_finite_prerequisite():
    scenes, episode_map = inputs()
    episode_map['windows'].append({'id': 'overlap', 'scene_id': 's0', 'start': 2, 'end': 8})
    episode_map['hypotheses'][0]['window_ids'].append('overlap')
    episode_map['hypotheses'][0]['prerequisite_window_ids'].append('w2')
    scope = resolve_scope(scenes, episode_map)
    assert [s['id'] for s in scope['scenes']] == ['s0', 's2', 's3']
    assert scope['analyzed_ranges'] == [{'start': 0, 'end': 10}, {'start': 20, 'end': 40}]


def test_window_cannot_claim_frames_outside_original_scene():
    scenes, episode_map = inputs()
    episode_map['windows'][0]['end'] = 11
    with pytest.raises(ValueError, match='ownership'):
        resolve_scope(scenes, episode_map)


def test_failed_model_contract_is_not_reported_as_only_semantic_uncertainty():
    failures = _technical_failures([
        {'id': 'uncertain', 'uncertain': True, 'uncertainty_reasons': ['missing_context']},
        {'id': 'failed', 'selection_adjudication': {'status': 'unresolved', 'decisions': [
            {'status': 'failed', 'reason': 'invalid_evidence', 'error_type': 'ValueError',
             'error': 'Private diagnostic path and model output stay local'}]}},
        {'id': 'recovered', 'uncertainty_reasons': ['model_failure'],
         'selection_adjudication': {'status': 'accepted'}},
        {'id': 'offline', 'uncertainty_reasons': ['model_failure']}])
    assert [row['event_id'] for row in failures] == ['failed', 'offline']
    assert failures[0]['reason'] == 'model_output_invalid'
    assert 'error' not in failures[0]


def test_truncated_generation_is_reported_as_technical_not_story_uncertainty():
    failures = _technical_failures([{'id': 'truncated', 'selection_adjudication': {
        'status': 'unresolved', 'decisions': [{'status': 'failed', 'reason': 'invalid_evidence',
            'error_type': 'ResponseContractError', 'error_category': 'response_length'}]}}])
    assert failures[0]['reason'] == 'model_output_truncated'


def test_native_qualification_preserves_failed_owner_and_qualifies_ready_owner():
    tmp_path = Path(__file__).resolve().parents[1]/'scratch'/'selective-native-mocked'
    scenes, episode_map = inputs()
    good = accepted()
    bad = copy.deepcopy(good)
    bad.update(id='event_0003', start=30, end=40, uncertain=True)
    transcript, shots = {'segments': [], 'words': []}, []
    original = copy.deepcopy((scenes, episode_map, transcript, shots))
    journal = Mock()
    journal.run.side_effect = lambda name, data, callback, producer: callback()
    sessions, session_calls = Mock(), []

    @contextmanager
    def session(*args, **kwargs):
        session_calls.append((args[2], kwargs))
        yield object()

    sessions.session.side_effect = session
    with ExitStack() as stack:
        native = stack.enter_context(patch('app.scene_analysis.analyze_scenes', return_value=[good, bad]))
        refine = stack.enter_context(patch('app.scene_refinement.refine_scene_story', side_effect=lambda events, *a, **k: events))
        stack.enter_context(patch('app.story.preserve_dialogue_in_credits', side_effect=lambda events, *a: events))
        adjudicate = stack.enter_context(patch('app.antigravity_batch.adjudicate_in_batches', side_effect=lambda source, events, *a, **k: events))
        structure = stack.enter_context(patch('app.story_structure_pass.infer_story_structure', side_effect=lambda events, *a, **k: {'events': events, 'arcs': []}))
        dialogue = stack.enter_context(patch('app.dialogue_relations.infer_dialogue_relations', return_value={'pairs': []}))
        stack.enter_context(patch('app.dialogue_relations.attach_dialogue_result', side_effect=lambda events, result: events))
        stack.enter_context(patch('app.analysis_result.analysis_result', side_effect=lambda job, provider, probe, tr, sh, events, **k: {'events': events, 'transcript': tr, 'shots': sh, 'scenes': k['scenes']}))
        stack.enter_context(patch('app.json_store.analysis_json'))
        result = qualify_episode_map('source.mp4', {'duration': 40}, transcript, shots, scenes,
            episode_map, tmp_path, sessions, 'deepseek_plan', Mock(), lambda: False, journal, Mock())
    assert [event['id'] for event in structure.call_args.args[0]] == ['event_0000']
    assert [event['id'] for event in dialogue.call_args.args[0]] == ['event_0000']
    assert result['events'][1]['uncertain'] is True
    assert result['selective_scope']['source_gate']['status'] == 'unresolved'
    assert session_calls[0] == ('local', {})
    assert session_calls[1][0] == 'deepseek_plan' and session_calls[1][1]['thinking'] is True
    assert native.call_args.kwargs['context_scenes']['s0']['next']['id'] == 's1'
    assert native.call_args.kwargs['event_ids']['s3'] == 'event_0003'
    assert adjudicate.call_args.kwargs['source_only'] is True
    refine.assert_not_called()
    from app.unit_decisions import CONTRACT
    assert adjudicate.call_args.kwargs['refiner'].keywords['decision_contract'] == CONTRACT
    assert all(call.args[0].startswith('selective_native_') for call in journal.run.call_args_list)
    assert (scenes, episode_map, transcript, shots) == original
