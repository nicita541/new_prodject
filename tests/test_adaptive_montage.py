import unittest
import shutil
import uuid

from app.dramatic_planner import build_dramatic_plan, _compress_dialogue_turns
from app.planner import validate_plan
from app.analysis import analysis_result
from app.config import TEMP
from app.media_probe import atomic_json, load_json
from tests.montage_fixtures import finalized_profile


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
        analysis['events'][0].update(initial_uncertain=True, uncertain_after_recovery=True, uncertain=False)
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
        summary = load_json(job/'diagnostics'/'pipeline'/'summary.json')
        self.assertEqual(summary['uncertain_initial'], 1)
        self.assertEqual(summary['uncertain_after_recovery'], 1)
        self.assertEqual(summary['uncertain_final'], 0)
        from app.pipeline_diagnostics import Diagnostics
        from app.analysis import selection_snapshot
        diagnostics = Diagnostics(job)
        selection_snapshot(diagnostics, 'story_refinement', analysis['events'])
        analysis_result(job, 'local', analysis['probe'], analysis['transcript'], shots, analysis['events'])
        diagnostics.start(provider='local')
        analysis_result(job, 'local', analysis['probe'], analysis['transcript'], shots, analysis['events'])
        cached_summary = load_json(diagnostics.path/'summary.json')
        self.assertEqual(cached_summary['duration_after_story_refinement'], 25)
        self.assertEqual(cached_summary['uncertain_after_recovery'], 1)
        diagnostics.summary(duration_after_story_refinement=21)
        analysis_result(job, 'local', analysis['probe'], analysis['transcript'], shots, analysis['events'])
        self.assertEqual(load_json(diagnostics.path/'summary.json')['duration_after_story_refinement'], 21)

    def test_corrupt_diagnostic_summary_does_not_block_valid_analysis_cache(self):
        job = TEMP / ('adaptive-summary-' + uuid.uuid4().hex)
        job.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(job) if job.resolve().is_relative_to(TEMP.resolve()) else None)
        analysis = episode(1)
        result = analysis_result(job, 'local', analysis['probe'], analysis['transcript'], [], analysis['events'])
        (job/'diagnostics/pipeline/analysis-summary.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(result, analysis_result(job, 'local', analysis['probe'], analysis['transcript'], [], analysis['events']))
        warnings = load_json(job/'diagnostics/pipeline/warnings.json')
        self.assertEqual(warnings[-1]['reason'], 'cached_analysis_summary_invalid')

    def test_real_quota_changes_retained_output_under_pressure(self):
        analysis = episode()
        short = build_dramatic_plan(finalized_profile(analysis, {'min': 80, 'optimal': 100, 'max': 150}))
        long = build_dramatic_plan(finalized_profile(analysis, {'min': 250, 'optimal': 300, 'max': 400}))
        for plan in (short, long):
            validate_plan(plan, analysis)
        self.assertLess(sum(p['duration'] for p in short['parts']), sum(p['duration'] for p in long['parts']))
        self.assertLess(len(short['selected_event_ids']), len(analysis['events']) / 2)
        self.assertLessEqual(sum(p['duration'] for p in short['parts']), 150)

    def test_quota_measures_selected_material_instead_of_scene_envelope(self):
        analysis = episode()
        for event in analysis['events']:
            event['selected_ranges'][0]['end'] = event['start'] + 4
        plan = build_dramatic_plan(finalized_profile(analysis, {'min': 35, 'optimal': 40, 'max': 60}))
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
