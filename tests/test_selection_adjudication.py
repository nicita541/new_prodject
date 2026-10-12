"""Mechanism tests with a fake adapter; these do not measure VLM quality."""
import copy
import json
import shutil
import ssl
import subprocess
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import FFMPEG, TEMP
from app.deepseek import BudgetExceeded, RemoteError
from app.jobs import BusyError
from app.json_store import analysis_json as atomic_json, load_json
from app.selection_adjudication import (adjudicate_event, issues, minimal_semantic_context,
    validate_adjudication, adjudication_schema, _views)


EMPTY = {'words': [], 'segments': []}
STATE = {'locations': [], 'character_state': '', 'objects': []}


def evidence(unit, frames, kind='physical_action'):
    index = next(i+1 for i, f in enumerate(frames) if unit['start'] <= f['time'] < unit['end'])
    return {'unit': unit['id'], 'kind': kind, 'evidence': 'В CURRENT кадре руки персонажа стягивают видимый ремень.',
            'confidence': .95, 'frame_indices': [index], 'speech_quote': ''}


def answer(payload, keep=None, **changes):
    units, frames = payload['CURRENT']['units'], payload['CURRENT']['frames']
    keep = [u['id'] for u in units if u['id'] != 'c000_u001'] if keep is None else keep
    drop = [u['id'] for u in units if u['id'] not in keep]
    return {'summary': 'В исходных кадрах видно действие и ответную реакцию.', 'resolved': True,
            'understanding_confidence': .95, 'selection_confidence': .95,
            'keep_units': keep, 'drop_units': drop, 'action_units': keep,
            'unit_evidence': [evidence(u, frames, 'physical_action' if u['id'] in keep else 'neutral_scenery') for u in units],
            'causal_links': [], 'state_before': copy.deepcopy(STATE), 'state_after': copy.deepcopy(STATE), **changes}


