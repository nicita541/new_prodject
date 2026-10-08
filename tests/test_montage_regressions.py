import json
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP
from app.dramatic_planner import build_dramatic_plan
from app.planner import build_plan, validate_plan
from app.scene_analysis import analyze_scenes
from app.scene_detection import detect_semantic_scenes
from app.semantic_identity import semantic_identity
from app.scene_analysis import SCENE_PROMPT
from app.vision import storyboard_samples
from tests.montage_fixtures import event, state, source_episode, kidnapping_episode, five_arcs_episode, finalized_profile
from tests import test_semantic_pipeline as semantic_test_support


def coverage(plan):
    return [c for p in plan['parts'] for c in p['cuts']]


def retained_event_seconds(plan, data, identifier):
    item = next(e for e in data['events'] if e['id'] == identifier)
    return sum(max(0, min(c['end'], item['end'])-max(c['start'], item['start'])) for c in coverage(plan))


class LongMontageRegressionTests(unittest.TestCase):
    def test_01_conversation_binding_car_survive_as_bounded_causal_path(self):
        data = kidnapping_episode()
        plan = build_dramatic_plan(data)
        validate_plan(plan, data)
        for identifier in ('binding', 'transport'):
            cuts = [c for c in coverage(plan) if identifier in c['event_ids']]
            self.assertTrue(cuts, identifier)
            self.assertLessEqual(retained_event_seconds(plan, data, identifier), 8)
        self.assertTrue(plan['planner_diagnostics']['transitions'])
        self.assertTrue(plan['planner_diagnostics']['bridges'])

    def test_02_explanatory_context_is_short_without_unexplained_topic_jump(self):
        before, after = state(topic='doubt'), state(topic='Hinako')
        words = [{'start': 1, 'end': 3, 'text': 'Я не уверен, что справлюсь.'},
                 {'start': 143, 'end': 148, 'text': 'Хинако должна помочь.'},
                 {'start': 153, 'end': 157, 'text': 'Хинако, что ты тут делаешь?'}]
        data = source_episode([
            event('doubt', 0, 30, 5, state_before=before, state_after=before),
            event('explanation', 30, 150, 2, state_before=before, state_after=after,
                  units=[{'id': 'context', 'start': 143, 'end': 148}]),
            event('arrival', 150, 180, 5, state_before=after, state_after=after, requires=['explanation'])],
            transcript={'words': words, 'segments': words})
        plan = build_dramatic_plan(data)
        selected = [c for c in coverage(plan) if 'explanation' in c['event_ids']]
        self.assertTrue(selected)
        self.assertLess(retained_event_seconds(plan, data, 'explanation'), 10)

    def test_03_ninety_second_conversation_remains_complete_in_long_source(self):
        words = [{'start': i, 'end': i+1.5, 'text': 'Слово.'} for i in range(0, 89, 2)]
        data = source_episode([event('conversation', 0, 90, 5)],
            transcript={'words': words, 'segments': [{'start': 0, 'end': 90, 'text': 'Длинный спокойный разговор.'}]})
        plan = build_dramatic_plan(data)
        self.assertEqual(len(plan['parts']), 1)
        self.assertEqual(plan['parts'][0]['duration'], 90)

    def test_04_editing_candidates_cannot_assert_motion_and_measured_motion_controls_profile(self):
        data = source_episode()
        data['shots'] = [{'id': 'accepted', 'start': 0, 'end': 1440,
            'raw_shot_candidates': [{'id': f'raw{i}', 'time': i+.5, 'scene_score': .55, 'accepted': False}
                                    for i in range(1000)]}]
        plan = build_dramatic_plan(data)
        self.assertEqual(plan['episode_profile']['profile'], 'balanced')
        self.assertIsNone(plan['episode_profile']['motion_score'])
        data['perception'] = {'motion': {'available': True, 'adequate_coverage': True,
            'measurement_coverage': .9, 'evidence': 'source_optical_flow', 'physical_motion_density': .8}}
        plan = build_dramatic_plan(finalized_profile(data))
        self.assertEqual(plan['episode_profile']['profile'], 'action_dense')
        validate_plan(plan, data)
        self.assertLess(sum(p['duration'] for p in plan['parts']), 1440)

    def test_05_one_second_silent_action_during_speech_is_retained_and_sampled(self):
        unit = {'id': 'handover', 'start': 55, 'end': 56}
        item = event('handover_scene', 0, 90, 5, units=[unit], action_units=['handover'],
                     selected_ranges=[{'start': 25, 'end': 28}, {'start': 55, 'end': 56}])
        speech = [{'start': 25, 'end': 28, 'text': 'Продолжает говорить.'}]
        data = source_episode([item], transcript={'words': speech, 'segments': speech})
        plan = build_dramatic_plan(data)
        self.assertTrue(any(c['start'] <= 55 and c['end'] >= 56 for c in coverage(plan)))
        frames = storyboard_samples(0, 90, [{'start': 0}, {'start': 55}, {'start': 56}], data['transcript'])
        self.assertGreaterEqual(sum(55 <= f['time'] < 56 for f in frames), 3)

    def test_06_recovery_corrects_wrong_local_hypothesis_inside_long_episode(self):
        job = TEMP/('long-recovery-'+uuid.uuid4().hex)
        job.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(job) if job.resolve().is_relative_to(TEMP.resolve()) else None)
        class Vision(semantic_test_support.FakeVision):
            def query(self, prompt, image=None, max_tokens=1000, schema=None):
                raw = super().query(prompt, image, max_tokens, schema)
                recovery = 'initial_analysis' in prompt
                raw.update(summary='Героев связывают.' if recovery else 'Только разговор.', uncertain=not recovery,
                           semantic_confidence=.95 if recovery else .4,
                           visual_confidence=.95 if recovery else .4, context_confidence=.95 if recovery else .4,
                           uncertainty_reasons=[] if recovery else ['visual_ambiguity'])
                raw['action_units'] = raw['keep_units'][:1] if recovery else []
                return raw
        shots = [{'id': 'scene_shot', 'start': 0, 'end': 90, 'location': 'street'}]
        scenes = detect_semantic_scenes(shots, {'words': [], 'segments': []}, 90)
        vision = Vision()
        with patch('app.vision.storyboard', side_effect=semantic_test_support.SemanticPipelineTests.fake_board), \
             patch('app.vision.inference_storyboard',side_effect=semantic_test_support.SemanticPipelineTests.fake_inference_board):
            result = analyze_scenes(job/'episode.mp4', scenes, {'words': [], 'segments': []}, shots, job,
                                    vision, 'fresh', lambda *args: None, lambda: False)
        data = source_episode(result)
        plan = build_dramatic_plan(data)
        self.assertIn('Героев связывают', result[0]['final_summary'])
        self.assertIn('Только разговор', result[0]['local_summary'])
        self.assertEqual(result[0]['summary_source'], 'recovery')
        self.assertGreaterEqual(len(vision.requests), 6)
        validate_plan(plan, data)

    def test_07_bad_dependency_does_not_restore_three_minutes_or_transitive_chain(self):
        data = source_episode([
            event('ancestor', 0, 180, 1),
            event('context', 180, 360, 2, requires=['ancestor'], units=[{'id': 'necessary', 'start': 353, 'end': 359}]),
            event('payoff', 360, 390, 5, requires=['context'])])
        for builder in (build_plan, build_dramatic_plan):
            plan = builder(data)
            self.assertIn('context', plan['selected_event_ids'])
            self.assertNotIn('ancestor', plan['selected_event_ids'])
            cuts = [c for c in coverage(plan) if 'context' in c['event_ids']]
            self.assertLessEqual(retained_event_seconds(plan, data, 'context'), 7.1)
            self.assertTrue(plan['planner_diagnostics']['bridges'])

    def test_08_five_complete_arcs_beat_preferred_six_parts(self):
        data = five_arcs_episode()
        plan = build_dramatic_plan(finalized_profile(data, {'min': 420, 'optimal': 420, 'max': 420}))
        self.assertEqual(len(plan['parts']), 5)
        self.assertEqual([p['duration'] for p in plan['parts']], [84]*5)
        self.assertEqual(plan['planner_diagnostics']['part_policy']['preferred_part_count'], 6)
        self.assertEqual(len(plan['planner_diagnostics']['arcs']), 5)

    def test_09_prompt_change_without_version_change_invalidates_semantic_identity(self):
        initial = semantic_identity()
        with patch('app.scene_analysis.SCENE_PROMPT', SCENE_PROMPT+' Verify an object handover.'):
            changed = semantic_identity()
        self.assertNotEqual(initial['digest'], changed['digest'])
        self.assertEqual(initial['components']['shot_detector'], changed['components']['shot_detector'])

    def test_10_real_quota_pressure_omits_low_ranked_material_with_complete_audit(self):
        data = source_episode()
        plan = build_dramatic_plan(finalized_profile(data, {'min': 100, 'optimal': 125, 'max': 150}))
        self.assertLess(len(plan['selected_event_ids']), 10)
        self.assertLessEqual(sum(p['duration'] for p in plan['parts']), 150)
        audit = plan['planner_diagnostics']
        self.assertTrue(any(not row['selected'] and row['reasons'] for row in audit['candidates']))
        rows = audit['decisions']
        self.assertEqual(rows[0]['source_start'], 0)
        self.assertEqual(rows[-1]['source_end'], 1440)
        self.assertTrue(all(a['source_end'] == b['source_start'] for a,b in zip(rows,rows[1:])))
        json.dumps(audit, ensure_ascii=False, allow_nan=False)

    def test_question_answer_cannot_be_split_by_high_confidence_cliffhanger_label(self):
        speech = [{'start': 0, 'end': 70, 'text': 'Ты справишься?'},
                  {'start': 71, 'end': 85, 'text': 'Да, я справлюсь.'},
                  {'start': 100, 'end': 170, 'text': 'Следующая история.'}]
        endings = [{'time': 70.55, 'kind': 'cliffhanger', 'confidence': .95, 'evidence': 'Неверный выход перед ответом'},
                   {'time': 85.55, 'kind': 'closure', 'confidence': .95, 'evidence': 'Ответ завершён',
                    'verification': {'supported': True, 'confidence': .95}}]
        data = source_episode([event('dialogue', 0, 100, 5, part_endings=endings),
                               event('next_story', 100, 170, 5)],
                              transcript={'words': speech, 'segments': speech})
        plan = build_dramatic_plan(data)
        self.assertAlmostEqual(plan['parts'][0]['cuts'][-1]['end'], 85.55)
        rejected = plan['planner_diagnostics']['part_policy']['rejected_boundaries']
        self.assertTrue(any(r['reason'] == 'immediate_question_answer' for r in rejected))

    def test_consequential_action_is_not_cut_by_ending_label(self):
        endings = [{'time': 55, 'kind': 'cliffhanger', 'confidence': .95, 'evidence': 'Внутри действия'},
                   {'time': 75, 'kind': 'closure', 'confidence': .95, 'evidence': 'Действие завершено',
                    'verification': {'supported': True, 'confidence': .95}}]
        data = source_episode([event('action', 0, 90, 5, units=[{'id': 'physical', 'start': 40, 'end': 75}],
                                    action_units=['physical'], part_endings=endings), event('after', 90, 170, 5)])
        plan = build_dramatic_plan(data)
        self.assertFalse(any(abs(c['end']-55) < .01 for p in plan['parts'][:-1] for c in p['cuts'][-1:]))
        self.assertTrue(any(r['reason'] == 'inside_consequential_action'
                            for r in plan['planner_diagnostics']['part_policy']['rejected_boundaries']))

    def test_short_confirmed_exclusion_is_never_restored_by_close_gap_merging(self):
        data = source_episode([event('mixed', 0, 20, 5,
            selected_ranges=[{'start': 0, 'end': 9.5}, {'start': 10, 'end': 20}],
            excluded_title_units=[{'id': 'title', 'start': 9.5, 'end': 10}])])
        plan = build_dramatic_plan(data)
        self.assertFalse(any(c['start'] < 10 and c['end'] > 9.5 for c in coverage(plan)))
        self.assertAlmostEqual(sum(p['duration'] for p in plan['parts']), 19.5)

    def test_word_at_camera_boundary_is_preserved_at_its_original_timestamps(self):
        words = [{'start': 9.8, 'end': 10.8, 'text': 'Слово.'}]
        data = source_episode([event('camera', 0, 30, 5, selected_ranges=[{'start': 10, 'end': 20}])],
                              transcript={'words': words, 'segments': words})
        data['shots'] = [{'start': 0, 'end': 10}, {'start': 10, 'end': 1440}]
        plan = build_dramatic_plan(data)
        self.assertTrue(any(c['start'] <= 9.8 and c['end'] >= 10.8 for c in coverage(plan)))
        broken = json.loads(json.dumps(plan))
        broken['parts'][0]['cuts'][0]['start'] = 10
        with self.assertRaisesRegex(ValueError, 'ASR-слово'):
            validate_plan(broken, data)

    def test_quota_cannot_remove_immediate_response_when_dependency_is_missing(self):
        speech = [{'start': 8, 'end': 10, 'text': 'Ты поможешь?'},
                  {'start': 10.5, 'end': 13, 'text': 'Да, помогу.'}]
        data = source_episode([event('question', 0, 10, 5), event('reply', 10, 180, 1)],
                              transcript={'words': speech, 'segments': speech})
        for builder in (build_plan, build_dramatic_plan):
            plan = builder(data)
            self.assertIn('reply', plan['selected_event_ids'])
            self.assertTrue(any(c['start'] <= 10.5 and c['end'] >= 13 for c in coverage(plan)))
            self.assertLess(retained_event_seconds(plan, data, 'reply'), 5)
            self.assertTrue(any(b['reason'] == 'immediate_question_response_context'
                                for b in plan['planner_diagnostics']['bridges']))

    def test_selected_response_receives_only_its_short_immediate_question(self):
        speech = [{'start': 8, 'end': 10, 'text': 'Ты поможешь?'},
                  {'start': 10.5, 'end': 13, 'text': 'Да, помогу.'}]
        data = source_episode([event('question', 0, 10, 1), event('reply', 10, 40, 5)],
                              transcript={'words': speech, 'segments': speech})
        plan = build_dramatic_plan(data)
        self.assertIn('question', plan['selected_event_ids'])
        self.assertLessEqual(retained_event_seconds(plan, data, 'question'), 3)
        self.assertTrue(any(c['start'] <= 8 and c['end'] >= 10 for c in coverage(plan)))
