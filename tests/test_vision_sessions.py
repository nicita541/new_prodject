"""Lazy local runtime ownership; no real inference or model files needed."""
from pathlib import Path
from contextlib import contextmanager
import unittest

from app.config import VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
from app.vision import AnalysisVisionSessions


class LazyVisionSessionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        active = []

        class Session:
            supports_image_pages = True
            supports_thinking_override = True
            max_current_frames = 64
            max_boundary_batch = 3
            cpu_fallback = False

            def __init__(self, job_dir, cancelled, provider, **settings):
                self.model = settings.get('model', VLM_MODEL)
                self.projector = settings.get('projector', VLM_PROJECTOR)
                self.thinking = settings.get('thinking', False)

            @property
            def cache_profile(self):
                return str(self.model)

            def __enter__(self):
                if active:
                    raise AssertionError('concurrent model load')
                active.append(self)
                calls.append(('start', self.model))
                return self

            def __exit__(self, *args):
                active.remove(self)
                calls.append(('close', self.model))

            def query(self, prompt, **kwargs):
                calls.append(('query', self.model, self.thinking, prompt, kwargs))
                if prompt == 'fail':
                    raise ValueError('inference failed')
                return {'ok': True}

            def token_count(self, text):
                calls.append(('token_count', self.model))
                return len(text)

        self.factory = Session
        self.directory = Path('unused-job')

    def session(self, owner, **settings):
        return owner.session(self.directory, lambda: False, **settings)

    def test_cached_or_skipped_stage_reads_metadata_without_loading(self):
        with AnalysisVisionSessions(self.directory, lambda: False, self.factory) as owner:
            with self.session(owner, model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True) as vision:
                self.assertEqual(vision.model, STORY_MODEL)
                self.assertEqual(vision.projector, STORY_PROJECTOR)
                self.assertEqual(vision.cache_profile, str(STORY_MODEL))
                self.assertTrue(vision.supports_image_pages)
                self.assertTrue(vision.supports_thinking_override)
                self.assertTrue(vision.thinking)
                self.assertFalse(vision.cpu_fallback)
                self.assertEqual(vision.max_boundary_batch, 3)
                self.assertTrue(callable(vision.query))
                self.assertFalse(hasattr(vision, 'query_many'))
            self.assertEqual(self.calls, [])
        self.assertEqual(self.calls, [])

    def test_only_inference_switches_models_and_sequential_stages_reuse(self):
        with AnalysisVisionSessions(self.directory, lambda: False, self.factory) as owner:
            with self.session(owner) as vision:
                self.assertEqual(vision.query('scene'), {'ok': True})
            with self.session(owner, model=STORY_MODEL, projector=STORY_PROJECTOR):
                pass
            self.assertEqual([row for row in self.calls if row[0] == 'close'], [])
            with self.session(owner) as vision:
                vision.query('another scene')
            for thinking in (True, False):
                with self.session(owner, model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=thinking) as vision:
                    vision.query('story', thinking_override=False)
                    self.assertEqual(vision.thinking, thinking)
        self.assertEqual([row for row in self.calls if row[0] in ('start', 'close')],
                         [('start', VLM_MODEL), ('close', VLM_MODEL),
                          ('start', STORY_MODEL), ('close', STORY_MODEL)])
        self.assertEqual([row[2] for row in self.calls if row[0] == 'query'], [False, False, True, False])

    def test_token_count_acquires_runtime_and_exception_closes_it(self):
        with self.assertRaisesRegex(ValueError, 'inference failed'):
            with AnalysisVisionSessions(self.directory, lambda: False, self.factory) as owner:
                with self.session(owner) as vision:
                    self.assertEqual(vision.token_count('abc'), 3)
                    vision.query('fail')
        self.assertEqual(self.calls[-1], ('close', VLM_MODEL))

    def test_closed_stage_cannot_start_runtime(self):
        with AnalysisVisionSessions(self.directory, lambda: False, self.factory) as owner:
            with self.session(owner) as vision:
                query = vision.query
            with self.assertRaisesRegex(RuntimeError, 'stage is closed'):
                query('late')
        self.assertEqual(self.calls, [])

    def test_cancellation_before_first_request_does_not_load_model(self):
        cancelled = [False]
        with AnalysisVisionSessions(self.directory, lambda: cancelled[0], self.factory) as owner:
            with owner.session(self.directory, lambda: cancelled[0]) as vision:
                cancelled[0] = True
                with self.assertRaises(InterruptedError):
                    vision.query('cancelled')
        self.assertEqual(self.calls, [])

    def test_contextmanager_observer_factory_remains_lazy_and_forwards_real_calls(self):
        @contextmanager
        def observed(*args, **kwargs):
            with self.factory(*args, **kwargs) as vision:
                yield vision
        with AnalysisVisionSessions(self.directory, lambda: False, observed) as owner:
            with self.session(owner, model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
                self.assertEqual(vision.model, STORY_MODEL)
                self.assertTrue(callable(vision.query))
                self.assertEqual(self.calls, [])
                self.assertEqual(vision.token_count('real tokenizer boundary'), 23)
                self.assertEqual(vision.query('source'), {'ok': True})
        self.assertEqual([row[0] for row in self.calls], ['start', 'token_count', 'query', 'close'])
