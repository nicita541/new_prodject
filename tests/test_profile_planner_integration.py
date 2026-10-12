"""Source-profile handoff and real planner quota pressure, without model calls."""
import copy
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.analysis import analysis_result
from app.config import TEMP
from app.dramatic_planner import build_dramatic_plan
from app.episode_profile import build_episode_profile
from app.json_store import analysis_json as atomic_json, load_json
from app.semantic_identity import component_identity
from tests.test_retention_allocation import event

EMPTY = {'words': [], 'segments': []}
MOTION = {'motion': {'available': True, 'evidence': 'source_optical_flow',
    'physical_motion_density': .8, 'measurement_coverage': 1., 'adequate_coverage': True}}


def analysis_fixture():
    events = [event('optional', 0, 9), event('mandatory', 20, 22, True), event('small', 30, 35)]
    for item, importance in zip(events, (5, 2, 3)):
        item.update(kind='story', importance=importance, summary='Исходный эпизод.', requires=[],
            focus=[{'time': item['start'], 'x': .5, 'y': .5, 'confidence': .9}], unit_selection_version=1)
    return {'probe': {'duration': 50., 'width': 640, 'height': 360, 'fps': 24., 'has_audio': True},
        'events': events, 'transcript': copy.deepcopy(EMPTY), 'shots': [{'start': 0., 'end': 50.}]}


class ProfilePlannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP/('profile-planner-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)

    def tearDown(self):
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_analysis_finalizes_measured_profile_and_planner_reuses_identical_snapshot(self):
        source = analysis_fixture()
        atomic_json(self.directory/'media-evidence.json', MOTION)
        actual = analysis_result(self.directory, 'local', source['probe'], source['transcript'],
            source['shots'], source['events'])
        profile = actual['episode_profile']
        self.assertEqual(profile['profile'], 'action_dense')
        self.assertEqual(profile['motion_score'], .8)
        self.assertEqual(profile['initial_profile']['motion_score'], .8)
        self.assertEqual(load_json(self.directory/'episode_profile.json'), profile)
        before = copy.deepcopy(actual)
        with patch('app.dramatic_planner.build_episode_profile', side_effect=AssertionError('profile recomputed')):
            plan = build_dramatic_plan(actual)
        self.assertEqual(plan['episode_profile'], profile)
        self.assertEqual(plan['retention_budget'], profile['retention_budget'])
        self.assertEqual(actual, before)

    def test_actual_planner_reserves_transition_before_higher_ranked_optional_cost(self):
        source = analysis_fixture()
        profile = build_episode_profile(50., EMPTY, source['shots'], events=source['events'], perception=MOTION)
        profile['retention_budget'] = {'min': 6., 'optimal': 9., 'max': 10.}
        source['episode_profile'] = profile
        plan = build_dramatic_plan(source)
        self.assertEqual(set(plan['selected_event_ids']), {'mandatory', 'small'})
        self.assertEqual(plan['retention_allocation']['mandatory_duration'], 2.)
        self.assertEqual(plan['retention_allocation']['retained_duration'], 7.)
        self.assertFalse(plan['retention_budget_exceeded'])
        self.assertEqual(sum(part['duration'] for part in plan['parts']), 7.)

    def test_actual_planner_explains_mandatory_overflow_without_trimming_unit(self):
        source = analysis_fixture()
        source['events'] = [source['events'][1]]
        profile = build_episode_profile(50., EMPTY, source['shots'], events=source['events'], perception=MOTION)
        profile['retention_budget'] = {'min': .5, 'optimal': .8, 'max': 1.}
        source['episode_profile'] = profile
        plan = build_dramatic_plan(source)
        self.assertTrue(plan['retention_budget_exceeded'])
        allocation = plan['planner_diagnostics']['retention_allocation']
        self.assertEqual(allocation['optional_budget'], 0.)
        self.assertEqual(allocation['overflow_reasons'][0]['reason'], 'mandatory_source_context_exceeds_max')
        self.assertEqual(allocation['overflow_reasons'][0]['excess'], 1.)
        cuts = [cut for part in plan['parts'] for cut in part['cuts']]
        self.assertEqual([(cut['start'], cut['end']) for cut in cuts], [(20., 22.)])

    def test_missing_motion_stays_explicit_and_wrong_source_profile_is_rejected(self):
        source = analysis_fixture()
        profile = build_episode_profile(50., EMPTY, source['shots'], events=source['events'])
        self.assertIsNone(profile['motion_score'])
        self.assertEqual(profile['profile'], 'balanced')
        profile['source_duration'] = 51.
        source['episode_profile'] = profile
        with self.assertRaisesRegex(ValueError, 'не соответствует'):
            build_dramatic_plan(source)

    def test_allocation_code_and_measured_motion_invalidate_semantic_cache(self):
        planner_before = component_identity('planner')
        profile_before = component_identity('episode_profile')
        original = Path.read_text
        def changed(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return value+'\n# changed source policy\n' if path.name in {'retention_allocation.py','media_evidence.py'} else value
        with patch('app.semantic_identity.Path.read_text', new=changed):
            self.assertNotEqual(planner_before, component_identity('planner'))
            self.assertNotEqual(profile_before, component_identity('episode_profile'))
