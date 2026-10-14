"""Lifecycle, source mutation and bounded overlap regressions without inference."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import shutil
from threading import Event, Thread
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP, STORY_MODEL, STORY_PROJECTOR, VLM_MODEL
from app import source_identity
from app.processing import source_digest
from app.bounded_storyboard import _source_identity
from app.vision import AnalysisVisionSessions, LocalVision
from app.scene_preparation import CurrentPreparation


class RuntimePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP / ('runtime-performance-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)

    def tearDown(self):
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_hash_shared_across_processing_and_storyboard_and_invalidated(self):
        source = self.directory / 'source.mp4'
        source.write_bytes(b'original')
        with patch.object(source_identity, '_hash_source', wraps=source_identity._hash_source) as hash_source:
            first = source_identity.source_identity(source)['sha256']
            self.assertEqual(first, hashlib.sha256(b'original').hexdigest())
            self.assertEqual(source_digest(source), first)
            self.assertEqual(_source_identity(source, lambda: False)['sha256'], first)
            self.assertEqual(hash_source.call_count, 1)
            source.write_bytes(b'modified')
            self.assertNotEqual(source_digest(source), first)
            self.assertEqual(hash_source.call_count, 2)
            with self.assertRaises(InterruptedError):
                source_identity.source_identity(source, lambda: True)

    def test_mutation_during_hash_is_never_cached(self):
        source = self.directory / 'source.mp4'
        source.write_bytes(b'original')
        original_hash = source_identity._hash_source
        def mutate(path, cancelled):
            result = original_hash(path, cancelled)
            path.write_bytes(b'changed!')
            return result
        with patch.object(source_identity, '_hash_source', side_effect=mutate):
            with self.assertRaises(ValueError):
                source_digest(source)
        self.assertEqual(source_digest(source), hashlib.sha256(b'changed!').hexdigest())

    def test_concurrent_first_hash_computed_once(self):
        source = self.directory / 'source.mp4'
        source.write_bytes(b'original')
        results = []
        with patch.object(source_identity, '_hash_source', wraps=source_identity._hash_source) as hash_source:
            threads = [Thread(target=lambda: results.append(source_digest(source))) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertEqual(results, [hashlib.sha256(b'original').hexdigest()] * 2)
            self.assertEqual(hash_source.call_count, 1)

    def test_two_local_loads_keep_thinking_and_nonthinking_request_contracts(self):
        active, lifecycle, bodies = [], [], []
        def start(vision):
            self.assertFalse(active)
            active.append(vision)
            lifecycle.append(('start', vision.model, vision.thinking))
            vision.port = 9999
            class Opener:
                def open(self, request, timeout):
                    bodies.append(json.loads(request.data))
                    return io.BytesIO(json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode())
            vision.opener = Opener()
        def close(vision):
            lifecycle.append(('close', vision.model))
            active.remove(vision)
        with patch.object(LocalVision, 'start', start), patch.object(LocalVision, 'close', close):
            with AnalysisVisionSessions(self.directory, lambda: False) as sessions:
                for stage in ('boundary', 'scene'):
                    with sessions.session(self.directory, lambda: False) as vision:
                        vision.query(stage, max_tokens=100)
                for thinking in (True, False, False):
                    with sessions.session(self.directory, lambda: False, model=STORY_MODEL,
                                          projector=STORY_PROJECTOR, thinking=thinking) as vision:
                        vision.query('stage', max_tokens=100)
                        if thinking:
                            vision.query('credit', max_tokens=20, thinking_override=False)
                            self.assertTrue(vision.thinking)
            self.assertFalse(active)
        self.assertEqual([row[1] for row in lifecycle if row[0] == 'start'], [VLM_MODEL, STORY_MODEL])
        self.assertEqual([body['chat_template_kwargs']['enable_thinking'] for body in bodies],
                         [False, False, True, False, False, False])
        self.assertEqual([body['max_tokens'] for body in bodies], [100, 100, 612, 20, 100, 100])

    def test_provider_switch_and_failure_release_owned_model(self):
        calls = []
        class Session:
            def __init__(self, *args, **kwargs):
                self.provider = args[2]
            def __enter__(self):
                calls.append(('start', self.provider))
                return self
            def __exit__(self, *args):
                calls.append(('close', self.provider))
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            with AnalysisVisionSessions(self.directory, lambda: False, factory=Session) as sessions:
                with sessions.session(self.directory, lambda: False):
                    pass
                with sessions.session(self.directory, lambda: False, 'deepseek_plan'):
                    pass
                with sessions.session(self.directory, lambda: False):
                    raise RuntimeError('failure')
        self.assertEqual(calls, [('start', 'local'), ('close', 'local'),
                                 ('start', 'deepseek_plan'), ('close', 'deepseek_plan'),
                                 ('start', 'local'), ('close', 'local')])

    def test_one_lookahead_prepares_while_current_inference_is_running(self):
        second_started, release, third_started = Event(), Event(), Event()
        def prepare(chunk, cancelled):
            if chunk['key'] == 1:
                second_started.set()
                self.assertTrue(release.wait(5))
            if chunk['key'] == 2:
                third_started.set()
            return chunk['key']
        with CurrentPreparation([{'key': n} for n in range(3)], prepare, lambda: False) as prepared:
            self.assertEqual(prepared.take(0)[0], 0)
            prepared.advance()
            try:
                # A model response is still pending, and only the next item starts.
                self.assertTrue(second_started.wait(5))
                self.assertFalse(third_started.is_set())
            finally:
                release.set()
            self.assertEqual(prepared.take(1)[0], 1)
            prepared.advance()
            self.assertEqual(prepared.take(2)[0], 2)

    def test_prefetch_failure_propagates_in_source_order(self):
        def prepare(chunk, cancelled):
            if chunk['key'] == 1:
                raise ValueError('decode failed')
            return chunk['key']
        with CurrentPreparation([{'key': n} for n in range(3)], prepare, lambda: False) as prepared:
            self.assertEqual(prepared.take(0)[0], 0)
            prepared.advance()
            with self.assertRaisesRegex(ValueError, 'decode failed'):
                prepared.take(1)

    def test_prefetch_drains_on_model_failure_and_cancellation(self):
        started, stopped = Event(), Event()
        def prepare(chunk, cancelled):
            started.set()
            while not cancelled():
                stopped.wait(.01)
            stopped.set()
            raise InterruptedError('stopped')
        with self.assertRaisesRegex(RuntimeError, 'model failure'):
            with CurrentPreparation([{'key': 0}], prepare, lambda: False):
                self.assertTrue(started.wait(5))
                raise RuntimeError('model failure')
        self.assertTrue(stopped.is_set())
        with CurrentPreparation([{'key': 0}], lambda *args: 0, lambda: True) as prepared:
            with self.assertRaises(InterruptedError):
                prepared.take(0)

    def test_analysis_orchestration_uses_two_loads_and_closes_on_cache_hit(self):
        from app.analysis import analyze
        from app.json_store import analysis_json as atomic_json
        from app.inference import REPAIR_VERSION
        source = self.directory / 'source.mp4'
        source.write_bytes(b'original')
        (self.directory / 'audio.wav').write_bytes(b'prepared')
        transcript = {'segments': [], 'words': [], 'repair_version': REPAIR_VERSION}
        atomic_json(self.directory / 'transcript.json', transcript)
        atomic_json(self.directory / 'analysis-settings.json', {'economy_mode': False})
        probe = {'duration': 2, 'width': 160, 'height': 90, 'fps': 24, 'has_audio': True}
        scenes = [{'id': 'scene', 'start': 0, 'end': 2, 'boundary_reason': 'start',
                   'confidence': 1, 'uncertain': False}]
        events = [{'id': 'event_0000', 'summary': 'source', 'start': 0, 'end': 2,
                   'importance': 4, 'requires': [], 'selected_ranges': [{'start': 0, 'end': 2}]}]
        stages, loads, closes = [], [], []
        def stage(label):
            def run(*args, **kwargs):
                vision = next((value for value in args if isinstance(value, LocalVision)), None)
                if vision is not None:
                    stages.append((label, vision.model, vision.thinking))
                return events
            return run
        def start(vision):
            loads.append(vision.model)
        def close(vision):
            closes.append(vision.model)
        with ExitStack() as stack:
            stack.enter_context(patch.object(LocalVision, 'start', start))
            stack.enter_context(patch.object(LocalVision, 'close', close))
            for target, result in (
                ('app.analysis.probe_media', probe),
                ('app.analysis.shot_checkpoint', []),
                ('app.media_probe.raw_shot_evidence', []),
                ('app.media_evidence.perception_checkpoint', {}),
                ('app.episode_profile.build_episode_profile', {}),
                ('app.episode_profile.scene_settings', {}),
                ('app.scene_detection.scene_checkpoint', scenes),
                ('app.eyecatch.detect_eyecatches', []),
                ('app.analysis.global_story_review', {'keep': ['event_0000'], 'omit': []}),
                ('app.analysis.apply_global_selection', None),
                ('app.speech_context.protect_speech_context', events),
                ('app.story.preserve_dialogue_in_credits', events),
                ('app.analysis.analysis_result', {'events': events}),
            ):
                stack.enter_context(patch(target, return_value=result))
            for target, label in (
                ('app.scene_analysis.analyze_scenes', 'scene'),
                ('app.scene_refinement.refine_scene_story', 'story'),
                ('app.story.clean_credit_continuations', 'credits'),
                ('app.antigravity_batch.review_events_in_batches', 'checks'),
                ('app.antigravity_batch.closing_in_batches', 'closing'),
                ('app.global_verification.verify_global_visual', 'global'),
                ('app.antigravity_batch.adjudicate_in_batches', 'selection'),
                ('app.pacing.refine_pacing', 'pacing'),
                ('app.pacing.refine_silent_sequences', 'silent'),
                ('app.analysis.finalize_editorial_selection', 'editorial'),
                ('app.framing.refine_focus', 'framing'),
            ):
                stack.enter_context(patch(target, side_effect=stage(label)))
            expected = {'events': events, 'check_policy': {'version': 2, 'economy_mode': False}}
            self.assertEqual(analyze(self.directory, source, lambda *args: None, lambda: False), expected)
            self.assertEqual(loads, [VLM_MODEL, STORY_MODEL])
            self.assertEqual(closes, loads)
            self.assertIn(('story', STORY_MODEL, True), stages)
            self.assertIn(('pacing', STORY_MODEL, False), stages)
            self.assertIn(('framing', STORY_MODEL, False), stages)
            # Story cache reuse can start 9B directly in non-thinking mode.
            (self.directory / 'events.meta.json').unlink()
            loads.clear()
            closes.clear()
            stages.clear()
            analyze(self.directory, source, lambda *args: None, lambda: False)
            self.assertEqual(loads, [STORY_MODEL])
            self.assertEqual(closes, loads)
            self.assertFalse(any(stage[0] == 'story' for stage in stages))
            # The completed pacing pass can itself be restored without query.
            loads.clear()
            closes.clear()
            self.assertEqual(analyze(self.directory, source, lambda *args: None, lambda: False), expected)
            self.assertEqual(loads, [])
            self.assertEqual(closes, [])
            # A policy switch must miss the all-analysis cache and skip optional
            # model callbacks even when their completed snapshots are absent.
            from app.analysis_checks import OPTIONAL_CHECKS
            for name in OPTIONAL_CHECKS:
                (self.directory / 'continuation/stages' / (name + '.json')).unlink(missing_ok=True)
            atomic_json(self.directory / 'analysis-settings.json', {'economy_mode': True})
            with patch('app.global_verification.verify_global_visual', side_effect=AssertionError('Optional model call')), \
                 patch('app.review_scope.prepare_review_scope', return_value=events), \
                 patch('app.pacing.refine_pacing', side_effect=AssertionError('Optional model call')), \
                 patch('app.pacing.refine_silent_sequences', side_effect=AssertionError('Optional model call')):
                result = analyze(self.directory, source, lambda *args: None, lambda: False)
                self.assertTrue(result['check_policy']['economy_mode'])
            self.assertNotIn(VLM_MODEL, loads)
            self.assertEqual(closes, loads)

    def test_scene_prefetch_crosses_scene_boundary_and_skips_valid_checkpoints(self):
        from app.scene_analysis import analyze_scenes
        from app.json_store import analysis_json as atomic_json
        next_ready = Event()
        prepared = []
        def board(source, start, end, units, image, cancelled, **settings):
            image.write_bytes(b'source-image')
            atomic_json(image.with_suffix('.storyboard.json'),
                        {'frames': [{'time': start}], 'pages': [str(image)]})
            if not settings.get('context'):
                prepared.append(start)
                if start == 2:
                    next_ready.set()
            return [start]
        class Vision:
            def __init__(self):
                self.calls = 0
            def query(inner, prompt, image, max_tokens, schema):
                if inner.calls == 0:
                    self.assertTrue(next_ready.wait(5))
                inner.calls += 1
                state = {'locations': [], 'character_state': '', 'objects': []}
                return {'summary': 'Source', 'kind': 'story', 'importance': 4, 'uncertain': False,
                        'semantic_confidence': .95, 'visual_confidence': .95, 'context_confidence': .95,
                        'selection_confidence': .95, 'uncertainty_reasons': [], 'action_units': [],
                        'keep_units': schema['properties']['keep_units']['items']['enum'],
                        'narrative_bridge': False, 'state_before': state, 'state_after': state}
        scenes = [{'id': f'scene_{n}', 'start': n*2, 'end': (n+1)*2} for n in range(3)]
        transcript = {'segments': [], 'words': []}
        vision = Vision()
        def overview(source, start, end, shots, transcript, image, cancelled):
            return board(source, start, end, [], image, cancelled, context=True)
        with patch('app.vision.inference_storyboard', side_effect=board), patch('app.vision.storyboard', side_effect=overview):
            def run():
                return analyze_scenes(self.directory / 'missing-source.mp4', scenes, transcript, [],
                                      self.directory, vision, 'signature', lambda *args: None, lambda: False)
            first = run()
            self.assertEqual(vision.calls, 3)
            self.assertEqual([start for start in prepared[:2]], [0, 2])
            prepared.clear()
            self.assertEqual(run(), first)
            self.assertFalse(prepared)
            self.assertEqual(vision.calls, 3)
            # Reconstruct a lost parent from valid chunk decisions, without inference.
            (self.directory / 'visual/event_0001.json').unlink()
            self.assertEqual(run(), first)
            self.assertEqual(vision.calls, 3)