class FakeVision:
    supports_image_pages = True
    model = 'fake-selection-model'
    projector = 'fake-projector'
    cache_profile = {'version': 1}

    def __init__(self, response=None):
        self.response, self.requests = response, []

    def query(self, prompt, image, max_tokens=None, schema=None):
        payload = json.JSONDecoder().raw_decode('{'+prompt.split('\n{', 1)[1])[0]
        self.requests.append((prompt, image, schema, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response(payload) if callable(self.response) else copy.deepcopy(self.response) if self.response is not None else answer(payload)


class SelectionAdjudicationTests(unittest.TestCase):
    def test_silent_current_cannot_borrow_a_spoken_contribution_from_context(self):
        unit = {'id': 'silent', 'start': 0., 'end': 1., 'text': ''}
        frames = [{'time': .5}]
        payload = {'CURRENT': {'units': [unit], 'frames': frames}}
        raw = answer(payload, keep=['silent'], action_units=[],
            unit_evidence=[evidence(unit, frames, 'causal_dialogue')])
        with self.assertRaisesRegex(ValueError, 'собственную ASR цитату'):
            validate_adjudication(raw, [unit], frames)
        branches = adjudication_schema([unit], frames)['properties']['unit_evidence']['items']['oneOf']
        self.assertNotIn('causal_dialogue', branches[0]['properties']['kind']['enum'])
        self.assertNotIn('response', branches[0]['properties']['kind']['enum'])
        raw['unit_evidence'][0]['kind'] = 'character_reaction'
        self.assertTrue(validate_adjudication(raw, [unit], frames)['accepted'])

    def setUp(self):
        self.job = TEMP/('selection-adjudication-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.source = self.job/'source.mp4'
        self.source.write_bytes(b'mechanism-test-source')
        self.event = {'id': 'event0', 'start': 0., 'end': 12., 'summary': 'Неуверенное старое описание.',
            'importance': 5, 'kind': 'story', 'uncertain': True, 'selection_uncertain': True,
            'selected_ranges': [{'start': 0., 'end': 12.}],
            'units': [{'id': f'c000_u{i:03d}', 'start': float(i*4), 'end': float((i+1)*4), 'text': ''} for i in range(3)]}
        self.inspect = patch('app.selection_adjudication.inspect_media', return_value={
            'streams': [{'codec_type': 'video', 'start_time': '0', 'duration': '12'}]})
        self.storyboard = patch('app.selection_adjudication.storyboard', side_effect=self.board)
        self.inspect.start()
        self.storyboard.start()

    def tearDown(self):
        self.inspect.stop()
        self.storyboard.stop()
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    def board(self, source, start, end, destination, cancelled, *, times=None, context=False):
        Image.new('RGB', (96, 54), 'white').save(destination)
        if times is None:
            times = [start+(end-start)*fraction for fraction in (.25,.75)]
        atomic_json(destination.with_suffix('.storyboard.json'), {'pages': [str(destination)],
            'frames': [{'time': t, 'reasons': ['recovery_dense_sample'], 'unit_ids': []} for t in times]})
        return times

    def adjudicate(self, vision=None, event=None, transcript=None, cancelled=lambda: False, questions=None):
        return adjudicate_event(self.source, event or self.event, transcript or EMPTY, [], self.job,
            vision or FakeVision(), cancelled, questions)

    def positive_event(self):
        event = copy.deepcopy(self.event)
        event['unit_evidence'] = [{'unit': 'c000_u000', 'kind': 'physical_action',
            'evidence': 'В исходном кадре персонаж надевает видимый ремень на запястья.',
            'confidence': .95, 'frame_indices': [1], 'speech_quote': '', 'decision': 'keep'}]
        return event

    def test_confident_partition_replaces_selection_and_preserves_input(self):
        snapshot = copy.deepcopy(self.event)
        vision = FakeVision()
        result = self.adjudicate(vision)
        self.assertEqual(self.event, snapshot)
        self.assertEqual(result['selected_ranges'], [{'start': 0., 'end': 4.}, {'start': 8., 'end': 12.}])
        self.assertEqual(result['selection_status'], 'accepted')
        self.assertFalse(result['analysis_unresolved'])
        self.assertEqual(result['drop_units'], ['c000_u001'])
        self.assertEqual([u['id'] for u in result['units']], [u['id'] for u in self.event['units']])
        self.assertEqual(result['action_units'], ['c000_u000', 'c000_u002'])
        self.assertEqual(result['summary_source'], 'targeted_adjudication')
        self.assertEqual(result['summary'], result['final_summary'])
        self.assertEqual(result['confidence'], .95)
        self.assertEqual(result['confidence_status'], 'accepted')
        self.assertTrue(result['confidence_known'])
        self.assertEqual(result['uncertainty_reasons'], [])
        self.assertEqual(len(vision.requests), 3)
        histories = {h['checkpoint']: h for h in result['selection_adjudication']['decisions']}
        for record in result['unit_evidence']:
            self.assertEqual(record['frame_count'], len(histories[record['checkpoint']]['frame_times']))
            self.assertTrue(all(1 <= index <= record['frame_count'] for index in record['frame_indices']))
        for _, images, _, payload in vision.requests:
            paths = images if isinstance(images, list) else [images]
            self.assertLessEqual(len(paths), 8)
            self.assertTrue(all(Path(p).is_file() for p in paths))
            self.assertLessEqual(payload['CURRENT']['end']-payload['CURRENT']['start'], 10)
            self.assertTrue(all(c['role'].endswith('CONTEXT_ONLY') for c in payload['CONTEXT_ONLY']))

    def test_understanding_does_not_imply_selection_confidence(self):
        result = self.adjudicate(FakeVision(lambda p: answer(p, selection_confidence=.4)), self.positive_event())
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [{'start': 0., 'end': 4.}])
        self.assertEqual(result['selection_adjudication']['understanding_confidence'], .95)

    def test_adjacent_source_speech_outlives_short_visual_context_without_current_ownership(self):
        event={**copy.deepcopy(self.event),'start':8.26,'end':12.,
               'units':[{'id':'reply','start':8.26,'end':12.,'text':''}]}
        transcript={'words':[{'start':.85,'end':3.17,'text':'Где ключ от двери'},
                             {'start':8.26,'end':11.88,'text':'Он под синей чашкой на столе.'}],
                    'segments':[]}
        vision=FakeVision()
        self.adjudicate(vision,event=event,transcript=transcript)
        payload=vision.requests[0][3]
        before=next(c for c in payload['CONTEXT_ASR_ONLY'] if c['role']=='BEFORE_CONTEXT_ONLY')
        self.assertEqual(before['ASR']['words'],[transcript['words'][0]])
        self.assertEqual(payload['CURRENT']['ASR']['words'],[transcript['words'][1]])
        self.assertEqual(payload['CURRENT']['units'][0]['text'],transcript['words'][1]['text'])
        visual=next(c for c in payload['CONTEXT_ONLY'] if c['role']=='BEFORE_CONTEXT_ONLY')
        self.assertTrue(all(6.26<=f['time']<8.26 for f in visual['frames']))
        self.assertEqual(visual['ASR']['words'],[])
        self.assertEqual(len(vision.requests[0][1]),2)

    def test_unresolved_without_positive_evidence_has_no_asr_or_endpoint_keep_all(self):
        transcript = {'words': [{'start': 0., 'end': 12., 'text': 'Длинная реплика'}], 'segments': []}
        result = self.adjudicate(FakeVision(), transcript=transcript)
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [])
        self.assertFalse(result['whole_scene_last_resort'])

    def test_individual_low_confidence_and_explicit_unresolved_gate(self):
        def low(payload):
            raw = answer(payload)
            raw['unit_evidence'][0]['confidence'] = .89
            return raw
        for vision in [FakeVision(low), FakeVision(lambda p: answer(p, resolved=False))]:
            with self.subTest(response=vision.response):
                result = self.adjudicate(vision)
                self.assertTrue(result['analysis_unresolved'])
                self.assertEqual(result['selected_ranges'], [])

    def test_drop_every_unit_does_not_get_restored_by_importance_or_speech(self):
        result = self.adjudicate(FakeVision(lambda p: answer(p, keep=[])))
        self.assertEqual(result['selected_ranges'], [])
        self.assertEqual(result['selection_status'], 'accepted')
        self.assertEqual(result['action_units'], [])
        self.assertTrue(result['selection_empty_verified'])
        self.assertEqual(result['kind'], 'filler')
        self.assertEqual(result['importance'], 1)
        self.assertNotIn('global_omission', result)

    def test_invalid_ids_incomplete_partition_and_generic_evidence_are_rejected(self):
        def mutate(field):
            def response(payload):
                raw = answer(payload)
                if field == 'unknown':
                    raw['keep_units'].append('after_context_unit')
                elif field == 'missing':
                    raw['unit_evidence'].pop()
                elif field == 'duplicate':
                    raw['drop_units'].append(raw['keep_units'][0])
                elif field == 'generic':
                    raw['unit_evidence'][0]['evidence'] = 'generic atmosphere'
                elif field == 'frame':
                    raw['unit_evidence'][0]['frame_indices'] = [999]
                elif field == 'bool':
                    raw['selection_confidence'] = True
                elif field == 'nan':
                    raw['selection_confidence'] = float('nan')
                elif field == 'quote':
                    raw['unit_evidence'][0]['speech_quote'] = 'Выдуманная реплика'
                return raw
            return response
        for field in ('unknown', 'missing', 'duplicate', 'generic', 'frame', 'bool', 'nan', 'quote'):
            with self.subTest(field=field):
                result = self.adjudicate(FakeVision(mutate(field)))
                self.assertTrue(result['analysis_unresolved'])
                self.assertEqual(result['selected_ranges'], [])

    def test_confirmed_exclusions_and_overlapping_words_trim_inward(self):
        event = self.positive_event()
        event['excluded_title_units'] = [{'start': 1., 'end': 2.}]
        transcript = {'words': [{'start': .8, 'end': 1.3, 'text': 'one'},
                               {'start': 1.2, 'end': 2.2, 'text': 'two'}], 'segments': []}
        result = self.adjudicate(FakeVision(), event, transcript)
        self.assertEqual(result['selected_ranges'], [{'start': 0., 'end': .8},
            {'start': 2.2, 'end': 4.}, {'start': 8., 'end': 12.}])
        self.assertEqual(result['excluded_title_units'], event['excluded_title_units'])
        self.assertNotIn('excluded_review_ranges', result)

    def test_no_naked_action_id_or_generic_atmosphere_in_minimal_context(self):
        event = copy.deepcopy(self.event)
        event.update(action_units=['c000_u000'], protected_atmosphere_units=['c000_u001'], narrative_bridge=True)
        result = minimal_semantic_context(event, event['units'], EMPTY)
        self.assertEqual(result['selected_ranges'], [])
        event = self.positive_event()
        event['selected_ranges'] = [{'start': 1., 'end': 2.}]
        self.assertEqual(minimal_semantic_context(event, event['units'], EMPTY)['selected_ranges'], [{'start': 1., 'end': 2.}])

    def test_context_frame_cannot_prove_current_unit_and_neutral_keep_is_invalid(self):
        units = self.event['units'][:2]
        frames = [{'time': 2.}, {'time': 6.}]
        payload = {'CURRENT': {'units': units, 'frames': frames}}
        raw = answer(payload)
        raw['unit_evidence'][0]['frame_indices'] = [2]
        with self.assertRaises(ValueError):
            validate_adjudication(raw, units, frames)
        raw = answer(payload)
        raw['unit_evidence'][0]['kind'] = 'neutral_scenery'
        with self.assertRaises(ValueError):
            validate_adjudication(raw, units, frames)

    def test_positive_contribution_in_dropped_unit_is_a_rejected_contradiction(self):
        from app.selection_adjudication import POSITIVE_KINDS
        units = [{'id': 'u0', 'start': 0., 'end': 4., 'text': 'Дверь закрыта.'}]
        frames = [{'time': 2.}]
        for kind in POSITIVE_KINDS:
            raw = answer({'CURRENT': {'units': units, 'frames': frames}}, keep=[])
            raw['unit_evidence'][0]['kind'] = kind
            if kind in ('causal_dialogue', 'response'):
                raw['unit_evidence'][0]['speech_quote'] = units[0]['text']
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'drop_units'):
                validate_adjudication(raw, units, frames)

    def test_positive_nonstory_drop_requires_whole_unit_exclusion_and_preserves_actual_proof(self):
        units = [{'id': 'u0', 'start': 0., 'end': 4., 'text': ''}]
        frames = [{'time': 2.}]
        raw = answer({'CURRENT': {'units': units, 'frames': frames}}, keep=[])
        raw['unit_evidence'][0]['kind'] = 'physical_action'
        original = copy.deepcopy(raw)
        excluded = [{'start': 0., 'end': 2.}, {'start': 2., 'end': 4.}]
        result = validate_adjudication(raw, units, frames, excluded)
        self.assertTrue(result['accepted'])
        self.assertEqual(raw, original)
        self.assertEqual(result['unit_evidence'][0]['kind'], 'physical_action')
        # The cited act lies in an exclusion, but the unexamined remainder is
        # still CURRENT footage. It cannot justify deleting the whole unit.
        with self.assertRaisesRegex(ValueError, 'drop_units'):
            validate_adjudication(raw, units, frames, [{'start': 0., 'end': 3.5}])

    def test_causal_links_require_distinct_kept_current_ids_and_spoken_contribution_is_not_action(self):
        units = [{'id': 'u0', 'start': 0., 'end': 2., 'text': 'Почему?'},
                 {'id': 'u1', 'start': 2., 'end': 4., 'text': 'Дверь закрыта.'}]
        frames = [{'time': 1.}, {'time': 3.}]
        payload = {'CURRENT': {'units': units, 'frames': frames}}
        raw = answer(payload, keep=['u0', 'u1'])
        link = {'from_unit': 'u0', 'to_unit': 'u1', 'relation': 'response',
                'evidence': 'Ответ объясняет причину исходного вопроса.'}
        raw['causal_links'] = [link]
        self.assertTrue(validate_adjudication(raw, units, frames)['accepted'])
        for target in ('u0', 'outside_current'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_adjudication({**raw, 'causal_links': [{**link, 'to_unit': target}]}, units, frames)
        dropped = answer(payload, keep=['u0'], causal_links=[link])
        with self.assertRaises(ValueError):
            validate_adjudication(dropped, units, frames)
        single = answer({'CURRENT': {'units': units[:1], 'frames': frames[:1]}}, keep=['u0'])
        single['unit_evidence'][0].update(kind='causal_dialogue', speech_quote='Почему?', frame_indices=[])
        with self.assertRaises(ValueError):
            validate_adjudication(single, units[:1], frames[:1])
        single['action_units'] = []
        self.assertTrue(validate_adjudication(single, units[:1], frames[:1])['accepted'])

    def test_control_auth_tls_budget_and_cancel_propagate_even_wrapped(self):
        wrapped = RuntimeError('wrapper')
        wrapped.__cause__ = ssl.SSLError('TLS')
        errors = [BudgetExceeded('budget'), BusyError('busy'), RemoteError('remote'), InterruptedError('cancel'),
                  ssl.SSLError('TLS'), urllib.error.HTTPError('http://test', 401, 'auth', None, None), wrapped]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    self.adjudicate(FakeVision(error))
        with self.assertRaises(InterruptedError):
            self.adjudicate(cancelled=lambda: True)

    def test_noncontrol_model_failure_records_explicit_fallback(self):
        result = self.adjudicate(FakeVision(RuntimeError('invalid model output')), self.positive_event())
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [{'start': 0., 'end': 4.}])
        row = result['selection_adjudication']['decisions'][-1]
        self.assertEqual(row['error_type'], 'RuntimeError')
        self.assertEqual(row['reason'], 'model_or_source_failure')

    def test_same_inputs_cache_reuse_and_prompt_model_asr_source_invalidation(self):
        first = self.adjudicate(FakeVision())
        vision = FakeVision()
        second = self.adjudicate(vision)
        self.assertEqual(first, second)
        self.assertEqual(vision.requests, [])
        with patch('app.selection_adjudication.ADJUDICATION_PROMPT', 'Changed factual prompt.'):
            changed = FakeVision()
            self.adjudicate(changed)
            self.assertEqual(len(changed.requests), 3)
        changed = FakeVision()
        changed.model = 'different-model'
        self.adjudicate(changed)
        self.assertEqual(len(changed.requests), 3)
        transcript = {'words': [{'start': .2, 'end': .6, 'text': 'Факт'}], 'segments': []}
        changed = FakeVision()
        self.adjudicate(changed, transcript=transcript)
        self.assertEqual(len(changed.requests), 3)
        self.source.write_bytes(b'different-source')
        changed = FakeVision()
        self.adjudicate(changed)
        self.assertEqual(len(changed.requests), 3)

    def test_bounded_storyboard_runtime_version_or_policy_invalidates_pages_and_decisions(self):
        from app import bounded_storyboard
        self.adjudicate(FakeVision())
        changes = [patch.object(bounded_storyboard, 'BOUNDED_STORYBOARD_VERSION',
                                bounded_storyboard.BOUNDED_STORYBOARD_VERSION+1),
                   patch.object(bounded_storyboard, 'POLICY',
                                {**bounded_storyboard.POLICY, 'thumbnail_width': 640})]
        for change in changes:
            with self.subTest(change=change), change, \
                    patch('app.selection_adjudication.storyboard', side_effect=self.board) as builder:
                vision = FakeVision()
                result = self.adjudicate(vision)
                self.assertEqual(result['selection_status'], 'accepted')
                self.assertEqual(len(vision.requests), 3)
                self.assertGreater(builder.call_count, 0)
                builder.reset_mock()
                warm = FakeVision()
                self.adjudicate(warm)
                self.assertEqual(warm.requests, [])
                builder.assert_not_called()
                checkpoint = result['selection_adjudication']['decisions'][0]['checkpoint']
                proof = load_json(self.job/'selection-adjudication'/(checkpoint+'.json'))
                self.assertEqual(proof['source_evidence']['storyboard_identity']['version'],
                                 bounded_storyboard.BOUNDED_STORYBOARD_VERSION)
                self.assertEqual(proof['source_evidence']['storyboard_identity']['policy'], bounded_storyboard.POLICY)

    def test_bounded_storyboard_code_change_invalidates_without_manual_version_bump(self):
        from app import bounded_storyboard
        self.adjudicate(FakeVision())
        helper = Path(bounded_storyboard.__file__).resolve()
        read = Path.read_text
        def modified(path, *args, **kwargs):
            text = read(path, *args, **kwargs)
            return text+'\n# Changed extraction implementation.\n' if path.resolve() == helper else text
        with patch.object(Path, 'read_text', modified), \
                patch('app.selection_adjudication.storyboard', side_effect=self.board) as builder:
            vision = FakeVision()
            self.adjudicate(vision)
            self.assertEqual(len(vision.requests), 3)
            self.assertGreater(builder.call_count, 0)

    def test_bounded_storyboard_line_endings_do_not_invalidate_same_code_cache(self):
        from app import bounded_storyboard
        self.adjudicate(FakeVision())
        helper = Path(bounded_storyboard.__file__).resolve()
        read = Path.read_text
        def windows_lines(path, *args, **kwargs):
            text = read(path, *args, **kwargs)
            return text.replace('\n', '\r\n') if path.resolve() == helper else text
        with patch.object(Path, 'read_text', windows_lines), \
                patch('app.selection_adjudication.storyboard', side_effect=self.board) as builder:
            vision = FakeVision()
            self.adjudicate(vision)
            self.assertEqual(vision.requests, [])
            builder.assert_not_called()

    def test_tampered_response_revalidated_and_image_cache_regenerated(self):
        result = self.adjudicate(FakeVision())
        row = result['selection_adjudication']['decisions'][0]
        checkpoint = self.job/'selection-adjudication'/(row['checkpoint']+'.json')
        cached = load_json(checkpoint)
        cached['decision']['keep_units'].append('invalid-unit')
        atomic_json(checkpoint, cached)
        vision = FakeVision()
        self.adjudicate(vision)
        self.assertEqual(len(vision.requests), 1)
        jpg = next((self.job/'selection-adjudication').glob('*.jpg'))
        jpg.unlink()
        vision = FakeVision()
        self.adjudicate(vision)
        self.assertTrue(jpg.exists())

    def test_corrupt_checkpoint_and_source_cache_json_are_rebuilt(self):
        result = self.adjudicate(FakeVision())
        directory = self.job/'selection-adjudication'
        row = result['selection_adjudication']['decisions'][0]
        (directory/(row['checkpoint']+'.json')).write_text('{bad json', encoding='utf-8')
        (directory/'source-identity.json').write_text('{bad json', encoding='utf-8')
        vision = FakeVision()
        new = self.adjudicate(vision)
        self.assertEqual(new['selection_status'], 'accepted')
        self.assertEqual(len(vision.requests), 1)

    def test_failure_audit_redacts_provider_token(self):
        result = self.adjudicate(FakeVision(RuntimeError('Bearer abc.private-token malformed')))
        history = result['selection_adjudication']['decisions']
        self.assertNotIn('abc.private-token', json.dumps(history))
        self.assertIn('[redacted]', history[-1]['error'])

    def test_ownership_unresolved_flag_is_not_cleared_by_selection_acceptance(self):
        event = copy.deepcopy(self.event)
        event['source_role_unresolved'] = True
        result = self.adjudicate(event=event)
        self.assertTrue(result['source_role_unresolved'])
        self.assertEqual(result['selection_status'], 'accepted')

    def test_long_unit_conflicting_views_unresolved_never_whole_scene(self):
        event = copy.deepcopy(self.event)
        event['units'] = [{'id': 'long_unit', 'start': 0., 'end': 12., 'text': ''}]
        def conflict(payload):
            return answer(payload, keep=['long_unit'] if payload['CURRENT']['start'] == 0 else [])
        result = self.adjudicate(FakeVision(conflict), event)
        self.assertEqual(result['selected_ranges'], [])
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selection_adjudication']['decisions'][-1]['reason'], 'conflicting_source_unit_views')

    def test_removed_neutral_views_cannot_truncate_later_verified_reaction_summary(self):
        def response(payload):
            unit=payload['CURRENT']['units'][0]['id']
            keep=[unit] if unit=='c000_u002' else []
            summary='Персонаж отвечает и меняет выражение лица.' if keep else 'Пустая неизменная комната. '*45
            return answer(payload,keep=keep,summary=summary)
        result=self.adjudicate(FakeVision(response))
        self.assertEqual(result['selection_status'],'accepted')
        self.assertEqual(result['summary'],'Персонаж отвечает и меняет выражение лица.')
        self.assertEqual(result['selected_ranges'],[{'start':8.,'end':12.}])

    def test_invalid_source_partition_gets_one_bounded_reinspection_without_answer_repair(self):
        vision=FakeVision()
        def response(payload):
            result=answer(payload)
            if len(vision.requests)==1:
                result['unit_evidence']=[]
            return result
        vision.response=response
        result=self.adjudicate(vision)
        self.assertEqual(result['selection_status'],'accepted')
        self.assertEqual(len(vision.requests),4)
        self.assertIn('previous response failed source validation',vision.requests[1][0])
        self.assertEqual(vision.requests[0][1],vision.requests[1][1])
        self.assertEqual(vision.requests[1][2]['properties']['unit_evidence']['minItems'],1)
        self.assertEqual(result['selected_ranges'],[{'start':0.,'end':4.},{'start':8.,'end':12.}])

    def test_retry_explains_self_dropped_links_and_dialogue_action_contract_without_answer_injection(self):
        event = copy.deepcopy(self.event)
        event.update(end=4., selected_ranges=[{'start': 0., 'end': 4.}],
                     units=[{'id': 'u0', 'start': 0., 'end': 2., 'text': ''},
                            {'id': 'u1', 'start': 2., 'end': 4., 'text': ''}])
        for issue in ('self_link', 'dropped_link', 'dialogue_action'):
            vision = FakeVision()
            vision.model = 'fake-contract-'+issue
            def response(payload):
                raw = answer(payload, keep=['u0'])
                if len(vision.requests) == 1:
                    if issue == 'dialogue_action':
                        raw['unit_evidence'][0]['kind'] = 'causal_dialogue'
                    else:
                        raw['causal_links'] = [{'from_unit': 'u0',
                            'to_unit': 'u0' if issue == 'self_link' else 'u1', 'relation': 'response',
                            'evidence': 'Причинный вклад описан в исходном ответе.'}]
                return raw
            vision.response = response
            with self.subTest(issue=issue):
                result = self.adjudicate(vision, event)
                self.assertEqual(result['selection_status'], 'accepted')
                self.assertEqual(len(vision.requests), 2)
                primary, retry = vision.requests
                self.assertEqual(primary[1], retry[1])
                self.assertEqual(primary[3], retry[3])
                self.assertIn('TWO DIFFERENT kept CURRENT IDs', primary[0])
                self.assertIn('inside one unit', retry[0])
                self.assertIn('not causal_dialogue/response', retry[0])
                self.assertIn('never dropped/context IDs', retry[0])
                self.assertEqual(result['selection_adjudication']['decisions'][0]['decision']['causal_links'], [])

    def test_missing_legacy_units_use_real_candidate_ids_and_causal_partition(self):
        event = copy.deepcopy(self.event)
        event.pop('units')
        transcript = {'words': [{'start': 1., 'end': 2., 'text': 'Почему?'}],
                      'segments': [{'start': 1., 'end': 2., 'text': 'Почему?'}]}
        vision = FakeVision(lambda p: answer(p, keep=[u['id'] for u in p['CURRENT']['units']]))
        result = self.adjudicate(vision, event, transcript)
        self.assertEqual(result['selection_status'], 'accepted')
        units = vision.requests[0][3]['CURRENT']['units']
        self.assertTrue(all(u['id'].startswith('u') for u in units))
        self.assertTrue(all('boundary_reason' in u for u in units))
        self.assertTrue(all(u['text'] in ('', 'Почему?') for u in units))

    def test_specific_questions_and_audit_are_persisted_without_volatile_flags(self):
        event = self.positive_event()
        event['protected_atmosphere_units'] = ['c000_u001']
        self.assertTrue(any('конкретная реакция' in q for q in issues(event)))
        result = self.adjudicate(event=event, questions=['Показывает ли CURRENT видимое действие?'])
        self.assertEqual(result['selection_adjudication']['questions'], ['Показывает ли CURRENT видимое действие?'])
        audit = next((self.job/'selection-adjudication').glob('*.audit.json'))
        self.assertEqual(load_json(audit), result['selection_adjudication'])
        self.assertNotIn('cache_hit', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('protected_atmosphere_units', result)

    def test_accepted_rebuild_clears_review_hints(self):
        event = copy.deepcopy(self.event)
        event.update(selection_needs_adjudication=True, atmosphere_review_units=['c000_u001'],
                     unresolved_omission_units=['c000_u001'])
        result = self.adjudicate(event=event)
        self.assertEqual(result['selection_status'], 'accepted')
        for key in ('selection_needs_adjudication', 'atmosphere_review_units', 'unresolved_omission_units'):
            self.assertNotIn(key, result)

    def test_current_units_do_not_include_prior_model_semantic_answers(self):
        event = copy.deepcopy(self.event)
        for unit in event['units']:
            unit.update(action='injected answer', state_after={'character_state': 'injected'},
                        summary='injected label', protected_atmosphere=True)
        vision = FakeVision()
        self.adjudicate(vision, event)
        for request in vision.requests:
            for unit in request[3]['CURRENT']['units']:
                self.assertEqual(set(unit), {'id', 'start', 'end', 'text', 'boundary_reason','frame_indices'})
                frames = request[3]['CURRENT']['frames']
                expected = [f['index'] for f in frames if unit['start'] <= f['time'] < unit['end']]
                self.assertEqual(unit['frame_indices'],expected)

    def test_generation_schema_limits_each_unit_to_its_actual_current_frames(self):
        frames = [{'time':.5},{'time':3.99},{'time':4},{'time':7.9},{'time':8},{'time':11.9}]
        schema = adjudication_schema(self.event['units'],frames)
        branches = schema['properties']['unit_evidence']['items']['oneOf']
        for unit,branch,allowed in zip(self.event['units'],branches,([1,2],[3,4],[5,6])):
            self.assertEqual(branch['properties']['unit']['enum'],[unit['id']])
            self.assertEqual(branch['properties']['frame_indices']['items']['enum'],allowed)
        # These domains are measured source geometry, not prescribed keep/drop,
        # action, quote or semantic decisions.
        self.assertEqual(schema['properties']['keep_units']['items']['enum'],[u['id'] for u in self.event['units']])

    def test_source_mutated_during_query_is_unresolved(self):
        def mutate(payload):
            self.source.write_bytes(b'changed-during-query')
            return answer(payload)
        result = self.adjudicate(FakeVision(mutate))
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [])

    def test_partial_unit_input_cannot_silently_drop_unexamined_source(self):
        event = copy.deepcopy(self.event)
        event['units'].pop(1)
        vision = FakeVision()
        result = self.adjudicate(vision, event)
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [])
        self.assertEqual(vision.requests, [])

    def test_malformed_prior_positive_quote_and_view_bounds_do_not_restore_material(self):
        event = self.positive_event()
        event['unit_evidence'][0].update(frame_indices=[], speech_quote='Несуществующая реплика')
        self.assertEqual(minimal_semantic_context(event, event['units'], EMPTY)['selected_ranges'], [])
        event = self.positive_event()
        event['unit_evidence'][0]['view_start'] = 'foreign_timestamp'
        self.assertEqual(minimal_semantic_context(event, event['units'], EMPTY)['selected_ranges'], [])

    def test_missing_required_state_fields_is_not_accepted_from_cache_or_adapter(self):
        result = self.adjudicate(FakeVision(lambda p: answer(p, state_before={})))
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [])

    def test_speech_alone_cannot_prove_visible_action_or_reaction(self):
        units = [{'id': 'u0', 'start': 0., 'end': 4., 'text': 'Что случилось?'}]
        frames = [{'time': 2.}]
        raw = answer({'CURRENT': {'units': units, 'frames': frames}}, keep=['u0'])
        raw['unit_evidence'][0].update(frame_indices=[], speech_quote='Что случилось?')
        with self.assertRaises(ValueError):
            validate_adjudication(raw, units, frames)
        raw['unit_evidence'][0]['kind'] = 'causal_dialogue'
        raw['action_units'] = []
        self.assertTrue(validate_adjudication(raw, units, frames)['accepted'])

    def test_broad_source_ownership_proof_is_not_positive_selection_proof(self):
        event = copy.deepcopy(self.event)
        event['verified_current_story_ranges'] = [{'start': 0., 'end': 12.}]
        self.assertEqual(minimal_semantic_context(event, event['units'], EMPTY)['selected_ranges'], [])

    def test_action_evidence_inside_confirmed_credit_cannot_promote_current(self):
        event = copy.deepcopy(self.event)
        event['excluded_credit_ranges'] = [{'start': 0., 'end': 4.}]
        result = self.adjudicate(FakeVision(), event)
        self.assertTrue(result['analysis_unresolved'])
        self.assertEqual(result['selected_ranges'], [])
        self.assertEqual(result['excluded_credit_ranges'], event['excluded_credit_ranges'])
        self.assertNotIn('action_units', result)

    def test_crlf_normalized_prompt_reuses_cache(self):
        from app.selection_adjudication import ADJUDICATION_PROMPT
        self.adjudicate(FakeVision())
        with patch('app.selection_adjudication.ADJUDICATION_PROMPT', ADJUDICATION_PROMPT.replace('\n', '\r\n')):
            vision = FakeVision()
            self.adjudicate(vision)
            self.assertEqual(vision.requests, [])

    def test_dense_cut_page_bound_is_split_before_frame_generation(self):
        unit = {'id': 'source_u', 'start': 0., 'end': 10., 'text': ''}
        shots = [{'id': str(i), 'start': i*.05, 'end': (i+1)*.05} for i in range(200)]
        views = _views([unit], EMPTY, shots, lambda: False)
        self.assertGreater(len(views), 1)
        self.assertEqual(views[0]['start'], 0.)
        self.assertEqual(views[-1]['end'], 10.)
        self.assertTrue(all(a['end'] == b['start'] for a, b in zip(views, views[1:])))

    def test_segment_quote_without_word_times_is_not_transferred_to_smaller_view(self):
        event = copy.deepcopy(self.event)
        event['units'] = [{'id': 'long', 'start': 0., 'end': 12., 'text': ''}]
        transcript = {'words': [], 'segments': [{'start': 0., 'end': 12., 'text': 'Очень длинный исходный разговор.'}]}
        vision = FakeVision(lambda p: answer(p, keep=[]))
        result = self.adjudicate(vision, event, transcript)
        self.assertEqual(result['selection_status'], 'accepted')
        self.assertTrue(all(u['text'] == '' for request in vision.requests
                            for u in request[3]['CURRENT']['units']))

    def test_real_ffmpeg_storyboard_supplies_dense_source_frames_without_model(self):
        self.storyboard.stop()
        self.inspect.stop()
        subprocess.run([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=160x90:rate=20:duration=1.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            str(self.source)], check=True, capture_output=True)
        event = {'id': 'actual-source', 'start': 0., 'end': 1.5, 'summary': '',
                 'selected_ranges': [{'start': 0., 'end': 1.5}], 'importance': 3, 'kind': 'story'}
        vision = FakeVision(lambda p: answer(p, keep=[]))
        result = self.adjudicate(vision, event)
        self.assertEqual(result['selection_status'], 'accepted')
        payload = vision.requests[0][3]
        self.assertGreaterEqual(len(payload['CURRENT']['frames']), 3)
        for frame in payload['CURRENT']['frames']:
            self.assertTrue(0 <= frame['time'] < 1.5)
        images = vision.requests[0][1]
        images = images if isinstance(images, list) else [images]
        with Image.open(images[0]) as picture:
            self.assertGreater(picture.width, 160)


if __name__ == '__main__':
    unittest.main()
