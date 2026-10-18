"""Durable ordinary submission, crash recovery and API replay; no inference."""
import concurrent.futures
import copy
import shutil
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, jobs
from app.jobs import JobManager, SubmissionConflict
from app.json_store import atomic_json, read_json
from app.library import Library
from app.server import create_app
from tests.test_jobs import FakeWorker


class CreationCrash(BaseException):
    """Simulate termination without ordinary application exception recovery."""


class JobIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP / ('job-idempotency-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        (self.root / 'episode-one.mp4').write_bytes(b'authored source one')
        (self.root / 'episode-two.mp4').write_bytes(b'authored source two')
        self.launched = []

        def factory(directory):
            child = FakeWorker(directory)
            self.launched.append(child)
            return child

        self.factory = factory
        self.manager = JobManager(self.root, self.factory)
        self.sources = self.manager.list_sources()
        self.source_id = self.sources[0]['id']
        self.operation_id = str(uuid.uuid4())

    def tearDown(self):
        self.manager.close()
        self.root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(self.root)

    def create(self, **changes):
        return self.manager.create(**{'source_id': self.source_id, 'operation_id': self.operation_id, **changes})

    def receipt_path(self, operation_id=None):
        return self.manager.data / 'job-operations' / ((operation_id or self.operation_id) + '.json')

    def restart(self):
        self.manager.close()
        self.manager = JobManager(self.root, self.factory)

    def episode(self, library, number=1, source_id=None):
        project = library.create_project('Project ' + str(number))
        episode = library.create_episode(project['id'], number)
        library.save_episode(episode['id'], source_id or self.source_id,
                             {'analysis_provider': 'local', 'layout': 'cinema', 'caption_style': 'accent'})
        return episode

    def test_concurrent_identical_commands_launch_one_worker_and_return_one_job(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.create(), range(12)))
        self.assertEqual(len({job['id'] for job in results}), 1)
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(len(self.manager.list_jobs()), 1)
        receipt = read_json(self.receipt_path())
        self.assertEqual(receipt['state'], 'committed')
        self.assertEqual(receipt['job_id'], results[0]['id'])
        self.assertEqual(results[0]['operation_id'], self.operation_id)

    def test_response_lost_after_launch_returns_existing_before_busy_or_preflight(self):
        original = self.manager._start

        def lost_response(job):
            original(job)
            raise RuntimeError('response lost')

        with patch.object(self.manager, '_start', side_effect=lost_response), self.assertRaises(RuntimeError):
            self.create()
        identifier = self.manager.active[0]
        with patch.object(self.manager, '_assert_available', side_effect=AssertionError('busy check')), \
                patch.object(self.manager, '_check_analysis_provider', side_effect=AssertionError('provider check')):
            repeated = self.create(preflight=lambda: self.fail('readiness cannot gate replay'))
        self.assertEqual(repeated['id'], identifier)
        self.assertEqual(repeated['status'], 'running')
        self.assertEqual(len(self.launched), 1)

    def test_changed_explicit_payload_conflicts_before_start_or_readiness(self):
        first = self.create()
        for changes in ({'source_id': self.sources[1]['id']}, {'analysis_provider': 'deepseek_plan'},
                        {'layout': 'cinema'}, {'caption_style': 'accent'}, {'economy_mode': False},
                        {'economy_mode': 1},
                        {'episode_id': str(uuid.uuid4())}, {'processing_mode': 'incremental'},
                        {'reuse_job_id': str(uuid.uuid4())}):
            with self.subTest(changes=changes), self.assertRaises(SubmissionConflict):
                self.create(**changes)
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.manager.active[0], first['id'])

    def test_terminal_replay_never_restarts_any_completed_or_stopped_job(self):
        job = self.create()
        self.manager.cancel(job['id'])
        path = self.manager.job_dir(job['id']) / 'job.json'
        for status in ('failed', 'cancelled', 'interrupted', 'waiting_analysis', 'completed'):
            state = read_json(path)
            state['status'] = status
            atomic_json(path, state)
            repeated = self.create()
            self.assertEqual((repeated['id'], repeated['status']), (job['id'], status))
        self.assertEqual(len(self.launched), 1)

    def test_worker_launch_failure_remains_the_same_failed_job(self):
        with patch.object(self.manager, 'worker_factory', side_effect=OSError('child could not start')) as start:
            first, second = self.create(), self.create()
        self.assertEqual(start.call_count, 1)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['status'], 'failed')

    def test_creation_crash_boundaries_recover_reserved_job_without_starting_worker(self):
        original = jobs.atomic_json
        boundaries = ('reserved_receipt', 'source.json', 'analysis-settings.json', 'render-settings.json',
                      'processing-settings.json', 'before_job', 'after_job', 'committed_receipt', 'running_job')
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                operation = str(uuid.uuid4())
                failed = []

                def write(path, value, **kwargs):
                    matches = ((boundary == 'reserved_receipt' and path.parent.name == 'job-operations'
                                and value.get('state') == 'reserved')
                               or (boundary == 'committed_receipt' and path.parent.name == 'job-operations'
                                   and value.get('state') == 'committed')
                               or (boundary == 'before_job' and path.name == 'job.json')
                               or (boundary == 'after_job' and path.name == 'job.json' and value.get('status') == 'queued')
                               or (boundary == 'running_job' and path.name == 'job.json' and value.get('status') == 'running')
                               or path.name == boundary)
                    if matches and not failed:
                        failed.append(True)
                        if boundary != 'before_job':
                            original(path, value, **kwargs)
                        raise CreationCrash(boundary)
                    return original(path, value, **kwargs)

                with patch('app.jobs.atomic_json', side_effect=write), self.assertRaises(CreationCrash):
                    self.create(operation_id=operation, layout='cinema', caption_style='accent', economy_mode=False)
                receipt = read_json(self.receipt_path(operation))
                identifier = receipt['job_id']
                self.restart()
                recovered = self.manager.get(identifier)
                self.assertEqual(recovered['status'], 'interrupted')
                self.assertEqual(recovered['operation_id'], operation)
                self.assertEqual((recovered['layout'], recovered['caption_style'], recovered['economy_mode']),
                                 ('cinema', 'accent', False))
                repeated = self.create(operation_id=operation, layout='cinema', caption_style='accent', economy_mode=False)
                self.assertEqual(repeated['id'], identifier)
                self.assertEqual(repeated['status'], 'interrupted')
                self.assertEqual(read_json(self.receipt_path(operation))['state'], 'committed')
                self.assertFalse(self.launched)
                self.assertEqual(read_json(self.manager.job_dir(identifier) / 'source.json'), receipt['files']['source.json'])
        self.assertEqual(len(self.manager.list_jobs()), len(boundaries))

    def test_replay_completes_partial_creation_in_same_server_without_start(self):
        original = jobs.atomic_json

        def fail(path, value, **kwargs):
            if path.name == 'source.json':
                raise OSError('disk full')
            return original(path, value, **kwargs)

        with patch('app.jobs.atomic_json', side_effect=fail), self.assertRaises(OSError):
            self.create()
        identifier = read_json(self.receipt_path())['job_id']
        repeated = self.create()
        self.assertEqual((repeated['id'], repeated['status']), (identifier, 'interrupted'))
        self.assertFalse(self.launched)
        self.assertEqual(self.manager.retry(identifier)['status'], 'running')
        self.assertEqual(len(self.launched), 1)

    def test_incremental_recovery_keeps_reserved_settings_and_finishes_cache_copy(self):
        previous = self.manager.create(self.source_id)
        self.manager.cancel(previous['id'])
        previous_dir = self.manager.job_dir(previous['id'])
        from app.processing import source_digest
        atomic_json(previous_dir / 'analysis.meta.json', {'source': source_digest(self.root / 'episode-one.mp4')})
        atomic_json(previous_dir / 'editorial-settings.json', {'fixture_policy': 'reserved'})
        atomic_json(previous_dir / 'transcript.json', {'words': [{'text': 'checkpoint'}]})
        original = jobs.atomic_json

        def fail(path, value, **kwargs):
            if path.name == 'source.json':
                raise CreationCrash()
            return original(path, value, **kwargs)

        with patch('app.jobs.atomic_json', side_effect=fail), self.assertRaises(CreationCrash):
            self.create(processing_mode='incremental', reuse_job_id=previous['id'])
        receipt = read_json(self.receipt_path())
        atomic_json(previous_dir / 'editorial-settings.json', {'fixture_policy': 'edited after reservation'})
        atomic_json(previous_dir / 'planning-preferences.json', {'preferred_part_count': 42})
        self.restart()
        directory = self.manager.job_dir(receipt['job_id'])
        self.assertEqual(read_json(directory / 'editorial-settings.json'), {'fixture_policy': 'reserved'})
        self.assertEqual(read_json(directory / 'transcript.json'), read_json(previous_dir / 'transcript.json'))
        self.assertFalse((directory / 'planning-preferences.json').exists())
        self.assertEqual(self.manager.get(receipt['job_id'])['reuse_job_id'], previous['id'])
        self.assertEqual(len(self.launched), 1)

    def test_invalid_operation_and_legacy_calls_preserve_existing_contract(self):
        for operation in ('../foreign', 'invalid', uuid.uuid4().hex, str(uuid.uuid4()).upper()):
            with self.assertRaises(ValueError):
                self.create(operation_id=operation)
        self.assertEqual(self.manager.list_jobs(), [])
        self.assertFalse(self.receipt_path().parent.exists())
        first = self.manager.create(self.source_id)
        self.manager.cancel(first['id'])
        second = self.manager.create(self.source_id)
        self.assertNotEqual(first['id'], second['id'])
        self.assertFalse(self.receipt_path().parent.exists())

    def test_deleted_and_missing_committed_jobs_are_not_recreated(self):
        first = self.create()
        self.manager.cancel(first['id'])
        self.manager.delete_job(first['id'])
        self.assertEqual(read_json(self.receipt_path())['state'], 'deleted')
        with self.assertRaises(SubmissionConflict):
            self.create()
        self.assertFalse(self.manager.job_dir(first['id']).exists())
        self.assertEqual(len(self.launched), 1)

    def test_failed_delete_keeps_original_operation_replay(self):
        first = self.create()
        self.manager.cancel(first['id'])
        with patch('app.jobs.shutil.rmtree', side_effect=PermissionError('locked')), self.assertRaises(PermissionError):
            self.manager.delete_job(first['id'])
        self.assertEqual(read_json(self.receipt_path())['state'], 'committed')
        self.assertEqual(self.create()['id'], first['id'])
        self.assertEqual(len(self.launched), 1)

    def test_committed_receipt_with_externally_missing_job_cannot_resurrect_it(self):
        first = self.create()
        self.manager.cancel(first['id'])
        target = self.manager.job_dir(first['id'])
        target.resolve().relative_to(self.root.resolve())
        shutil.rmtree(target)
        with self.assertRaises(SubmissionConflict):
            self.create()
        self.assertFalse(target.exists())
        self.assertEqual(read_json(self.receipt_path())['state'], 'committed')
        self.assertEqual(len(self.launched), 1)

    def test_corrupt_receipt_is_preserved_and_cannot_authorize_new_submission(self):
        job = self.create()
        self.manager.cancel(job['id'])
        self.receipt_path().write_bytes(b'{broken receipt')
        with self.assertRaises(SubmissionConflict):
            self.create()
        self.restart()
        self.assertEqual(self.receipt_path().read_bytes(), b'{broken receipt')
        self.assertEqual(len(self.manager.list_jobs()), 1)
        self.assertEqual(len(self.launched), 1)

    def test_valid_json_with_changed_reserved_settings_is_not_silently_adopted(self):
        original = jobs.atomic_json

        def fail(path, value, **kwargs):
            if path.name == 'source.json':
                raise CreationCrash()
            return original(path, value, **kwargs)

        with patch('app.jobs.atomic_json', side_effect=fail), self.assertRaises(CreationCrash):
            self.create()
        receipt = read_json(self.receipt_path())
        receipt['files']['render-settings.json']['layout'] = 'cinema'
        atomic_json(self.receipt_path(), receipt)
        saved = self.receipt_path().read_bytes()
        with self.assertRaises(SubmissionConflict):
            self.create()
        self.restart()
        self.assertEqual(self.receipt_path().read_bytes(), saved)
        self.assertFalse((self.manager.job_dir(receipt['job_id']) / 'job.json').exists())
        self.assertFalse(self.launched)

    def test_api_replay_precedes_readiness_and_changed_request_returns_409(self):
        with patch('app.server.config.readiness', return_value={'ready': True, 'missing': []}), \
                TestClient(create_app(self.manager), base_url='http://127.0.0.1:8765') as client:
            body = {'source_id': self.source_id, 'operation_id': self.operation_id}
            first = client.post('/api/jobs', json=body)
            self.assertEqual(first.status_code, 201, first.text)
            with patch('app.server.config.readiness', side_effect=AssertionError('no readiness on replay')):
                repeated = client.post('/api/jobs', json=body)
                conflict = client.post('/api/jobs', json={**body, 'caption_style': 'accent'})
            self.assertEqual(repeated.status_code, 201, repeated.text)
            self.assertEqual(repeated.json()['id'], first.json()['id'])
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertEqual(client.post('/api/jobs', json={**body, 'operation_id': 'invalid'}).status_code, 422)
            self.assertEqual(len(self.launched), 1)

    def test_episode_operation_binds_owner_and_saved_settings_without_credentials(self):
        with patch('app.server.config.readiness', return_value={'ready': True, 'missing': []}), \
                TestClient(create_app(self.manager), base_url='http://127.0.0.1:8765') as client:
            library = client.app.state.library
            first_episode = self.episode(library)
            second_episode = self.episode(library, 2, self.sources[1]['id'])
            url = f"/api/episodes/{first_episode['id']}/jobs"
            first = client.post(url, json={'operation_id': self.operation_id})
            self.assertEqual(first.status_code, 201, first.text)
            with patch('app.server.config.readiness', side_effect=AssertionError('no readiness on replay')):
                repeated = client.post(url, json={'operation_id': self.operation_id})
                foreign = client.post(f"/api/episodes/{second_episode['id']}/jobs", json={'operation_id': self.operation_id})
            self.assertEqual(repeated.json()['id'], first.json()['id'])
            self.assertEqual(foreign.status_code, 409, foreign.text)
            self.assertEqual(first.json()['episode_id'], first_episode['id'])
            self.manager.cancel(first.json()['id'])
            settings = copy.deepcopy(library.data['episodes'][first_episode['id']]['settings'])
            library.save_episode(first_episode['id'], self.source_id, {**settings, 'economy_mode': False})
            self.assertEqual(client.post(url, json={'operation_id': self.operation_id}).status_code, 409)
            receipt = read_json(self.receipt_path())
            self.assertEqual(receipt['request']['episode_id'], first_episode['id'])
            self.assertEqual(set(receipt['files']['analysis-settings.json']), {'provider', 'economy_mode'})
            self.assertEqual(len(self.launched), 1)

    def test_existing_episode_operation_can_be_read_after_archiving_but_new_cannot_launch(self):
        library = Library(self.manager)
        episode = self.episode(library)
        job = library.launch(episode['id'], operation_id=self.operation_id)
        self.manager.cancel(job['id'])
        library.archive('episode', episode['id'])
        self.assertEqual(library.launch(episode['id'], operation_id=self.operation_id)['id'], job['id'])
        with self.assertRaises(KeyError):
            library.launch(episode['id'], operation_id=str(uuid.uuid4()))
        self.assertEqual(len(self.launched), 1)
