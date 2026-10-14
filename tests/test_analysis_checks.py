"""Economy changes model dispatch, never bypassing source correctness gates."""
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from app.analysis_checks import AnalysisChecks, OPTIONAL_CHECKS, economy_mode
from app.json_store import atomic_json, read_json
from app.jobs import BusyError, JobManager
from app.server import create_app
from tests.test_jobs import FakeWorker


@pytest.mark.parametrize('name', sorted(OPTIONAL_CHECKS))
def test_economy_skips_optional_model_calls_without_faking_completed_result(tmp_path, name):
    journal, diagnostics, callback = Mock(), Mock(), Mock()
    journal.load.return_value = None
    checks = AnalysisChecks(tmp_path, journal, diagnostics, lambda *args: None)
    events = [{'id': 'original', 'uncertain': True}]
    inputs = {'events': events, 'probe': {}} if name == 'endings' else events
    assert checks.run(name, inputs, callback, 'deepseek_plan') is events
    callback.assert_not_called()
    journal.run.assert_not_called()
    diagnostics.event.assert_called_once_with(name, 'skipped', reason='economy_mode')


def test_full_checks_dispatch_and_economy_reuses_matching_accepted_optional_results(tmp_path):
    journal = Mock()
    atomic_json(tmp_path / 'analysis-settings.json', {'economy_mode': False})
    checks = AnalysisChecks(tmp_path, journal, Mock(), Mock())
    callback = Mock()
    checks.run('pacing', ['source'], callback, 'deepseek_plan')
    journal.run.assert_called_once_with('pacing', ['source'], callback, 'deepseek_plan')
    atomic_json(tmp_path / 'analysis-settings.json', {'economy_mode': True})
    journal.reset_mock(); journal.load.return_value = ['already accepted']
    checks = AnalysisChecks(tmp_path, journal, Mock(), Mock())
    assert checks.run('pacing', ['source'], callback, 'deepseek_plan') == ['already accepted']
    journal.run.assert_not_called()


@pytest.mark.parametrize('name', ['visual_analysis', 'story_refinement', 'titles', 'closing_novelty',
    'source_roles', 'selection_adjudication', 'global_story', 'final_selection_adjudication',
    'story_structure_analysis', 'dialogue_relations', 'framing'])
def test_core_checks_still_use_native_journal_and_model_validation(tmp_path, name):
    journal = Mock()
    checks = AnalysisChecks(tmp_path, journal, Mock(), Mock())
    callback = Mock()
    checks.run(name, ['source'], callback, 'deepseek_plan')
    journal.run.assert_called_once_with(name, ['source'], callback, 'deepseek_plan')


@pytest.fixture
def manager(tmp_path):
    (tmp_path / 'source.mp4').write_bytes(b'source')
    manager = JobManager(tmp_path, worker_factory=FakeWorker)
    manager.list_sources()
    try:
        yield manager
    finally:
        manager.close()


def test_new_jobs_default_to_economy_and_active_change_drains_before_restart(manager):
    job = manager.create(next(iter(manager.sources)), 'local')
    directory, worker = manager.job_dir(job['id']), manager.active[1]
    assert job['economy_mode'] is True and economy_mode(directory)
    atomic_json(directory / 'continuation/stages/titles.json', {'original': 'accepted'})
    changed = manager.change_analysis_economy(job['id'], False, resume=True)
    assert worker.terminated and worker.closed
    assert changed['status'] == 'running' and not economy_mode(directory)
    assert read_json(directory / 'continuation/stages/titles.json') == {'original': 'accepted'}


def test_stopped_change_keeps_job_stopped_and_other_active_job_is_protected(manager):
    first = manager.create(next(iter(manager.sources)), 'local')
    manager.cancel(first['id'])
    result = manager.change_analysis_economy(first['id'], False)
    assert result['status'] == 'cancelled' and manager.active is None
    second = manager.create(next(iter(manager.sources)), 'local')
    worker = manager.active[1]
    with pytest.raises(BusyError):
        manager.change_analysis_economy(first['id'], True, resume=True)
    assert manager.active[0] == second['id'] and not worker.terminated


def test_api_mode_remembers_episode_and_preserves_source_and_provider(manager):
    job = manager.create(next(iter(manager.sources)), 'local')
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        path = f"/api/jobs/{job['id']}/analysis-checks"
        assert client.post(path, json={'economy_mode': False}).status_code == 409
        before = client.get('/api/library').json()['episodes'][0]
        reply = client.post(path, json={'economy_mode': False, 'resume': True})
        assert reply.status_code == 200 and reply.json()['economy_mode'] is False
        after = client.get('/api/library').json()['episodes'][0]
        assert after['settings']['economy_mode'] is False
        assert after['source_id'] == before['source_id']
        assert after['settings']['analysis_provider'] == before['settings']['analysis_provider']
        manager.cancel(job['id'])
        reply = client.post(path, json={'economy_mode': True})
        assert reply.status_code == 200 and reply.json()['status'] == 'cancelled'


def test_story_cache_identity_distinguishes_full_and_economy():
    from app.analysis import derived_story_identity
    assert derived_story_identity('same', 'local', economy_mode=True) != derived_story_identity('same', 'local', economy_mode=False)


def test_snapshot_policy_rejects_cross_mode_reuse_and_preserves_legacy_metadata(tmp_path):
    from app.processing import snapshot_identity
    source = tmp_path / 'source.mp4'; source.write_bytes(b'source')
    analysis = {'check_policy': {'version':1, 'economy_mode':True}}
    economical = snapshot_identity(tmp_path, source, analysis)
    atomic_json(tmp_path / 'analysis-settings.json', {'economy_mode':False})
    complete = snapshot_identity(tmp_path, source, analysis)
    assert economical != complete and complete['economy_mode'] is False
    assert 'economy_mode' not in snapshot_identity(tmp_path, source, {})


def test_skipped_pass_end_is_not_reported_as_completed(tmp_path):
    from app.job_progress import analysis_passes
    audit = tmp_path / 'diagnostics/pipeline'
    atomic_json(audit / 'run.json', {'run_id': 'run'})
    import json
    (audit / 'timeline.jsonl').write_text('\n'.join(json.dumps({'run_id':'run','stage':'pacing','action':action,
        **({'reason':'economy_mode'} if action=='skipped' else {})}) for action in ('start','skipped','end')), 'utf-8')
    rows = analysis_passes({'status':'running','stage':'plan'}, tmp_path)
    assert rows['pacing']['status'] == 'disabled' and rows['pacing']['fraction'] is None
