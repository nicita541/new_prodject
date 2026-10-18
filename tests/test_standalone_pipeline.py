"""Real standalone orchestration/publication with authored non-media boundary bytes.

No model, network, decoder or encoder is exercised by these mechanism tests.
"""
import copy
from contextlib import ExitStack
import json
import shutil
import unittest
import uuid
from unittest.mock import patch

from app import pipeline
from app.artifact_publication import current_revision
from app.config import ROOT
from app.json_store import atomic_json, read_json
from app.music import DEFAULT_CONFIG
from tests.test_standalone_planner import source_fixture


class StandalonePipelineTests(unittest.TestCase):
    def setUp(self):
        self.job = ROOT/'temp'/('standalone-mechanism-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.addCleanup(self.cleanup)
        self.source = self.job/'source.mp4'
        self.source.write_bytes(b'authored source placeholder; not encoded media')
        atomic_json(self.job/'source.json', {'path': str(self.source), 'name': 'authored.mp4'})
        atomic_json(self.job/'story-objective.json', {'version': 1, 'objective': 'standalone_shorts'})
        self.analysis = source_fixture(2)
        self.failure = None
        self.rendered = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        def stub(target, **kwargs):
            return self.stack.enter_context(patch(target, **kwargs))
        self.analyzer = stub('app.analysis.analyze', side_effect=lambda *a: copy.deepcopy(self.analysis))
        self.renderer = stub('app.pipeline.render_part', side_effect=self.render)
        self.encoder = stub('app.pipeline.choose_encoder', return_value='authored_encoder')
        stub('app.pipeline.prepare_clean_part', side_effect=lambda s,p,pr,*a: (s,p,pr,False))
        stub('app.pipeline.setup_environment')
        stub('app.pipeline._run_identity', return_value={'kind': 'authored_mechanism'})
        stub('app.pipeline.load_settings', return_value={**DEFAULT_CONFIG, 'enabled': False})
        stub('app.pipeline.validate_export')
        stub('app.subtitles.style_identity', return_value={'kind': 'authored_style'})
        stub('app.analysis_provider.analysis_provider', return_value='authored_provider')
        self.query = stub('app.vision.vision_session', side_effect=AssertionError('No model session is allowed'))
        stub('app.semantic_identity.scoped_identity', return_value={'digest': 'authored_compiler_identity'})
        stub('app.editorial.load_profile', return_value={'dramatic_condensation': False})

    def cleanup(self):
        self.job.resolve().relative_to((ROOT/'temp').resolve())
        shutil.rmtree(self.job)

    def render(self, source, part, probe, output_dir, workdir, *args, **kwargs):
        event = part['cuts'][0]['start']
        if self.failure is not None:
            self.failure(event)
        self.rendered.append(event)
        output = output_dir/f"part_{part['index']:03}.mp4"
        output.write_bytes(('authored render placeholder '+str(event)).encode())
        output.with_suffix('.srt').write_text('authored subtitle placeholder\n', encoding='utf-8')
        return output

    def run_job(self):
        return pipeline.run_job(self.job, lambda *a: None, lambda: False)

    def invalidate_renders(self):
        for checkpoint in (self.job/'candidate-renders').rglob('part_001.json'):
            checkpoint.unlink()

    def test_unknown_elsewhere_does_not_apply_global_episode_gate(self):
        self.analysis['events'][1].update(analysis_unresolved=True, understanding_confidence=.4)
        self.assertEqual(self.run_job(), ['part_001.mp4', 'part_001.srt'])
        committed = current_revision(self.job)
        self.assertEqual(committed['plan']['selected_event_ids'], ['e0'])
        self.assertTrue(committed['plan']['outcome']['drafts'])
        self.assertFalse((self.job/'final_quality_gate.json').exists())
        self.query.assert_not_called()

    def test_native_failure_elsewhere_stays_visible_without_vetoing_ready_clip(self):
        self.analysis['events'][1].update(analysis_unresolved=True, understanding_confidence=.4)
        failure = {'stage': 'source_selection', 'event_id': 'e1',
                   'reason': 'model_output_invalid', 'error_type': 'ValueError', 'export_eligible': False}
        self.analysis['analysis_technical_failures'] = [failure]
        self.run_job()
        outcome = current_revision(self.job)['plan']['outcome']
        self.assertEqual(outcome['status'], 'partial')
        self.assertEqual(outcome['technical_failures'], [failure])
        self.assertEqual(len(outcome['accepted']), 1)

    def test_rank_is_independent_from_source_chronology_and_warm_cache(self):
        self.analysis['events'][1]['importance'] = 5
        self.run_job()
        plan = current_revision(self.job)['plan']
        self.assertEqual(plan['parts'][0]['cuts'][0]['start'], 70)
        for part in plan['parts']:
            self.assertEqual(part['cuts'], sorted(part['cuts'], key=lambda c: c['start']))
        self.renderer.reset_mock(); self.encoder.reset_mock()
        self.run_job()
        self.renderer.assert_not_called(); self.encoder.assert_not_called(); self.query.assert_not_called()
        self.analysis['events'][0]['importance'] = 5
        self.analysis['events'][1]['importance'] = 2
        self.run_job()
        self.assertEqual(current_revision(self.job)['plan']['parts'][0]['cuts'][0]['start'], 0)
        self.renderer.assert_not_called()

    def test_job_owned_clean_folder_allows_actual_process_start(self):
        import sys
        from pathlib import Path
        from app.clean_parts import clean_identity
        from app.media import run_command
        self.analysis = source_fixture()
        fingerprint = 'a' * 64
        spawned = []

        def prepare(source, part, probe, folder, cancelled):
            identity = clean_identity(source, part, probe)
            cwd = folder/'clean'/f"part_{part['index']:03}"/identity
            # This is the same Windows CreateProcess cwd shape that failed in
            # real cleaning, with a harmless Python child instead of an encode.
            self.assertLess(len(str(cwd)), 260)
            self.assertEqual(folder, self.job)
            output = run_command([sys.executable, '-B', '-c', 'import os; print(os.getcwd())'],
                                 cwd, cancelled, timeout=10)
            self.assertEqual(Path(output.strip()).resolve(), cwd.resolve())
            spawned.append(cwd)
            return source, part, probe, False

        with patch('app.pipeline._part_render_fingerprint', return_value=fingerprint), \
             patch('app.pipeline.prepare_clean_part', side_effect=prepare):
            self.assertEqual(self.run_job(), ['part_001.mp4', 'part_001.srt'])
        self.assertEqual(len(spawned), 1)
        self.assertEqual(current_revision(self.job)['plan']['outcome']['status'], 'ready')
        self.query.assert_not_called()

    def test_compact_folder_collision_still_checks_full_fingerprint_and_reuses_exact_match(self):
        self.analysis = source_fixture()
        prefix = 'a' * 24
        fingerprints = [prefix + '1' * 40, prefix + '2' * 40]
        active = [fingerprints[0]]

        def render(*args, **kwargs):
            path = self.render(*args, **kwargs)
            path.write_bytes(('authored render for full fingerprint ' + active[0]).encode())
            return path

        self.renderer.side_effect = render
        with patch('app.pipeline._part_render_fingerprint', side_effect=lambda *a: active[0]):
            self.run_job()
            previous = current_revision(self.job)
            previous_video = self.job/'revisions'/previous['revision_id']/'part_001.mp4'
            previous_bytes = previous_video.read_bytes()
            checkpoints = list((self.job/'candidate-renders').rglob('part_001.json'))
            self.assertEqual(len(checkpoints), 1)
            checkpoint = checkpoints[0]
            self.assertEqual(checkpoint.parent.parent.name, prefix)
            self.assertEqual(read_json(checkpoint)['fingerprint'], fingerprints[0])
            self.renderer.reset_mock()
            self.run_job()
            self.renderer.assert_not_called()
            active[0] = fingerprints[1]
            self.run_job()
            self.renderer.assert_called_once()
            self.assertEqual(list((self.job/'candidate-renders').rglob('part_001.json')), [checkpoint])
            self.assertEqual(read_json(checkpoint)['fingerprint'], fingerprints[1])
            latest = current_revision(self.job)
            latest_video = self.job/'revisions'/latest['revision_id']/'part_001.mp4'
            self.assertNotEqual(latest_video.read_bytes(), previous_bytes)
            self.assertIn(fingerprints[1].encode(), latest_video.read_bytes())
            self.assertEqual(previous_video.read_bytes(), previous_bytes)
            self.renderer.reset_mock()
            self.run_job()
            self.renderer.assert_not_called()
        self.query.assert_not_called()

    def test_avatar_bytes_change_invalidates_render_without_changing_asset_id(self):
        self.analysis = source_fixture()
        avatar = self.job / 'avatar.png'
        avatar.write_bytes(b'authored first avatar')
        video = {'frame_style': 'social', 'avatar_id': 'same_asset_id'}
        with patch('app.standalone_pipeline._appearance', return_value=(video,
                {'video': video, 'avatar_path': avatar})):
            self.run_job()
            self.renderer.reset_mock()
            self.run_job()
            self.renderer.assert_not_called()
            avatar.write_bytes(b'authored other avatar')
            self.run_job()
            self.renderer.assert_called_once()
        self.query.assert_not_called()

    def test_candidate_failure_publishes_other_candidate_as_partial(self):
        def fail_first(start):
            if start == 0:
                raise RuntimeError('authored candidate failure')
        self.failure = fail_first
        self.assertEqual(self.run_job(), ['part_002.mp4', 'part_002.srt'])
        outcome = current_revision(self.job)['plan']['outcome']
        self.assertEqual(outcome['status'], 'partial')
        self.assertEqual(len(outcome['technical_failures']), 1)
        self.assertEqual(len(outcome['accepted']), 1)

    def test_framing_failure_keeps_approved_cuts_and_other_candidate_publication(self):
        self.analysis['analysis_contract'] = 'standalone_selective_v1'
        calls, original_cuts = [], {}

        def frame(source, compiled, *args, **kwargs):
            self.assertEqual(len(compiled['candidates']), 1)
            candidate = compiled['candidates'][0]
            calls.append((candidate['id'], kwargs['allow_new_session']))
            original_cuts[candidate['id']] = copy.deepcopy(candidate['plan']['parts'][0]['cuts'])
            if len(calls) == 1:
                raise TimeoutError('Authored framing failure; the approved story is unchanged')
            return compiled  # Authored stand-in for a previously cached overlay.

        with patch('app.candidate_framing.frame_final_candidates', side_effect=frame):
            self.assertEqual(self.run_job(), ['part_001.mp4', 'part_001.srt', 'part_002.mp4', 'part_002.srt'])
        self.assertEqual([allow for _, allow in calls], [True, False])
        committed = current_revision(self.job)['plan']
        outcome = committed['outcome']
        self.assertEqual(outcome['status'], 'partial')
        self.assertEqual(len(outcome['accepted']), 2)
        self.assertEqual(len(outcome['technical_failures']), 1)
        failure = outcome['technical_failures'][0]
        self.assertEqual(failure['candidate_id'], calls[0][0])
        self.assertEqual(failure['stage'], 'candidate_framing')
        self.assertEqual(failure['reason'], 'technical_focus_failure')
        self.assertEqual(failure['error_type'], 'TimeoutError')
        self.assertEqual(failure['fallback'], 'cinema')
        first, second = committed['parts']
        self.assertEqual(first['candidate_id'], calls[0][0])
        self.assertEqual(first['layout'], 'cinema')
        self.assertEqual(first['framing_fallback']['reason'], 'technical_focus_failure')
        self.assertNotIn('framing_fallback', second)
        for part in committed['parts']:
            self.assertEqual(part['cuts'], original_cuts[part['candidate_id']])
            native = committed['candidate_plans'][part['candidate_id']]
            self.assertTrue(native['export_eligible'])
            self.assertEqual(native['parts'][0]['cuts'], original_cuts[part['candidate_id']])
        self.assertEqual(read_json(self.job/'standalone-outcome.json')['status'], 'partial')
        self.query.assert_not_called()

    def test_framing_cancellation_propagates_without_render_or_publication(self):
        self.analysis['analysis_contract'] = 'standalone_selective_v1'
        with patch('app.candidate_framing.frame_final_candidates',
                   side_effect=InterruptedError('Authored framing cancellation')) as framer, \
             self.assertRaisesRegex(InterruptedError, 'framing cancellation'):
            self.run_job()
        framer.assert_called_once()
        self.assertTrue(framer.call_args.kwargs['allow_new_session'])
        self.assertIsNone(current_revision(self.job))
        self.assertFalse((self.job/'publication.json').exists())
        self.assertEqual(read_json(self.job/'timings.json')['status'], 'cancelled')
        self.renderer.assert_not_called()
        self.encoder.assert_not_called()
        self.query.assert_not_called()

    def test_all_failure_and_cancellation_preserve_committed_plan_and_bytes(self):
        self.run_job()
        previous = current_revision(self.job)
        pointer = (self.job/'publication.json').read_bytes()
        self.invalidate_renders()
        def fail(start):
            raise RuntimeError('authored all-candidate failure')
        self.failure = fail
        with self.assertRaisesRegex(RuntimeError, 'предыдущая публикация'):
            self.run_job()
        self.assertEqual((self.job/'publication.json').read_bytes(), pointer)
        self.assertEqual(current_revision(self.job), previous)
        self.assertEqual(read_json(self.job/'standalone-outcome.json')['status'], 'failed')
        self.assertEqual(read_json(self.job/'plan.json')['parts'], [])
        def cancel(start):
            raise InterruptedError('authored cancellation')
        self.failure = cancel
        with self.assertRaises(InterruptedError):
            self.run_job()
        self.assertEqual(current_revision(self.job), previous)
        self.assertEqual(read_json(self.job/'timings.json')['status'], 'cancelled')

    def test_plan_only_uses_snapshot_without_analyzing_or_exporting(self):
        self.run_job()
        previous = current_revision(self.job)
        atomic_json(self.job/'processing-settings.json', {'mode': 'plan_only'})
        self.renderer.reset_mock(); self.analyzer.reset_mock()
        self.assertEqual(self.run_job(), [])
        self.renderer.assert_not_called(); self.analyzer.assert_not_called(); self.query.assert_not_called()
        self.assertEqual(current_revision(self.job), previous)
        self.assertEqual(read_json(self.job/'standalone-outcome.json')['status'], 'planned')

    def whole_candidate_source(self):
        """Authored native evidence tied to this mechanism test's source bytes."""
        from app.content_identity import file_sha256
        from app.story_candidates import CONTRACT
        from tests.test_story_candidates import candidate_fixture
        with patch('tests.test_story_candidates.SOURCE_SHA', file_sha256(self.source)):
            qualified, record, _ = candidate_fixture()
        qualified.update(analysis_contract=CONTRACT, quality_policy=CONTRACT,
                         events=[], candidate_records=[record])
        source = copy.deepcopy(qualified)
        source.pop('candidate_records')
        source.update(analysis_contract='standalone_source_v2', quality_policy='standalone_source_v2',
            check_policy={'objective': 'standalone_shorts', 'authority': 'hypothesis_only'},
            episode_map={'source_sha256': qualified['source_sha256'], 'authority': 'hypothesis_only',
                'windows': [{'id': 'w1', 'start': 0., 'end': 60.}],
                'hypotheses': [{'id': 'h1', 'window_ids': ['w1'], 'prerequisite_window_ids': []}]})
        self.analysis = source
        return qualified

    def test_source_contract_qualifies_then_compiles_then_frames_new_native_contract(self):
        from app.standalone_planner import build_standalone_candidates
        qualified = self.whole_candidate_source()
        original = copy.deepcopy(self.analysis)
        calls = []

        def qualify(source, analysis, settings, *args, **kwargs):
            calls.append('qualification')
            self.assertEqual(source, self.source)
            self.assertEqual(analysis, original)
            self.assertTrue(kwargs['allow_new'])
            return copy.deepcopy(qualified)

        def compile(analysis, settings):
            calls.append('compiler')
            self.assertEqual(analysis['analysis_contract'], 'standalone_candidate_proved_v1')
            return build_standalone_candidates(analysis, settings)

        def frame(source, compiled, *args, **kwargs):
            calls.append('framing')
            self.assertEqual(len(compiled['candidates']), 1)
            self.assertEqual(compiled['candidates'][0]['scoped_analysis']['quality_policy'],
                             'standalone_candidate_proved_v1')
            self.assertTrue(kwargs['allow_new_session'])
            return compiled

        with patch('app.candidate_analysis.qualify_candidates', side_effect=qualify), \
             patch('app.standalone_planner.build_standalone_candidates', side_effect=compile), \
             patch('app.candidate_framing.frame_final_candidates', side_effect=frame):
            self.assertEqual(self.run_job(), ['part_001.mp4', 'part_001.srt'])
        self.assertEqual(calls, ['qualification', 'compiler', 'framing'])
        self.assertEqual(read_json(self.job/'analysis-final.json'), original)
        self.assertNotIn('candidate_records', read_json(self.job/'analysis-final.json'))
        published = current_revision(self.job)['plan']
        self.assertEqual(published['outcome']['status'], 'ready')
        owners = {event['id']: event for event in published['events']}
        self.assertTrue(published['selected_event_ids'])
        self.assertLessEqual(set(published['selected_event_ids']), set(owners))
        for part in published['parts']:
            for cut in part['cuts']:
                self.assertLessEqual(set(cut['event_ids']), set(owners))
                self.assertTrue(all(owners[owner]['source_interval'] for owner in cut['event_ids']))
        self.assertEqual(original['events'], [])
        self.assertEqual(self.analysis['events'], [])
        self.assertEqual(read_json(self.job/'analysis-final.json')['events'], [])
        self.query.assert_not_called()

    def test_contextual_native_positive_with_negative_cut_only_screen_produces_review_draft_only(self):
        from app.story_candidates import review_status, prototype_plan
        qualified = self.whole_candidate_source()
        record = qualified['candidate_records'][0]
        native, _ = prototype_plan(qualified, record['case'], record['proposal'])
        self.assertEqual(review_status(qualified, record['case'], record['proposal'], native, record['review']), 'ready')
        record['screen']['verdict']['criteria']['understandable_without_external_context'] = False
        record['screen']['verdict']['issues'] = ['AUTHORED negative viewer judgement: an omitted cause is needed.']
        with patch('app.candidate_analysis.qualify_candidates', return_value=qualified), \
             patch('app.candidate_framing.frame_final_candidates') as framing:
            self.assertEqual(self.run_job(), [])
        self.assertIsNone(current_revision(self.job))
        self.assertFalse((self.job/'publication.json').exists())
        outcome = read_json(self.job/'standalone-outcome.json')
        self.assertEqual(outcome['status'], 'needs_review')
        self.assertEqual(outcome['accepted'], [])
        self.assertTrue(outcome['drafts'])
        self.assertTrue(all(draft['export_eligible'] is False for draft in outcome['drafts']))
        framing.assert_not_called()
        self.assertEqual(read_json(self.job/'analysis-final.json')['analysis_contract'], 'standalone_source_v2')
        self.query.assert_not_called()

    def test_source_snapshot_reused_with_new_count_plan_only_forbids_new_qualification_and_framing(self):
        from app.processing import save_snapshot, cached_analysis
        qualified = self.whole_candidate_source()
        save_snapshot(self.job, self.source, self.analysis)
        saved = (self.job/'analysis-final.json').read_bytes()
        atomic_json(self.job/'processing-settings.json', {'mode': 'plan_only'})
        atomic_json(self.job/'story-objective.json', {'version': 1, 'objective': 'standalone_shorts',
                                                    'settings': {'max_clips': 1}})
        self.assertEqual(cached_analysis(self.job, self.source), self.analysis)

        def qualify(source, analysis, settings, *args, **kwargs):
            self.assertFalse(kwargs['allow_new'])
            self.assertEqual(settings['max_clips'], 1)
            self.assertEqual(analysis, self.analysis)
            return copy.deepcopy(qualified)

        with patch('app.candidate_analysis.qualify_candidates', side_effect=qualify) as qualifier, \
             patch('app.candidate_framing.frame_final_candidates', side_effect=lambda s, c, *a, **k: c) as framer:
            self.assertEqual(self.run_job(), [])
        qualifier.assert_called_once()
        framer.assert_called_once()
        self.assertFalse(framer.call_args.kwargs['allow_new_session'])
        self.assertEqual((self.job/'analysis-final.json').read_bytes(), saved)
        self.assertEqual(read_json(self.job/'standalone-outcome.json')['status'], 'planned')
        self.analyzer.assert_not_called()
        self.renderer.assert_not_called()
        self.query.assert_not_called()

    def test_source_plan_only_qualification_miss_is_explicit_and_starts_no_inference(self):
        from app.processing import save_snapshot
        self.whole_candidate_source()
        save_snapshot(self.job, self.source, self.analysis)
        atomic_json(self.job/'processing-settings.json', {'mode': 'plan_only'})

        def missing(source, analysis, settings, *args, **kwargs):
            self.assertFalse(kwargs['allow_new'])
            raise ValueError('Authored missing whole-candidate checkpoint; new inference is forbidden')

        with patch('app.candidate_analysis.qualify_candidates', side_effect=missing) as qualifier, \
             patch('app.standalone_planner.build_standalone_candidates') as compiler, \
             patch('app.candidate_framing.frame_final_candidates') as framer, \
             self.assertRaisesRegex(ValueError, 'whole-candidate checkpoint'):
            self.run_job()
        qualifier.assert_called_once()
        compiler.assert_not_called()
        framer.assert_not_called()
        self.analyzer.assert_not_called()
        self.renderer.assert_not_called()
        self.query.assert_not_called()
        self.assertIsNone(current_revision(self.job))

    def test_no_ready_candidates_keep_drafts_nonexportable(self):
        for event in self.analysis['events']:
            event.update(analysis_unresolved=True, understanding_confidence=.4)
        self.assertEqual(self.run_job(), [])
        self.assertIsNone(current_revision(self.job))
        self.assertEqual(self.renderer.call_count, 2)
        outcome = read_json(self.job/'standalone-outcome.json')
        self.assertEqual(outcome['status'], 'needs_review')
        self.assertTrue(outcome['drafts'])
        self.assertTrue(all(d['export_eligible'] is False for d in outcome['drafts']))
        self.assertTrue(all(d['status'] == 'rendered_needs_review' and d['video_url'] for d in outcome['drafts']))
        self.assertTrue(all('plan' not in d for d in outcome['drafts']))
        self.renderer.reset_mock()
        self.run_job()
        self.renderer.assert_not_called()

    def test_complete_negative_selective_discovery_is_reusable_for_plan_only(self):
        self.analysis['events'] = []
        self.analysis['analysis_contract'] = 'standalone_selective_v1'
        self.analysis['check_policy'] = {'objective': 'standalone_shorts'}
        self.assertEqual(self.run_job(), [])
        self.assertEqual(read_json(self.job/'standalone-outcome.json')['status'], 'needs_review')
        atomic_json(self.job/'processing-settings.json', {'mode': 'plan_only'})
        self.analyzer.reset_mock()
        self.assertEqual(self.run_job(), [])
        self.analyzer.assert_not_called()
        self.renderer.assert_not_called()
        self.query.assert_not_called()

    def test_new_drafts_preserve_previous_ready_publication(self):
        outputs = self.run_job()
        previous = current_revision(self.job)
        for event in self.analysis['events']:
            event.update(analysis_unresolved=True, understanding_confidence=.4)
        self.assertEqual(self.run_job(), outputs)
        self.assertEqual(current_revision(self.job), previous)
        latest = read_json(self.job/'standalone-outcome.json')
        self.assertEqual(latest['status'], 'needs_review')
        self.assertTrue(all(d['status'] == 'rendered_needs_review' for d in latest['drafts']))


    def test_failed_job_api_serves_previous_committed_plan_and_artifact(self):
        from fastapi.testclient import TestClient
        from app.jobs import JobManager
        from app.server import create_app
        from tests.test_jobs import FakeWorker
        root = self.job
        manager = JobManager(root, FakeWorker)
        self.addCleanup(manager.close)
        job = manager.create(source_id=manager.list_sources()[0]['id'],
            story_objective={'objective': 'standalone_shorts'})
        self.job = manager.job_dir(job['id'])
        try:
            self.run_job()
            committed = current_revision(self.job)
            self.invalidate_renders()
            def fail(start):
                raise RuntimeError('authored subsequent attempt failure')
            self.failure = fail
            with self.assertRaises(RuntimeError):
                self.run_job()
            state = read_json(self.job/'job.json')
            state.update(status='failed', outputs=[])
            atomic_json(self.job/'job.json', state)
            with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
                response = client.get(f"/api/jobs/{job['id']}/plan")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([p['cuts'] for p in response.json()['parts']],
                                 [p['cuts'] for p in committed['plan']['parts']])
                artifact = client.get(f"/api/jobs/{job['id']}/files/part_001.mp4")
                self.assertEqual(artifact.status_code, 200)
                self.assertIn(b'authored render placeholder', artifact.content)
                detail = client.get(f"/api/jobs/{job['id']}")
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertTrue(detail.json()['files'])
        finally:
            self.job = root


class SourceOnlySnapshotPolicyTests(unittest.TestCase):
    """Exercise real persisted policy loaders, with every inference boundary forbidden."""

    def setUp(self):
        from app.content_identity import file_sha256
        self.job = ROOT/'temp'/('source-snapshot-policy-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.addCleanup(self.cleanup)
        self.source = self.job/'source.mp4'
        self.source_bytes = b'authored physical source; no encoded media'
        self.source.write_bytes(self.source_bytes)
        self.legacy = source_fixture()
        self.analysis = copy.deepcopy(self.legacy)
        self.analysis.update(events=[], analysis_contract='standalone_source_v2',
            quality_policy='standalone_source_v2', source_sha256=file_sha256(self.source),
            check_policy={'objective': 'standalone_shorts', 'authority': 'hypothesis_only'})
        for index, shot in enumerate(self.analysis['shots']):
            shot['id'] = f'original_shot_{index}'
        self.analysis['episode_map'] = {'source_sha256': self.analysis['source_sha256'],
                                      'authority': 'hypothesis_only', 'windows': [], 'hypotheses': []}
        atomic_json(self.job/'story-objective.json', {'version': 1, 'objective': 'standalone_shorts'})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('app.analysis_provider.analysis_provider', return_value='authored_provider'))
        self.analyzer = self.stack.enter_context(patch('app.analysis.analyze', side_effect=AssertionError('No ASR or analysis allowed')))
        self.model = self.stack.enter_context(patch('app.vision.vision_session', side_effect=AssertionError('No model allowed')))
        self.reset_policies()

    def cleanup(self):
        self.job.resolve().relative_to((ROOT/'temp').resolve())
        shutil.rmtree(self.job)

    def reset_policies(self):
        from app.editorial import DEFAULT_PROFILE
        atomic_json(self.job/'render-settings.json', {'layout': 'portrait', 'caption_style': 'classic'})
        atomic_json(self.job/'editorial-settings.json', DEFAULT_PROFILE)
        atomic_json(self.job/'selection-policy.json', {'version': 1, 'mode': 'strict'})

    def test_source_only_snapshot_survives_layout_editorial_and_confirmed_selection_changes(self):
        from app.editorial import DRAMATIC_PROFILE
        from app.processing import save_snapshot, cached_analysis, snapshot_identity
        save_snapshot(self.job, self.source, self.analysis)
        original = snapshot_identity(self.job, self.source, self.analysis)
        snapshot_bytes = (self.job/'analysis-final.json').read_bytes()
        atomic_json(self.job/'render-settings.json', {'layout': 'cinema', 'caption_style': 'accent'})
        atomic_json(self.job/'editorial-settings.json', DRAMATIC_PROFILE)
        atomic_json(self.job/'selection-policy.json', {'version': 1, 'mode': 'confirmed_only'})
        self.assertEqual(snapshot_identity(self.job, self.source, self.analysis), original)
        self.assertEqual(original['layout'], 'source_only')
        self.assertEqual(original['editorial_profile'], {})
        self.assertNotIn('selection_policy', original)
        self.assertEqual(cached_analysis(self.job, self.source), self.analysis)
        self.assertEqual((self.job/'analysis-final.json').read_bytes(), snapshot_bytes)
        self.analyzer.assert_not_called()
        self.model.assert_not_called()

    def test_legacy_snapshot_keeps_existing_layout_editorial_and_selection_bindings(self):
        from app.editorial import DRAMATIC_PROFILE
        from app.processing import save_snapshot, cached_analysis
        for policy in ('layout', 'editorial', 'confirmed_selection'):
            self.reset_policies()
            save_snapshot(self.job, self.source, self.legacy)
            self.assertEqual(cached_analysis(self.job, self.source), self.legacy)
            if policy == 'layout':
                atomic_json(self.job/'render-settings.json', {'layout': 'cinema', 'caption_style': 'classic'})
            elif policy == 'editorial':
                atomic_json(self.job/'editorial-settings.json', DRAMATIC_PROFILE)
            else:
                atomic_json(self.job/'selection-policy.json', {'version': 1, 'mode': 'confirmed_only'})
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'подходящего сохранённого анализа'):
                cached_analysis(self.job, self.source)
        self.analyzer.assert_not_called()
        self.model.assert_not_called()

    def test_source_only_snapshot_still_rejects_source_and_transcript_mutations(self):
        from app.processing import save_snapshot, cached_analysis
        for changed in ('source_bytes', 'transcript_checkpoint', 'snapshot_transcript'):
            self.source.write_bytes(self.source_bytes)
            atomic_json(self.job/'transcript.json', self.analysis['transcript'])
            save_snapshot(self.job, self.source, self.analysis)
            if changed == 'source_bytes':
                self.source.write_bytes(self.source_bytes + b' changed')
            else:
                transcript = copy.deepcopy(self.analysis['transcript'])
                transcript['words'][0]['text'] = 'An altered original utterance.'
                if changed == 'transcript_checkpoint':
                    atomic_json(self.job/'transcript.json', transcript)
                else:
                    atomic_json(self.job/'analysis-final.json', {**self.analysis, 'transcript': transcript})
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'подходящего сохранённого анализа'):
                cached_analysis(self.job, self.source)
        self.analyzer.assert_not_called()
        self.model.assert_not_called()

