"""Independent visual corrections use source evidence and preserve ownership."""
import copy
import json
import shutil
import ssl
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import TEMP
from app.deepseek import RemoteError
from app.jobs import BusyError
from app.global_verification import verify_global_visual, validate_global_visual
from app.media_probe import atomic_json, load_json
from app.source_roles import confirmed_exclusions


EMPTY = {'words': [], 'segments': []}


def answer(**changes):
    return {'summary': 'Героев связывают и помещают в машину.', 'correction': True,
            'semantic_confidence': .95, 'visual_confidence': .95, 'context_confidence': .9,
            'uncertain': False, 'action_units': ['c000_u001'], 'narrative_bridge': True,
            'state_before': {'locations': ['street'], 'character_state': 'free', 'objects': []},
            'state_after': {'locations': ['car'], 'character_state': 'bound', 'objects': []}, **changes}


class FakeVision:
    supports_image_pages = True
    model = 'fake-model'
    projector = 'fake-projector'
    cache_profile = {'version': 1}

    def __init__(self, answers):
        self.answers, self.requests = list(answers), []

    def query(self, prompt, image=None, max_tokens=1000, schema=None):
        self.requests.append((prompt, image, schema))
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


class GlobalVerificationTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP / ('global-visual-' + uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.visual = self.job / 'visual'
        self.visual.mkdir()
        self.source = self.job / 'source.mp4'
        self.source.write_bytes(b'original-source')
        self.event = {'id': 'event_0000', 'scene_id': 'scene_0000', 'start': 0, 'end': 12,
                      'summary': 'Персонажи разговаривают.', 'kind': 'story', 'importance': 4,
                      'uncertain': True, 'understanding_status': 'unresolved',
                      'selected_ranges': [{'start': 0, 'end': 4}],
                      'analysis_chunks': [{'id': 'scene_0000_chunk_000', 'parent_scene_id': 'scene_0000', 'start': 0, 'end': 12}],
                      'units': [{'id': f'c000_u{i:03d}', 'start': i*4, 'end': (i+1)*4,
                                 'text': ''} for i in range(3)]}
        self.board('event_0000_chunk_000', self.event['units'])

    def tearDown(self):
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    def board(self, stem, units, color='white'):
        image = self.visual / (stem + '.jpg')
        Image.new('RGB', (64, 36), color).save(image)
        atomic_json(image.with_suffix('.storyboard.json'), {'pages': [str(image)],
            'frames': [{'time': (u['start'] + u['end'])/2, 'unit_ids': [u['id']], 'reasons': ['unit_center']} for u in units]})
        return image

    def verify(self, events=None, vision=None, transcript=None):
        return verify_global_visual(self.source, events or [self.event], transcript or EMPTY, [], self.job,
                                    vision or FakeVision([answer()]), lambda *a: None, lambda: False)

    def test_wrong_conversation_hypothesis_is_corrected_from_actual_images_and_units(self):
        snapshot = copy.deepcopy(self.event)
        vision = FakeVision([answer()])
        result = self.verify(vision=vision)[0]
        self.assertEqual(self.event, snapshot)
        self.assertEqual(result['local_summary'], 'Персонажи разговаривают.')
        self.assertEqual(result['global_summary'], answer()['summary'])
        self.assertEqual(result['final_summary'], result['summary'])
        self.assertEqual(result['summary_source'], 'global_correction')
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['understanding_status'], 'accepted')
        self.assertEqual(result['confidence'], .9)
        self.assertEqual(result['selected_ranges'], [{'start': 0, 'end': 8}])
        self.assertTrue(result['narrative_bridge'])
        self.assertEqual(result['action_units'], ['c000_u001'])
        prompt, image, schema = vision.requests[0]
        self.assertTrue(Path(image).is_file())
        payload = json.loads(prompt[prompt.index('\n{')+1:])
        self.assertEqual(payload['HYPOTHESES']['local_summary'], snapshot['summary'])
        self.assertEqual(payload['CURRENT']['units'], snapshot['units'])
        self.assertEqual(schema['properties']['action_units']['items']['enum'], [u['id'] for u in snapshot['units']])
        self.assertNotIn('verified_current_story_ranges', result)
        self.assertNotIn('excluded_credit_ranges', result)

    def test_uncertain_or_low_confidence_correction_cannot_overrule_existing_understanding(self):
        for change in ({'uncertain': True}, {'context_confidence': .5}):
            with self.subTest(change=change):
                result = self.verify(vision=FakeVision([answer(**change)]))[0]
                self.assertEqual(result['summary'], self.event['summary'])
                self.assertEqual(result['summary_source'], 'local')
                self.assertEqual(result['selected_ranges'], self.event['selected_ranges'])
                self.assertTrue(result['uncertain'])

    def test_invalid_unit_ids_and_boolean_confidence_are_rejected_without_added_ranges(self):
        for change in ({'action_units': ['made_up']}, {'semantic_confidence': True},
                       {'visual_confidence': float('nan')}, {'correction': 1}):
            with self.subTest(change=change):
                result = self.verify(vision=FakeVision([answer(**change)]))[0]
                self.assertEqual(result['selected_ranges'], self.event['selected_ranges'])
                self.assertEqual(result['summary'], self.event['summary'])
                self.assertEqual(result['global_verification_history'][0]['fallback'], 'preserve_previous_understanding')

    def test_current_proof_never_overrides_confirmed_nonstory_exclusion(self):
        event = {**self.event, 'excluded_credit_ranges': [{'start': 4, 'end': 8}]}
        result = self.verify([event], FakeVision([answer()]))[0]
        self.assertEqual(confirmed_exclusions(result), confirmed_exclusions(event))
        self.assertEqual(result['selected_ranges'], event['selected_ranges'])
        self.assertEqual(result['summary'], event['summary'])
        self.assertEqual(result['global_verification_history'][0]['blocked_action_units'], ['c000_u001'])
        pure = {**self.event, 'contains_credits': True, 'credit_montage': True, 'kind': 'opening', 'importance': 1}
        result = self.verify([pure], FakeVision([answer()]))[0]
        self.assertTrue(result['credit_montage'])
        self.assertEqual(result['kind'], 'opening')

    def test_cache_reuse_and_prompt_image_transcript_invalidation(self):
        first = FakeVision([answer()])
        initial = self.verify(vision=first)
        cached = self.verify(vision=FakeVision([]))
        self.assertEqual(initial, cached)
        with patch('app.global_verification.GLOBAL_VISUAL_PROMPT', 'Changed independent verification policy'):
            changed = FakeVision([answer()])
            self.verify(vision=changed)
            self.assertEqual(len(changed.requests), 1)
        self.board('event_0000_chunk_000', self.event['units'], color='blue')
        changed_image = FakeVision([answer()])
        self.verify(vision=changed_image)
        self.assertEqual(len(changed_image.requests), 1)
        changed_transcript = FakeVision([answer()])
        self.verify(vision=changed_transcript, transcript={'words': [], 'segments': [{'start': 1, 'end': 3, 'text': 'Original ASR'}]})
        self.assertEqual(len(changed_transcript.requests), 1)

    def test_before_after_images_and_asr_are_context_only(self):
        event = copy.deepcopy(self.event)
        event.update(start=4, end=16)
        event['analysis_chunks'][0].update(start=4, end=16)
        event['units'] = [{**u, 'start': u['start']+4, 'end': u['end']+4} for u in event['units']]
        self.board('event_0000_chunk_000', event['units'])
        self.board('event_0000_previous', [{'id': 'before', 'start': 0, 'end': 4}])
        self.board('event_0000_next', [{'id': 'after', 'start': 16, 'end': 20}])
        before = {'id': 'previous', 'start': 0, 'end': 4, 'summary': 'before', 'kind': 'story', 'importance': 2}
        after = {'id': 'next', 'start': 16, 'end': 20, 'summary': 'after', 'kind': 'story', 'importance': 2}
        transcript = {'words': [], 'segments': [{'start': 0, 'end': 3, 'text': 'before quote'},
                                               {'start': 5, 'end': 10, 'text': 'current quote'},
                                               {'start': 17, 'end': 19, 'text': 'after quote'}]}
        vision = FakeVision([answer()])
        self.verify([before, event, after], vision, transcript)
        prompt, images, _ = vision.requests[0]
        payload = json.loads(prompt[prompt.index('\n{')+1:])
        self.assertEqual(len(images), 3)
        self.assertEqual(payload['image_order'], ['CURRENT', 'BEFORE CONTEXT ONLY', 'AFTER CONTEXT ONLY'])
        self.assertEqual(payload['BEFORE']['role'], 'context_only')
        self.assertEqual(payload['AFTER']['role'], 'context_only')
        self.assertEqual(payload['CURRENT']['transcript']['segments'][0]['text'], 'current quote')

    def test_diagnostics_keep_local_global_and_final_decision_history(self):
        result = self.verify()[0]
        audit = load_json(self.job/'diagnostics/pipeline/global_story.json')['events'][self.event['id']]
        self.assertEqual(audit['local_decision']['summary'], self.event['summary'])
        self.assertEqual(audit['global_decisions'], result['global_verification_history'])
        self.assertTrue(audit['final_decision']['changed'])
        self.assertEqual(audit['final_decision']['summary_source'], 'global_correction')
        records = [json.loads(line) for line in (self.job/'diagnostics/pipeline/timeline.jsonl').read_text().splitlines()]
        self.assertTrue(any(r['action'] == 'request' and r['pages'] == 1 for r in records))

    def test_remote_auth_tls_and_cancellation_errors_propagate(self):
        wrapped = RuntimeError('wrapped model failure')
        wrapped.__cause__ = ssl.SSLCertVerificationError('wrapped TLS')
        errors = [RemoteError('Remote denied', category='auth'), InterruptedError('cancelled'), BusyError('busy'), wrapped,
                  urllib.error.HTTPError('https://example.test', 401, 'auth', {}, None),
                  urllib.error.URLError(ssl.SSLCertVerificationError('bad certificate'))]
        for error in errors:
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.verify(vision=FakeVision([error]))

    def test_model_quality_failure_keeps_original_and_records_specific_fallback(self):
        result = self.verify(vision=FakeVision([RuntimeError('Original local model symptom')]))[0]
        self.assertEqual(result['summary'], self.event['summary'])
        self.assertEqual(result['global_verification_history'][0]['error_type'], 'RuntimeError')
        self.assertIn('Original local model symptom', result['global_verification_history'][0]['error'])
        self.assertEqual(load_json(self.job/'diagnostics/pipeline/warnings.json')[0]['reason'], 'verification_failed')

    def test_recovery_summary_is_preserved_when_global_corrects_it(self):
        event = {**self.event, 'local_summary': 'Первичная ошибка.', 'recovery_summary': 'Recovery hypothesis.',
                 'final_summary': 'Recovery hypothesis.', 'summary_source': 'recovery'}
        result = self.verify([event], FakeVision([answer()]))[0]
        self.assertEqual(result['local_summary'], event['local_summary'])
        self.assertEqual(result['recovery_summary'], event['recovery_summary'])
        self.assertEqual(result['summary_source'], 'global_correction')

    def test_schema_rejects_duplicate_ids_and_missing_state_dimensions(self):
        for change in ({'action_units': ['c000_u001', 'c000_u001']},
                       {'state_after': {'character_state': 'bound', 'locations': ['car']}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_global_visual(answer(**change), self.event['units'])

    def test_confident_unchanged_scene_does_not_receive_an_unresolved_global_flag(self):
        event = {**self.event, 'uncertain': True, 'understanding_status': 'unresolved'}
        result = self.verify([event], FakeVision([answer(correction=False)]))[0]
        self.assertEqual(result['summary_source'], 'local')
        self.assertEqual(result['summary'], event['summary'])
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['understanding_status'], 'accepted')
        self.assertEqual(result['action_units'], ['c000_u001'])
        self.assertFalse(result['global_verification_unresolved'])

    def test_corrected_and_confirmed_unchanged_chunks_merge_into_one_resolved_parent(self):
        event = copy.deepcopy(self.event)
        event['analysis_chunks'] = [{'id': f'scene_0000_chunk_{i:03d}', 'start': i*6, 'end': (i+1)*6} for i in range(2)]
        event['units'] = [{'id': f'c{i:03d}_u000', 'start': i*6, 'end': (i+1)*6, 'text': ''} for i in range(2)]
        for i in range(2):
            self.board(f'event_0000_chunk_{i:03d}', [event['units'][i]])
        decisions = [answer(action_units=['c000_u000']), answer(correction=False, action_units=[], summary='Unchanged next beat.')]
        result = self.verify([event], FakeVision(decisions))[0]
        self.assertEqual(result['id'], event['id'])
        self.assertEqual(result['summary_source'], 'global_correction')
        self.assertFalse(result['uncertain'])
        self.assertFalse(result['global_verification_unresolved'])
        self.assertEqual(len(result['global_verification_history']), 2)
        self.assertEqual(result['selected_ranges'], [{'start': 0, 'end': 6}])

    def test_many_current_pages_are_batched_without_exceeding_eight_with_neighbors(self):
        event = copy.deepcopy(self.event)
        before = {'id': 'previous', 'start': 0, 'end': 1, 'summary': 'context', 'kind': 'story', 'importance': 2}
        after = {'id': 'next', 'start': 12, 'end': 13, 'summary': 'context', 'kind': 'story', 'importance': 2}
        self.board('event_0000_previous', [{'id': 'before', 'start': 0, 'end': 1}])
        self.board('event_0000_next', [{'id': 'after', 'start': 12, 'end': 13}])
        image = self.visual / 'event_0000_chunk_000.jpg'
        pages = []
        for number in range(9):
            page = self.visual / f'page-{number}.jpg'
            Image.new('RGB', (64, 36), 'white').save(page)
            pages.append(str(page))
        frames = [{'time': (i+.5)*12/(9*36), 'unit_ids': [], 'reasons': ['source_frame']} for i in range(9*36)]
        atomic_json(image.with_suffix('.storyboard.json'), {'pages': pages, 'frames': frames})
        vision = FakeVision([answer(action_units=['c000_u001']), answer(action_units=['c000_u002'])])
        result = self.verify([before, event, after], vision)[1]
        self.assertEqual([len(request[1]) for request in vision.requests], [8, 5])
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['selected_ranges'], [{'start': 0, 'end': 12}])
        self.assertEqual(len(result['global_verification_history']), 2)

    def test_page_over_four_mib_is_explicit_missing_evidence_fallback(self):
        image = self.visual / 'event_0000_chunk_000.jpg'
        image.write_bytes(b'x' * (4*1024**2+1))
        vision = FakeVision([])
        result = self.verify(vision=vision)[0]
        self.assertFalse(vision.requests)
        self.assertEqual(result['summary'], self.event['summary'])
        self.assertIn('4 MiB', result['global_verification_history'][0]['error'])

    def test_fallback_error_history_redacts_credentials_before_event_persistence(self):
        result = self.verify(vision=FakeVision([RuntimeError('Local error Bearer private-value')]))[0]
        self.assertNotIn('private-value', result['global_verification_history'][0]['error'])

    def test_local_and_recovery_dimension_decisions_survive_global_audit(self):
        local = {'summary': 'local', 'semantic_confidence': .5, 'visual_confidence': .4, 'context_confidence': .3}
        recovery = {'summary': 'recovery', 'semantic_confidence': .8, 'visual_confidence': .7, 'context_confidence': .6}
        event = {**self.event, 'local_decision': local, 'recovery_decision': recovery}
        self.verify([event], FakeVision([answer()]))
        audit = load_json(self.job/'diagnostics/pipeline/global_story.json')['events'][self.event['id']]
        self.assertEqual(audit['local_decision'], local)
        self.assertEqual(audit['recovery_decision'], recovery)

    def test_corrupted_checkpoint_is_rebuilt_instead_of_permanent_fallback(self):
        self.verify()
        checkpoint = next((self.job/'global_verification').glob('*.json'))
        checkpoint.write_text('truncated JSON {', encoding='utf-8')
        vision = FakeVision([answer()])
        result = self.verify(vision=vision)[0]
        self.assertEqual(len(vision.requests), 1)
        self.assertEqual(result['summary_source'], 'global_correction')
        saved = load_json(checkpoint)
        saved['decision']['action_units'] = ['unknown-source-unit']
        atomic_json(checkpoint, saved)
        vision = FakeVision([answer()])
        self.verify(vision=vision)
        self.assertEqual(len(vision.requests), 1)

    def test_weak_unselected_event_keeps_complete_summary_provenance_without_request(self):
        event = {**self.event, 'uncertain': False, 'understanding_status': 'accepted', 'importance': 2}
        vision = FakeVision([])
        result = self.verify([event], vision)[0]
        self.assertFalse(vision.requests)
        self.assertEqual(result['local_summary'], event['summary'])
        self.assertIsNone(result['global_summary'])
        self.assertEqual(result['summary_source'], 'local')


if __name__ == '__main__':
    unittest.main()
