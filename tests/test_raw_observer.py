"""The diagnostic recorder must preserve actual runtime thinking settings."""
import shutil
import unittest
import uuid
import json
from contextlib import contextmanager
from unittest.mock import Mock, patch

from app.config import TEMP
from app.vision import LocalVision
from scripts.run_raw_video_quality import RecordedVision


class RawObserverTests(unittest.TestCase):
    def _shared_factory_observation(self, *, fail):
        import app.analysis as analysis_module
        import app.candidate_framing as framing_module
        import app.pipeline as pipeline_module
        import app.vision as vision_module
        from scripts.run_production_raw_quality import run

        directory = TEMP/('raw-observer-shared-factory-'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        try:
            fixture, job = directory/'input', directory/'job'
            fixture.mkdir()
            source = fixture/'authored-source.mp4'
            source.write_bytes(b'Authored source identity only; never decoded or used for inference')
            (fixture/'input.json').write_text(json.dumps({'source': str(source)}), encoding='utf-8')
            clients = []

            @contextmanager
            def metadata_factory(*args, **kwargs):
                # Do not enter LocalVision: construction exposes metadata only.
                native = LocalVision(job, lambda: False, thinking=False)
                clients.append(native)
                yield native

            shared_before = Mock(side_effect=AssertionError('unobserved shared factory used'))
            framing_before = Mock(side_effect=AssertionError('unobserved framing factory used'))

            def authored_pipeline(job_dir, report, cancelled):
                self.assertIs(analysis_module.vision_session, vision_module.vision_session)
                self.assertIs(framing_module.vision_session, vision_module.vision_session)
                self.assertIsNot(vision_module.vision_session, shared_before)
                self.assertIsNot(analysis_module.vision_session, metadata_factory)
                # Match candidate_analysis's downstream dynamic factory import.
                from app.vision import vision_session
                with vision_session(job_dir, cancelled, 'local') as observed:
                    self.assertIsInstance(observed, RecordedVision)
                    self.assertFalse(observed.thinking)
                    self.assertIsNone(observed.vision.process)
                    self.assertEqual(observed.calls, 0)
                if fail:
                    raise RuntimeError('Authored pipeline failure after observed metadata session')
                (job_dir/'final_quality_gate.json').write_text(
                    json.dumps({'status': 'passed', 'authored_test_gate': True}), encoding='utf-8')
                return []

            with patch.object(analysis_module, 'vision_session', metadata_factory), \
                 patch.object(vision_module, 'vision_session', shared_before), \
                 patch.object(framing_module, 'vision_session', framing_before), \
                 patch.object(pipeline_module, 'run_job', side_effect=authored_pipeline) as pipeline, \
                 patch.object(LocalVision, 'query', side_effect=AssertionError('no model requests allowed')), \
                 patch.object(LocalVision, '__enter__', side_effect=AssertionError('no model startup allowed')):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'Authored pipeline failure'):
                        run(fixture, job, render=True)
                else:
                    result = run(fixture, job, render=True)
                    self.assertTrue(result['complete'])
                # Check inside the patch context: run() itself must restore each
                # previous binding, even when they were three distinct factories.
                self.assertIs(analysis_module.vision_session, metadata_factory)
                self.assertIs(vision_module.vision_session, shared_before)
                self.assertIs(framing_module.vision_session, framing_before)
                pipeline.assert_called_once()
            shared_before.assert_not_called()
            framing_before.assert_not_called()
            self.assertEqual(len(clients), 1)
            self.assertIsNone(clients[0].process)
            sessions = json.loads((job/'observed-sessions.json').read_text(encoding='utf-8'))
            self.assertEqual(len(sessions), 1)
            self.assertFalse(sessions[0]['thinking'])
            self.assertEqual(sessions[0]['new_requests'], 0)
            self.assertEqual(sessions[0]['total_requests'], 0)
            outcome = json.loads((job/'observed-outcome.json').read_text(encoding='utf-8'))
            self.assertEqual(outcome['actual_model_requests'], 0)
            self.assertEqual(outcome['recorded_local_calls'], 0)
            self.assertTrue(outcome['pipeline_code_stable'])
            if fail:
                self.assertEqual(outcome['error_type'], 'RuntimeError')
                self.assertFalse(outcome['complete'])
        finally:
            directory.resolve().relative_to(TEMP.resolve())
            shutil.rmtree(directory)

    def test_production_observer_wraps_shared_downstream_factory_and_restores_success(self):
        self._shared_factory_observation(fail=False)

    def test_production_observer_restores_all_factories_after_pipeline_failure(self):
        self._shared_factory_observation(fail=True)

    def test_remote_alias_and_retries_count_transports_not_recorded_calls(self):
        from scripts.run_production_raw_quality import _transport_records
        directory = TEMP/('raw-observer-counts-'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        try:
            rows = [{'event': 'request_start', 'model': 'deepseek_flash'},
                    {'event': 'request_end', 'model': 'deepseek_flash'},
                    {'event': 'request_start', 'model': 'deepseek_flash', 'transport_attempt': 2},
                    {'event': 'request_start', 'model': 'visual4b'},
                    {'event': 'startup', 'model': 'visual4b'},
                    {'event': 'cache_reuse', 'model': 'deepseek_flash'}]
            path = directory/'model-performance.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in rows), 'utf-8')
            self.assertEqual(_transport_records(directory, 'deepseek-flash'), {'local': 1, 'remote': 2, 'complete': True})
            with path.open('a', encoding='utf-8') as stream:
                stream.write('\n{torn')
            self.assertEqual(_transport_records(directory, 'deepseek-flash'), {'local': 1, 'remote': 2, 'complete': False})
        finally:
            directory.resolve().relative_to(TEMP.resolve())
            shutil.rmtree(directory)

    def test_shared_session_thinking_changes_reach_underlying_client(self):
        directory = TEMP/('raw-observer-'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        try:
            # Construct metadata only: no server, GPU, model or request starts.
            native = LocalVision(directory, lambda: False, thinking=True)
            recorder = RecordedVision(native, directory/'records')
            self.assertTrue(recorder.thinking)
            recorder.thinking = False
            self.assertFalse(native.thinking)
            native.thinking = True
            self.assertTrue(recorder.thinking)
            self.assertIsNone(native.process)
        finally:
            directory.resolve().relative_to(TEMP.resolve())
            shutil.rmtree(directory)


class StandaloneAcceptanceTests(unittest.TestCase):
    def fixture(self):
        import copy
        current = {'status': 'ready', 'technical_failures': [], 'accepted': [
            {'id': 'candidate-a', 'filename': 'part_001.mp4', 'status': 'ready', 'export_eligible': True}]}
        published = {'plan': {'outcome': copy.deepcopy(current), 'parts': [{'candidate_id': 'candidate-a'}]},
            'outputs': ['part_001.mp4', 'part_001.srt'], 'artifacts': [
                {'candidate_id': 'candidate-a', 'video': {'filename': 'part_001.mp4'}}]}
        return published, current, published['outputs'][:]

    def test_current_accepted_media_matches_committed_publication(self):
        from scripts.run_production_raw_quality import _standalone_accepted
        self.assertTrue(_standalone_accepted(*self.fixture()))

    def test_preserved_previous_output_is_not_current_attempt_acceptance(self):
        from scripts.run_production_raw_quality import _standalone_accepted
        published, current, outputs = self.fixture()
        current.update(status='needs_review', accepted=[])
        self.assertFalse(_standalone_accepted(published, current, outputs))

    def test_changed_current_verdict_cannot_borrow_previous_candidate_media(self):
        from scripts.run_production_raw_quality import _standalone_accepted
        published, current, outputs = self.fixture()
        current['accepted'][0]['source_contract_digest'] = 'changed-new-review'
        self.assertFalse(_standalone_accepted(published, current, outputs))

    def test_partial_technical_failure_remains_visible_even_with_valid_media(self):
        from scripts.run_production_raw_quality import _standalone_accepted
        published, current, outputs = self.fixture()
        current.update(status='partial', technical_failures=[{'reason': 'decoder_failed'}])
        published['plan']['outcome'] = current
        self.assertFalse(_standalone_accepted(published, current, outputs))

    def test_candidate_or_filename_mismatch_fails_acceptance(self):
        from scripts.run_production_raw_quality import _standalone_accepted
        for mismatch in ('candidate_id', 'filename', 'outputs'):
            with self.subTest(mismatch=mismatch):
                published, current, outputs = self.fixture()
                if mismatch == 'candidate_id':
                    published['plan']['parts'][0]['candidate_id'] = 'other-candidate'
                elif mismatch == 'filename':
                    published['artifacts'][0]['video']['filename'] = 'part_002.mp4'
                else:
                    outputs = ['part_002.mp4', 'part_002.srt']
                self.assertFalse(_standalone_accepted(published, current, outputs))
