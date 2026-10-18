"""Useful question dispatch is finite across failures and restarts."""
from unittest.mock import Mock, patch
from pathlib import Path
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier

import pytest

from app.analysis_questions import QuestionLedger, QuestionJournalError
from app.json_store import atomic_json, read_json


def question(**changes):
    result = dict(purpose='prerequisite', question='Is the outcome explained?',
                affected_refs=['event:12'], evidence_digest='evidence-a',
                possible_plan_changes=['extend opening'],
                request_identity={'prompt': 'exact', 'schema': {}, 'frame_hashes': []})
    result.update(changes)
    return result


@pytest.fixture
def tmp_path():
    # Default pytest's mode=0700 directories are inaccessible to this Windows sandbox.
    path = Path(__file__).resolve().parents[1] / 'temp' / ('question-tests-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def test_positive_and_negative_reuse_and_original_producer(tmp_path):
    for answer in ({'keep': [1]}, None):
        ledger = QuestionLedger(tmp_path, 'a' * 64)
        q = question(evidence_digest=str(answer))
        call = Mock(return_value=answer)
        result = ledger.run(q, call, 'original')
        if result:
            result['keep'].append(2)
        assert ledger.run(q, Mock(side_effect=AssertionError()), 'other') == answer
        assert call.call_count == 1
        artifact = next(ledger.root.glob(ledger.question_key(q) + '.*.result.json'))
        assert read_json(artifact)['producer'] == 'original'


def test_failure_and_unknown_reservation_never_resend_but_new_evidence_can(tmp_path):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    with pytest.raises(RuntimeError):
        ledger.run(question(), Mock(side_effect=RuntimeError('failed')))
    restarted = QuestionLedger(tmp_path, 'a' * 64)
    with pytest.raises(QuestionJournalError, match='unknown'):
        restarted.run(question(), Mock(side_effect=AssertionError()))
    assert restarted.run(question(evidence_digest='new'), lambda: 4) == 4


@pytest.mark.parametrize('phase', ['result', 'pointer'])
def test_write_faults(tmp_path, phase):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    call = Mock(return_value={'x': 1})
    real = atomic_json
    def write(path, value):
        if ((phase == 'reserve' and str(path).endswith('.reserved.json'))
                or (phase == 'result' and str(path).endswith('.result.json'))
                or (phase == 'pointer' and str(path).endswith('.completed.json'))):
            raise OSError('fault')
        real(path, value)
    with patch('app.analysis_questions.atomic_json', side_effect=write), pytest.raises(OSError):
        ledger.run(question(), call)
    assert call.call_count == (0 if phase == 'reserve' else 1)
    next_call = Mock(return_value=7)
    with pytest.raises(QuestionJournalError, match='unknown'):
        ledger.run(question(), next_call)
    assert next_call.call_count == 0


def test_cancellation_before_and_after_dispatch(tmp_path):
    state = [True]
    ledger = QuestionLedger(tmp_path, 'a' * 64, lambda: state[0])
    call = Mock()
    with pytest.raises(InterruptedError):
        ledger.run(question(), call)
    assert not ledger.root.exists() and not call.called
    state[0] = False
    def dispatch():
        state[0] = True
        return 5
    with pytest.raises(InterruptedError):
        ledger.run(question(), dispatch)
    state[0] = False
    with pytest.raises(QuestionJournalError, match='unknown'):
        ledger.run(question(), Mock(side_effect=AssertionError()))


def test_two_ledger_instances_dispatch_once(tmp_path):
    entered, release = Event(), Event()
    first = QuestionLedger(tmp_path, 'a' * 64)
    second = QuestionLedger(tmp_path, 'a' * 64)
    def dispatch():
        entered.set()
        assert release.wait(5)
        return {'ok': True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(first.run, question(), dispatch)
        assert entered.wait(5)
        try:
            with pytest.raises(QuestionJournalError):
                second.run(question(), Mock(side_effect=AssertionError()))
        finally:
            release.set()
        assert future.result() == {'ok': True}
    assert second.run(question(), Mock(side_effect=AssertionError())) == {'ok': True}


def test_two_ledger_instances_race_at_absent_reservation(tmp_path):
    barrier = Barrier(2)
    ledgers = [QuestionLedger(tmp_path, 'a' * 64) for _ in range(2)]
    original = QuestionLedger._load
    calls = Mock(return_value={'ok': True})
    def read_absent(self, path):
        value = original(self, path)
        if path.name.endswith('.reserved.json') and value is None:
            barrier.wait(timeout=5)
        return value
    with patch.object(QuestionLedger, '_load', read_absent), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ledger.run, question(), calls) for ledger in ledgers]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except QuestionJournalError:
                outcomes.append('reserved')
    assert calls.call_count == 1
    assert outcomes.count('reserved') == 1


def test_reservation_write_failure_never_dispatches_or_retries(tmp_path):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    call = Mock(return_value=1)
    with patch('app.analysis_questions.os.fsync', side_effect=OSError('disk')), pytest.raises(OSError):
        ledger.run(question(), call)
    assert not call.called
    with pytest.raises(QuestionJournalError):
        ledger.run(question(), call)
    assert not call.called


@pytest.mark.parametrize('change', [dict(affected_refs=[]), dict(possible_plan_changes=[]),
    dict(request_identity={}), dict(estimated_cost={'tokens': float('nan')}),
    dict(estimated_cost={'tokens': True})])
def test_reject_useless_or_nonfinite(tmp_path, change):
    q = question()
    q.update(change)
    with pytest.raises(ValueError):
        QuestionLedger(tmp_path, 'a' * 64).run(q, Mock(side_effect=AssertionError()))


def test_source_request_identity_and_order(tmp_path):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    q = question()
    key = ledger.question_key(q)
    q['estimated_cost'] = {'tokens': 200}
    q['rank'] = 3
    assert ledger.question_key(q) == key
    q['request_identity']['prompt'] = 'changed'
    assert ledger.question_key(q) != key
    assert QuestionLedger(tmp_path, 'b' * 64).question_key(question()) != key


@pytest.mark.parametrize('target', ['reserved', 'completed', 'result'])
def test_corruption_fails_closed(tmp_path, target):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    ledger.run(question(), lambda: {'x': 1})
    pattern = '*.result.json' if target == 'result' else '*.' + target + '.json'
    next(ledger.root.glob(pattern)).write_text('{}', encoding='utf-8')
    with pytest.raises(QuestionJournalError):
        ledger.run(question(), Mock(side_effect=AssertionError()))


def test_path_escape_rejected(tmp_path):
    ledger = QuestionLedger(tmp_path, 'a' * 64)
    ledger.root = tmp_path.parent / 'outside'
    with pytest.raises(QuestionJournalError):
        ledger.run(question(), Mock(side_effect=AssertionError()))
