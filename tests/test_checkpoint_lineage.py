"""Cross-job cache reuse is explicit, source bound, and never copies model state."""
import copy
import uuid
from unittest.mock import patch

import pytest

from app.analysis_continuation import StageJournal, AcceptedReplies
from app.analysis_questions import QuestionLedger, QuestionJournalError
from app.checkpoint_lineage import LineageError, ancestors, dependents, link
from app.json_store import atomic_json, read_json
from app.pipeline_diagnostics import Diagnostics


SHA = 'a' * 64


def make_job(root, *, owner=None, sha=SHA, source='episode.mp4'):
    directory = root / str(uuid.uuid4())
    atomic_json(directory / 'job.json', {'id': directory.name, 'episode_id': owner})
    atomic_json(directory / 'analysis.meta.json', {'source': sha})
    atomic_json(directory / 'source.json', {'path': source})
    return directory


def journal(directory):
    return StageJournal(directory, SHA, {'words': [], 'segments': []}, [], {},
                        Diagnostics(directory), lambda *_: None, lambda: False)


def connect(previous, child):
    link(previous, child, source_sha256=SHA, episode_id=None)


def question():
    return {'purpose': 'episode_map', 'question': 'Does this story conclude?',
            'affected_refs': ['story_1'], 'evidence_digest': 'evidence',
            'possible_plan_changes': ['accept', 'decline'],
            'request_identity': {'model': 'native', 'prompt': 'exact'}}


def test_explicit_chain_is_read_only_and_protects_parent_even_before_job_commit(tmp_path):
    first, second = make_job(tmp_path), make_job(tmp_path)
    before = (first / 'job.json').read_bytes()
    connect(first, second)
    third = tmp_path / str(uuid.uuid4())
    link(second, third, source_sha256=SHA, episode_id=None)
    assert dependents(tmp_path, first.name) == [second.name]
    assert dependents(tmp_path, second.name) == [third.name]
    assert ancestors(second) == [first]
    assert (first / 'job.json').read_bytes() == before


@pytest.mark.parametrize('mismatch', ['source_sha', 'owner', 'path', 'missing', 'cycle'])
def test_broken_or_unrelated_chain_fails_before_any_cache_fallback(tmp_path, mismatch):
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    if mismatch == 'source_sha':
        atomic_json(first / 'analysis.meta.json', {'source': 'b' * 64})
    elif mismatch == 'owner':
        row = read_json(first / 'job.json')
        atomic_json(first / 'job.json', {**row, 'episode_id': str(uuid.uuid4())})
    elif mismatch == 'path':
        atomic_json(first / 'source.json', {'path': 'different.mp4'})
    elif mismatch == 'missing':
        (first / 'job.json').unlink()
    else:
        atomic_json(first / 'checkpoint-lineage.json', {**read_json(second / 'checkpoint-lineage.json'),
                                                      'parent_job_id': second.name})
    with pytest.raises(LineageError):
        ancestors(second)


def test_equal_source_alone_never_grants_ancestor_access(tmp_path):
    first, second = make_job(tmp_path), make_job(tmp_path)
    journal(first).save('episode_map', [], {'complete': True}, 'local')
    assert ancestors(second) == []
    assert journal(second).load('episode_map', []) is None


def test_migrated_parent_and_unmapped_legacy_child_keep_explicit_ancestry(tmp_path):
    parent, child = make_job(tmp_path / 'jobs'), make_job(tmp_path / 'jobs')
    connect(parent, child)
    owner = str(uuid.uuid4())
    atomic_json(tmp_path / 'library.json', {'legacy_jobs': {parent.name: owner}})
    before = (parent / 'job.json').read_bytes()
    assert ancestors(child) == [parent]
    atomic_json(tmp_path / 'library.json', {'legacy_jobs': {parent.name: owner, child.name: owner}})
    assert ancestors(child) == [parent]
    assert (parent / 'job.json').read_bytes() == before


def test_migrated_known_owners_cannot_disagree_across_unmapped_hop(tmp_path):
    parent, middle, child = [make_job(tmp_path / 'jobs') for _ in range(3)]
    connect(parent, middle)
    connect(middle, child)
    atomic_json(tmp_path / 'library.json', {'legacy_jobs': {
        parent.name: str(uuid.uuid4()), child.name: str(uuid.uuid4())}})
    with pytest.raises(LineageError, match='migrated owner'):
        ancestors(child)


