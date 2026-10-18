"""Objective normalization, persistence and submission replay without inference."""
import copy
import shutil
import unittest
import uuid

from app.config import ROOT
from app.jobs import JobManager, SubmissionConflict
from app.json_store import read_json
from app.library import Library
from app.story_objective import LEGACY, STANDALONE, validate_objective
from tests.test_jobs import FakeWorker


class StoryObjectiveTests(unittest.TestCase):
    def test_default_preserves_legacy_and_standalone_normalizes_without_mutation(self):
        self.assertEqual(validate_objective(), {'version': 1, 'objective': LEGACY})
        value = {'objective': STANDALONE, 'settings': {'max_clips': 2}}
        before = copy.deepcopy(value)
        normalized = validate_objective(value)
        self.assertEqual(normalized['settings']['max_clips'], 2)
        self.assertEqual(normalized['settings']['max_duration'], 120)
        self.assertEqual(value, before)
        self.assertEqual(validate_objective(normalized), normalized)

    def test_invalid_objectives_and_duration_settings_are_rejected(self):
        for value in ([], {}, {'objective': 'unknown'}, {'objective': STANDALONE, 'version': True},
                      {'objective': STANDALONE, 'unknown': 1},
                      {'objective': LEGACY, 'settings': {'max_clips': 1}},
                      {'objective': STANDALONE, 'settings': {'max_clips': True}},
                      {'objective': STANDALONE, 'settings': {'max_duration': 121}},
                      {'objective': STANDALONE, 'settings': {'max_duration': float('nan')}},
                      {'objective': STANDALONE, 'settings': {'preferred_min_duration': 100}},
                      {'objective': STANDALONE, 'settings': {'typo': 1}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_objective(value)

    def test_saved_source_settings_and_idempotent_payload_binding(self):
        root = ROOT/'temp'/('objective-mechanism-'+uuid.uuid4().hex)
        root.mkdir(parents=True)
        manager = None
        try:
            (root/'authored.mp4').write_bytes(b'authored source placeholder; not encoded media')
            manager = JobManager(root, FakeWorker)
            source = manager.list_sources()[0]['id']
            library = Library(manager)
            project = library.create_project('Authored project')
            episode = library.create_episode(project['id'], 1)
            objective = {'objective': STANDALONE, 'settings': {'max_clips': 2}}
            settings = {'layout': 'cinema', 'caption_style': 'classic', 'analysis_provider': 'local',
                        'story_objective': objective}
            saved = library.save_episode(episode['id'], source, settings)
            self.assertEqual(saved['settings']['story_objective'], validate_objective(objective))
            with self.assertRaises(ValueError):
                library.save_episode(episode['id'], source, {**settings, 'story_objective': {'objective': 'bad'}})
            operation = str(uuid.uuid4())
            first = library.launch(episode['id'], operation_id=operation)
            self.assertEqual(read_json(manager.job_dir(first['id'])/'story-objective.json'), validate_objective(objective))
            self.assertEqual(library.launch(episode['id'], operation_id=operation)['id'], first['id'])
            manager.cancel(first['id'])
            changed = {**settings, 'story_objective': {'objective': STANDALONE, 'settings': {'max_clips': 1}}}
            library.save_episode(episode['id'], source, changed)
            with self.assertRaises(SubmissionConflict):
                library.launch(episode['id'], operation_id=operation)
        finally:
            if manager is not None:
                manager.close()
            root.resolve().relative_to((ROOT/'temp').resolve())
            shutil.rmtree(root)
