"""Owned stop/switch/resume, provider banks and runner isolation; no inference."""
import sys
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.jobs import BusyError, JobManager
from app.json_store import atomic_json, read_json
from app.server import create_app
from app.analysis_provider import perception_provider, framing_provider
from tests.test_jobs import FakeWorker


@pytest.fixture
def manager(tmp_path):
    (tmp_path / 'source.mp4').write_bytes(b'source')
    manager = JobManager(tmp_path, worker_factory=FakeWorker)
    manager.list_sources()
    with patch('app.deepseek.public_status', return_value={'configured': True}):
        try:
            yield manager
        finally:
            manager.close()


def start(manager, provider='antigravity_manual'):
    return manager.create(next(iter(manager.sources)), provider)


def test_active_switch_banks_both_providers_and_preserves_source_and_preferences(manager):
    job = start(manager)
    directory = manager.job_dir(job['id'])
    old_worker = manager.active[1]
    (directory / 'audio.wav').write_bytes(b'prepared audio')
    atomic_json(directory / 'transcript.json', {'words': ['original']})
    atomic_json(directory / 'story-events.json', {'provider': 'antigravity_manual'})
    atomic_json(directory / 'analysis-final.meta.json', {'provider': 'antigravity_manual'})
    atomic_json(directory / 'planning-preferences.json', {'preferred_part_count': 1})
    from app.antigravity_exchange import preserve_provider_checkpoints
    def bank(*args):
        assert old_worker.terminated and old_worker.closed
        assert manager.active is None
        preserve_provider_checkpoints(*args)
    with patch('app.antigravity_exchange.preserve_provider_checkpoints', side_effect=bank):
        changed = manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert changed['status'] == 'running'
    assert changed['analysis_provider'] == 'deepseek_plan'
    assert manager.active[1] is not old_worker
    assert read_json(directory / 'analysis-settings.json')['provider'] == 'deepseek_plan'
    atomic_json(directory / 'story-events.json', {'provider': 'deepseek_plan'})
    atomic_json(directory / 'planning-preferences.json', {'preferred_part_count': 2})
    manager.change_analysis_provider(job['id'], 'antigravity_manual', resume=True)
    assert read_json(directory / 'story-events.json')['provider'] == 'antigravity_manual'
    assert read_json(directory / 'analysis-final.meta.json')['provider'] == 'antigravity_manual'
    assert read_json(directory / 'planning-preferences.json')['preferred_part_count'] == 2
    manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert read_json(directory / 'story-events.json')['provider'] == 'deepseek_plan'
    assert (directory / 'audio.wav').read_bytes() == b'prepared audio'
    assert read_json(directory / 'transcript.json') == {'words': ['original']}
    assert not (directory / '.cancel').exists()


def test_missing_deepseek_configuration_does_not_stop_current_worker(manager):
    job = start(manager)
    worker = manager.active[1]
    with patch('app.deepseek.public_status', return_value={'configured': False}):
        with pytest.raises(ValueError, match='не настроен'):
            manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert manager.active[1] is worker and not worker.terminated
    assert manager.get(job['id'])['analysis_provider'] == 'antigravity_manual'


def test_foreign_active_job_is_never_cancelled(manager):
    old = start(manager)
    manager.cancel(old['id'])
    current = start(manager)
    worker = manager.active[1]
    with pytest.raises(BusyError):
        manager.change_analysis_provider(old['id'], 'deepseek_plan', resume=True)
    assert manager.active[0] == current['id'] and not worker.terminated


def test_bank_failure_leaves_recoverable_old_provider(manager):
    job = start(manager)
    with patch('app.antigravity_exchange.preserve_provider_checkpoints', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert manager.active is None
    assert manager.get(job['id'])['status'] == 'cancelled'
    assert read_json(manager.job_dir(job['id']) / 'analysis-settings.json')['provider'] == 'antigravity_manual'


def test_late_terminal_worker_is_drained_before_switch(manager):
    job = start(manager)
    worker = manager.active[1]
    directory = manager.job_dir(job['id'])
    atomic_json(directory / 'job.json', {**manager.get(job['id']), 'status': 'waiting_analysis'})
    changed = manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert worker.terminated and worker.closed
    assert changed['status'] == 'running'
    assert manager.active[1] is not worker


def test_same_provider_running_request_is_idempotent(manager):
    job = start(manager)
    worker = manager.active[1]
    assert manager.change_analysis_provider(job['id'], 'antigravity_manual', resume=True)['status'] == 'running'
    assert manager.active[1] is worker and not worker.terminated


def test_worker_launch_failure_reports_failed_and_keeps_selected_provider(manager):
    job = start(manager)
    manager.worker_factory = lambda directory: (_ for _ in ()).throw(RuntimeError('launch failure'))
    result = manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)
    assert result['status'] == 'failed' and result['analysis_provider'] == 'deepseek_plan'
    assert manager.active is None


def test_completed_run_cannot_switch(manager):
    job = start(manager)
    manager.cancel(job['id'])
    atomic_json(manager.job_dir(job['id']) / 'job.json', {**manager.get(job['id']), 'status': 'completed'})
    with pytest.raises(BusyError, match='Готовое'):
        manager.change_analysis_provider(job['id'], 'deepseek_plan', resume=True)


def test_api_switch_resumes_and_remembers_episode_without_changing_presentation(manager):
    job = start(manager)
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        path = '/api/jobs/' + job['id'] + '/analysis-provider'
        assert client.post(path, json={'provider': 'deepseek_plan'}).status_code == 409
        assert client.post(path, json={'provider': 'foreign', 'resume': True}).status_code == 422
        before = client.get('/api/library').json()['episodes'][0]
        reply = client.post(path, json={'provider': 'deepseek_plan', 'resume': True})
        assert reply.status_code == 200, reply.text
        assert reply.json()['status'] == 'running'
        after = client.get('/api/library').json()['episodes'][0]
        assert after['settings']['analysis_provider'] == 'deepseek_plan'
        for key in ('source_id', 'id'):
            assert before[key] == after[key]
        for key in ('layout', 'caption_style'):
            assert before['settings'][key] == after['settings'][key]
        assert client.post(path, json={'provider': 'antigravity_manual', 'resume': True}).status_code == 200


def test_story_transports_share_local_perception_and_keep_framing_route():
    assert perception_provider('antigravity_manual') == 'local'
    assert perception_provider('deepseek_plan') == 'local'
    assert perception_provider('deepseek') == 'deepseek'
    assert framing_provider('deepseek_plan') == 'local'


def test_deepseek_worker_ignores_retained_antigravity_quota(tmp_path, monkeypatch):
    import app.worker as worker
    directory = tmp_path / str(uuid.uuid4())
    directory.mkdir()
    (directory / '.start').touch()
    atomic_json(directory / 'job.json', {'id': directory.name, 'status': 'running',
                                       'analysis_provider': 'deepseek_plan'})
    atomic_json(directory / 'analysis-settings.json', {'provider': 'deepseek_plan'})
    atomic_json(directory / 'antigravity/automation.json', {'enabled': True, 'managed': True})
    monkeypatch.setattr(sys, 'argv', ['worker', '--job', directory.name])
    monkeypatch.setattr(worker.config, 'JOBS', tmp_path)
    with patch('app.antigravity_runner.ManagedRunner') as runner, \
         patch('app.antigravity_quota.wait_for_quota') as quota, \
         patch('app.pipeline.run_job', return_value=[]):
        assert worker.main() == 0
        quota.assert_not_called()
    assert read_json(directory / 'job.json')['status'] == 'completed'
    assert not (directory / 'antigravity/exchange.json').exists()