def test_invalid_migrated_owner_is_not_a_cache_miss(tmp_path):
    parent, child = make_job(tmp_path / 'jobs'), make_job(tmp_path / 'jobs')
    connect(parent, child)
    atomic_json(tmp_path / 'library.json', {'legacy_jobs': {parent.name: 'bad-owner'}})
    with pytest.raises(LineageError):
        ancestors(child)


def test_multigeneration_stage_reuse_preserves_artifact_and_producing_provider(tmp_path):
    first, second, third = [make_job(tmp_path) for _ in range(3)]
    connect(first, second)
    connect(second, third)
    inputs = {'image': str(first / 'visual' / 'page.jpg')}
    result = {'events': [1], 'board': str(first / 'visual' / 'page.jpg')}
    journal(first).save('titles', inputs, result, 'antigravity_manual')
    pointer = first / 'continuation/stages/titles.json'
    original = pointer.read_bytes()
    descendant_inputs = {'image': str(third / 'visual' / 'page.jpg')}
    assert journal(third).run('titles', descendant_inputs,
                              lambda: pytest.fail('ancestor cache dispatched inference'), 'deepseek_plan') == result
    assert pointer.read_bytes() == original
    assert read_json(pointer)['producer'] == 'antigravity_manual'
    assert not (third / 'continuation/artifacts').exists()


def test_ancestor_does_not_bypass_changed_stage_dependencies_or_corrupt_bytes(tmp_path):
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    journal(first).save('titles', ['original'], {'answer': 1}, 'local')
    assert journal(second).load('titles', ['changed']) is None
    pointer = read_json(first / 'continuation/stages/titles.json')
    (first / 'continuation' / pointer['artifact']['path']).write_bytes(b'torn')
    assert journal(second).load('titles', ['original']) is None


@pytest.mark.parametrize('answer', [None, {'accepted': True}, {'accepted': False}])
def test_completed_ancestor_question_reuses_positive_and_negative_without_new_files(tmp_path, answer):
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    QuestionLedger(first, SHA).run(question(), lambda: copy.deepcopy(answer), 'local')
    result = QuestionLedger(second, SHA).run(question(), lambda: pytest.fail('duplicate dispatch'), 'remote')
    assert result == answer
    assert not (second / 'continuation/questions').exists()


