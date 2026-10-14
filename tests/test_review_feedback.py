"""Authored review mechanisms: fake workers/providers/media, no real inference."""
import copy
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager, ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, pipeline, processing, review_feedback, speech_handles
from app.jobs import JobManager
from app.json_store import atomic_json, read_json
from app.planner import build_plan
from app.server import create_app
from app.music import DEFAULT_CONFIG
from tests.test_jobs import FakeWorker


class FeedbackVision:
    model = 'authored-provider'
    projector = 'authored-projector'
    thinking = True
    supports_image_pages = True

    def __init__(self, intent):
        self.intent, self.calls = intent, []

    def query(self, prompt, *args, **kwargs):
        self.calls.append(prompt)
        return copy.deepcopy(self.intent)


class ReviewFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP/('review-feedback-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.source = self.root/'episode.mp4'
        self.source.write_bytes(b'authored source placeholder, not encoded video')
        self.manager = JobManager(self.root, FakeWorker)
        source_id = self.manager.list_sources()[0]['id']
        self.parent = self.manager.create(source_id)
        self.manager.cancel(self.parent['id'])
        self.directory = self.manager.job_dir(self.parent['id'])
        self.analysis = {'provider': 'local',
            'probe': {'duration': 10, 'width': 640, 'height': 360, 'fps': 30, 'has_audio': True},
            'transcript': {'words': [{'start': 2, 'end': 3, 'text': 'Ответ.'}],
                           'segments': [{'start': 2, 'end': 3, 'text': 'Ответ.'}]},
            'shots': [], 'events': [{'id': 'e', 'start': 0, 'end': 10, 'kind': 'story',
                'importance': 4, 'summary': 'Подтверждённый ответ.', 'requires': [], 'focus': [],
                'selected_ranges': [{'start': 2, 'end': 3}], 'unit_selection_version': 1}]}
        atomic_json(self.directory/'transcript.json', self.analysis['transcript'])
        atomic_json(self.directory/'analysis.meta.json', {'source': processing.source_digest(self.source), 'version': 16})
        processing.save_snapshot(self.directory, self.source, self.analysis)
        self.plan = build_plan(self.analysis)
        atomic_json(self.directory/'plan.json', self.plan)
        state = self.manager.get(self.parent['id'])
        state.update(status='completed', stage='completed', outputs=[])
        atomic_json(self.directory/'job.json', state)
        self.intent = {'actions': [{'kind': 'speech', 'parts': [1]}], 'confidence': .99, 'reply': 'Проверю обрыв речи.'}
        self.vision = FeedbackVision(self.intent)

    def tearDown(self):
        self.manager.close()
        self.root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(self.root)

    def submit(self, operation_id=None, text='В первой части оборвана фраза'):
        return self.manager.create_feedback(self.parent['id'], operation_id or str(uuid.uuid4()), text, 1, 2.5)

    @contextmanager
    def provider(self):
        @contextmanager
        def session(*args, **kwargs):
            yield self.vision
        with patch('app.vision.vision_session', side_effect=session):
            yield

    def run_correction(self, directory):
        rendered = []
        def render(source, part, probe, output, workdir, *args, **kwargs):
            rendered.append(part['index'])
            path = output/f"part_{part['index']:03}.mp4"
            path.write_bytes(b'authored export stub, not encoded media')
            path.with_suffix('.srt').write_text('authored subtitle stub', 'utf-8')
            return path
        with ExitStack() as stack:
            stack.enter_context(self.provider())
            stack.enter_context(patch.object(pipeline, '_run_identity', return_value={}))
            stack.enter_context(patch.object(pipeline, 'setup_environment'))
            stack.enter_context(patch.object(pipeline, 'load_settings', return_value={**DEFAULT_CONFIG, 'enabled': False}))
            stack.enter_context(patch.object(pipeline, 'choose_encoder', return_value='authored-encoder'))
            stack.enter_context(patch.object(pipeline, 'validate_export'))
            stack.enter_context(patch.object(pipeline, 'prepare_clean_part', side_effect=lambda s,p,pr,*a: (s,p,pr,False)))
            stack.enter_context(patch.object(pipeline, 'render_part', side_effect=render))
            stack.enter_context(patch('app.part_context.generate'))
            analyzer = stack.enter_context(patch('app.analysis.analyze', side_effect=AssertionError('whole analysis forbidden')))
            outputs = pipeline.run_job(directory, lambda *args: None, lambda: False)
            analyzer.assert_not_called()
        return outputs, rendered

    def test_submission_is_idempotent_and_original_plan_is_immutable(self):
        operation_id = str(uuid.uuid4())
        before = (self.directory/'plan.json').read_bytes()
        result = self.submit(operation_id)
        replay = self.submit(operation_id)
        self.assertEqual(result['id'], replay['id'])
        self.assertEqual(len(self.manager.list_jobs()), 2)
        with self.assertRaisesRegex(ValueError, 'другого запроса'):
            self.submit(operation_id, 'Здесь заставка')
        self.assertEqual((self.directory/'plan.json').read_bytes(), before)
        dest = self.manager.job_dir(result['id'])
        request = read_json(dest/'correction-request.json')
        base, plan = review_feedback.load_base(dest, self.source, request)
        self.assertEqual(base, self.analysis)
        self.assertEqual(plan, self.plan)

    def test_api_reads_never_infer_and_validates_context_and_origin(self):
        with patch('app.vision.vision_session', side_effect=AssertionError('GET must not infer')), \
                TestClient(create_app(self.manager), base_url='http://127.0.0.1:8765') as client:
            route = f"/api/jobs/{self.parent['id']}/feedback"
            self.assertEqual(client.get(route).json()['messages'], [])
            body = {'operation_id': str(uuid.uuid4()), 'text': 'Здесь обрыв речи', 'part_index': 1, 'source_time': 2.5}
            self.assertEqual(client.post(route, json=body, headers={'Origin': 'https://other.example'}).status_code, 403)
            self.assertEqual(client.post(route, json={**body, 'part_index': 99}).status_code, 400)
            self.assertEqual(client.post(route, json={**body, 'source_time': 11}).status_code, 400)
            self.assertEqual(client.post(route, json={**body, 'operation_id': '../invalid'}).status_code, 404)
            self.assertEqual(client.post(route, json={**body, 'text': ' '}).status_code, 400)
            self.assertEqual(client.post(route, json={**body, 'part_index': True}).status_code, 422)
            response = client.post(route, json=body)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(client.post(route, json=body).json()['id'], response.json()['id'])
            messages = client.get(route).json()['messages']
            self.assertEqual(messages[0]['text'], body['text'])
            self.assertEqual(messages[0]['job_id'], response.json()['id'])
            self.assertEqual(len(self.manager.list_jobs()), 2)
            episode = client.get('/api/library').json()['episodes'][0]
            self.assertEqual(response.json()['episode_id'], episode['id'])

    def test_archived_owner_blocks_new_feedback_without_starting_worker(self):
        with TestClient(create_app(self.manager), base_url='http://127.0.0.1:8765') as client:
            episode = client.get('/api/library').json()['episodes'][0]
            client.delete(f"/api/episodes/{episode['id']}")
            body = {'operation_id': str(uuid.uuid4()), 'text': 'Здесь обрыв речи', 'part_index': 1}
            response = client.post(f"/api/jobs/{self.parent['id']}/feedback", json=body)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(len(self.manager.list_jobs()), 1)
            self.assertIsNone(self.manager.active)

    def test_history_rejects_a_foreign_version_link(self):
        corrected = self.submit()
        self.manager.cancel(corrected['id'])
        state = self.manager.get(corrected['id'])
        state['episode_id'] = str(uuid.uuid4())
        atomic_json(self.manager.job_dir(corrected['id'])/'job.json', state)
        with self.assertRaisesRegex(ValueError, 'Нарушена связь'):
            review_feedback.history(self.manager, self.parent['id'])

    def test_real_pipeline_repairs_margins_and_retry_reuses_same_correction(self):
        result = self.submit()
        self.manager.cancel(result['id'])
        directory = self.manager.job_dir(result['id'])
        outputs, rendered = self.run_correction(directory)
        self.assertEqual(rendered, [1])
        self.assertEqual(len(outputs), 2)
        current = read_json(directory/'plan.json')
        self.assertAlmostEqual(current['parts'][0]['cuts'][0]['start'], 1.65)
        self.assertAlmostEqual(current['parts'][0]['cuts'][0]['end'], 3.95)
        self.assertEqual(read_json(directory/'feedback-result.json')['status'], 'completed')
        before = current['parts'][0]['cuts']
        calls = len(self.vision.calls)
        outputs, rendered = self.run_correction(directory)
        self.assertEqual(rendered, [])
        self.assertEqual(read_json(directory/'plan.json')['parts'][0]['cuts'], before)
        self.assertEqual(len(self.vision.calls), calls)
        self.assertEqual(read_json(self.directory/'plan.json'), self.plan)

    def test_unsupported_or_invalid_model_action_requests_clarification(self):
        for intent in (
                {'actions': [], 'confidence': .99, 'reply': 'Какую сцену нужно изменить?'},
                {'actions': [{'kind': 'delete_everything', 'parts': [1]}], 'confidence': .99, 'reply': 'Delete'},
                {'actions': [{'kind': 'speech', 'parts': [42]}], 'confidence': .99, 'reply': 'Wrong part'}):
            with self.subTest(intent=intent):
                result = self.submit()
                self.manager.cancel(result['id'])
                directory = self.manager.job_dir(result['id'])
                self.vision.intent = intent
                with self.assertRaises(review_feedback.FeedbackClarification):
                    self.run_correction(directory)
                self.assertEqual(read_json(directory/'feedback-result.json')['status'], 'needs_clarification')
                self.assertFalse((directory/'output'/'part_001.mp4').exists())

    def test_opening_allegation_cannot_remove_unverified_footage(self):
        result = self.submit(text='В первой части осталась заставка')
        self.manager.cancel(result['id'])
        directory = self.manager.job_dir(result['id'])
        self.vision.intent = {'actions': [{'kind': 'opening', 'parts': [1]}], 'confidence': .99, 'reply': 'Проверю заставку.'}
        with self.provider(), patch('app.production_sequence.clean_whole_sequences', return_value=self.analysis['events']) as review:
            with self.assertRaisesRegex(review_feedback.FeedbackClarification, 'Не удалось подтвердить'):
                review_feedback.apply_feedback(self.analysis, self.plan, read_json(directory/'correction-request.json'),
                                              directory, lambda *args: None, lambda: False)
            self.assertEqual(review.call_args.kwargs['review_event_ids'], {'e'})
        self.assertEqual(read_json(self.directory/'plan.json'), self.plan)

    def test_opening_feedback_forces_original_boundaries_and_preserves_other_story(self):
        from app.production_sequence import original_clusters
        from tests.test_production_sequence import decision
        from tests.test_story import FakeVision
        analysis = copy.deepcopy(self.analysis)
        analysis['probe']['duration'] = 25
        analysis['transcript'] = {'words': [], 'segments': []}
        analysis['shots'] = [{'start': i*5, 'end': (i+1)*5} for i in range(5)]
        analysis['events'][0].update(end=25, selected_ranges=[{'start': 0, 'end': 25}])
        plan = build_plan(analysis)
        self.assertEqual(original_clusters(analysis['events']), [])
        scripted = FakeVision([decision(), decision(), {'confirmed': True, 'confidence': .95,
                                                      'evidence': 'Visible original theme credit.'}])
        opening_intent = {'actions': [{'kind': 'opening', 'parts': [1]}], 'confidence': .99, 'reply': 'Проверю заставку.'}
        class RecheckingVision(FeedbackVision):
            def query(self, prompt, *args, **kwargs):
                return (opening_intent if prompt.startswith(review_feedback.PROMPT)
                        else scripted.query(prompt, *args, **kwargs))
        self.vision = RecheckingVision(opening_intent)
        request = {'text': 'В первой части осталась заставка', 'part_index': 1,
                   'source_time': 10., 'operation_id': str(uuid.uuid4())}
        with self.provider(), patch('app.production.sequence_sheet', return_value=[self.directory/'authored-page.jpg']):
            repaired = review_feedback.apply_feedback(analysis, plan, request, self.directory,
                                                      lambda *args: None, lambda: False)
        self.assertEqual(len(scripted.calls), 3, 'boundary and anchor checks must remain independent')
        self.assertEqual(repaired['events'][0]['confirmed_opening_ranges'], [{'start': 5., 'end': 20.}])
        self.assertEqual([(c['start'], c['end']) for p in build_plan(repaired)['parts'] for c in p['cuts']],
                         [(0., 5.), (20., 25.)])

    def test_followup_request_inherits_bounded_conversation(self):
        first = self.submit(text='Здесь что-то не так')
        self.manager.cancel(first['id'])
        atomic_json(self.manager.job_dir(first['id'])/'feedback-result.json', {
            'status': 'needs_clarification', 'reply': 'Это заставка или обрыв речи?'})
        second = self.submit(text='Обрыв речи, в конце первой части')
        request = read_json(self.manager.job_dir(second['id'])/'correction-request.json')
        self.assertEqual(request['context_messages'][0]['reply'], 'Это заставка или обрыв речи?')
        self.assertEqual(request['context_messages'][0]['text'], 'Здесь что-то не так')

    def test_here_repairs_only_the_cut_at_playback_position(self):
        analysis = copy.deepcopy(self.analysis)
        analysis['transcript']['words'].append({'start': 6, 'end': 7, 'text': 'Другой.'})
        analysis['transcript']['segments'].append({'start': 6, 'end': 7, 'text': 'Другой.'})
        analysis['events'][0]['selected_ranges'].append({'start': 6, 'end': 7})
        plan = build_plan(analysis)
        self.vision.intent = {'actions': [{'kind': 'speech', 'parts': [1], 'scope': 'position'}],
                              'confidence': .99, 'reply': 'Проверю эту границу речи.'}
        request = {'text': 'Здесь оборвана фраза', 'part_index': 1, 'source_time': 2.5}
        with self.provider():
            repaired = review_feedback.apply_feedback(analysis, plan, request, self.directory,
                                                      lambda *args: None, lambda: False)
        cuts = build_plan(repaired)['parts'][0]['cuts']
        self.assertAlmostEqual(cuts[0]['end'], 3.95)
        self.assertEqual(cuts[1], plan['parts'][0]['cuts'][1])

    def test_no_change_never_claims_a_completed_correction(self):
        with self.assertRaises(review_feedback.FeedbackClarification):
            review_feedback.verify_changed_plan(self.directory, self.plan, self.plan)
        review_feedback.finish(self.directory, 'completed')
        self.assertEqual(read_json(self.directory/'feedback-result.json')['status'], 'needs_clarification')

    def test_changed_original_source_stops_before_any_model(self):
        result = self.submit()
        self.manager.cancel(result['id'])
        self.source.write_bytes(b'changed source')
        with patch('app.vision.vision_session') as session:
            with self.assertRaisesRegex(ValueError, 'Исходник или базовая версия'):
                directory = self.manager.job_dir(result['id'])
                review_feedback.load_base(directory, self.source, read_json(directory/'correction-request.json'))
            session.assert_not_called()

    def test_extended_handles_preserve_exclusions_and_omitted_neighbor_words(self):
        transcript = {'words': [{'start': 1, 'end': 2}, {'start': 2.1, 'end': 3}, {'start': 3.2, 'end': 4}]}
        overrides = [{'start': 2.1, 'end': 3, 'lead': .6, 'tail': 1.5}]
        self.assertEqual(speech_handles.expand_ranges([{'start': 2.1, 'end': 3}], transcript, 10,
                         overrides=overrides), [{'start': 2.04, 'end': 3.16}])
        self.assertEqual(speech_handles.expand_ranges([{'start': 2.1, 'end': 3}], transcript, 10,
                         [{'start': 3.1, 'end': 4}], overrides=overrides)[0]['end'], 3.1)
        with self.assertRaises(ValueError):
            speech_handles.expand_ranges([{'start': 2.1, 'end': 3}], transcript, 10,
                overrides=[{**overrides[0], 'tail': 5}])

    def test_source_policy_is_required_for_longer_handles_and_verified_endings(self):
        from app.final_quality import _source_part_endings
        transcript = self.analysis['transcript']
        overrides = [{'start': 1.82, 'end': 3.55, 'lead': .35, 'tail': .95}]
        plan = {'parts': [{'index': 1, 'cuts': [{'start': 1.65, 'end': 3.95}]}],
                'semantic_ranges': [{'start': 2., 'end': 3.}], 'speech_handle_overrides': overrides}
        self.assertEqual(speech_handles.semantic_ranges(plan, [], transcript, 10, overrides=overrides), plan['semantic_ranges'])
        with self.assertRaises(ValueError):
            speech_handles.semantic_ranges(plan, [], transcript, 10)
        events = [{'part_endings': [{'id': 'end3', 'kind': 'closure', 'time': 3., 'confidence': .95,
            'verification': {'boundary': 'end3', 'supported': True, 'confidence': .95,
                             'evidence': 'The original spoken answer is complete.',
                             'last_reply': 'r0000', 'next_reply': 'none'}}]}]
        self.assertFalse(_source_part_endings(events, transcript, plan['parts'], []))
        self.assertIn(1, _source_part_endings(events, transcript, plan['parts'], [], speech_overrides=overrides))

    def test_per_part_identity_reuses_other_parts_but_detects_cut_and_style_changes(self):
        inputs = {'music': {'enabled': False}, 'source': {'id': 'original'}, 'appearance': None}
        part = copy.deepcopy(self.plan['parts'][0])
        first = pipeline._part_render_fingerprint(part, inputs, None, self.analysis['transcript'])
        part['cover_context'] = {'brief': 'metadata only'}
        self.assertEqual(first, pipeline._part_render_fingerprint(part, inputs, None, self.analysis['transcript']))
        part['cuts'][0]['end'] += .1
        self.assertNotEqual(first, pipeline._part_render_fingerprint(part, inputs, None, self.analysis['transcript']))
        self.assertNotEqual(first, pipeline._part_render_fingerprint(self.plan['parts'][0],
            {**inputs, 'appearance': {'frame_style': 'social'}}, None, self.analysis['transcript']))
