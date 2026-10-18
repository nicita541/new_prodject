"""Real survey/journal/question orchestration; scripted answers are mechanism proof only."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from PIL import Image

from app.analysis_continuation import StageJournal
from app.analysis_questions import QuestionJournalError
from app.config import TEMP
from app.json_store import atomic_json, read_json
from app.standalone_analysis import analyze_standalone


class StandaloneAnalysisTests(unittest.TestCase):
    def test_standalone_semantic_scope_exists_with_real_code_identity(self):
        from app.semantic_identity import scoped_identity
        identity = scoped_identity('standalone')
        self.assertEqual(len(identity['digest']), 64)

    def setUp(self):
        self.directory = TEMP/('standalone-analysis-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.source = self.directory/'source.mp4'
        self.source.write_bytes(b'authored source placeholder')
        self.source_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.model = self.directory/'authored-model.bin'
        self.model.write_bytes(b'model metadata, no inference')
        self.probe = {'duration': 90, 'width': 320, 'height': 180, 'fps': 24, 'has_audio': True}
        self.transcript = {'segments': [{'start': 1, 'end': 2, 'text': 'Exact source speech.'}], 'words': []}
        self.shots = []
        self.scenes = [{'id': 'speech', 'start': 0, 'end': 30}, {'id': 'quiet', 'start': 30, 'end': 60},
                       {'id': 'quiet_tail', 'start': 60, 'end': 90}]
        self.evidence = {'source_sha256': self.source_sha, 'probe': self.probe,
                         'transcript': self.transcript, 'shots': self.shots}
        self.queries, self.counts, self.extracted = [], [], []
        self.empty, self.fail_map = False, False
        outer = self

        class Vision:
            max_current_frames = 8
            text_budget = 100000
            cache_profile = 'authored-test-provider'
            model = outer.model
            projector = outer.model
            thinking = False

            def token_count(self, wire):
                outer.counts.append(wire)
                return len(wire)//4

            def query(self, prompt, image=None, **kwargs):
                outer.queries.append({'prompt': prompt, 'image': str(image) if image else None,
                                      'schema': kwargs['schema'], 'max_tokens': kwargs['max_tokens']})
                payload = json.loads(prompt.split('\n', 1)[1])
                if image:
                    return {'observations': [{'window_id': row['id'], 'summary': 'Authored sparse observation.',
                        'uncertain': True} for row in payload]}
                if outer.fail_map:
                    raise RuntimeError('transport outcome unknown')
                catalog = payload['catalog']
                return {'hypotheses': [] if outer.empty else [{'id': 'story', 'window_ids': [catalog[0]['id']],
                    'prerequisite_window_ids': [], 'premise': 'Source premise hypothesis',
                    'development': 'Source development hypothesis', 'payoff': 'Source payoff hypothesis',
                    'interesting_why': 'Authored test hypothesis', 'unanswered_questions': ['Verify source.']}],
                    'unanswered_questions': []}

        self.vision_class = Vision
        self.sessions = Mock()

        @contextmanager
        def session(*args, **kwargs):
            vision = Vision()
            vision.thinking = kwargs.get('thinking', False)
            yield vision

        self.sessions.session.side_effect = session

    def tearDown(self):
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def frames(self, source, start, end, directory, cancelled, times):
        self.extracted.append((start, end))
        records, paths = [], []
        for index, time in enumerate(times):
            path = directory/f'authored-{start}-{index}.jpg'
            Image.new('RGB', (24, 16), (int(time)%255, 30, 60)).save(path)
            records.append({'time': time, 'requested_time': time, 'pts': round(time*24),
                            'time_base': '1/24', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            paths.append(path)
        return {'sha256': self.source_sha}, records, paths

    def journal(self, profile=None):
        return StageJournal(self.directory, self.source_sha, self.transcript, self.shots,
                            profile or {}, Mock(), Mock(), lambda: False)

    def run_analysis(self, journal=None):
        return analyze_standalone(self.source, self.probe, self.transcript, self.shots, self.scenes,
            self.evidence, self.directory, self.sessions, 'local', journal or self.journal(),
            Mock(), Mock(), lambda: False)

    def boundaries(self):
        stack = ExitStack()
        stack.enter_context(patch('app.analysis_provider._model_files_for_provider', return_value=(self.model,)))
        stack.enter_context(patch('app.analysis_provider.provider_identity', return_value={'provider': 'authored-local'}))
        stack.enter_context(patch('app.episode_survey.source_frame_files', side_effect=self.frames))
        self.native_qualification = stack.enter_context(patch('app.selective_analysis.qualify_episode_map'))
        return stack

    def test_whole_episode_source_discovery_then_warm_style_reuse(self):
        legacy = {'analysis_contract': 'standalone_selective_v1', 'authored': 'preserve exact snapshot'}
        atomic_json(self.directory/'selective-analysis.json', legacy)
        legacy_bytes = (self.directory/'selective-analysis.json').read_bytes()
        with self.boundaries(), patch('app.analysis.global_story_review') as global_story, \
                patch('app.review_scope.prepare_review_scope') as legacy_scope:
            result = self.run_analysis()
            self.assertEqual(self.extracted, [(0, 30), (30, 60), (60, 90)])
            self.assertEqual(result['analysis_contract'], 'standalone_source_v2')
            self.assertEqual(result['quality_policy'], 'standalone_source_v2')
            self.assertEqual(result['source_sha256'], self.source_sha)
            self.assertEqual(result['scenes'], self.scenes)
            self.assertEqual(result['events'], [])
            self.assertEqual(result['check_policy']['authority'], 'hypothesis_only')
            self.assertFalse(result['check_policy']['publication_eligible'])
            survey_query, map_query = self.queries
            self.assertIsNotNone(survey_query['image'])
            self.assertIsNone(map_query['image'])
            survey_catalog = json.loads(survey_query['prompt'].split('\n', 1)[1])
            self.assertEqual(survey_catalog[-1]['scene_id'], 'quiet_tail')
            self.assertEqual(survey_catalog[-1]['ASR'], [])
            self.assertTrue(survey_catalog[-1]['frames'][0]['pts'] > 0)
            map_payload = json.loads(map_query['prompt'].split('\n', 1)[1])
            self.assertEqual(map_payload['scope'], 'complete_episode')
            self.assertEqual(map_payload['exact_ASR'], self.transcript['segments'])
            self.assertEqual(map_payload['catalog'][-1]['scene_id'], 'quiet_tail')
            reserved = list((self.directory/'continuation'/'questions'/self.source_sha).glob('*.reserved.json'))
            self.assertEqual(len(reserved), 2)
            for path in reserved:
                identity = read_json(path)['identity']
                request = identity['request_identity']
                self.assertIn('schema', request)
                self.assertIn('provider', request)
                self.assertEqual(identity['question'], request['prompt'])
            initial = (len(self.queries), len(self.counts), len(self.extracted))
            atomic_json(self.directory/'planning-preferences.json', {'preferred_part_count': 7})
            atomic_json(self.directory/'render-settings.json', {'layout': 'cinema'})
            atomic_json(self.directory/'story-objective.json', {'version': 1, 'objective': 'standalone_shorts',
                        'settings': {'max_clips': 7}})
            self.assertEqual(self.run_analysis(), result)
            self.assertEqual((len(self.queries), len(self.counts), len(self.extracted)), initial)
            self.assertEqual(self.sessions.session.call_count, 2)
            self.native_qualification.assert_not_called()
            global_story.assert_not_called()
            legacy_scope.assert_not_called()
        self.assertEqual((self.directory/'selective-analysis.json').read_bytes(), legacy_bytes)
        self.assertEqual(read_json(self.directory/'standalone-source.json'), result)
        self.assertEqual(read_json(self.directory/'standalone-source.meta.json')['analysis_contract'],
                         'standalone_source_v2')

    def test_editorial_semantics_reuse_source_record_without_opening_sessions(self):
        with self.boundaries():
            result = self.run_analysis()
            initial = (len(self.queries), len(self.counts), len(self.extracted))
            self.sessions.session.reset_mock(side_effect=False)
            self.assertEqual(self.run_analysis(self.journal({'changed': 'editorial semantic preferences'})), result)
            self.sessions.session.assert_not_called()
        self.assertEqual((len(self.queries), len(self.counts), len(self.extracted)), initial)
        self.native_qualification.assert_not_called()

    def test_source_identity_has_discovery_dependencies_without_candidate_semantics(self):
        from app.content_identity import file_sha256
        with self.boundaries(), patch('app.standalone_analysis.file_sha256', wraps=file_sha256) as hashed:
            journal = self.journal()
            with patch.object(journal, 'run', wraps=journal.run) as stages:
                self.run_analysis(journal)
        inputs = next(call.args[1] for call in stages.call_args_list if call.args[0] == 'standalone_source')
        self.assertIn('episode_survey', inputs['code'])
        self.assertIn('discovery_regions', inputs['code'])
        self.assertIn('bounded_storyboard', inputs['code'])
        self.assertIn('vision', inputs['code'])
        self.assertNotIn('native', inputs)
        self.assertTrue(set(inputs['code']).isdisjoint({'selective_analysis', 'unit_decisions',
            'candidate_analysis', 'story_candidates', 'story', 'standalone_planner', 'candidate_framing'}))
        self.assertEqual({call.args[0].stem for call in hashed.call_args_list}, set(inputs['code']))
        self.assertEqual(inputs['scenes'], self.scenes)
        self.assertEqual(inputs['model_files'][0]['path'], str(self.model))

    def test_source_facts_change_outer_identity_even_when_evidence_argument_is_unchanged(self):
        with self.boundaries():
            self.run_analysis()
            self.probe = {**self.probe, 'fps': 30}
            result = self.run_analysis()
        self.assertEqual(result['probe']['fps'], 30)
        self.assertEqual(len(self.queries), 2)  # The unchanged survey/map are reused.
        self.native_qualification.assert_not_called()

    def test_empty_hypotheses_still_preserve_complete_physical_source(self):
        self.empty = True
        with self.boundaries():
            result = self.run_analysis()
        self.assertEqual(result['events'], [])
        self.assertEqual(result['episode_map']['hypotheses'], [])
        self.assertEqual(result['scenes'], self.scenes)
        self.assertNotIn('selective_scope', result)
        self.native_qualification.assert_not_called()

    def test_empty_hypotheses_real_adapter_never_opens_native_session(self):
        self.empty = True
        with self.boundaries(), \
                patch('app.analysis_result.analysis_result', return_value={'events': []}), \
                patch('app.scene_analysis.analyze_scenes') as native_perception:
            result = self.run_analysis()
        self.assertEqual(result['episode_map']['hypotheses'], [])
        self.assertEqual(result['events'], [])
        self.assertEqual(self.sessions.session.call_count, 2)
        native_perception.assert_not_called()
        self.native_qualification.assert_not_called()

    def test_unknown_map_transport_is_not_resent_on_resume(self):
        self.fail_map = True
        with self.boundaries():
            with self.assertRaisesRegex(RuntimeError, 'unknown'):
                self.run_analysis()
            queries = len(self.queries)
            with self.assertRaisesRegex(QuestionJournalError, 'outcome is unknown'):
                self.run_analysis()
        self.assertEqual(len(self.queries), queries)
        self.native_qualification.assert_not_called()
        self.assertEqual(len(self.extracted), 3)

    def test_analyze_routes_before_legacy_per_scene_or_global_selection(self):
        from app.analysis import _analyze
        from app.inference import REPAIR_VERSION
        self.transcript['repair_version'] = REPAIR_VERSION
        atomic_json(self.directory/'probe.json', self.probe)
        atomic_json(self.directory/'transcript.json', self.transcript)
        atomic_json(self.directory/'story-objective.json', {'version': 1, 'objective': 'standalone_shorts'})
        (self.directory/'audio.wav').write_bytes(b'already prepared audio')
        for scene in self.scenes:
            scene.update(boundary_reason='authored boundary', confidence=1, uncertain=False)
        with self.boundaries(), ExitStack() as stack:
            for target, value in [('app.analysis.shot_checkpoint', []), ('app.media_probe.raw_shot_evidence', []),
                ('app.media_evidence.perception_checkpoint', {}), ('app.episode_profile.build_episode_profile', {}),
                ('app.episode_profile.scene_settings', {}), ('app.scene_detection.scene_checkpoint', self.scenes)]:
                stack.enter_context(patch(target, return_value=value))
            legacy_native = stack.enter_context(patch('app.scene_analysis.analyze_scenes'))
            legacy_global = stack.enter_context(patch('app.analysis.global_story_review'))
            legacy_scope = stack.enter_context(patch('app.review_scope.prepare_review_scope'))
            result = _analyze(self.directory, self.source, Mock(), lambda: False, self.sessions)
        self.assertEqual(result['analysis_contract'], 'standalone_source_v2')
        self.assertEqual(self.extracted[-1], (60, 90))
        legacy_native.assert_not_called()
        legacy_global.assert_not_called()
        legacy_scope.assert_not_called()
