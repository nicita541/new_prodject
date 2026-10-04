import json
import unittest
from unittest.mock import Mock, patch

from app.analysis import analysis_context_limit, framing_provider, global_story_review, vision_session
from app.config import TEMP
from app.deepseek import DeepSeekVision, RemoteError, provider_identity


class AnalysisProviderTests(unittest.TestCase):
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
        self.assertEqual(analysis_context_limit(vision), 16000)

    def test_invalid_global_cloud_domain_does_not_automatically_pay_again(self):
        vision = DeepSeekVision(TEMP, lambda:False)
        vision.query = Mock(return_value={'keep':[], 'dependencies':[], 'summary':'История'})
        with self.assertRaises(RemoteError):
            global_story_review(vision, [{'id':'event_0000', 'summary':'Событие', 'kind':'story', 'importance':4}])
        self.assertEqual(vision.query.call_count, 1)
