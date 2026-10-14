import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.part_context import evidence, fallback, generate, sample_times, validate, with_context
from tests.test_media import workspace_directory
from pathlib import Path


class PartContextTests(unittest.TestCase):
    def setUp(self):
        policy = patch('app.analysis_checks.economy_mode', return_value=False)
        policy.start()
        self.addCleanup(policy.stop)
        self.part = {'index': 1, 'cuts': [{'start': 10, 'end': 18}, {'start': 22, 'end': 30}],
                     'subtitles': [{'text': 'Герой приходит в магазин.'}, {'text': 'Кассир его приветствует.'}]}
        self.events = [
            {'id': 'before', 'start': 0, 'end': 12, 'kind': 'story', 'summary': 'Предыдущий разговор.'},
            {'id': 'inside', 'start': 12, 'end': 28, 'kind': 'story', 'summary': 'Герой заходит в магазин после работы.'},
            {'id': 'after', 'start': 28, 'end': 40, 'kind': 'story', 'summary': 'Секрет следующей части.'},
            {'id': 'removed', 'start': 19, 'end': 21, 'kind': 'story', 'summary': 'Удалённая сцена.'},
            {'id': 'credit', 'start': 14, 'end': 15, 'kind': 'opening', 'summary': 'Титры.'}]
        self.brief = {'title': 'Отдушина после работы', 'synopsis': 'Герой ищет спокойствия в знакомом магазине.',
                      'prompt': 'Аниме, вертикальная композиция 9:16: герой у кассы, тёплый свет. Без текста.'}

    def test_evidence_excludes_boundary_crossing_and_removed_scenes(self):
        facts = evidence(self.part, self.events)
        self.assertEqual(facts['scenes'], ['Герой заходит в магазин после работы.'])
        self.assertEqual(facts['dialogue'], 'Герой приходит в магазин. Кассир его приветствует.')
        self.assertNotIn('Секрет', json.dumps(facts, ensure_ascii=False))

    def test_visual_samples_belong_to_retained_footage_in_source_order(self):
        times = sample_times(self.part['cuts'])
        self.assertEqual(len(times), 6)
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(any(cut['start'] <= time < cut['end'] for cut in self.part['cuts']) for time in times))

    def test_bounded_fallback_and_empty_historical_plan_do_not_invent_story(self):
        context = fallback(self.part, self.events)
        self.assertEqual(context['method'], 'extractive')
        self.assertNotIn('Секрет', context['prompt'])
        self.assertIn('9:16', context['prompt'])
        self.assertLessEqual(len(context['synopsis']), 400)
        self.assertIn('нет достаточного', with_context({'parts': [{'number': 1}]})['parts'][0]['cover_context']['synopsis'])

    def test_bad_model_fields_are_rejected_and_portrait_ratio_is_added(self):
        for value in (None, {}, {**self.brief, 'extra': 'wrong'}, {**self.brief, 'synopsis': ''},
                      {**self.brief, 'title': 3}, {**self.brief, 'synopsis': 'а' * 401}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)
        self.assertIn('9:16', validate({**self.brief, 'prompt': 'Аниме у кассы.'})['prompt'])

    def test_legacy_compatibility_is_read_only_and_preserves_generated_context(self):
        plan = {'parts': [copy.deepcopy(self.part)], 'events': self.events}
        before = copy.deepcopy(plan)
        self.assertEqual(with_context(plan)['parts'][0]['cover_context']['method'], 'extractive')
        self.assertEqual(plan, before)
        plan['parts'][0]['cover_context'] = {**self.brief, 'method': 'model'}
        self.assertEqual(with_context(plan)['parts'][0]['cover_context'], plan['parts'][0]['cover_context'])

    def test_generation_uses_selected_provider_and_reuses_only_matching_evidence(self):
        with workspace_directory('part_context_') as directory:
            base = Path(directory)
            (base / 'analysis-settings.json').write_text('{"provider":"deepseek_plan"}', 'utf-8')
            plan = {'parts': [copy.deepcopy(self.part)], 'events': self.events}
            vision = Mock()
            vision.query.return_value = self.brief
            session = Mock()
            session.__enter__ = Mock(return_value=vision)
            session.__exit__ = Mock(return_value=False)
            with patch('app.vision.vision_session', return_value=session) as factory:
                generate(plan, base, lambda *args: None, lambda: False)
                self.assertEqual(plan['parts'][0]['cover_context']['method'], 'model')
                self.assertEqual(factory.call_args.args[2], 'deepseek_plan')
                self.assertNotIn('Секрет', vision.query.call_args.args[0])
                self.assertNotIn('Герой заходит в магазин после работы.', vision.query.call_args.args[0])
                with patch('app.analysis_checks.economy_mode', return_value=True):
                    generate(plan, base, lambda *args: None, lambda: False)
                self.assertEqual(vision.query.call_count, 1)
                self.assertEqual(plan['parts'][0]['cover_context']['method'], 'model')
                plan['parts'][0]['subtitles'][0]['text'] = 'Он ищет другой магазин.'
                generate(plan, base, lambda *args: None, lambda: False)
                self.assertEqual(vision.query.call_count, 2)
                (base / 'analysis-settings.json').write_text('{"provider":"local"}', 'utf-8')
                generate(plan, base, lambda *args: None, lambda: False)
                self.assertEqual(vision.query.call_count, 3)
                self.assertEqual(factory.call_args.args[2], 'local')

    def test_provider_failure_preserves_all_parts_without_more_requests(self):
        with workspace_directory('part_context_') as directory:
            vision = Mock()
            vision.query.side_effect = RuntimeError('offline')
            session = Mock()
            session.__enter__ = Mock(return_value=vision)
            session.__exit__ = Mock(return_value=False)
            parts = [copy.deepcopy(self.part), {**copy.deepcopy(self.part), 'index': 2}]
            before = copy.deepcopy(parts)
            plan = {'parts': parts, 'events': self.events}
            with patch('app.vision.vision_session', return_value=session):
                generate(plan, Path(directory), lambda *args: None, lambda: False)
            self.assertEqual(vision.query.call_count, 1)
            self.assertTrue(all(part['cover_context']['method'] == 'extractive' for part in parts))
            self.assertEqual([{k: v for k, v in part.items() if k != 'cover_context'} for part in parts], before)

    def test_cancellation_is_propagated(self):
        with workspace_directory('part_context_') as directory, patch('app.vision.vision_session') as factory:
            with self.assertRaises(InterruptedError):
                generate({'parts': [self.part]}, Path(directory), lambda *args: None, lambda: True)
            factory.assert_not_called()

    def test_silent_part_uses_current_frames_without_requiring_dialogue(self):
        with workspace_directory('part_context_silent_') as directory:
            base = Path(directory)
            source = base / 'source.mp4'
            source.write_bytes(b'source')
            (base / 'source.json').write_text(json.dumps({'path': str(source)}), 'utf-8')
            part = {'index': 1, 'cuts': [{'start': 0, 'end': 5}], 'subtitles': []}
            vision = Mock()
            vision.query.return_value = self.brief
            session = Mock()
            session.__enter__ = Mock(return_value=vision)
            session.__exit__ = Mock(return_value=False)
            with patch('app.part_context.frames', return_value=base / 'frames.jpg'), \
                    patch('app.vision.vision_session', return_value=session):
                generate({'parts': [part], 'events': []}, base, lambda *args: None, lambda: False)
            self.assertEqual(part['cover_context']['method'], 'model')
            self.assertEqual(vision.query.call_args.args[1], base / 'frames.jpg')

    def test_pipeline_adds_context_automatically_without_rerendering_on_resume(self):
        from app.pipeline import run_job
        with workspace_directory('part_context_pipeline_') as directory:
            base = Path(directory)
            source = base / 'source.mp4'
            source.write_bytes(b'source')
            (base / 'source.json').write_text(json.dumps({'path': str(source)}), 'utf-8')
            analysis = {'probe': {'duration': 5, 'width': 640, 'height': 360, 'has_audio': True},
                        'transcript': {'words': [], 'segments': []}, 'shots': [],
                        'events': [{'id': 'a', 'start': 0, 'end': 5, 'kind': 'story', 'importance': 4,
                                    'summary': 'Герой заходит в магазин.'}]}
            vision = Mock()
            vision.query.return_value = self.brief
            session = Mock()
            session.__enter__ = Mock(return_value=vision)
            session.__exit__ = Mock(return_value=False)
            def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
                path = output / 'part_001.mp4'
                path.write_bytes(b'video unchanged')
                path.with_suffix('.srt').write_text('', 'utf-8')
                return path
            with patch('app.analysis.analyze', return_value=analysis), \
                    patch('app.vision.vision_session', return_value=session), \
                    patch('app.part_context.frames', return_value=None), \
                    patch('app.pipeline.render_part', side_effect=render) as renderer, \
                    patch('app.pipeline.prepare_clean_part', side_effect=lambda s, p, pr, *a: (s, p, pr, False)), \
                    patch('app.pipeline.choose_encoder', return_value='libx264'), \
                    patch('app.pipeline.validate_export'):
                run_job(base, lambda *args: None, lambda: False)
                run_job(base, lambda *args: None, lambda: False)
            saved = json.loads((base / 'output' / 'plan.json').read_text('utf-8'))
            self.assertEqual(saved['parts'][0]['cover_context']['method'], 'model')
            self.assertEqual(vision.query.call_count, 1)
            self.assertEqual(renderer.call_count, 1)
            self.assertEqual((base / 'output' / 'part_001.mp4').read_bytes(), b'video unchanged')
