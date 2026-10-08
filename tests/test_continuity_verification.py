"""Authored API mechanisms with mocked source boards, not VLM quality tests."""
import copy
import json
from pathlib import Path
import shutil
import ssl
import unittest
import urllib.error
import uuid
from unittest.mock import patch

from PIL import Image

from app import continuity_verification as verification
from app.config import TEMP
from app.deepseek import BudgetExceeded, RemoteError
from app.jobs import BusyError
from app.media_probe import atomic_json, load_json
from app.source_continuity import resolve_source_continuity
from app.source_roles import merge_ranges
from tests.test_selection_adjudication import answer as selection_answer
from tests.test_source_continuity import chain, span


EMPTY = {'words': [], 'segments': []}


def decision(refs=None, **fields):
    refs = [] if refs is None else refs
    return {'resolved': True, 'coherent_without_bridges': not bool(refs),
            'bridge_refs': copy.deepcopy(refs), 'left_frame_indices': [1], 'right_frame_indices': [1],
            'evidence': 'В исходных BEFORE и AFTER видна конкретная смена состояния рук персонажа.',
            'confidence': .95, **fields}


class FakeVision:
    supports_image_pages = True
    model = 'authored-continuity-mechanism-model'
    projector = 'authored-projector'
    cache_profile = {'version': 1}

    def __init__(self, selection=None, continuity=None, failure=None):
        self.selection, self.continuity, self.failure = selection, continuity, failure
        self.requests = []
        self.tokens = lambda prompt: len(prompt)//4

    def token_count(self, prompt):
        return self.tokens(prompt)

    def query(self, prompt, image, max_tokens=None, schema=None):
        payload = json.JSONDecoder().raw_decode('{'+prompt.split('\n{', 1)[1])[0]
        stage = 'selection' if 'CURRENT' in payload else 'continuity'
        self.requests.append({'stage': stage, 'payload': payload, 'images': image,
                              'prompt': prompt, 'max_tokens': max_tokens, 'schema': schema})
        if self.failure and self.failure[0] == stage:
            raise self.failure[1]
        if stage == 'selection':
            if self.selection:
                return self.selection(payload)
            return selection_answer(payload, keep=[u['id'] for u in payload['CURRENT']['units']])
        if self.continuity:
            return self.continuity(payload)
        return decision([row['ref'] for row in payload['CURRENT_CANDIDATES']])


