"""Processing contracts with fake workers; no inference or actual encoding."""
import copy
import json
import shutil
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, pipeline, processing
from app.jobs import JobManager
from app.json_store import atomic_json, read_json
from app.server import create_app
from app.semantic_identity import scoped_identity
from tests.test_jobs import FakeWorker
from tests.test_final_quality import fixture, make_plan
from tests.test_semantic_identity import changed_source


class ProcessingModesTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP / ('processing-modes-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.source = self.root/'episode.mp4'
        self.source.write_bytes(b'authored source placeholder, not encoded media')
        self.manager = JobManager(self.root, FakeWorker)
        self.source_id = self.manager.list_sources()[0]['id']

    def tearDown(self):
        self.manager.close()
        self.root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(self.root)

    def previous(self, episode_id=None, *, snapshot=True):
        job = self.manager.create(self.source_id, episode_id=episode_id)
        self.manager.cancel(job['id'])
        directory = self.manager.job_dir(job['id'])
        atomic_json(directory/'analysis.meta.json', {'source': processing.source_digest(self.source), 'version': 16})
        atomic_json(directory/'transcript.json', {'words': [], 'segments': []})
        from app.editorial import DEFAULT_PROFILE
        atomic_json(directory/'editorial-settings.json', {**DEFAULT_PROFILE, 'dramatic_condensation': False})
        if snapshot:
            analysis, _ = fixture()
            analysis['provider'] = 'local'
            analysis['events'][0]['part_endings'][0]['evidence'] = 'The original response completes the supplied source exchange.'
            processing.save_snapshot(directory, self.source, analysis)
        return self.manager.get(job['id']), directory

    def test_incremental_copies_small_checkpoints_and_keeps_media_with_ancestor(self):
        owner = str(uuid.uuid4())
        old, directory = self.previous(owner)
        (directory/'.cancel').write_text('cancel', 'utf-8')
        (directory/'worker.log').write_text('old log', 'utf-8')
        (directory/'output').mkdir()
        (directory/'output'/'part_001.mp4').write_bytes(b'export')
        (directory/'output'/'part_001.srt').write_text('subtitles', 'utf-8')
        (directory/'render').mkdir()
        atomic_json(directory/'render'/'part_001.json', {'fingerprint': 'verified-by-pipeline'})
        (directory/'clean'/'part_001'/'identity').mkdir(parents=True)
        (directory/'clean'/'part_001'/'identity'/'clean.mkv').write_bytes(b'clean media')
        before = (directory/'job.json').read_bytes()
        new = self.manager.create(self.source_id, episode_id=owner, processing_mode='incremental')
        dest = self.manager.job_dir(new['id'])
        self.assertEqual(new['reuse_job_id'], old['id'])
        self.assertEqual(read_json(dest/'transcript.json'), {'words': [], 'segments': []})
        self.assertFalse((dest/'.cancel').exists())
        self.assertFalse((dest/'worker.log').exists())
        self.assertFalse((dest/'output').exists())
        self.assertFalse((dest/'render').exists())
        self.assertFalse((dest/'clean').exists())
        from app.checkpoint_lineage import ancestors
        self.assertEqual(ancestors(dest), [directory])
        (dest/'output').mkdir()
        (dest/'output'/'part_001.mp4').write_bytes(b'new export')
        self.assertEqual((directory/'output'/'part_001.mp4').read_bytes(), b'export')
        self.assertEqual((directory/'job.json').read_bytes(), before)

    def test_full_and_changed_source_do_not_inherit_old_checkpoints(self):
        _, old = self.previous()
        new = self.manager.create(self.source_id)
        self.assertEqual(new['processing_mode'], 'full')
        self.assertIsNone(new['reuse_job_id'])
        self.assertFalse((self.manager.job_dir(new['id'])/'transcript.json').exists())
        self.manager.cancel(new['id'])
        self.source.write_bytes(b'changed original content')
        new = self.manager.create(self.source_id, processing_mode='incremental')
        self.assertIsNone(new['reuse_job_id'])
        self.assertTrue((old/'transcript.json').exists())

    def test_incremental_snapshot_skips_both_pcm_files_and_keeps_perception_metadata(self):
        _, old = self.previous()
        # Copier-only fixture: bytes are deliberately not passed to an audio reader.
        (old/'audio.wav').write_bytes(b'large derived ASR PCM placeholder')
        atomic_json(old/'audio.receipt.json', {'producer_job_id': old.name})
        (old/'media-evidence').mkdir()
        (old/'media-evidence/audio.wav').write_bytes(b'different transient source-PTS PCM')
        atomic_json(old/'media-evidence/observations.json', {'source_samples': []})
        new = self.manager.create(self.source_id, processing_mode='incremental')
        child = self.manager.job_dir(new['id'])
        self.assertFalse((child/'audio.wav').exists())
        self.assertFalse((child/'audio.receipt.json').exists())
        self.assertFalse((child/'media-evidence/audio.wav').exists())
        self.assertEqual(read_json(child/'media-evidence/observations.json'), {'source_samples': []})
        self.assertTrue((old/'audio.wav').exists())
        self.assertTrue((old/'media-evidence/audio.wav').exists())
        self.assertEqual(read_json(child/'transcript.json'), read_json(old/'transcript.json'))

    def test_cache_ownership_is_checked_before_creation(self):
        first = str(uuid.uuid4())
        old, _ = self.previous(first)
        before = len(self.manager.list_jobs())
        with self.assertRaisesRegex(ValueError, 'другой серии'):
            self.manager.create(self.source_id, episode_id=str(uuid.uuid4()),
                                processing_mode='incremental', reuse_job_id=old['id'])
        self.assertEqual(len(self.manager.list_jobs()), before)

    def test_plan_only_preflight_rejects_missing_corrupt_and_mismatched_snapshots(self):
        with self.assertRaisesRegex(ValueError, 'сохранённого анализа'):
            self.manager.create(self.source_id, processing_mode='plan_only')
        old, directory = self.previous()
        for options in ({'layout': 'cinema'}, {'analysis_provider': 'deepseek'}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'сохранённого анализа'):
                self.manager.create(self.source_id, processing_mode='plan_only', **options)
        (directory/'analysis-final.json').write_text('{broken', 'utf-8')
        with self.assertRaisesRegex(ValueError, 'сохранённого анализа'):
            self.manager.create(self.source_id, processing_mode='plan_only')
        self.assertEqual(len(self.manager.list_jobs()), 1)

    def test_plan_only_api_needs_no_models_or_configured_provider(self):
        self.previous()
        with patch('app.server.config.readiness', return_value={'ready': False, 'missing': ['model']}), \
                patch.object(self.manager, '_check_analysis_provider', side_effect=AssertionError('must not check provider')), \
                TestClient(create_app(self.manager), base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(set(client.get('/api/health').json()['processing_modes']), processing.MODES)
            response = client.post('/api/jobs', json={'source_id': self.source_id, 'processing_mode': 'plan_only'})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['processing_mode'], 'plan_only')
            dest = self.manager.job_dir(response.json()['id'])
            self.assertFalse((dest/'output').exists())
            self.assertEqual(client.post('/api/jobs', json={'source_id': self.source_id,
                'processing_mode': 'invented'}).status_code, 422)
            self.manager.cancel(response.json()['id'])
            episode = client.get('/api/library').json()['episodes'][0]
            response = client.post(f"/api/episodes/{episode['id']}/jobs", json={'processing_mode': 'plan_only'})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['episode_id'], episode['id'])

    def test_snapshot_verifies_source_bytes_and_analysis_content(self):
        _, directory = self.previous()
        original = processing.cached_analysis(directory, self.source)
        damaged = copy.deepcopy(original)
        damaged['events'][0]['summary'] = 'Modified snapshot'
        atomic_json(directory/'analysis-final.json', damaged)
        with self.assertRaisesRegex(ValueError, 'подходящего'):
            processing.cached_analysis(directory, self.source)
        processing.save_snapshot(directory, self.source, original)
        self.source.write_bytes(b'different original')
        with self.assertRaisesRegex(ValueError, 'подходящего'):
            processing.cached_analysis(directory, self.source)

    def test_real_plan_only_pipeline_does_not_analyze_repair_or_encode(self):
        _, old = self.previous()
        atomic_json(old/'plan.json', {'fingerprint': 'previous-plan', 'parts': []})
        new = self.manager.create(self.source_id, processing_mode='plan_only')
        self.manager.cancel(new['id'])
        directory = self.manager.job_dir(new['id'])
        reports = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, '_run_identity', return_value={}))
            stack.enter_context(patch.object(pipeline, 'setup_environment'))
            stack.enter_context(patch.object(pipeline, 'load_settings', return_value={'enabled': False}))
            analyze = stack.enter_context(patch('app.analysis.analyze', side_effect=AssertionError('inference forbidden')))
            sessions = stack.enter_context(patch('app.vision.vision_session', side_effect=AssertionError('sessions forbidden')))
            briefs = stack.enter_context(patch('app.part_context.generate', side_effect=AssertionError('briefs forbidden')))
            renderer = stack.enter_context(patch.object(pipeline, 'render_part', side_effect=AssertionError('encoding forbidden')))
            stack.enter_context(patch.object(pipeline, 'build_plan', side_effect=lambda a: make_plan(a, [[{'start': 0, 'end': 8}]])))
            self.assertEqual(pipeline.run_job(directory, lambda *r: reports.append(r), lambda: False), [])
            for mocked in (analyze, sessions, briefs, renderer):
                mocked.assert_not_called()
        plan = read_json(directory/'plan.json')
        self.assertEqual(len(plan['parts']), 1)
        self.assertEqual(plan['processing_mode'], 'plan_only')
        self.assertEqual(read_json(directory/'timings.json')['status'], 'completed')
        self.assertFalse((directory/'output').exists())
        self.assertIn('Видео не экспортировалось', reports[-1][-1])

    def test_plan_only_progress_distinguishes_cached_analysis_from_export(self):
        from app.job_progress import stage_progress, analysis_passes
        job = {'processing_mode': 'plan_only', 'status': 'completed', 'stage': 'completed'}
        rows = stage_progress(job, self.root)
        self.assertEqual(rows['transcribe']['status'], 'cached')
        self.assertEqual(rows['plan']['status'], 'completed')
        self.assertEqual(rows['render']['status'], 'not_required')
        self.assertTrue(all(row['status'] == 'cached' for row in analysis_passes(job, self.root).values()))

    def test_plan_only_quality_failure_requires_incremental_without_model_repair(self):
        _, directory = self.previous()
        analysis = processing.cached_analysis(directory, self.source)
        analysis['events'][0]['source_role_unresolved'] = True
        processing.save_snapshot(directory, self.source, analysis)
        job = self.manager.create(self.source_id, processing_mode='plan_only')
        self.manager.cancel(job['id'])
        destination = self.manager.job_dir(job['id'])
        with patch.object(pipeline, '_run_identity', return_value={}), \
                patch.object(pipeline, 'setup_environment'), \
                patch.object(pipeline, 'load_settings', return_value={'enabled': False}), \
                patch('app.analysis.analyze') as analyze, \
                patch('app.vision.vision_session') as sessions, \
                patch('app.quality_recovery.recover_final_quality') as repair, \
                patch.object(pipeline, 'render_part') as renderer:
            with self.assertRaisesRegex(ValueError, 'Обновить по изменениям'):
                pipeline.run_job(destination, lambda *args: None, lambda: False)
            for mocked in (analyze, sessions, repair, renderer):
                mocked.assert_not_called()
        self.assertEqual(read_json(destination/'timings.json')['status'], 'failed')

    def test_plan_only_preserves_upstream_cache_lineage_for_next_incremental_run(self):
        old, directory = self.previous()
        (directory/'visual').mkdir()
        atomic_json(directory/'visual'/'event_0000.json', {'signature': 'upstream'})
        plan = self.manager.create(self.source_id, processing_mode='plan_only')
        self.manager.cancel(plan['id'])
        updated = self.manager.create(self.source_id, processing_mode='incremental')
        inherited = self.manager.job_dir(updated['id'])/'visual'/'event_0000.json'
        self.assertEqual(updated['reuse_job_id'], plan['id'])
        self.assertEqual(read_json(inherited)['signature'], 'upstream')

    def test_planner_changes_preserve_perception_and_story_signatures(self):
        from app import planner
        before = {name: scoped_identity(name) for name in ('perception', 'story', 'late_analysis', 'planning')}
        with changed_source(planner, 'TARGET_DURATION = 90.0', 'TARGET_DURATION = 91.0'):
            after = {name: scoped_identity(name) for name in before}
        self.assertEqual(before['perception'], after['perception'])
        self.assertEqual(before['story'], after['story'])
        self.assertNotEqual(before['late_analysis'], after['late_analysis'])
        self.assertNotEqual(before['planning'], after['planning'])

    def test_preparation_signatures_only_invalidate_dependent_work(self):
        model = self.root/'asr-model'
        model.mkdir()
        (model/'model.bin').write_bytes(b'original weights')
        with patch.object(config, 'ASR_MODEL', model):
            first = processing.preparation_identity('source', {'audio_stream': 0}, {})
            (model/'model.bin').write_bytes(b'changed model weights')
            changed = processing.preparation_identity('source', {'audio_stream': 0}, {})
        self.assertEqual(first['audio'], changed['audio'])
        self.assertNotEqual(first['transcript'], changed['transcript'])
        # Provided transcripts do not depend on installed ASR models.
        supplied = processing.preparation_identity('source', {}, {'transcript_mode': 'provided'})
        with patch.object(config, 'ASR_MODEL', self.root/'missing-model'):
            self.assertEqual(supplied, processing.preparation_identity('source', {}, {'transcript_mode': 'provided'}))
        changed_source = processing.preparation_identity('changed', {'audio_stream': 0}, {})
        self.assertNotEqual(first['audio'], changed_source['audio'])
        self.assertNotEqual(first['transcript'], changed_source['transcript'])
