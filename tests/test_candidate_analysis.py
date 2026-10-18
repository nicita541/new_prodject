"""Candidate execution safety with authored evidence; no cloud or real inference."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

import pytest

from app import candidate_analysis as native
from app.analysis_questions import QuestionJournalError, QuestionLedger
from app.content_identity import file_sha256
from app.deepseek import ResponseContractError, RequestCapacityError


@pytest.fixture
def workspace():
    # pytest's restricted temporary-directory ACL is unsuitable in this sandbox.
    path = Path(__file__).resolve().parents[1] / 'temp' / ('candidate-tests-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
          'required': ['ok'], 'additionalProperties': False}
EVIDENCE = {'unit_ids': ['u_authored'], 'source': 'a' * 64}


def vision(answer=None, error=None):
    return SimpleNamespace(model='authored-model', projector='authored-projector', thinking=False,
        token_count=Mock(return_value=20), text_budget=64000,
        query=Mock(return_value={'ok': True} if answer is None else answer, side_effect=error))


def ask(root, client, *, provider='local', prompt='Authored source-only question', pages=()):
    # Recreate the ledger to exercise process-restart reuse, not an in-memory memo.
    return native._ask(QuestionLedger(root, 'a' * 64), client, provider,
        'candidate_proposal', prompt, SCHEMA, pages, EVIDENCE)


def test_completed_question_reuses_before_local_tokenization_or_query(workspace):
    original = vision()
    assert ask(workspace, original) == {'status': 'answered', 'raw': {'ok': True}}
    assert original.token_count.call_count == original.query.call_count == 1
    restarted = vision(error=AssertionError('must not acquire or query a model'))
    restarted.token_count.side_effect = AssertionError('warm reuse must not tokenize')
    assert ask(workspace, restarted) == {'status': 'answered', 'raw': {'ok': True}}
    restarted.token_count.assert_not_called()
    restarted.query.assert_not_called()


@pytest.mark.parametrize('error,reason', [
    (ResponseContractError('cut output', category='response_length', finish_reason='length'),
     'model_output_truncated'),
    (ResponseContractError('bad contract'), 'model_output_invalid'),
    (ValueError('bad JSON'), 'model_output_invalid'),
])
def test_known_failed_response_is_completed_and_not_redispatched(workspace, error, reason):
    original = vision(error=error)
    expected = {'status': 'technical_failed', 'reason': reason}
    assert ask(workspace, original) == expected
    restarted = vision(error=AssertionError('known negative must be cached'))
    assert ask(workspace, restarted) == expected
    restarted.token_count.assert_not_called()
    restarted.query.assert_not_called()
    ledger = QuestionLedger(workspace, 'a' * 64)
    assert len(list(ledger.root.glob('*.completed.json'))) == 1


def test_schema_invalid_return_is_a_known_negative_not_success(workspace):
    client = vision(answer={'ok': 'invented type'})
    assert ask(workspace, client) == {'status': 'technical_failed', 'reason': 'model_output_invalid'}
    assert ask(workspace, vision()) == {'status': 'technical_failed', 'reason': 'model_output_invalid'}
    assert client.query.call_count == 1


def test_unknown_transport_retains_reservation_and_restart_does_not_resend(workspace):
    client = vision(error=RuntimeError('transport outcome unknown'))
    with pytest.raises(RuntimeError):
        ask(workspace, client)
    restarted = vision()
    with pytest.raises(QuestionJournalError, match='unknown'):
        ask(workspace, restarted)
    restarted.query.assert_not_called()
    restarted.token_count.assert_not_called()
    ledger = QuestionLedger(workspace, 'a' * 64)
    assert len(list(ledger.root.glob('*.reserved.json'))) == 1
    assert not list(ledger.root.glob('*.completed.json'))


def test_context_limit_is_cached_without_query(workspace):
    client = vision()
    client.token_count.return_value = 8192
    assert ask(workspace, client) == {'status': 'context_limit'}
    client.query.assert_not_called()
    restarted = vision(error=AssertionError('known limit is a result'))
    assert ask(workspace, restarted) == {'status': 'context_limit'}
    restarted.query.assert_not_called()


def test_deepseek_capacity_uses_actual_adapter_wire_instead_of_expanded_schema(workspace):
    from app import deepseek
    # Local validation retains this verbose schema. Its lossless wire form fits
    # the adapter; checking canonical JSON here would block a valid request.
    repeated = {'type': 'string', 'enum': [f'authored-value-{i}' for i in range(50)]}
    schema = {'type': 'object', 'properties': {
        'ok': {'type': 'boolean'}, **{f'optional_{i}': repeated for i in range(100)}},
        'required': ['ok'], 'additionalProperties': False}
    assert len(json.dumps(schema).encode()) > 64000
    client = deepseek.DeepSeekVision(workspace, lambda: False)
    with patch.object(deepseek, '_key', return_value='test-key'), \
            patch.object(deepseek, 'RESPONSES', workspace/'responses'), \
            patch.object(client, '_fetch', return_value={
                'choices': [{'message': {'content': '{"ok":true}'}}]}) as fetch:
        result = native._ask(QuestionLedger(workspace, 'a'*64), client, 'deepseek_plan',
            'candidate_screen', 'Authored cut-only question', schema, [], EVIDENCE)
    assert result == {'status': 'answered', 'raw': {'ok': True}}
    fetch.assert_called_once()
    assert len(fetch.call_args.args[0]['messages'][1]['content'][0]['text'].encode()) < 64000


def test_only_legacy_unsent_deepseek_capacity_result_migrates_and_then_reuses(workspace):
    ledger = QuestionLedger(workspace, 'a'*64)
    recorder = SimpleNamespace(run=Mock(return_value={'status': 'answered', 'raw': {'ok': True}}))
    native._ask(recorder, vision(), 'deepseek_plan', 'candidate_screen',
        'Authored old capacity question', SCHEMA, [], EVIDENCE)
    # Reproduce a persisted pre-fix capacity rejection under the original key.
    ledger.run(recorder.run.call_args.args[0], lambda: {'status': 'context_limit'})
    client = vision()
    assert native._ask(ledger, client, 'deepseek_plan', 'candidate_screen',
        'Authored old capacity question', SCHEMA, [], EVIDENCE)['status'] == 'answered'
    client.query.assert_called_once()
    client.query.side_effect = AssertionError('Warm capacity migration must not send again')
    assert native._ask(ledger, client, 'deepseek_plan', 'candidate_screen',
        'Authored old capacity question', SCHEMA, [], EVIDENCE)['status'] == 'answered'


def test_deepseek_preflight_change_never_migrates_unknown_dispatch(workspace):
    client = vision(error=RuntimeError('Authored unknown transport outcome'))
    with pytest.raises(native.CandidateDispatchError):
        ask(workspace, client, provider='deepseek_plan')
    restarted = vision()
    with pytest.raises(QuestionJournalError, match='unknown'):
        ask(workspace, restarted, provider='deepseek_plan')
    restarted.query.assert_not_called()


@pytest.mark.parametrize('dispatched,status,reason', [
    (False, 'context_limit', 'provider_request_capacity'),
    (True, 'technical_failed', 'correction_request_capacity')])
def test_provider_capacity_distinguishes_unsent_packet_from_paid_response(workspace, dispatched, status, reason):
    first = vision(error=RequestCapacityError('Authored capacity rejection', dispatched=dispatched))
    expected = {'status': status, 'reason': reason}
    assert ask(workspace, first) == expected
    restarted = vision(error=AssertionError('Known capacity result must not repeat'))
    assert ask(workspace, restarted) == expected
    restarted.query.assert_not_called()
    restarted.token_count.assert_not_called()


def test_visual_proposal_shrinks_only_preflight_miss_and_warm_never_tokenizes(workspace):
    owned = authored_case()
    frames = [{'index': i, 'unit': 'u_authored', 'time': i/10,
               'sha256': f'{i:064x}', 'path': str(workspace/f'frame-{i}.jpg')} for i in range(1, 37)]
    pages = [workspace/'board-1.jpg', workspace/'board-2.jpg']
    for index, page in enumerate(pages):
        page.write_bytes(f'Authored board {index}; no real image inference'.encode())
    def physical(source, analysis, case, directory, provider, cancelled, *, page_budget):
        return {**case, 'frames': frames[:18*page_budget]}
    def boards(case, *args, **kwargs):
        return pages[:(len(case['frames'])+17)//18]
    negative = {'viable': False, 'title': 'No story', 'reason': 'Authored proposal negative',
                'interest': 1, 'cuts': []}
    first = vision(answer=negative)
    first.token_count.return_value = 2000  # Two pages cannot fit8192; one can.
    record = {}
    def run(client, target):
        return native._propose_candidate(workspace/'source.mp4', source_analysis(), owned, {}, target,
            workspace, 'local', client, QuestionLedger(workspace, 'a'*64), lambda: False)
    with patch.object(native, '_prepare_proposal_frames', side_effect=physical), \
            patch.object(native, '_pages', side_effect=boards):
        assert run(first, record) == {'status': 'answered', 'raw': negative}
        assert [row['status'] for row in record['proposal_capacity_attempts']] == ['context_limit', 'answered']
        assert first.query.call_count == 1  # No dispatch/correction for oversized packet.
        assert first.token_count.call_count == 2
        restarted = vision(error=AssertionError('Warm request forbidden'))
        restarted.token_count.side_effect = AssertionError('Warm tokenization forbidden')
        assert run(restarted, {}) == {'status': 'answered', 'raw': negative}
        restarted.query.assert_not_called()
        restarted.token_count.assert_not_called()
    restarted.token_count.assert_not_called()


def test_source_bound_proposal_keeps_private_preview_separate_and_reuses_exact_question(workspace):
    owned = {**authored_case(), 'proposal_policy': dict(native.PROPOSAL_POLICY)}
    frames = [{'index': i, 'unit': 'u_authored', 'time': float(i),
        'sha256': f'{i:064x}', 'path': str(workspace/f'frame-{i}.jpg')} for i in (1, 2, 3)]
    page = workspace/'shot-rows.jpg'
    page.write_bytes(b'Authored shot rows; no real image inference')
    mapping = [{'image': 1, 'row': 1, 'source_start': 0., 'source_end': 6.,
                'frames': [{key: frame[key] for key in ('index', 'time')} for frame in frames]}]
    negative = {'viable': False, 'title': 'No observed payoff', 'reason': 'Authored negative',
                'interest': 1, 'cuts': [], 'beats': []}
    first, record = vision(answer=negative), {}
    def run(client, target):
        return native._propose_candidate(workspace/'source.mp4', source_analysis(), owned, {}, target,
            workspace, 'local', client, QuestionLedger(workspace, 'a'*64), lambda: False)
    with patch.object(native, '_prepare_proposal_frames', return_value={**owned, 'frames': frames}), \
            patch.object(native, '_proposal_pages', return_value=([page], mapping)):
        assert run(first, record) == {'status': 'answered', 'raw': negative}
        assert owned['frames'] == [] and 'proposal_observations' not in owned
        assert record['case']['frames'] == []
        assert record['case']['proposal_observations'] == frames
        assert record['case']['proposal_observations'] is not record['proposal_observations']
        payload = json.loads(first.query.call_args.args[0].split('\n')[-1])
        assert payload['proposal_shots'] == mapping
        assert payload['proposal_policy'] == native.PROPOSAL_POLICY
        restarted = vision(error=AssertionError('No warm transport'))
        restarted.token_count.side_effect = AssertionError('No warm tokenization')
        assert run(restarted, {}) == {'status': 'answered', 'raw': negative}
        restarted.query.assert_not_called()
        restarted.token_count.assert_not_called()


def test_unknown_source_bound_dispatch_never_shrinks_or_resamples(workspace):
    owned = {**authored_case(), 'proposal_policy': dict(native.PROPOSAL_POLICY)}
    with patch.object(native, '_prepare_proposal_frames', return_value=owned) as physical, \
            patch.object(native, '_proposal_pages', return_value=([], [])), \
            patch.object(native, '_ask', side_effect=native.CandidateDispatchError('Authored unknown')):
        with pytest.raises(native.CandidateDispatchError):
            native._propose_candidate(workspace/'source.mp4', source_analysis(), owned, {}, {},
                workspace, 'local', vision(), Mock(), lambda: False)
    physical.assert_called_once()


def test_source_review_stores_compiled_binding_but_does_not_receive_preview_beats(workspace):
    owned = {**authored_case(), 'proposal_policy': dict(native.PROPOSAL_POLICY),
        'proposal_observations': [{'index': 99, 'unit': 'u_authored', 'time': 1.,
                                  'sha256': 'c'*64, 'path': 'PRIVATE_PREVIEW_PATH'}]}
    proposal = {'viable': True, 'title': 'PRIVATE_TITLE', 'reason': 'PRIVATE_REASON', 'interest': 3,
        'cuts': [{'first': 'u_authored', 'last': 'u_authored'}],
        'beats': [{'role': role, 'kind': 'speech', 'first': 'u_authored', 'last': 'u_authored',
                   'quote': 'Original', 'frames': [], 'states': []}
                  for role in ('setup', 'development', 'payoff')]}
    plan = {'parts': [{'cuts': [{'start': 0., 'end': 6.}]}],
            'proposal_binding': {'private': 'PRIVATE_COMPILED_BINDING'}}
    frame = {'index': 1, 'unit': 'u_authored', 'time': 1., 'sha256': 'b'*64, 'path': 'own.jpg'}
    record = {}
    def framed(source, case, *args, **kwargs):
        return {**case, 'frames': [frame]}
    with patch.object(native, 'with_cut_context', side_effect=lambda analysis, case, p: case), \
            patch.object(native, 'prototype_plan', return_value=(plan, {})), \
            patch.object(native, '_prepare_frames', side_effect=framed), \
            patch.object(native, '_pages', return_value=[]), \
            patch.object(native, 'review_schema', return_value={}), \
            patch.object(native, '_ask', return_value={'status': 'answered', 'raw': {'requested_units': []}}) as ask_model, \
            patch.object(native, 'review_status', return_value='needs_review'):
        native._qualify_edit(workspace/'source.mp4', {**source_analysis(),
            'proposal_policy': dict(native.PROPOSAL_POLICY)}, owned, proposal, record,
            workspace, 'local', vision(), Mock(), Mock(), lambda: False)
    assert record['proposal_binding'] == plan['proposal_binding']
    assert record['proposal_binding'] is not plan['proposal_binding']
    assert record['case']['proposal_observations'] == owned['proposal_observations']
    prompt = ask_model.call_args.args[4]
    for private in ('PRIVATE_', 'beats', 'proposal_observations', 'proposal_binding'):
        assert private not in prompt
    payload = json.loads(prompt.split('\n')[-1])
    assert payload['original_frames'] == [{'index': 1, 'time': 1.}]


def test_changed_original_image_hash_requires_new_question(workspace):
    image = workspace / 'authored-image.bin'
    image.write_bytes(b'authored original image A; not decoded in this request test')
    client = vision()
    ask(workspace, client, pages=[image])
    image.write_bytes(b'authored original image B; changed source evidence')
    ask(workspace, client, pages=[image])
    assert client.query.call_count == 2


@pytest.mark.parametrize('relocated', ['page', 'frame'])
def test_identical_owned_evidence_relocated_on_disk_reuses_before_model_acquisition(workspace, relocated):
    page = workspace / 'original-page.jpg'
    page.write_bytes(b'authored identical storyboard bytes; not decoded by this transport test')
    evidence = {'unit_ids': ['u_authored'], 'frames': [{'index': 1, 'unit': 'u_authored',
        'time': 1.0, 'sha256': 'b' * 64, 'path': str(workspace/'original-frame.jpg')}]}
    client = vision()
    first = native._ask(QuestionLedger(workspace, 'a' * 64), client, 'local',
        'candidate_review', 'Same original source facts', SCHEMA, [page], evidence)
    changed = copy.deepcopy(evidence)
    if relocated == 'page':
        page = workspace / 'relocated-page.jpg'
        page.write_bytes(b'authored identical storyboard bytes; not decoded by this transport test')
    else:
        changed['frames'][0]['path'] = str(workspace/'relocated-frame.jpg')
    restarted = vision(error=AssertionError('storage relocation must not redispatch'))
    restarted.token_count.side_effect = AssertionError('storage relocation must not acquire model')
    assert native._ask(QuestionLedger(workspace, 'a' * 64), restarted, 'local',
        'candidate_review', 'Same original source facts', SCHEMA, [page], changed) == first
    restarted.query.assert_not_called()
    restarted.token_count.assert_not_called()


class Journal:
    def __init__(self, saved=None):
        self.saved = saved
        self.loaded = []
        self.executions = 0

    def load(self, name, inputs):
        self.loaded.append((name, copy.deepcopy(inputs)))
        return copy.deepcopy(self.saved)

    def run(self, name, inputs, callback, producer):
        self.executions += 1
        self.saved = callback()
        return copy.deepcopy(self.saved)


def source_analysis():
    return {'probe': {'duration': 6}, 'transcript': {'segments': []}, 'shots': [],
            'source_sha256': 'a' * 64, 'episode_map': {'hypotheses': []}}


@pytest.mark.parametrize('saved', [None, {'candidate_records': [], 'authored_cached': True}])
def test_plan_only_loads_cache_before_sessions_and_never_infers_on_miss(workspace, saved):
    journal = Journal(saved)
    with patch('app.analysis_provider._model_files_for_provider', return_value=()), \
         patch('app.vision.AnalysisVisionSessions', side_effect=AssertionError('must not open sessions')) as sessions:
        args = (workspace / 'source.mp4', source_analysis(), {'max_clips': 2}, workspace,
                'local', Mock(), lambda: False, journal)
        if saved is None:
            with pytest.raises(ValueError, match='модели не запускались'):
                native.qualify_candidates(*args, allow_new=False)
        else:
            assert native.qualify_candidates(*args, allow_new=False) == saved
    assert journal.executions == 0
    sessions.assert_not_called()


class Sessions:
    def __init__(self, client):
        self.client = client
        self.opened = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def session(self, *args, **kwargs):
        self.opened += 1
        yield self.client


def authored_case():
    return {'id': 'h_authored', 'source_sha256': 'a' * 64,
        'units': [{'id': 'u_authored', 'start': 0, 'end': 6, 'text': 'Original authored ASR'}],
        'hypothesis': {'title': 'HYPOTHESIS_SECRET', 'reason': 'HYPOTHESIS_JUSTIFICATION'},
        'frames': []}


def run_authored_candidate(workspace, client, requested=(), *, frame_records=None, cuts=None, review_error=None,
                           overview_pages=()):
    """Mock physical adapters only; retain actual question ledger and dispatch."""
    case = authored_case()
    frame = {'index': 1, 'unit': 'u_authored', 'time': 1.0, 'sha256': 'b' * 64,
             'path': str(workspace / 'authored-frame.jpg')}
    framed = {**case, 'source_join_policy': dict(native.SOURCE_JOIN_POLICY),
              'frames': frame_records if frame_records is not None else [frame]}
    page = workspace / 'authored-page.jpg'
    page.write_bytes(b'authored storyboard transport bytes; no real media')
    plan = {'parts': [{'cuts': cuts if cuts is not None else [{'start': 0, 'end': 6}]}]}
    sessions = Sessions(client)
    review = {'requested_units': list(requested)}
    schema = {'type': 'object', 'properties': {'requested_units': {
        'type': 'array', 'items': {'type': 'string'}}}, 'required': ['requested_units']}
    with patch('app.analysis_provider._model_files_for_provider', return_value=()), \
         patch('app.vision.AnalysisVisionSessions', return_value=sessions), \
         patch.object(native, 'candidate_cases', return_value=[case]), \
         patch.object(native, 'with_cut_context', side_effect=lambda analysis, owned, proposal: owned), \
         patch.object(native, 'prototype_plan', return_value=(plan, {})), \
         patch.object(native, '_prepare_proposal_frames', return_value=framed), \
         patch.object(native, '_prepare_frames', return_value=framed) as frames, \
         patch.object(native, '_pages', return_value=[page]), \
         patch.object(native, '_join_change_pages', return_value=(list(overview_pages), [])), \
         patch.object(native, 'review_schema', return_value=schema), \
         patch.object(native, 'review_status', return_value='needs_review', side_effect=review_error):
        result = native.qualify_candidates(workspace/'source.mp4', source_analysis(),
            {'max_clips': 2}, workspace, 'local', Mock(), lambda: False, Journal())
    return result, frames, review


def test_independent_review_omits_proposer_title_reason_and_hypothesis(workspace):
    proposal = {'viable': True, 'title': 'PROPOSER_SECRET_TITLE', 'reason': 'PROPOSER_SECRET_REASON',
                'interest': 3, 'cuts': [{'first': 'u_authored', 'last': 'u_authored'}]}
    client = vision()
    client.query.side_effect = [proposal, {'requested_units': []}]
    result, _, _ = run_authored_candidate(workspace, client)
    assert result['candidate_records'][0]['status'] == 'needs_review'
    assert client.query.call_count == 2
    proposed_payload = json.loads(client.query.call_args_list[0].args[0].split('\n')[-1])
    assert proposed_payload['original_frames'] == [{'index': 1, 'time': 1.0}]
    assert proposed_payload['source_units'][0]['frame_indices'] == [1]
    assert client.query.call_args_list[0].args[1] == [workspace/'authored-page.jpg']
    prompt = client.query.call_args_list[1].args[0]
    for prohibited in ('PROPOSER_SECRET_TITLE', 'PROPOSER_SECRET_REASON',
                       'HYPOTHESIS_SECRET', 'HYPOTHESIS_JUSTIFICATION'):
        assert prohibited not in prompt
    payload = json.loads(prompt.split('\n')[-1])
    assert payload['source_units'][0]['text'] == 'Original authored ASR'
    assert payload['actual_cuts'] == [[{'start': 0, 'end': 6}]]
    assert payload['original_frames'] == [{'index': 1, 'time': 1.0}]
    assert {unit['id']: unit['frame_indices'] for unit in payload['source_units']} == {'u_authored': [1]}
    assert payload['retained_spoken_units'] == ['u_authored']
    assert payload['boundary_anchors'] == [{'cut': 1, 'side': 'start', 'frame': 1},
                                          {'cut': 1, 'side': 'end', 'frame': 1}]


def test_review_packet_names_actual_own_anchors_for_each_cut_not_context_frames(workspace):
    proposal = {'viable': True, 'title': 'PRIVATE_PROPOSAL_TITLE', 'reason': 'PRIVATE_PROPOSAL_REASON',
                'interest': 3, 'cuts': [{'first': 'u_authored', 'last': 'u_authored'}]}
    client = vision()
    client.query.side_effect = [proposal, {'requested_units': []}]
    frames = [{'index': i, 'unit': 'u_authored', 'time': time, 'sha256': 'b' * 64,
               'path': str(workspace/f'authored-{i}.jpg')}
              for i, time in enumerate((.5, 1.04, 1.96, 3., 4.04, 4.96, 5.5), 1)]
    result, _, _ = run_authored_candidate(workspace, client, frame_records=frames,
        cuts=[{'start': 1., 'end': 2.}, {'start': 4., 'end': 5.}])
    assert result['candidate_records'][0]['status'] == 'needs_review'
    prompt = client.query.call_args_list[1].args[0]
    payload = json.loads(prompt.split('\n')[-1])
    assert payload['boundary_anchors'] == [
        {'cut': 1, 'side': 'start', 'frame': 2}, {'cut': 1, 'side': 'end', 'frame': 3},
        {'cut': 2, 'side': 'start', 'frame': 5}, {'cut': 2, 'side': 'end', 'frame': 6}]
    assert len(payload['original_frames']) == 7  # Omitted context is explicitly visible.
    assert payload['source_join_policy'] == native.SOURCE_JOIN_POLICY
    assert payload['source_joins'] == [{'after_cut': 1, 'start': 2., 'end': 4.,
        'left_frame': 3, 'right_frame': 5, 'omitted_frames': [4], 'unit_ids': ['u_authored']}]
    assert {unit['id']: unit['frame_indices'] for unit in payload['source_units']} == {
        'u_authored': list(range(1, 8))}
    assert all(set(frame) == {'index', 'time'} for frame in payload['original_frames'])
    for secret in ('PRIVATE_PROPOSAL_TITLE', 'PRIVATE_PROPOSAL_REASON', 'HYPOTHESIS_SECRET'):
        assert secret not in prompt


def test_added_overviews_count_toward_actual_provider_page_capacity(workspace):
    client = vision()
    client.query.return_value = {'viable': True, 'title': 'Authored', 'reason': 'Capacity fixture',
        'interest': 3, 'cuts': [{'first': 'u_authored', 'last': 'u_authored'}]}
    result, _, _ = run_authored_candidate(workspace, client,
        overview_pages=[workspace/'pair-1.jpg', workspace/'pair-2.jpg'])
    assert result['candidate_records'][0]['status'] == 'context_limit'
    assert client.query.call_count == 1  # Proposal only: no evidence was dropped to fit.


def test_raw_semantically_invalid_review_and_validation_error_survive_and_reuse(workspace):
    proposal = {'viable': True, 'title': 'Authored proposal', 'reason': 'Mechanism test',
                'interest': 3, 'cuts': [{'first': 'u_authored', 'last': 'u_authored'}]}
    raw_review = {'requested_units': []}
    client = vision()
    client.query.side_effect = [proposal, raw_review]
    result, _, _ = run_authored_candidate(workspace, client,
        review_error=ValueError('Authored source ownership mismatch'))
    record = result['candidate_records'][0]
    assert record['status'] == 'technical_failed'
    assert record['review'] == raw_review
    assert record['validation_error'] == 'Authored source ownership mismatch'
    assert isinstance(record['timeline_digest'], str)
    saved = json.loads((workspace/'candidate-analysis.json').read_text(encoding='utf-8'))
    assert saved['candidate_records'][0] == record
    assert len(saved['analysis_technical_failures']) == 1
    restarted = vision(error=AssertionError('known raw review must not redispatch'))
    restarted.token_count.side_effect = AssertionError('known raw review must not acquire model')
    warm, _, _ = run_authored_candidate(workspace, restarted,
        review_error=ValueError('Authored source ownership mismatch'))
    assert warm['candidate_records'][0] == record
    restarted.query.assert_not_called()
    restarted.token_count.assert_not_called()


def test_review_schema_rejects_speech_proof_with_motion_before_dispatch(workspace):
    from app.deepseek import _validate
    from app.story_candidates import review_schema
    from tests.test_story_candidates import candidate_fixture
    _, record, plan = candidate_fixture()
    schema = review_schema(record['case'], record['proposal'], plan)
    raw = copy.deepcopy(record['review'])
    _validate(raw, schema)
    raw['proofs'][0]['frames'] = [1, 2]
    raw['proofs'][0]['motion'] = [{'frame': 1, 'state': 'Closed'}, {'frame': 2, 'state': 'Open'}]
    with pytest.raises(ValueError):
        _validate(raw, schema)
    client = vision()
    # The supplied wire schema already forbids the contradiction; it cannot be
    # accepted as a source-qualified response even if the provider ignores it.
    client.query.return_value = raw
    result = native._ask(QuestionLedger(workspace, 'a' * 64), client, 'local',
        'candidate_review', 'Authored speech/motion contradiction', schema, [], EVIDENCE)
    assert result == {'status': 'technical_failed', 'reason': 'model_output_invalid'}


def test_review_wire_schema_rejects_cross_unit_appearance_frame_before_query():
    from app.deepseek import _validate
    from app.story_candidates import review_schema
    from tests.test_story_candidates import candidate_fixture
    _, record, plan = candidate_fixture()
    schema = review_schema(record['case'], record['proposal'], plan)
    raw = copy.deepcopy(record['review'])
    first = raw['proofs'][0]
    first.update(mode='appearance', quote='', frames=[1], motion=[])
    _validate(raw, schema)  # Own frame for the first original interval is valid.
    first['frames'] = [3]  # Global original image exists, but belongs to unit B.
    with pytest.raises(ValueError):
        _validate(raw, schema)


def test_review_wire_schema_speech_proof_cannot_attach_even_its_own_visual_frame():
    from app.deepseek import _validate
    from app.story_candidates import review_schema
    from tests.test_story_candidates import candidate_fixture
    _, record, plan = candidate_fixture()
    schema = review_schema(record['case'], record['proposal'], plan)
    raw = copy.deepcopy(record['review'])
    _validate(raw, schema)
    assert raw['proofs'][0]['mode'] == 'speech'
    assert raw['proofs'][0]['frames'] == []
    raw['proofs'][0]['frames'] = [1]
    with pytest.raises(ValueError):
        _validate(raw, schema)


@pytest.mark.parametrize('invalid', ['wrong_anchor', 'outside_cut'])
def test_review_wire_schema_owns_each_actual_cut_boundary(invalid):
    from app.deepseek import _validate
    from app.story_candidates import prototype_plan, review_schema
    from tests.test_story_candidates import candidate_fixture
    analysis, record, _ = candidate_fixture()
    case, proposal = record['case'], record['proposal']
    first, _, last = case['units']
    proposal['cuts'] = [{'first': unit['id'], 'last': unit['id']} for unit in (first, last)]
    plan, _ = prototype_plan(analysis, case, proposal)
    schema = review_schema(case, proposal, plan)['properties']['boundaries']
    correct = {'cut': 1, 'side': 'start', 'safe': True, 'frames': [1],
               'evidence': 'Authored first retained edge'}
    _validate([correct], schema)
    wrong = copy.deepcopy(correct)
    wrong['frames'] = [2] if invalid == 'wrong_anchor' else [1, 3]
    with pytest.raises(ValueError):
        _validate([wrong], schema)


def test_identical_enrichment_evidence_never_redispatches_same_native_question(workspace):
    proposal = {'viable': True, 'title': 'Authored', 'reason': 'Mechanism fixture',
                'interest': 3, 'cuts': [{'first': 'u_authored', 'last': 'u_authored'}]}
    client = vision()
    client.query.side_effect = [proposal, {'requested_units': ['u_authored']}]
    result, frames, _ = run_authored_candidate(workspace, client, requested=['u_authored'])
    assert result['candidate_records'][0]['status'] == 'needs_review'
    assert client.query.call_count == 2  # One proposal and one review; no third transport.
    assert client.token_count.call_count == 2
    assert frames.call_count <= 2


@pytest.mark.parametrize('unknown', [False, True])
def test_known_candidate_failure_isolated_but_unknown_dispatch_stops_further_requests(workspace, unknown):
    cases = [authored_case(), authored_case()]
    cases[1]['id'] = 'h_second'
    cases[1]['hypothesis']['id'] = 'h_second'
    declined = {'viable': False, 'title': 'No story', 'reason': 'Authored negative result',
                'interest': 1, 'cuts': []}
    client = vision()
    first = RuntimeError('unknown transport') if unknown else ResponseContractError('known invalid JSON')
    client.query.side_effect = [first, declined]
    sessions = Sessions(client)
    with patch('app.analysis_provider._model_files_for_provider', return_value=()), \
         patch('app.vision.AnalysisVisionSessions', return_value=sessions), \
         patch.object(native, 'candidate_cases', return_value=cases), \
         patch.object(native, '_prepare_proposal_frames', side_effect=lambda source, analysis, case, *a, **kw: case) as physical, \
         patch.object(native, '_pages', return_value=[]):
        result = native.qualify_candidates(workspace/'source.mp4', source_analysis(), {},
            workspace, 'local', Mock(), lambda: False, Journal())
    records = result['candidate_records']
    assert records[0]['status'] == 'technical_failed'
    assert records[1]['status'] == ('technical_failed' if unknown else 'declined')
    assert client.query.call_count == (1 if unknown else 2)
    assert physical.call_count == (1 if unknown else 2)
    assert sessions.opened == (1 if unknown else 2)
    assert len(result['analysis_technical_failures']) == (2 if unknown else 1)
    if unknown:
        assert all(row['reason'] == 'unknown_dispatch' for row in records)


def test_original_image_page_reuse_and_tamper_fail_closed(workspace):
    from PIL import Image
    directory = workspace / 'candidate-evidence'
    directory.mkdir()
    image = directory / 'authored-original.jpg'
    with Image.new('RGB', (320, 180), '#123456') as picture:
        picture.save(image)
    case = {'frames': [{'index': 1, 'unit': 'u_authored', 'time': 1.0,
                       'path': str(image), 'sha256': file_sha256(image)}]}
    pages = native._pages(case, directory / 'pages', lambda: False)
    assert len(pages) == 1
    original_hash = file_sha256(pages[0])
    assert native._pages(case, directory / 'pages', lambda: False) == pages
    assert file_sha256(pages[0]) == original_hash
    # New identity forces page construction and must verify original image bytes.
    image.write_bytes(b'not the source image anymore')
    changed = copy.deepcopy(case)
    changed['frames'][0]['time'] = 2.0
    with pytest.raises(ValueError, match='source image changed'):
        native._pages(changed, directory / 'pages', lambda: False)


def test_join_endpoint_pair_labels_actual_omitted_frames_and_reuses_verified_page(workspace):
    from PIL import Image
    directory = workspace/'candidate-evidence'
    directory.mkdir()
    frames = []
    for index, time in enumerate((.5, 1., 2., 3., 4., 4.5), 31):
        image = directory/f'frame-{index}.jpg'
        with Image.new('RGB', (320, 180), (index*3, 50, 90)) as picture:
            picture.save(image)
        frames.append({'index': index, 'unit': 'u', 'time': time, 'requested_time': 999.,
                       'path': str(image), 'sha256': file_sha256(image)})
    case = {'source_join_policy': dict(native.SOURCE_JOIN_POLICY), 'frames': frames,
            'units': [{'id': 'u', 'start': 0., 'end': 5.}]}
    edit = {'parts': [{'cuts': [{'start': 0., 'end': 1.}, {'start': 4., 'end': 5.}]}]}
    before = copy.deepcopy((case, edit))
    pages, mapping = native._join_change_pages(case, edit, directory/'join-pages', lambda: False)
    assert mapping == [{'after_cut': 1, 'image': 1, 'before_frame': 32, 'after_frame': 34}]
    assert len(pages) == 1
    with Image.open(pages[0]) as picture:
        assert picture.size == (640, 240)
        assert abs(picture.getpixel((20, 100))[0]-96) <= 2
        assert abs(picture.getpixel((340, 100))[0]-102) <= 2
    assert native._join_change_pages(case, edit, directory/'join-pages', lambda: False) == (pages, mapping)
    assert (case, edit) == before
    pages[0].write_bytes(b'torn overview')
    rebuilt, same = native._join_change_pages(case, edit, directory/'join-pages', lambda: False)
    with Image.open(rebuilt[0]) as picture:
        assert picture.size == (640, 240)
    assert same == mapping
    Path(frames[1]['path']).write_bytes(b'changed source')
    pages[0].unlink()
    with pytest.raises(ValueError, match='source image changed'):
        native._join_change_pages(case, edit, directory/'join-pages', lambda: False)


@pytest.mark.parametrize('policy', [None, {'version': 1}])
def test_old_join_policies_do_not_add_new_pair_images(workspace, policy):
    case = {'source_join_policy': policy}
    assert native._join_change_pages(case, {}, workspace/'pages', lambda: False) == ([], [])


def repair_execution_fixture():
    from tests.test_candidate_screen import repair_fixture
    from app.source_text import source_text
    analysis, case, plan, projection, screen, proposal, _ = repair_fixture()
    for unit in case['units']:
        unit['text'] = source_text(analysis['transcript'], unit['start'], unit['end'])
    case.update(id='h_repair', hypothesis={'id': 'h_repair', 'note': 'Authored hypothesis only'})
    analysis.update(episode_map={'hypotheses': []}, source_sha256=case['source_sha256'], shots=[])
    record = {'case': copy.deepcopy(case), 'proposal': copy.deepcopy(proposal),
              'source_status': 'ready', 'status': 'needs_review', 'screen': screen,
              'review': {'original_source_proof': 'authored'},
              'timeline_digest': native.timeline_digest(plan)}
    trimmed = {'semantic_ranges': [{'start': 2., 'end': 6.}],
               'parts': [{'cuts': [{'start': 1.8, 'end': 6.2}]}]}
    return analysis, case, plan, projection, record, proposal, trimmed


@pytest.mark.parametrize('cuts,maximum', [
    ([{'start': 0., 'end': 1.9}, {'start': 2., 'end': 6.}], 6.),
    ([{'start': -.1, 'end': 3.}, {'start': 4., 'end': 6.}], 6.),
    ([{'start': 0., 'end': 2.}, {'start': 4., 'end': 6.}], 6.),
    ([{'start': 0., 'end': 3.}, {'start': 4., 'end': 6.}], 4.),
])
def test_source_restoration_rejects_lost_content_outer_expansion_no_change_or_excess_duration(workspace, cuts, maximum):
    original = {'parts': [{'cuts': [{'start': 0., 'end': 2.}, {'start': 4., 'end': 6.}]}]}
    changed = {'parts': [{'cuts': cuts}]}
    case, proposal = authored_case(), {'authored_original': True}
    restored = {'authored_restored': True}
    record = {'status': 'needs_review', 'review': {'authored_failed_gap': True}}
    with patch.object(native, 'proposal_from_source_joins', return_value=restored), \
            patch.object(native, 'with_cut_context', return_value=case), \
            patch.object(native, '_audio_case', return_value=case) as audio, \
            patch.object(native, 'prototype_plan', return_value=(changed, {})), \
            patch.object(native, '_qualify_edit', side_effect=AssertionError('Invalid restoration must not query')) as qualify:
        result, _ = native._restore_source_joins(workspace/'source.mp4', source_analysis(), proposal,
            record, original, case, workspace, 'local', vision(), Mock(), Mock(), lambda: False,
            max_duration=maximum)
    assert result == original
    assert record['repair_attempt']['status'] == 'rejected'
    assert record['status'] == 'needs_review'
    audio.assert_called_once()  # Validate measured audible geometry, not just semantic IDs.
    qualify.assert_not_called()


def test_source_restoration_rechecks_changed_edit_once_and_cannot_then_trim_again(workspace):
    original = {'parts': [{'cuts': [{'start': 0., 'end': 2.}, {'start': 4., 'end': 6.}]}]}
    changed = {'parts': [{'cuts': [{'start': 0., 'end': 3.}, {'start': 4., 'end': 6.}]}]}
    case, proposal = authored_case(), {'authored_original': True}
    restored = {'authored_restored': True}
    record = {'case': case, 'status': 'needs_review', 'review': {'authored_failed_gap': True}}
    def checked(source, analysis, context, proposed, stored, *args):
        assert proposed == restored
        assert stored['qualification_history'][0]['review'] == {'authored_failed_gap': True}
        assert 'review' not in stored  # The old approval cannot qualify changed geometry.
        stored.update(status='needs_review', source_status='ready',
                      review={'authored_fresh_source': True}, screen={'authored_fresh_blind': True})
        return changed, context
    with patch.object(native, 'proposal_from_source_joins', return_value=restored) as derive, \
            patch.object(native, 'with_cut_context', return_value=case), \
            patch.object(native, '_audio_case', return_value=case), \
            patch.object(native, 'prototype_plan', return_value=(changed, {})), \
            patch.object(native, '_qualify_edit', side_effect=checked) as qualify, \
            patch('app.candidate_screen.proposal_from_repair', side_effect=AssertionError('No second editorial repair')) as trim:
        args = (workspace/'source.mp4', source_analysis(), proposal, record, original, case,
                workspace, 'local', vision(), Mock(), Mock(), lambda: False)
        result, _ = native._restore_source_joins(*args, max_duration=6.)
        native._restore_source_joins(*args, max_duration=6.)
        native._repair_candidate(*args)
    assert result == changed
    assert record['repair_attempt']['added_source_ranges'] == [{'start': 2., 'end': 3.}]
    assert record['repair_attempt']['status'] == 'needs_review'
    assert record['proposal'] == restored and record['original_proposal'] == proposal
    derive.assert_called_once()
    qualify.assert_called_once()
    trim.assert_not_called()


@pytest.mark.parametrize('final_status', ['ready', 'needs_review'])
def test_one_directed_repair_requalifies_new_proposal_preserves_original_history_and_stops(workspace, final_status):
    analysis, case, plan, _, record, proposal, trimmed = repair_execution_fixture()
    before = copy.deepcopy(record)

    def fresh(source, analysis_arg, context, changed, target, *args):
        assert changed['cuts'] == [{'first': 'original-1', 'last': 'original-2'}]
        assert changed != proposal
        assert target['qualification_history'] == [before]
        assert 'screen' not in target and 'review' not in target
        target.update(source_status='ready', status=final_status,
                      screen={'fresh_directed_edit_screen': True, 'repair': {'further_trim': 'must not recurse'}})
        return trimmed, context

    with patch.object(native, 'with_cut_context', side_effect=lambda analysis, owned, candidate: owned), \
         patch.object(native, 'prototype_plan', return_value=(trimmed, {})), \
         patch.object(native, '_qualify_edit', side_effect=fresh) as qualify:
        updated, owned = native._repair_candidate(workspace/'source.mp4', analysis, proposal, record,
            plan, case, workspace, 'local', vision(), Mock(), Mock(), lambda: False)
    qualify.assert_called_once()
    assert updated == trimmed and owned == case
    assert record['proposal']['cuts'] == [{'first': 'original-1', 'last': 'original-2'}]
    assert record['original_proposal'] == proposal
    assert record['qualification_history'][0] == before
    assert record['qualification_history'][0]['screen'] != record['screen']
    assert record['repair_attempt']['status'] == final_status
    assert proposal['cuts'] == [{'first': 'original-1', 'last': 'original-2'},
                                {'first': 'original-5', 'last': 'original-6'}]


@pytest.mark.parametrize('bad_geometry', ['unchanged', 'expands_handle', 'restores_source_gap'])
def test_directed_repair_rejects_unchanged_or_expanded_actual_cuts_before_new_questions(workspace, bad_geometry):
    analysis, case, plan, _, record, proposal, trimmed = repair_execution_fixture()
    if bad_geometry == 'unchanged':
        rebuilt = copy.deepcopy(plan)
        rebuilt['semantic_ranges'] = trimmed['semantic_ranges']
    elif bad_geometry == 'expands_handle':
        rebuilt = copy.deepcopy(trimmed)
        rebuilt['parts'][0]['cuts'][0]['start'] = 1.7
    else:
        rebuilt = copy.deepcopy(trimmed)
        rebuilt['parts'][0]['cuts'][0]['end'] = 12.
    original_screen = copy.deepcopy(record['screen'])
    with patch.object(native, 'with_cut_context', side_effect=lambda analysis, owned, candidate: owned), \
         patch.object(native, 'prototype_plan', return_value=(rebuilt, {})), \
         patch.object(native, '_qualify_edit', side_effect=AssertionError('unsafe geometry must not dispatch')) as qualify:
        updated, _ = native._repair_candidate(workspace/'source.mp4', analysis, proposal, record,
            plan, case, workspace, 'local', vision(), Mock(), Mock(), lambda: False)
    assert updated == plan
    qualify.assert_not_called()
    assert record['repair_attempt']['status'] == 'rejected'
    assert record['repair_attempt']['reason'] == 'actual_edit_not_strict_trim'
    assert record['screen'] == original_screen
    assert record['status'] == 'needs_review'
    assert 'qualification_history' not in record


def test_native_approval_of_directed_edit_still_requires_new_bound_blind_verdict(workspace):
    from app.candidate_screen import inspect_screen, project_candidate
    analysis, case, plan, _, record, proposal, trimmed = repair_execution_fixture()
    old_screen = copy.deepcopy(record['screen'])
    fresh_negative = {'resolved': True, 'is_story': False, 'title': 'Fresh trim remains incomplete',
        'criteria': {key: False for key in old_screen['verdict']['criteria']},
        'issues': ['The changed clip does not resolve the story.'], 'proofs': []}
    purposes = []

    def authored_answer(ledger, client, provider, purpose, prompt, schema, pages, evidence):
        purposes.append(purpose)
        if purpose == 'candidate_review':
            assert 'screen' not in record  # Parent negative is in history only.
            return {'status': 'answered', 'raw': {'requested_units': []}}
        assert purpose == 'candidate_screen'
        assert record['source_status'] == 'ready'
        payload = json.loads(prompt.split('\n')[-1])
        assert payload['duration'] == pytest.approx(4.4)
        assert evidence['screen_binding'] != old_screen['binding']
        return {'status': 'answered', 'raw': fresh_negative}

    with patch.object(native, 'with_cut_context', side_effect=lambda analysis, owned, candidate: owned), \
         patch.object(native, 'prototype_plan', return_value=(trimmed, {})), \
         patch.object(native, '_prepare_frames', return_value=case), \
         patch.object(native, '_pages', return_value=[]), \
         patch.object(native, 'review_schema', return_value={}), \
         patch.object(native, 'review_status', return_value='ready'), \
         patch.object(native, '_ask', side_effect=authored_answer):
        updated, owned = native._repair_candidate(workspace/'source.mp4', analysis, proposal, record,
            plan, case, workspace, 'local', vision(), Mock(), Mock(), lambda: False)
    assert purposes == ['candidate_review', 'candidate_screen']
    assert record['source_status'] == 'ready' and record['status'] == 'declined'
    assert record['repair_attempt']['status'] == 'declined'
    assert record['qualification_history'][0]['screen'] == old_screen
    projected = project_candidate(analysis, owned, updated)
    assert record['screen']['binding'] == projected['binding']
    assert inspect_screen(projected, record['screen'])['status'] == 'declined'
    assert inspect_screen(projected, old_screen)['status'] == 'unresolved'


def test_collection_runs_at_most_one_repair_and_keeps_candidate_correlation_scope(workspace):
    from app.execution_context import snapshot
    analysis, case, plan, _, initial_record, proposal, trimmed = repair_execution_fixture()
    client = vision(error=AssertionError('authored execution must not query real provider'))
    qualified_inputs, observed_ids = [], []
    outer = snapshot()

    def first_answer(*args):
        assert args[3] == 'candidate_proposal'
        observed_ids.append(snapshot().get('candidate_id'))
        return {'status': 'answered', 'raw': proposal}

    def qualify(source, analysis_arg, owned, selected, target, *args):
        qualified_inputs.append(copy.deepcopy(selected))
        observed_ids.append(snapshot().get('candidate_id'))
        if len(qualified_inputs) == 1:
            target.update(copy.deepcopy(initial_record))
            return plan, owned
        # Still negative and contains a further suggestion. Collection orchestration
        # must stop after this single fresh qualification, without quality search.
        target.update(source_status='ready', status='needs_review',
                      screen={'further_repair_present': True})
        return trimmed, owned

    with patch('app.analysis_provider._model_files_for_provider', return_value=()), \
         patch('app.vision.AnalysisVisionSessions', return_value=Sessions(client)), \
         patch.object(native, 'candidate_cases', return_value=[case]), \
         patch.object(native, '_ask', side_effect=first_answer), \
         patch.object(native, '_prepare_proposal_frames', return_value=case), \
         patch.object(native, '_pages', return_value=[]), \
         patch.object(native, '_qualify_edit', side_effect=qualify) as requalify, \
         patch.object(native, '_repair_candidate', wraps=native._repair_candidate) as repair, \
         patch.object(native, 'with_cut_context', side_effect=lambda analysis, owned, selected: owned), \
         patch.object(native, 'prototype_plan', return_value=(trimmed, {})):
        result = native.qualify_candidates(workspace/'source.mp4', analysis, {}, workspace,
            'local', Mock(), lambda: False, Journal())
    assert requalify.call_count == 2  # Original plus one directed edit, not a loop.
    repair.assert_called_once()
    assert qualified_inputs[0] == proposal
    assert qualified_inputs[1]['cuts'] == [{'first': 'original-1', 'last': 'original-2'}]
    assert observed_ids == ['h_repair', 'h_repair', 'h_repair']
    assert snapshot() == outer
    assert result['candidate_records'][0]['status'] == 'needs_review'
    assert result['candidate_records'][0]['repair_attempt']['status'] == 'needs_review'
    client.query.assert_not_called()
