import unittest
import shutil
import uuid
from unittest.mock import patch

from app.dramatic_planner import build_dramatic_plan, _compress_dialogue_turns
from app.planner import validate_plan
from app.analysis import analysis_result
from app.config import TEMP
from app.media_probe import atomic_json, load_json


def episode(count=30):
    events = []
    for i in range(count):
        start = i * 40.0
        events.append({'id': f'e{i}', 'start': start, 'end': start+30,
                       'kind': 'story', 'importance': 4, 'summary': 'Факт', 'requires': [],
                       'unit_selection_version': 1,
                       'selected_ranges': [{'start': start, 'end': start+25}]})
    return {'probe': {'duration': count*40.0, 'width': 320, 'height': 180, 'fps': 24, 'has_audio': True},
            'events': events, 'transcript': {'words': [], 'segments': []}, 'shots': []}


class AdaptiveMontageTests(unittest.TestCase):
    def test_analysis_result_persists_initial_and_refined_profile_with_raw_evidence(self):
        job = TEMP / ('adaptive-result-' + uuid.uuid4().hex)
        job.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(job) if job.resolve().is_relative_to(TEMP.resolve()) else None)
        analysis = episode(1)
        atomic_json(job/'scenes.json', [{'start': 0, 'end': 40}])
        shots = [{'id': 's0', 'start': 0, 'end': 40,
                  'raw_shot_candidates': [{'id': 'c0', 'time': 10, 'scene_score': .25, 'accepted': False}]}]
        result = analysis_result(job, 'local', analysis['probe'], analysis['transcript'], shots, analysis['events'])
        saved = load_json(job/'diagnostics'/'pipeline'/'episode_profile.json')
        self.assertEqual(saved, result['episode_profile'])
        self.assertEqual(saved['phase'], 'refined')
        self.assertEqual(saved['initial_profile']['phase'], 'initial')
        self.assertEqual(saved['metrics']['raw_candidates'], 1)
        self.assertIn('scene_settings', saved)

    def test_real_quota_changes_retained_output_under_pressure(self):
        analysis = episode()
        with patch('app.dramatic_planner.adaptive_retention_budget', return_value={'min': 80, 'optimal': 100, 'max': 150}):
            short = build_dramatic_plan(analysis)
        with patch('app.dramatic_planner.adaptive_retention_budget', return_value={'min': 250, 'optimal': 300, 'max': 400}):
            long = build_dramatic_plan(analysis)
        for plan in (short, long):
            validate_plan(plan, analysis)
        self.assertLess(sum(p['duration'] for p in short['parts']), sum(p['duration'] for p in long['parts']))
        self.assertLess(len(short['selected_event_ids']), len(analysis['events']) / 2)
        self.assertLessEqual(sum(p['duration'] for p in short['parts']), 150)

    def test_quota_measures_selected_material_instead_of_scene_envelope(self):
        analysis = episode()
        for event in analysis['events']:
            event['selected_ranges'][0]['end'] = event['start'] + 4
        with patch('app.dramatic_planner.adaptive_retention_budget', return_value={'min': 35, 'optimal': 40, 'max': 60}):
            plan = build_dramatic_plan(analysis)
        self.assertEqual(len(plan['selected_event_ids']), 10)
        self.assertAlmostEqual(sum(p['duration'] for p in plan['parts']), 40)

    def test_validated_action_and_minimal_fallback_survive_compression(self):
        event = {'start': 0, 'end': 180, 'unit_selection_version': 1,
                 'selected_ranges': [{'start': 10, 'end': 14}, {'start': 70, 'end': 71}],
                 'action_units': ['c000_u001'], 'fallback': 'minimal_safe_context'}
        words = [{'start': 10, 'end': 11, 'text': 'Речь'}, {'start': 120, 'end': 121, 'text': 'Лишнее'}]
        ranges = _compress_dialogue_turns(event, words, words, words, 180)
        self.assertTrue(any(r['start'] <= 70 and r['end'] >= 71 for r in ranges))
        self.assertLess(sum(r['end']-r['start'] for r in ranges), 8)
        self.assertFalse(any(r['start'] <= 120 < r['end'] for r in ranges))