def test_ancestor_unknown_dispatch_blocks_resend_but_new_evidence_can_run(tmp_path):
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    with pytest.raises(TimeoutError):
        QuestionLedger(first, SHA).run(question(), lambda: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(QuestionJournalError, match='unknown'):
        QuestionLedger(second, SHA).run(question(), lambda: pytest.fail('duplicate dispatch'))
    changed = {**question(), 'evidence_digest': 'new evidence'}
    assert QuestionLedger(second, SHA).run(changed, lambda: {'accepted': True}) == {'accepted': True}


def test_accepted_reply_keeps_source_schema_and_original_producer(tmp_path):
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    image_a, image_b = first / 'page.jpg', second / 'page.jpg'
    image_a.write_bytes(b'identical source images')
    image_b.write_bytes(image_a.read_bytes())
    with patch.object(AcceptedReplies, '_validate'):
        old = AcceptedReplies(first, 'antigravity_manual', lambda: False)
        key, _ = old.find('prompt', image_a, {'type': 'object'})
        old.store(key, {'answer': True}, {'type': 'object'})
        new = AcceptedReplies(second, 'deepseek_plan', lambda: False)
        assert new.find('prompt', image_b, {'type': 'object'}) == (key, {'answer': True})
        assert new.find('prompt', image_a, {'type': 'object'}) == (key, {'answer': True})
        assert new.find('changed', image_b, {'type': 'object'})[1] is None
    saved = read_json(first / 'continuation/replies' / (key + '.json'))
    assert saved['producer'] == 'antigravity_manual'
    assert not (second / 'continuation/replies').exists()


def test_null_lineage_is_not_treated_as_no_ancestor(tmp_path):
    child = make_job(tmp_path)
    atomic_json(child / 'checkpoint-lineage.json', None)
    with pytest.raises(LineageError):
        ancestors(child)
    with pytest.raises(LineageError):
        dependents(tmp_path, str(uuid.uuid4()))
    assert dependents(tmp_path, child.name) == []


def test_episode_adapter_adopts_only_legacy_ancestors_mapped_to_same_owner(tmp_path):
    owner = str(uuid.uuid4())
    first, second = make_job(tmp_path), make_job(tmp_path)
    connect(first, second)
    third = make_job(tmp_path, owner=owner)
    atomic_json(tmp_path.parent / 'library.json', {'legacy_jobs': {first.name: owner, second.name: owner}})
    link(second, third, source_sha256=SHA, episode_id=owner)
    assert ancestors(third) == [second, first]
    atomic_json(tmp_path.parent / 'library.json', {'legacy_jobs': {
        first.name: str(uuid.uuid4()), second.name: owner}})
    with pytest.raises(LineageError):
        ancestors(third)


@pytest.fixture
def manager(tmp_path):
    from app.jobs import JobManager
    from tests.test_jobs import FakeWorker
    source = tmp_path / 'episode.mp4'
    source.write_bytes(b'authored source placeholder, no inference')
    value = JobManager(tmp_path, FakeWorker)
    try:
        yield value, value.list_sources()[0]['id'], source
    finally:
        value.close()


def previous_job(manager, source_id, source):
    from app.processing import source_digest
    job = manager.create(source_id)
    manager.cancel(job['id'])
    directory = manager.job_dir(job['id'])
    atomic_json(directory / 'analysis.meta.json', {'source': source_digest(source)})
    atomic_json(directory / 'job.json', {**manager.get(job['id']), 'status': 'completed'})
    return job, directory


def test_manager_links_new_incremental_job_and_deletion_requires_removing_child_first(manager):
    from app.jobs import BusyError
    value, source_id, source = manager
    old, directory = previous_job(value, source_id, source)
    child = value.create(source_id, processing_mode='incremental', reuse_job_id=old['id'])
    value.cancel(child['id'])
    assert ancestors(value.job_dir(child['id'])) == [directory]
    with pytest.raises(BusyError, match='потомками'):
        value.delete_job(old['id'])
    value.delete_job(child['id'])
    assert value.delete_job(old['id'])['deleted']


def test_bulk_prune_preserves_referenced_parent_and_releases_after_child_removal(manager):
    value, source_id, source = manager
    old, directory = previous_job(value, source_id, source)
    child = value.create(source_id, processing_mode='incremental', reuse_job_id=old['id'])
    value.cancel(child['id'])
    atomic_json(value.job_dir(child['id']) / 'job.json', {**value.get(child['id']), 'status': 'completed'})
    assert old['id'] not in value.prune_jobs(max_jobs=0, max_age_days=0)['pruned_ids']
    assert directory.is_dir()
    assert child['id'] not in [j['id'] for j in value.list_jobs()]
    assert old['id'] in value.prune_jobs(max_jobs=0, max_age_days=0)['pruned_ids']


def test_corrupt_job_is_preserved_without_breaking_other_job_pruning(manager):
    value, source_id, source = manager
    old, _ = previous_job(value, source_id, source)
    broken = value.jobs / str(uuid.uuid4())
    broken.mkdir()
    (broken / 'job.json').write_bytes(b'{torn')
    assert old['id'] in value.prune_jobs(max_jobs=0, max_age_days=0)['pruned_ids']
    assert (broken / 'job.json').read_bytes() == b'{torn'


def test_corrupt_own_lineage_does_not_prevent_explicit_child_deletion(manager):
    value, source_id, source = manager
    old, directory = previous_job(value, source_id, source)
    atomic_json(directory / 'checkpoint-lineage.json', None)
    assert value.delete_job(old['id'])['deleted']


def test_reserved_submission_protects_ancestor_before_child_reference_commit(manager):
    from app.jobs import BusyError
    value, source_id, source = manager
    old, directory = previous_job(value, source_id, source)
    operation = str(uuid.uuid4())
    class Crash(BaseException):
        pass
    with patch('app.checkpoint_lineage.link', side_effect=Crash):
        with pytest.raises(Crash):
            value.create(source_id, operation_id=operation,
                         processing_mode='incremental', reuse_job_id=old['id'])
    receipt = read_json(value.data / 'job-operations' / (operation + '.json'))
    assert receipt['state'] == 'reserved'
    assert not (value.job_dir(receipt['job_id']) / 'checkpoint-lineage.json').exists()
    with pytest.raises(BusyError):
        value.delete_job(old['id'])
    assert old['id'] not in value.prune_jobs(max_jobs=0, max_age_days=0)['pruned_ids']
    recovered = value.create(source_id, operation_id=operation,
                             processing_mode='incremental', reuse_job_id=old['id'])
    assert recovered['id'] == receipt['job_id']
    assert ancestors(value.job_dir(recovered['id'])) == [directory]