class ValidateContinuityTests(unittest.TestCase):
    def setUp(self):
        self.refs = [{'event': 'one', 'unit': 'u0'}, {'event': 'two', 'unit': 'u1'}]

    def validate(self, raw):
        return verification.validate_continuity(raw, self.refs, 2, 3)

    def test_exact_scoped_refs_accept_and_output_does_not_alias_input(self):
        raw = decision([self.refs[0]])
        before = copy.deepcopy(raw)
        accepted = self.validate(raw)
        self.assertTrue(accepted['accepted'])
        accepted['bridge_refs'][0]['event'] = 'changed'
        self.assertEqual(raw, before)

    def test_unknown_cartesian_ref_repeated_ref_and_extra_ref_fields_are_rejected(self):
        bad = [[{'event': 'one', 'unit': 'u1'}], [self.refs[0], self.refs[0]],
               [{'event': 'foreign', 'unit': 'u0'}], [{**self.refs[0], 'time': 2}], ['u0']]
        for refs in bad:
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.validate(decision(refs))

    def test_both_original_endpoint_boards_need_unique_in_bounds_integer_indices(self):
        for key in ('left_frame_indices', 'right_frame_indices'):
            for indices in ([], [999], [0], [True], [1.0], [1, 1], '1'):
                with self.subTest(key=key, indices=indices), self.assertRaises(ValueError):
                    self.validate(decision(**{key: indices}))

    def test_finite_confidence_is_separate_from_resolved_and_has_point_nine_threshold(self):
        for value in (float('nan'), float('inf'), True, '0.95', -1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(decision(confidence=value))
        self.assertFalse(self.validate(decision(confidence=.89))['accepted'])
        self.assertTrue(self.validate(decision(confidence=.9))['accepted'])
        self.assertFalse(self.validate(decision(resolved=False))['accepted'])

    def test_strict_fields_boolean_types_and_bridge_necessity_are_required(self):
        for raw in (decision(start=0), {k: v for k, v in decision().items() if k != 'resolved'},
                    decision(resolved=1), decision(coherent_without_bridges=1),
                    decision(coherent_without_bridges=False), decision([self.refs[0]], coherent_without_bridges=True),
                    decision(evidence=''), decision(evidence='Кадр'), decision(evidence='x'*1501)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.validate(raw)


class OmittedContinuityMechanismTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP/('continuity-verification-mechanism-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.source = self.job/'source.mp4'
        self.source.write_bytes(b'authored-mechanism-source-with-mocked-frames')
        self.parent = chain()
        self.parent['unit_evidence'][1]['decision'] = 'drop'
        self.events = [self.parent]
        self.selected = ['room']
        self.transition = resolve_source_continuity(self.events, self.selected, EMPTY, 16)['warnings'][0]
        self.boards = []
        self.inspect = patch('app.selection_adjudication.inspect_media', return_value={
            'streams': [{'codec_type': 'video', 'start_time': '0', 'duration': '16'}]})
        self.board_patch = patch('app.selection_adjudication.storyboard', side_effect=self.board)
        self.inspect.start(); self.board_patch.start()

    def tearDown(self):
        self.inspect.stop(); self.board_patch.stop()
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    def board(self, source, start, end, destination, cancelled, *, times=None, context=False):
        self.assertEqual(Path(source), self.source)
        self.assertTrue(0 <= start < end <= 16)
        Image.new('RGB', (96, 54), 'white').save(destination)
        points = times if times is not None else [start+(end-start)*p for p in (.25, .75)]
        self.boards.append({'start': start, 'end': end, 'times': points, 'context': context})
        atomic_json(destination.with_suffix('.storyboard.json'), {'pages': [str(destination)],
            'frames': [{'time': t, 'reasons': ['authored_source_frame_mock'], 'unit_ids': []} for t in points]})
        return points

    def verify(self, vision=None, cancelled=lambda: False, events=None):
        return verification.verify_omitted_continuity(self.source, self.events if events is None else events,
            self.selected, EMPTY, [], self.transition, self.job, vision or FakeVision(), cancelled)

    def test_real_adjudicator_inspects_dropped_unit_in_retained_parent_and_restores_exact_source(self):
        before = copy.deepcopy((self.events, self.selected, self.transition))
        vision = FakeVision()
        with patch('app.continuity_verification.adjudicate_event', wraps=verification.adjudicate_event) as real_call:
            result, audit = self.verify(vision)
        self.assertEqual(real_call.call_count, 1)
        window = real_call.call_args.args[1]
        self.assertEqual((window['start'], window['end']), (4, 12))
        self.assertEqual([u['id'] for u in window['units']], ['u1'])
        self.assertEqual(window['selected_ranges'], [])
        self.assertEqual(window['unit_evidence'], [])
        self.assertEqual(audit['status'], 'accepted')
        self.assertEqual(audit['restored_refs'], [{'event': 'room', 'unit': 'u1'}])
        self.assertEqual(result[0]['selected_ranges'], [span(0, 16)])
        proof = next(p for p in result[0]['unit_evidence'] if p['unit'] == 'u1')
        self.assertEqual(proof['decision'], 'keep')
        self.assertTrue(proof['frame_count'] > 1)
        self.assertTrue(all(4 <= t < 12 for t in proof['frame_times']))
        self.assertTrue(result[0]['mandatory_continuity_units'])
        self.assertEqual((self.events, self.selected, self.transition), before)
        self.assertTrue(all('_continuity_selected' not in e for e in result))
        current = [r for r in vision.requests if r['stage'] == 'selection']
        final = [r for r in vision.requests if r['stage'] == 'continuity']
        self.assertGreaterEqual(len(current), 1)
        self.assertEqual(merge_ranges([span(r['payload']['CURRENT']['start'], r['payload']['CURRENT']['end'])
                                      for r in current]), [span(4, 12)])
        self.assertTrue(all([u['id'] for u in r['payload']['CURRENT']['units']] == ['u1'] for r in current))
        self.assertEqual(len(final), 1)
        self.assertTrue(all(2 <= f['time'] < 4 for f in final[0]['payload']['BEFORE']['frames']))
        self.assertTrue(all(12 <= f['time'] < 14 for f in final[0]['payload']['AFTER']['frames']))
        self.assertEqual(final[0]['max_tokens'], verification.POLICY['output_tokens'])
        self.assertTrue(all(b['end']-b['start'] <= 2 for b in self.boards if b['context']))

    def test_successful_cached_proof_is_revalidated_and_avoids_repeat_model_calls(self):
        vision = FakeVision()
        result, audit = self.verify(vision)
        count = len(vision.requests)
        with patch('app.continuity_verification.validate_continuity', wraps=verification.validate_continuity) as validate:
            cached, cached_audit = self.verify(vision)
        self.assertGreaterEqual(validate.call_count, 1)
        self.assertEqual(len(vision.requests), count)
        self.assertEqual(cached, result)
        self.assertEqual(cached_audit['checkpoint'], audit['checkpoint'])
        self.assertEqual(cached_audit['status'], 'accepted')

    def test_invalid_cached_endpoint_index_rebuilds_instead_of_granting_omission_authority(self):
        vision = FakeVision()
        _, audit = self.verify(vision)
        checkpoint = Path(audit['checkpoint'])
        raw = load_json(checkpoint)
        raw['decision']['left_frame_indices'] = [999]
        atomic_json(checkpoint, raw)
        result, rebuilt = self.verify(vision)
        self.assertEqual(rebuilt['status'], 'accepted')
        self.assertEqual(len([r for r in vision.requests if r['stage'] == 'continuity']), 2)
        self.assertEqual(load_json(checkpoint)['decision']['left_frame_indices'], [1])
        self.assertEqual(result[0]['selected_ranges'], [span(0, 16)])

    def test_neutral_dropped_unit_is_never_retained_after_original_inspection(self):
        vision = FakeVision(selection=lambda p: selection_answer(p, keep=[]))
        result, audit = self.verify(vision)
        self.assertEqual(result[0]['selected_ranges'], self.parent['selected_ranges'])
        self.assertEqual(audit['restored_refs'], [])
        self.assertEqual([r for r in vision.requests if r['stage'] == 'continuity'][0]['payload']['CURRENT_CANDIDATES'], [])
        self.assertGreaterEqual(len([r for r in vision.requests if r['stage'] == 'selection']), 1)

    def test_unaccepted_original_proof_cannot_be_selected_as_bridge(self):
        vision = FakeVision(selection=lambda p: selection_answer(p, keep=['u1'], selection_confidence=.4))
        result, audit = self.verify(vision)
        self.assertEqual(result[0]['selected_ranges'], self.parent['selected_ranges'])
        self.assertEqual(audit['restored_refs'], [])
        self.assertEqual([r for r in vision.requests if r['stage'] == 'continuity'][0]['payload']['CURRENT_CANDIDATES'], [])

    def test_confirmed_excluded_gap_unit_is_not_inspected_or_restored(self):
        events = copy.deepcopy(self.events)
        events[0]['excluded_credit_ranges'] = [span(4, 12)]
        vision = FakeVision()
        result, audit = self.verify(vision, events=events)
        self.assertEqual(result[0]['selected_ranges'], self.parent['selected_ranges'])
        self.assertEqual(audit['restored_refs'], [])
        self.assertEqual([r for r in vision.requests if r['stage'] == 'selection'], [])

    def test_endpoint_confidence_cannot_bypass_independent_current_proof(self):
        def forged(payload):
            return decision([{'event': 'room', 'unit': 'u1'}])
        vision = FakeVision(selection=lambda p: selection_answer(p, keep=[]), continuity=forged)
        result, audit = self.verify(vision)
        self.assertEqual(audit['status'], 'unresolved')
        self.assertEqual(result[0]['selected_ranges'], self.parent['selected_ranges'])
        self.assertEqual(audit['restored_refs'], [])

    def test_controls_from_source_adjudication_or_endpoint_query_propagate(self):
        errors = [BudgetExceeded('mechanism budget'), RemoteError('mechanism remote'), BusyError('mechanism busy'),
                  ssl.SSLError('mechanism TLS'), InterruptedError('mechanism cancel'),
                  urllib.error.HTTPError('https://invalid.example', 401, 'mechanism auth', {}, None)]
        wrapped = RuntimeError('mechanism wrapped TLS')
        wrapped.__cause__ = ssl.SSLError('mechanism nested TLS')
        errors.append(wrapped)
        for stage in ('selection', 'continuity'):
            for error in errors:
                with self.subTest(stage=stage, error=type(error).__name__), self.assertRaises(type(error)):
                    self.verify(FakeVision(failure=(stage, error)))
                # A previous successful CURRENT checkpoint must not bypass the
                # next source-stage failure injection.
                shutil.rmtree(self.job/'selection-adjudication', ignore_errors=True)

    def test_cancellation_before_work_propagates_without_model_call(self):
        vision = FakeVision()
        with self.assertRaises(InterruptedError):
            self.verify(vision, cancelled=lambda: True)
        self.assertEqual(vision.requests, [])

    def test_cancellation_arriving_during_endpoint_query_propagates(self):
        cancellation = {'cancelled': False}
        def response(payload):
            cancellation['cancelled'] = True
            return decision([n['ref'] for n in payload['CURRENT_CANDIDATES']])
        with self.assertRaises(InterruptedError):
            self.verify(FakeVision(continuity=response), cancelled=lambda: cancellation['cancelled'])

    def test_oversized_context_is_unresolved_and_never_submitted_to_endpoint_model(self):
        vision = FakeVision()
        vision.tokens = lambda prompt: verification.POLICY['input_tokens']+1
        result, audit = self.verify(vision)
        self.assertEqual(audit['status'], 'unresolved')
        self.assertEqual(result[0]['selected_ranges'], self.parent['selected_ranges'])
        self.assertEqual([r for r in vision.requests if r['stage'] == 'continuity'], [])


if __name__ == '__main__':
    unittest.main()
