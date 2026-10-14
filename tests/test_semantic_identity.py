"""Real cache reuse/invalidation without model calls or version-only assumptions."""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

from PIL import Image

from app.config import TEMP
from app import deepseek, episode_profile, scene_analysis, scene_detection, story, endings, pacing
from app.json_store import analysis_json as atomic_json, load_json
from app.media_probe import shot_checkpoint
from app.semantic_identity import component_identity, semantic_identity, _static_constants
from app.vision import storyboard_samples


EMPTY = {'words': [], 'segments': []}


@contextmanager
def changed_source(module, before, after):
    """Simulate a deployment changing an embedded literal, leaving versions intact."""
    target = Path(module.__file__).resolve()
    original_read = Path.read_text
    source = original_read(target, encoding='utf-8')
    if before not in source:
        raise AssertionError('The tested prompt literal disappeared')

    def read(path, *args, **kwargs):
        text = original_read(path, *args, **kwargs)
        return text.replace(before, after) if path.resolve() == target else text

    with patch('app.semantic_identity.Path.read_text', new=read):
        yield


class SceneVision:
    supports_image_pages = True
    cache_profile = 'identity-fixture'

    def __init__(self):
        self.requests = []

    def query(self, prompt, image=None, max_tokens=1000, schema=None):
        self.requests.append((prompt, image))
        return {'summary': 'Текущие действия.', 'kind': 'story', 'importance': 4, 'uncertain': False,
                'semantic_confidence': .95, 'visual_confidence': .95, 'context_confidence': .95,
                'uncertainty_reasons': [], 'action_units': [], 'narrative_bridge': False,
                'state_before': {'locations': [], 'character_state': '', 'objects': []},
                'state_after': {'locations': [], 'character_state': '', 'objects': []},
                'keep_units': schema['properties']['keep_units']['items']['enum']}


class SemanticIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP / ('semantic-identity-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)

    def tearDown(self):
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_identity_is_stable_json_and_covers_all_pipeline_components(self):
        first = semantic_identity()
        self.assertEqual(first, semantic_identity())
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        required = {'shot_detector', 'scene_detector', 'scene_grouping', 'visual_features',
                    'storyboard', 'local_prompt', 'recovery', 'global_story', 'episode_profile',
                    'story', 'pacing', 'planner', 'ending','story_structure','continuity','final_quality'}
        self.assertEqual(set(first['components']), required)
        planner = first['components']['planner']
        self.assertIn('app/story_structure.py', planner['sources'])
        self.assertIn('app/planner_audit.py', planner['sources'])
        self.assertTrue(first['components']['local_prompt']['prompt_hashes'])
        self.assertTrue(first['components']['planner']['versions'])
        with self.assertRaises(ValueError):
            component_identity('arbitrary_module')

    def test_shared_helper_changes_invalidate_their_consumers(self):
        from app import source_text, cancellation, content_identity
        cases = (
            (source_text, "replace('ё', 'е')", "replace('ё', 'ё')",
             ('episode_profile', 'story_structure', 'planner', 'final_quality')),
            (cancellation, 'Обработка отменена', 'Обработка отменена по запросу',
             ('storyboard', 'local_prompt', 'story_structure', 'final_quality')),
            (content_identity, "encode('utf-8')", "encode('utf-16')",
             ('scene_detector', 'story_structure', 'continuity', 'final_quality')),
        )
        for module, before, after, consumers in cases:
            original = {name: component_identity(name)['digest'] for name in consumers}
            with changed_source(module, before, after):
                for name in consumers:
                    with self.subTest(helper=module.__name__, component=name):
                        self.assertNotEqual(original[name], component_identity(name)['digest'])

    def test_viewer_interest_policy_invalidates_selection_and_planning_not_raw_media(self):
        from app import viewer_interest
        names = ('story_structure', 'story', 'global_story', 'planner', 'ending')
        original = {name: component_identity(name) for name in (*names, 'shot_detector')}
        with changed_source(viewer_interest, "'reversal': 16", "'reversal': 15"):
            for name in names:
                self.assertNotEqual(original[name]['digest'], component_identity(name)['digest'])
            self.assertEqual(original['shot_detector'], component_identity('shot_detector'))

    def test_literal_fallback_equals_loaded_policy_without_importing_components(self):
        expected = component_identity('episode_profile')
        with patch.dict(sys.modules, {'app.episode_profile': None}):
            self.assertEqual(expected, component_identity('episode_profile'))
            self.assertIsNone(sys.modules['app.episode_profile'])
        expected = component_identity('story')
        with patch.dict(sys.modules, {'app.editorial': None, 'app.story': None, 'app.deepseek': None}):
            self.assertEqual(expected, component_identity('story'))

    def test_literal_policy_spread_is_resolved_without_evaluating_calls(self):
        tree = ast.parse("BASE = {'version': 1, 'nested': [2, 3]}\nPOLICY = {**BASE, 'version': 2}\nUNSAFE = open('private')")
        values = _static_constants(tree)
        self.assertEqual(values['POLICY'], {'version': 2, 'nested': [2, 3]})
        self.assertEqual(values['BASE']['version'], 1)
        self.assertNotIn('UNSAFE', values)

    def test_numeric_literal_policy_does_not_change_identity_after_lazy_import(self):
        from app import selection_adjudication
        tree=ast.parse("POLICY={'max_image_bytes':4*1024**2}\nUNSAFE='private'*1024\nHUGE=2**1000000000")
        values=_static_constants(tree)
        self.assertEqual(values['POLICY'],{'max_image_bytes':4194304})
        self.assertNotIn('UNSAFE',values);self.assertNotIn('HUGE',values)
        for name in ('local_prompt','recovery','global_story','continuity','story','planner'):
            expected=component_identity(name)
            with patch.dict(sys.modules,{'app.selection_adjudication':None}):
                self.assertEqual(expected,component_identity(name),name)

    def test_batch_coordinator_changes_do_not_invalidate_early_vision(self):
        from app import antigravity_batch
        expected = {name: component_identity(name) for name in ('local_prompt', 'recovery', 'storyboard')}
        with changed_source(antigravity_batch, 'max_workers=4', 'max_workers=2'):
            self.assertEqual(expected, {name: component_identity(name) for name in expected})

    def test_runtime_prompt_and_policy_changes_invalidate_without_version_change(self):
        original = component_identity('recovery')
        from app import scene_understanding
        version = scene_understanding.SCENE_UNDERSTANDING_VERSION
        with patch.object(scene_understanding, 'RECOVERY_PROMPT', scene_understanding.RECOVERY_PROMPT + '\nFresh policy.'):
            changed = component_identity('recovery')
        self.assertEqual(version, scene_understanding.SCENE_UNDERSTANDING_VERSION)
        self.assertEqual(original['versions'], changed['versions'])
        self.assertNotEqual(original['digest'], changed['digest'])
        self.assertNotEqual(original['prompt_hashes'], changed['prompt_hashes'])
        original = component_identity('episode_profile')
        with patch.object(episode_profile, 'EPISODE_PROFILE_POLICY', {**episode_profile.EPISODE_PROFILE_POLICY, 'new_threshold': .7}):
            self.assertNotEqual(original['digest'], component_identity('episode_profile')['digest'])

    def test_identity_does_not_read_runtime_credentials_or_configuration(self):
        expected = component_identity('global_story')
        with patch.object(deepseek, 'PRIVATE', self.directory / 'private-value-never-read.json'), \
             patch.object(deepseek, 'ENDPOINT', 'https://configuration.example.invalid'), \
             patch.object(deepseek, 'api_key', 'credential-value-never-serialize', create=True):
            actual = component_identity('global_story')
        self.assertEqual(expected, actual)
        self.assertNotIn('credential-value', json.dumps(actual))
        self.assertNotIn('configuration.example', json.dumps(actual))

    def test_missing_required_module_is_not_treated_as_a_valid_identity(self):
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            if path.name == 'media_probe.py':
                raise FileNotFoundError('missing required component')
            return original_read(path, *args, **kwargs)

        with patch('app.semantic_identity.Path.read_text', new=read), self.assertRaises(FileNotFoundError):
            component_identity('shot_detector')

    @staticmethod
    def fake_board(source, start, end, shots, transcript, destination, cancelled, **settings):
        destination.write_bytes(b'collage-fixture')
        frames = storyboard_samples(start, end, shots, transcript)
        atomic_json(destination.with_suffix('.storyboard.json'), {'start': start, 'end': end, 'frames': frames})
        return [f['time'] for f in frames]

    def analyze(self, vision, transcript=EMPTY, signature='unchanged-parent-signature'):
        shots = [{'id': 'shot_0', 'start': 0, 'end': 10, 'location': 'room'}]
        scenes = scene_detection.detect_semantic_scenes(shots, transcript, 10)
        from tests.test_semantic_pipeline import SemanticPipelineTests
        with patch('app.vision.storyboard', side_effect=self.fake_board), \
             patch('app.vision.inference_storyboard',side_effect=SemanticPipelineTests.fake_inference_board):
            return scene_analysis.analyze_scenes(self.directory/'source.mp4', scenes, transcript, shots,
                self.directory, vision, signature, lambda *a: None, lambda: False)

    def test_story_only_changes_reuse_prior_fully_validated_visual_results(self):
        from app.analysis import _visual_checkpoint_signature
        vision = SceneVision()
        first_signature = 'a' * 64
        fresh_story_signature = 'b' * 64
        first = self.analyze(vision, signature=first_signature)
        sent = len(vision.requests)
        self.assertGreater(sent, 0)
        recovered = _visual_checkpoint_signature(self.directory, fresh_story_signature)
        self.assertEqual(recovered, first_signature)
        second = self.analyze(vision, signature=recovered)
        self.assertEqual(first, second)
        self.assertEqual(len(vision.requests), sent)
        # The intrinsic per-scene semantic identity still rejects changed
        # transcripts, providers, or source images (other tests below).
        self.analyze(vision, signature=fresh_story_signature)
        self.assertGreater(len(vision.requests), sent)

    def test_scene_cache_reuses_then_invalidates_runtime_prompt_without_version_bump(self):
        vision = SceneVision()
        first = self.analyze(vision)
        requests = len(vision.requests)
        self.assertEqual(first, self.analyze(vision))
        self.assertEqual(len(vision.requests), requests)
        with patch.object(scene_analysis, 'SCENE_PROMPT', scene_analysis.SCENE_PROMPT + '\nRevised current evidence policy.'):
            self.analyze(vision)
        self.assertEqual(len(vision.requests), 2*requests)
        self.assertIn('Revised current evidence policy.', vision.requests[-1][0])

    def test_scene_cache_validates_actual_images_transcript_and_provider(self):
        vision = SceneVision()
        self.analyze(vision)
        requests = len(vision.requests)
        self.analyze(vision)
        self.assertEqual(len(vision.requests), requests)
        canonical = self.directory/'visual/event_0000.jpg'
        canonical.write_bytes(b'changed-submitted-image')
        self.analyze(vision)
        # The canonical collage is generated locally; re-extract it from
        # valid chunk evidence without paying for an unnecessary model call.
        self.assertEqual(canonical.read_bytes(), b'collage-fixture')
        self.assertEqual(len(vision.requests), requests)
        self.assertTrue(load_json(self.directory/'visual/event_0000.json')['image_hashes'])
        transcript = {'words': [{'start': 1, 'end': 2, 'text': 'New word.'}],
                      'segments': [{'start': 1, 'end': 2, 'text': 'New word.'}]}
        self.analyze(vision, transcript)
        after_transcript = len(vision.requests)
        self.assertGreater(after_transcript, requests)
        vision.cache_profile = 'different-provider-policy'
        self.analyze(vision, transcript)
        after_provider = len(vision.requests)
        self.assertGreater(after_provider, after_transcript)
        self.analyze(vision, transcript)
        self.assertEqual(len(vision.requests), after_provider)

    def test_legacy_scene_cache_without_component_identity_is_rebuilt(self):
        vision = SceneVision()
        self.analyze(vision)
        requests = len(vision.requests)
        checkpoint = self.directory/'visual/event_0000.json'
        saved = load_json(checkpoint)
        saved.pop('semantic_identity')
        atomic_json(checkpoint, saved)
        self.analyze(vision)
        # Legacy parent metadata is rejected and regenerated. Its individually
        # verified, current-identity chunk checkpoints remain reusable.
        repaired = load_json(checkpoint)
        self.assertTrue(repaired.get('semantic_identity'))
        self.assertTrue(repaired['storyboards'])
        self.assertEqual(len(vision.requests), requests)
        # A legacy *chunk* without identity must trigger model re-analysis.
        chunk = self.directory/'visual/event_0000_chunk_000.checkpoint.json'
        stale_chunk = load_json(chunk)
        stale_chunk.pop('identity')
        atomic_json(chunk, stale_chunk)
        repaired.pop('semantic_identity')
        atomic_json(checkpoint, repaired)
        self.analyze(vision)
        self.assertGreater(len(vision.requests), requests)
        self.assertTrue(load_json(chunk).get('identity'))
        self.assertTrue(load_json(checkpoint).get('semantic_identity'))

    def test_incomplete_scene_image_cache_is_rebuilt(self):
        vision = SceneVision()
        self.analyze(vision)
        requests = len(vision.requests)
        checkpoint = self.directory/'visual/event_0000.json'
        saved = load_json(checkpoint)
        saved['storyboards'] = []
        saved['image_hashes'] = {}
        atomic_json(checkpoint, saved)
        self.analyze(vision)
        # The scene manifest must be rebuilt, but valid, fully validated
        # *chunk* checkpoints should prevent redundant model requests.
        self.assertEqual(len(vision.requests), requests)
        repaired = load_json(checkpoint)
        self.assertTrue(repaired['storyboards'])
        self.assertTrue(repaired['image_hashes'])
        # Corrupt both the parent and a chunk checkpoint: only now must the
        # model reprocess missing visual evidence instead of accepting it.
        chunk = self.directory/'visual/event_0000_chunk_000.checkpoint.json'
        piece = load_json(chunk)
        piece['boards'] = []
        piece['image_hashes'] = {}
        atomic_json(chunk, piece)
        repaired['storyboards'] = []
        repaired['image_hashes'] = {}
        atomic_json(checkpoint, repaired)
        self.analyze(vision)
        self.assertGreater(len(vision.requests), requests)
        self.assertTrue(load_json(chunk)['image_hashes'])
        self.assertTrue(load_json(checkpoint)['image_hashes'])

    def test_story_cache_invalidates_changed_embedded_prompt_with_same_version(self):
        (self.directory/'visual').mkdir()
        Image.new('RGB', (48, 27), 'white').save(self.directory/'visual/event_0000.jpg')
        atomic_json(self.directory/'analysis.meta.json', {'source': 'fixture', 'version': 3})
        events = [{'id': 'event_0000', 'start': 0, 'end': 20, 'kind': 'story', 'importance': 4,
                   'summary': 'Персонажи разговаривают.', 'requires': [], 'focus': []}]
        transcript = {'words': [{'start': 1, 'end': 19, 'text': 'Разговор.'}],
                      'segments': [{'start': 1, 'end': 19, 'text': 'Разговор.'}]}
        vision = Mock(model=self.directory/'model', projector=self.directory/'projector', cache_profile='fixture', thinking=False)
        vision.query.side_effect = lambda prompt, **kw: {'summary': 'Разговор.', 'uncertain': False,
            'keep_units': kw['schema']['properties']['keep_units']['items']['enum'],
            'preserve_silent_units': [], 'atmosphere_units': [], 'omit_units': []}
        def refine():
            return story.refine_story(events, transcript, [], self.directory, vision, lambda *a: None, lambda: False)
        first = refine()
        self.assertEqual(first, refine())
        vision.query.assert_called_once()
        version = story.STORY_VERSION
        with changed_source(story, 'Condense the central story', 'Condense the current story'):
            refine()
            self.assertEqual(story.STORY_VERSION, version)
        self.assertEqual(vision.query.call_count, 2)

    def test_ending_cache_invalidates_changed_embedded_prompt_with_same_version(self):
        events = [{'id': 'scene', 'start': 0, 'end': 200, 'kind': 'story', 'importance': 4,
                   'requires': [], 'focus': [], 'summary': 'Question and answer.',
                   'selected_ranges': [{'start': 0, 'end': 200}], 'unit_selection_version': 1}]
        transcript = {'words': [{'start': 80, 'end': 86.45, 'text': 'Вопрос?'},
                                {'start': 100, 'end': 109.45, 'text': 'Ответ.'}],
                      'segments': [{'start': 80, 'end': 86.45, 'text': 'Вопрос?'},
                                   {'start': 100, 'end': 109.45, 'text': 'Ответ.'}]}
        probe = {'duration': 200, 'width': 1920, 'height': 1080, 'has_audio': True}
        vision = Mock(model=self.directory/'model', projector=self.directory/'projector', cache_profile='fixture')
        vision.query.return_value = {'uncertain': False, 'endings': []}
        vision.token_count.return_value = 100
        def refine():
            return endings.refine_endings(events, transcript, [{'start': 90}, {'start': 110}], probe,
                self.directory, vision, lambda *a: None, lambda: False)
        with patch('app.endings.recover_fallback_endings', side_effect=lambda result, *a: result):
            first = refine()
            self.assertEqual(first, refine())
            calls = vision.query.call_count
            self.assertGreater(calls, 0)
            version = endings.VERSION
            with changed_source(endings, 'Choose natural episode-clip ENDINGS', 'Choose complete episode-clip ENDINGS'):
                refine()
                self.assertEqual(endings.VERSION, version)
        self.assertEqual(vision.query.call_count, calls*2)

    def test_shot_and_visual_feature_caches_invalidate_source_policy_change(self):
        source = self.directory/'source.mp4'
        source.write_bytes(b'fixture')
        shots = [{'id': 'shot_0', 'start': 0, 'end': 10}]
        from app import media_probe
        with patch('app.media_probe.detect_shots', return_value=shots) as detector:
            shot_checkpoint(source, 'same-source', 10, self.directory, lambda: False)
            shot_checkpoint(source, 'same-source', 10, self.directory, lambda: False)
            detector.assert_called_once()
            with changed_source(media_probe, 'below_adaptive_threshold', 'below_revised_threshold'):
                shot_checkpoint(source, 'same-source', 10, self.directory, lambda: False)
            self.assertEqual(detector.call_count, 2)
        features = {'shot_0': {'reliability': 0, 'samples': [], 'origin': 'source_frames'}}
        with patch('app.scene_detection.extract_visual_features', return_value=features) as extract:
            status = {}
            def checkpoint():
                return scene_detection.scene_checkpoint(source, 'same-source', 10, shots, EMPTY,
                    self.directory, lambda: False, cache_status=status)
            checkpoint()
            checkpoint()
            extract.assert_called_once()
            self.assertTrue(status['cache_hit'])
            with patch.object(scene_detection, 'DEFAULT_SETTINGS', {**scene_detection.DEFAULT_SETTINGS,
                   'feature_sample_interval': scene_detection.DEFAULT_SETTINGS['feature_sample_interval'] + .1}):
                checkpoint()
            self.assertEqual(extract.call_count, 2)
            self.assertFalse(status['cache_hit'])

    def test_silent_sequence_cache_invalidates_embedded_prompt_policy(self):
        source = self.directory/'source.mp4'
        source.write_bytes(b'fixture')
        events = [{'id': 'travel', 'start': 0, 'end': 20, 'kind': 'story', 'importance': 4,
                   'requires': [], 'selected_ranges': [{'start': 0, 'end': 20}]},
                  {'id': 'arrival', 'start': 20, 'end': 40, 'kind': 'story', 'importance': 4,
                   'requires': ['travel'], 'selected_ranges': [{'start': 20, 'end': 40}]}]
        vision = Mock(model=self.directory/'model', projector=self.directory/'projector',
                      cache_profile='fixture', supports_image_pages=True)
        vision.query.return_value = {'uncertain': False, 'decisions': [
            {'unit': 'q00', 'keep': True, 'reason': 'setup', 'story_change': True,
             'reaction_or_humor': False, 'retained_witness': 'none', 'evidence': 'Travel has a current action.'},
            {'unit': 'q01', 'keep': True, 'reason': 'setup', 'story_change': True,
             'reaction_or_humor': False, 'retained_witness': 'none', 'evidence': 'Arrival is an essential transition.'}]}
        def refine():
            return pacing.refine_silent_sequences(source, events, EMPTY, [], self.directory,
                                                  vision, lambda *a: None, lambda: False)
        with patch('app.pacing.make_sheet'):
            first = refine()
            self.assertEqual(first, refine())
            vision.query.assert_called_once()
            version = pacing.PACING_VERSION
            with changed_source(pacing, 'Review this WHOLE silent sequence', 'Review this CURRENT silent sequence'):
                refine()
                self.assertEqual(version, pacing.PACING_VERSION)
        self.assertEqual(vision.query.call_count, 2)

    def test_pacing_batch_cache_invalidates_embedded_prompt_policy(self):
        source = self.directory/'source.mp4'
        source.write_bytes(b'fixture')
        events = [{'id': 'one', 'start': 0, 'end': 10, 'summary': 'Silent current action.',
                   'kind': 'story', 'importance': 4, 'requires': [],
                   'selected_ranges': [{'start': 0, 'end': 10}]}]
        vision = Mock(model=self.directory/'model', projector=self.directory/'projector', cache_profile='fixture')
        vision.query.side_effect = lambda prompt, image, **kw: {'uncertain': False, 'decisions': [
            {'unit': unit, 'keep': True, 'reason': 'action', 'story_change': True,
             'reaction_or_humor': False, 'evidence': 'A current consequential action.'}
            for unit in kw['schema']['properties']['decisions']['items']['properties']['unit']['enum']]}
        def refine():
            return pacing.refine_pacing(source, events, EMPTY, [], self.directory,
                                       vision, lambda *a: None, lambda: False)
        with patch('app.pacing.make_sheet'):
            first = refine()
            self.assertEqual(first, refine())
            vision.query.assert_called_once()
            with changed_source(pacing, 'Condense this episode using ONLY', 'Condense the current episode using ONLY'):
                refine()
        self.assertEqual(vision.query.call_count, 2)


if __name__ == '__main__':
    unittest.main()
