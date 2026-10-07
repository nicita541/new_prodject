"""Fresh recovery, source-only validation and bounded uncertainty regressions."""
import copy
import json
from pathlib import Path
import shutil
import ssl
import unittest
import urllib.error
import uuid

from app.config import TEMP
from app.deepseek import BudgetExceeded, RemoteError
from app.jobs import BusyError
from app.pipeline_diagnostics import Diagnostics
from app.scene_understanding import (CONFIDENCE_FIELDS, RECOVERY_PROMPT, UNCERTAINTY_REASONS,
    minimal_safe_ranges, recover_chunk, recovery_trigger, understanding_schema, validate_understanding)


def response(**changes):
    return {'summary': 'Герой передаёт ключ.', 'kind': 'story', 'importance': 4, 'uncertain': False,
            'semantic_confidence': .94, 'visual_confidence': .96, 'context_confidence': .95,
            'uncertainty_reasons': [], 'keep_units': ['action'], 'action_units': ['action'],
            'narrative_bridge': True,
            'state_before': {'locations': ['комната'], 'character_state': 'герой держит ключ', 'objects': ['ключ']},
            'state_after': {'locations': ['комната'], 'character_state': 'девушка держит ключ', 'objects': ['ключ'],
                            'relationship': 'герой помогает девушке', 'topic': 'передача ключа'}, **changes}


def source_event(end=60):
    return {'id': 'event_0001', 'scene_id': 'scene_0001', 'chunk_id': 'scene_0001_chunk_000',
            'start': 0, 'end': end, 'summary': 'Герои только разговаривают.',
            'kind': 'story', 'importance': 4, 'uncertain': True, 'focus': []}


def units(end=60):
    return [{'id': 'before', 'start': 0, 'end': 22, 'text': 'разговор'},
            {'id': 'action', 'start': 22, 'end': 26, 'text': ''},
            {'id': 'after', 'start': 26, 'end': end, 'text': 'разговор'}]


class Vision:
    model = 'mock-local-model'

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def query(self, prompt, image, **options):
        self.calls.append({'prompt': prompt, 'images': image, **options})
        if isinstance(self.answer, BaseException):
            raise self.answer
        return copy.deepcopy(self.answer)


class UnderstandingValidationTests(unittest.TestCase):
    def test_schema_requires_confidence_and_current_evidence_fields(self):
        schema = understanding_schema(units())
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        for field in CONFIDENCE_FIELDS:
            self.assertEqual(schema['properties'][field], {'type': 'number', 'minimum': 0, 'maximum': 1})
        for field in ('keep_units', 'action_units'):
            self.assertEqual(schema['properties'][field]['items']['enum'], ['before', 'action', 'after'])
        self.assertEqual(schema['properties']['uncertainty_reasons']['items']['enum'], list(UNCERTAINTY_REASONS))
        self.assertFalse(schema['properties']['state_before']['additionalProperties'])

    def test_confidence_uses_weakest_dimension_and_exact_thresholds(self):
        for confidence, status in ((.85, 'accepted'), (.6, 'needs_review'), (.599, 'recovery_required')):
            with self.subTest(confidence=confidence):
                event = validate_understanding(response(context_confidence=confidence), source_event(), units())
                self.assertEqual(event['confidence'], confidence)
                self.assertEqual(event['confidence_status'], status)
                self.assertEqual(bool(recovery_trigger(event)), confidence < .85)

    def test_legacy_missing_confidence_is_unknown_and_cannot_be_accepted(self):
        legacy = {'summary': 'Разговор.', 'kind': 'story', 'importance': 3, 'uncertain': False,
                  'keep_units': ['before']}
        event = validate_understanding(legacy, source_event(), units())
        self.assertFalse(event['confidence_known'])
        self.assertEqual(event['confidence'], 0)
        self.assertTrue(event['uncertain'])
        self.assertEqual(event['confidence_status'], 'recovery_required')
        self.assertIn('invalid_json', recovery_trigger(event))
        self.assertEqual(event['local_summary'], 'Разговор.')
        self.assertEqual(event['final_summary'], 'Разговор.')
        self.assertEqual(event['summary_source'], 'local')

    def test_invalid_confidence_bool_nan_inf_string_or_out_of_range_is_rejected(self):
        for field in CONFIDENCE_FIELDS:
            for value in (True, False, float('nan'), float('inf'), '-.1', .99 + .02, -.01):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        validate_understanding(response(**{field: value}), source_event(), units())
        event = validate_understanding(response(visual_confidence=None), source_event(), units())
        self.assertFalse(event['confidence_known'])
        self.assertTrue(recovery_trigger(event))

    def test_invalid_scalar_state_reason_or_foreign_source_id_is_rejected(self):
        malformed = [{'uncertain': 'false'}, {'narrative_bridge': 'false'}, {'importance': True},
                     {'importance': 3.0}, {'kind': 'invented'}, {'summary': ''}, {'summary': 9},
                     {'summary': 'x'*1501}, {'keep_units': ['next_scene_unit']},
                     {'action_units': ['next_scene_unit']}, {'action_units': ['action', 'action']},
                     {'keep_units': 'action'}, {'uncertainty_reasons': ['invented']},
                     {'state_before': {'locations': ['x'*121]}},
                     {'state_after': {'character_state': {'hero': 'bound'}}},
                     {'state_after': {'topic': 'x'*301}}, {'state_before': {'invented': 'state'}}]
        for changes in malformed:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    validate_understanding(response(**changes), source_event(), units())
        outside = [*units(), {'id': 'foreign', 'start': 60, 'end': 80}]
        with self.assertRaises(ValueError):
            validate_understanding(response(keep_units=['foreign']), source_event(), outside)

    def test_explicit_uncertainty_and_reason_trigger_even_high_confidence(self):
        event = validate_understanding(response(uncertain=True, uncertainty_reasons=['missing_context']), source_event(), units())
        self.assertEqual(event['confidence_status'], 'accepted')
        self.assertEqual(event['understanding_status'], 'needs_review')
        self.assertEqual(recovery_trigger(event), ['uncertain', 'missing_context'])


