import json
from pathlib import Path
import shutil
import uuid
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from app.story_review import analysis_context_limit, global_story_review
from app.analysis_provider import framing_provider, _model_files_for_provider
from app.vision import vision_session
from app.analysis import _visual_checkpoint_signature, _recoverable_checkpoint
from app.config import TEMP
from app.deepseek import DeepSeekVision, RemoteError, provider_identity


@contextmanager
def checkpoint_directory():
    # Ordinary inherited ACLs match the repository's Windows test fixtures.
    directory = TEMP / ('analysis-provider-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(directory)


class AnalysisProviderTests(unittest.TestCase):
    def test_deepseek_story_needs_local_visual_4b_but_not_story_9b(self):
        from app.config import VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
        for provider in ('local_flash_story', 'local_flash_story_budgeted', 'deepseek'):
            self.assertEqual(_model_files_for_provider(provider), (VLM_MODEL, VLM_PROJECTOR))
        for provider in ('local', 'local_fast_story', 'deepseek_plan'):
            self.assertEqual(_model_files_for_provider(provider),
                             (VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR))

    def test_layout_only_removes_unused_plan_framing_model(self):
        from app.config import VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
        small = (VLM_MODEL, VLM_PROJECTOR)
        large = small + (STORY_MODEL, STORY_PROJECTOR)
        self.assertEqual(_model_files_for_provider('deepseek_plan', 'cinema'), small)
        self.assertEqual(_model_files_for_provider('deepseek_plan', 'portrait'), large)
        for provider in ('local', 'hybrid', 'local_fast_story'):
            for layout in ('portrait', 'cinema'):
                self.assertEqual(_model_files_for_provider(provider, layout), large)
        for provider in ('deepseek', 'antigravity_manual', 'local_flash_story', 'local_flash_story_budgeted'):
            for layout in ('portrait', 'cinema'):
                self.assertEqual(_model_files_for_provider(provider, layout), small)

    def test_existing_visual_cache_keeps_legacy_signature_only_when_well_formed(self):
        with checkpoint_directory() as root:
            directory = Path(root)
            original = 'a' * 64
            changed_story = 'b' * 64
            self.assertEqual(_visual_checkpoint_signature(directory, changed_story), changed_story)
            cache = directory / 'visual' / 'event_0000.json'
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({'signature': original}), encoding='utf-8')
            self.assertEqual(_visual_checkpoint_signature(directory, changed_story), original)
            for value in ('a' * 63, '../../wrong-cache', 'a' * 63 + 'g', 123, None):
                cache.write_text(json.dumps({'signature': value}), encoding='utf-8')
                self.assertEqual(_visual_checkpoint_signature(directory, changed_story), changed_story)
            cache.write_text('not json', encoding='utf-8')
            self.assertEqual(_visual_checkpoint_signature(directory, changed_story), changed_story)

    def test_recoverable_stage_metadata_ignores_torn_and_wrong_type_json(self):
        with checkpoint_directory() as root:
            checkpoint = Path(root) / 'story-events.json'
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            checkpoint.write_text('{"signature":', encoding='utf-8')
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            checkpoint.write_bytes(bytes((255, 254)))
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            checkpoint.write_text('[]', encoding='utf-8')
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            self.assertEqual(_recoverable_checkpoint(checkpoint, list), [])
            checkpoint.write_text('{"signature":"good"}', encoding='utf-8')
            self.assertEqual(_recoverable_checkpoint(checkpoint), {'signature': 'good'})

    def test_torn_story_or_final_event_cache_cannot_pass_analysis_resume(self):
        from pathlib import Path
        code = (Path(__file__).resolve().parents[1] / 'app' / 'analysis.py').read_text('utf-8')
        self.assertIn('_recoverable_checkpoint(story_checkpoint)', code)
        self.assertIn('_recoverable_checkpoint(derived_meta)', code)
        self.assertIn('_recoverable_checkpoint(events_path, list)', code)
        self.assertIn('isinstance(saved_story.get(\'events\'), list)', code)

    def test_cloud_plan_sessions_use_cloud_and_focus_uses_local(self):
        cancelled = lambda: False
        with patch('app.deepseek.DeepSeekVision') as cloud, patch('app.vision.LocalVision') as local:
            vision_session(TEMP, cancelled, 'deepseek_plan', thinking=True)
            cloud.assert_called_once_with(TEMP, cancelled)
            local.assert_not_called()
            vision_session(TEMP, cancelled, framing_provider('deepseek_plan'), thinking=False)
            local.assert_called_once_with(TEMP, cancelled, thinking=False)
        self.assertEqual(framing_provider('hybrid'), 'hybrid')
        self.assertEqual(framing_provider('deepseek'), 'deepseek')
        self.assertEqual(provider_identity('deepseek_plan')['focus'], 'local-qwen9-nonthinking')

    def test_global_cloud_preserves_all_event_ids_with_byte_counter_and_bounded_output(self):
        events = [{'id':f'event_{i:04}', 'summary':'Причина поступка и последующее событие. '*10,
                   'kind':'story', 'importance':4} for i in range(36)]
        vision = DeepSeekVision(TEMP, lambda:False)
        vision.query = Mock(side_effect=lambda *args, **kwargs: {
            'keep': kwargs['schema']['properties']['keep']['items']['enum'],
            'dependencies': [], 'omit': [], 'summary': 'История'})
        result = global_story_review(vision, events)
        self.assertEqual(set(result['keep']), {e['id'] for e in events})
        arguments = vision.query.call_args
        self.assertEqual(arguments.kwargs['max_tokens'], 1800)
        for identifier in arguments.kwargs['schema']['properties']['keep']['items']['enum']:
            self.assertIn(identifier, arguments.args[0])
        schema_bytes = len(json.dumps(arguments.kwargs['schema'], ensure_ascii=False).encode('utf-8'))
        self.assertLess(len(arguments.args[0].encode('utf-8')) + schema_bytes + 512, 64000)
        self.assertEqual(result['incomplete_event_ids'], [])
        self.assertEqual(analysis_context_limit(vision), 60000)

    def test_invalid_global_cloud_domain_does_not_automatically_pay_again(self):
        vision = DeepSeekVision(TEMP, lambda:False)
        vision.query = Mock(return_value={'keep':[], 'dependencies':[], 'summary':'История'})
        with self.assertRaises(RemoteError):
            global_story_review(vision, [{'id':'event_0000', 'summary':'Событие', 'kind':'story', 'importance':4}])
        self.assertEqual(vision.query.call_count, 1)
