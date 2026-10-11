import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.analysis import (analysis_context_limit, framing_provider, global_story_review, vision_session,
                          _model_files_for_provider, _visual_checkpoint_signature,
                          _recoverable_checkpoint)
from app.config import TEMP
from app.deepseek import DeepSeekVision, RemoteError, provider_identity


class AnalysisProviderTests(unittest.TestCase):
    def test_deepseek_story_needs_local_visual_4b_but_not_story_9b(self):
        from app.config import VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
        for provider in ('local_flash_story', 'local_flash_story_budgeted', 'deepseek'):
            self.assertEqual(_model_files_for_provider(provider), (VLM_MODEL, VLM_PROJECTOR))
        for provider in ('local', 'local_fast_story', 'deepseek_plan'):
            self.assertEqual(_model_files_for_provider(provider),
                             (VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR))

    def test_existing_visual_cache_keeps_legacy_signature_only_when_well_formed(self):
        with tempfile.TemporaryDirectory() as root:
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
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root) / 'story-events.json'
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            checkpoint.write_text('{"signature":', encoding='utf-8')
            self.assertIsNone(_recoverable_checkpoint(checkpoint))
            checkpoint.write_bytes(b'\\xff\\xfe invalid utf-8')
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
        with patch('app.deepseek.DeepSeekVision') as cloud, patch('app.analysis.LocalVision') as local:
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
        vision.query = Mock(return_value={'keep':[e['id'] for e in events], 'dependencies':[], 'summary':'История'})
        result = global_story_review(vision, events)
        self.assertEqual(result['keep'], [e['id'] for e in events])
        arguments = vision.query.call_args
        self.assertEqual(arguments.kwargs['max_tokens'], 1800)
        for event in events:
            self.assertIn(event['id'], arguments.args[0])
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