class MinimalSafeRangeTests(unittest.TestCase):
    def test_d_uncertain_long_scene_retains_only_speech_action_and_endpoint_context(self):
        event = source_event(180)
        event.update(action_units=['action'], narrative_bridge=True)
        transcript = {'words': [{'start': 60, 'end': 61, 'text': 'Да.'}],
                      'segments': [{'start': 0, 'end': 180, 'text': 'oversized ASR container'}]}
        selected = minimal_safe_ranges(event, units(180), transcript)
        self.assertEqual(selected['selected_ranges'], [{'start': 0, 'end': 1.5}, {'start': 22, 'end': 26},
            {'start': 59.85, 'end': 61.15}, {'start': 178.5, 'end': 180}])
        self.assertEqual(selected['unit_selection_version'], 1)
        self.assertFalse(selected['whole_scene_last_resort'])
        self.assertIn('potential_transition', selected['fallback_reasons'])

    def test_long_unit_with_one_second_of_speech_is_not_kept_whole(self):
        for end in (60, 180):
            with self.subTest(end=end):
                selected = minimal_safe_ranges(source_event(end), [{'id': 'long', 'start': 0, 'end': end, 'text': 'Да.'}],
                    {'words': [{'start': 30, 'end': 31, 'text': 'Да.'}], 'segments': []})
                self.assertLess(sum(item['end']-item['start'] for item in selected['selected_ranges']), 5)
                self.assertFalse(selected['whole_scene_last_resort'])

    def test_speech_handles_and_state_glimpses_never_cut_known_words(self):
        transcript = {'words': [{'start': 1.4, 'end': 2.8, 'text': 'длинное'},
                                {'start': 20, 'end': 21.1, 'text': 'два'}, {'start': 21.2, 'end': 22, 'text': 'слова'}],
                      'segments': []}
        selected = minimal_safe_ranges(source_event(), [], transcript)
        self.assertEqual(selected['selected_ranges'][0], {'start': 0, 'end': 2.9499999999999997})
        for item in selected['selected_ranges']:
            for word in transcript['words']:
                self.assertFalse(word['start'] < item['start'] < word['end'])
                self.assertFalse(word['start'] < item['end'] < word['end'])

    def test_confirmed_long_action_preserves_its_cause_middle_and_result(self):
        event = {**source_event(180), 'action_units': ['action']}
        selected = minimal_safe_ranges(event, [{'id': 'action', 'start': 60, 'end': 90}], {'words': [], 'segments': []})
        self.assertEqual(selected['selected_ranges'], [{'start': 0, 'end': 1.5}, {'start': 60, 'end': 90},
                                                      {'start': 178.5, 'end': 180}])
        self.assertIn('obvious_action', selected['fallback_reasons'])
        self.assertFalse(selected['whole_scene_last_resort'])

    def test_indivisible_word_covering_scene_is_explicit_last_resort(self):
        selected = minimal_safe_ranges(source_event(180), [],
            {'words': [{'start': 0, 'end': 180, 'text': 'single indivisible ASR word'}], 'segments': []})
        self.assertEqual(selected['selected_ranges'], [{'start': 0, 'end': 180}])
        self.assertTrue(selected['whole_scene_last_resort'])
        self.assertIn('indivisible_word', selected['fallback_reasons'])

    def test_without_words_factual_short_asr_segment_remains_intact(self):
        selected = minimal_safe_ranges(source_event(), [],
            {'words': [], 'segments': [{'start': 10, 'end': 13, 'text': 'Важная реплика.'}]})
        self.assertIn({'start': 9.85, 'end': 13.15}, selected['selected_ranges'])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = TEMP / ('scene-understanding-test-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.diagnostics = Diagnostics(self.root)
        self.transcript = {'words': [{'start': 10, 'end': 11, 'text': 'Сейчас.'}], 'segments': []}
        self.payload = {
            'PREVIOUS SCENE': {'role': 'context_only', 'scene_id': 'scene_0000',
                               'transcript': [{'text': 'Я не уверен, что справлюсь.'}]},
            'CURRENT SCENE': {'role': 'analyse', 'scene_id': 'scene_0001', 'start': 0, 'end': 60, 'units': units()},
            'NEXT SCENE': {'role': 'context_only', 'scene_id': 'scene_0002',
                          'transcript': [{'text': 'Хинако, что ты тут делаешь?'}]},
            'image_order': ['CURRENT', 'CURRENT', 'PREVIOUS CONTEXT ONLY', 'NEXT CONTEXT ONLY']}
        self.images = [Path('current-dense-1.jpg'), Path('current-dense-2.jpg'), Path('previous.jpg'), Path('next.jpg')]
        self.initial = validate_understanding(response(summary='Герои только разговаривают.', uncertain=True,
            semantic_confidence=.54, uncertainty_reasons=['transition_unclear'], action_units=[]), source_event(), units())

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(TEMP.resolve()))
        shutil.rmtree(self.root)

    def records(self):
        path = self.diagnostics.path / 'scene_recovery.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_b_uncertain_scene_runs_fresh_recovery_with_dense_evidence(self):
        vision = Vision(response())
        recover_chunk(vision, self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        self.assertEqual(len(vision.calls), 1)
        call = vision.calls[0]
        self.assertEqual(call['images'], self.images)
        self.assertTrue(call['prompt'].startswith(RECOVERY_PROMPT))
        self.assertIn('not a decision to confirm', call['prompt'])
        self.assertEqual(call['schema'], understanding_schema(units()))

    def test_c_success_replaces_wrong_local_summary_and_clears_initial_uncertainty(self):
        saved = copy.deepcopy(self.initial)
        event = recover_chunk(Vision(response()), self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        self.assertEqual(self.initial, saved)
        self.assertFalse(event['uncertain'])
        self.assertEqual(event['understanding_status'], 'accepted')
        self.assertEqual(event['uncertainty_reasons'], [])
        self.assertEqual(event['local_summary'], 'Герои только разговаривают.')
        self.assertEqual(event['recovery_summary'], 'Герой передаёт ключ.')
        self.assertEqual(event['final_summary'], event['recovery_summary'])
        self.assertEqual(event['summary_source'], 'recovery')
        self.assertEqual(event['selected_ranges'], [{'start': 22, 'end': 26}])
        self.assertEqual(event['unit_selection_version'], 1)
        self.assertEqual([item['source'] for item in event['understanding_history']], ['local', 'recovery'])
        self.assertEqual(self.records()[0]['action_units'], ['action'])
        self.assertTrue(self.records()[0]['changed'])

    def test_d_unresolved_recovery_ignores_keep_all_and_preserves_bounded_source(self):
        event = recover_chunk(Vision(response(uncertain=True, semantic_confidence=.59,
            uncertainty_reasons=['visual_ambiguity'], keep_units=['before', 'action', 'after'])),
            self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        self.assertTrue(event['uncertain'])
        self.assertEqual(event['understanding_status'], 'unresolved')
        self.assertEqual(event['fallback'], 'minimal_safe_context')
        self.assertLess(sum(item['end']-item['start'] for item in event['selected_ranges']), 10)
        self.assertNotIn('transition_unclear', event['uncertainty_reasons'])
        self.assertEqual(event['summary_source'], 'recovery')
        self.assertEqual(self.records()[0]['keep_units'], ['before', 'action', 'after'])

    def test_obvious_action_is_retained_even_if_missing_from_keep_units(self):
        event = recover_chunk(Vision(response(keep_units=[])), self.initial, units(), self.transcript,
                              self.payload, self.images, self.diagnostics)
        self.assertEqual(event['understanding_status'], 'accepted')
        self.assertEqual(event['selected_ranges'], [{'start': 22, 'end': 26}])

    def test_empty_important_story_selection_uses_bounded_fallback(self):
        event = recover_chunk(Vision(response(keep_units=[], action_units=[])), self.initial, units(), self.transcript,
                              self.payload, self.images, self.diagnostics)
        self.assertEqual(event['understanding_status'], 'unresolved')
        self.assertTrue(event['selected_ranges'])
        self.assertEqual(event['selection_reason'], 'important_story_without_source_selection')
        self.assertLess(sum(item['end']-item['start'] for item in event['selected_ranges']), 7)

    def test_e_neighbors_are_context_and_foreign_selection_is_rejected(self):
        vision = Vision(response(keep_units=['next_scene_unit']))
        event = recover_chunk(vision, self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        sent = json.loads(vision.calls[0]['prompt'][len(RECOVERY_PROMPT)+1:])
        self.assertEqual(sent['PREVIOUS SCENE']['transcript'][0]['text'], 'Я не уверен, что справлюсь.')
        self.assertEqual(sent['NEXT SCENE']['transcript'][0]['text'], 'Хинако, что ты тут делаешь?')
        self.assertEqual(sent['initial_analysis']['uncertainty_reasons'], ['transition_unclear'])
        self.assertEqual(event['summary_source'], 'local')
        self.assertEqual(event['understanding_status'], 'unresolved')
        self.assertEqual(self.records()[0]['reason'], 'invalid_json')

    def test_quality_model_failures_are_logged_and_use_minimal_fallback(self):
        failures = [(RuntimeError('local inference failed'), 'model_failure'), (ValueError('bad JSON'), 'invalid_json'),
                    (urllib.error.URLError('local model disconnected'), 'model_failure'), (TimeoutError('timeout'), 'model_failure')]
        for error, reason in failures:
            with self.subTest(error=error):
                vision = Vision(error)
                event = recover_chunk(vision, self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
                self.assertEqual(len(vision.calls), 1)
                self.assertEqual(event['understanding_status'], 'unresolved')
                self.assertEqual(event['local_summary'], self.initial['local_summary'])
                self.assertIsNone(event['recovery_summary'])
                self.assertIn(reason, event['uncertainty_reasons'])
                self.assertLess(sum(item['end']-item['start'] for item in event['selected_ranges']), 7)
                self.assertEqual(self.records()[-1]['reason'], reason)
                self.assertEqual(self.records()[-1]['error_type'], type(error).__name__)

    def test_cancellation_budget_busy_remote_auth_and_tls_are_never_fallback(self):
        errors = [InterruptedError('cancelled'), BudgetExceeded('budget'), BusyError('busy'),
                  RemoteError('provider auth failure', category='authentication'), ssl.SSLError('certificate failed'),
                  urllib.error.URLError(ssl.SSLError('TLS failed')),
                  urllib.error.HTTPError('https://model.invalid', 401, 'unauthorized', {}, None)]
        wrapped = RuntimeError('wrapped TLS')
        wrapped.__cause__ = ssl.SSLError('certificate failed')
        errors.append(wrapped)
        for error in errors:
            with self.subTest(error=error):
                with self.assertRaises(type(error)):
                    recover_chunk(Vision(error), self.initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        self.assertEqual(self.records(), [])

    def test_accepted_scene_makes_no_recovery_request(self):
        initial = validate_understanding(response(), source_event(), units())
        vision = Vision(RuntimeError('must not run'))
        recovered = recover_chunk(vision, initial, units(), self.transcript, self.payload, self.images, self.diagnostics)
        self.assertEqual(recovered, initial)
        self.assertIsNot(recovered, initial)
        self.assertEqual(vision.calls, [])
        self.assertEqual(self.records(), [])


if __name__ == '__main__':
    unittest.main()
