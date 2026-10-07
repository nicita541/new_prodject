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
from app.deepseek import RemoteError, BudgetExceeded
from app.jobs import BusyError
from app.global_verification import verify_global_visual, validate_global_visual, global_visual_schema
from app.media_probe import atomic_json, load_json
from app.source_roles import confirmed_exclusions


EMPTY = {'words': [], 'segments': []}


def answer(**changes):
    return {'summary': 'Героев связывают и помещают в машину.', 'correction': True,
            'semantic_confidence': .95, 'visual_confidence': .95, 'context_confidence': .9,
            'uncertain': False, 'action_units': ['c000_u001'], 'narrative_bridge': True,
            'state_before': {'locations': ['street'], 'character_state': 'free', 'objects': []},
            'state_after': {'locations': ['car'], 'character_state': 'bound', 'objects': []}, **changes}


def selection_answer(units, keep=None, actions=None, reasons=None, indices=None, **changes):
    """Mechanism fixture only: it does not test actual VLM perceptual truth."""
    keep = set(keep if keep is not None else [units[1]['id']])
    actions = list(actions if actions is not None else keep)
    reasons = reasons or {}
    records=[]
    for number,unit in enumerate(units):
        reason=reasons.get(unit['id'],'physical_action' if unit['id'] in keep else 'neutral_scenery')
        records.append({'unit':unit['id'],'reason':reason,
            'evidence':'Виден конкретный перенос предмета рукой персонажа.' if unit['id'] in keep
                       else 'Виден неизменный интерьер без действий и реакции персонажей.',
            'frame_indices':(indices or {}).get(unit['id'],[number+1]),'speech_quote':''})
    return answer(action_units=actions,narrative_bridge=bool(actions),replace_selection=True,
        understanding_confidence=.95,selection_confidence=.95,keep_units=[u['id'] for u in units if u['id'] in keep],
        drop_units=[u['id'] for u in units if u['id'] not in keep],selection_evidence=records,**changes)


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

    def test_legacy_unchanged_understanding_is_resolved_but_selection_remains_pending(self):
        event = {**self.event, 'uncertain': True, 'understanding_status': 'unresolved'}
        result = self.verify([event], FakeVision([answer(correction=False)]))[0]
        self.assertEqual(result['summary_source'], 'local')
        self.assertEqual(result['summary'], event['summary'])
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['understanding_status'], 'accepted')
        self.assertEqual(result['action_units'], ['c000_u001'])
        self.assertTrue(result['global_verification_unresolved'])
        self.assertTrue(result['selection_uncertain'])
        self.assertEqual(result['selection_confidence'],0)

    def test_legacy_corrected_and_unchanged_chunks_merge_understanding_without_deletion_authority(self):
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
        self.assertTrue(result['global_verification_unresolved'])
        self.assertEqual(result['selection_status'],'pending')
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

    def frames(self):
        return [{'index':i+1,'time':(u['start']+u['end'])/2} for i,u in enumerate(self.event['units'])]

    def clear_verifier_cache(self):
        for checkpoint in (self.job/'global_verification').glob('*.json'):
            checkpoint.resolve().relative_to(self.job.resolve())
            checkpoint.unlink()

    def test_strict_replacement_removes_old_keep_all_and_ownership_is_not_retention(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}],
               'verified_current_story_ranges':[{'start':0,'end':12}]}
        result=self.verify([event],FakeVision([selection_answer(event['units'])]))[0]
        self.assertEqual(result['selected_ranges'],[{'start':4,'end':8}])
        self.assertEqual(result['verified_current_story_ranges'],event['verified_current_story_ranges'])
        self.assertEqual(result['selection_status'],'accepted')
        self.assertFalse(result['selection_uncertain'])
        self.assertFalse(result['analysis_unresolved'])
        self.assertGreaterEqual(result['understanding_confidence'],.9)
        self.assertGreaterEqual(result['selection_confidence'],.9)
        self.assertEqual({r['unit'] for r in result['unit_evidence']},{u['id'] for u in event['units']})
        kept=next(r for r in result['unit_evidence'] if r['decision']=='keep')
        self.assertEqual(kept['frame_times'],[6])
        self.assertEqual((kept['view_start'],kept['view_end']),(4,8))
        self.assertEqual(len(kept['checkpoint']),64)

    def test_understanding_and_selection_confidence_gate_replacement_independently(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}]}
        for fields in ({'selection_confidence':.89},{'understanding_confidence':.6},
                       {'replace_selection':False},{'uncertain':True}):
            with self.subTest(fields=fields):
                self.clear_verifier_cache()
                raw=selection_answer(event['units']); raw.update(fields)
                result=self.verify([event],FakeVision([raw]))[0]
                self.assertEqual(result['selected_ranges'],event['selected_ranges'])
                self.assertTrue(result['selection_uncertain'])
                self.assertTrue(result['global_verification_unresolved'])
                if fields.get('selection_confidence')==.89:
                    self.assertFalse(result['uncertain'])
                    self.assertEqual(result['understanding_status'],'accepted')
                if fields.get('understanding_confidence')==.6:
                    self.assertEqual(result['understanding_confidence'],.6)
                    self.assertEqual(result['understanding_status'],'unresolved')

    def test_strict_partition_and_source_evidence_reject_invented_or_partial_answers(self):
        base=selection_answer(self.event['units'])
        malformed=[{'keep_units':['unknown']},{'drop_units':['c000_u000','c000_u000','c000_u002']},
            {'drop_units':['c000_u000']},{'drop_units':['c000_u000','c000_u001','c000_u002']},
            {'action_units':['c000_u000']},{'selection_confidence':True},
            {'selection_confidence':float('inf')},{'understanding_confidence':float('nan')},
            {'replace_selection':1},{'start':2}]
        for fields in malformed:
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                validate_global_visual({**base,**fields},self.event['units'],self.frames())
        for fields in ({'frame_indices':[1]},{'frame_indices':[True]},{'frame_indices':[2,2]},
                       {'frame_indices':[4]},{'speech_quote':'Несуществующая исходная реплика'},
                       {'reason':'atmosphere'},{'evidence':'generic atmosphere'},
                       {'frame_indices':[],'speech_quote':''},{'start':5}):
            raw=copy.deepcopy(base); raw['selection_evidence'][1].update(fields)
            with self.subTest(evidence=fields),self.assertRaises(ValueError):
                validate_global_visual(raw,self.event['units'],self.frames())
        raw=copy.deepcopy(base); raw.pop('drop_units')
        with self.assertRaises(ValueError):
            validate_global_visual(raw,self.event['units'],self.frames())

    def test_current_speech_quote_is_reconstructed_from_actual_asr_not_old_unit_text(self):
        event=copy.deepcopy(self.event); event['units'][1]['text']='Модель придумала эту фразу'
        text={'words':[{'start':4.5,'end':5,'text':'Ключ'},{'start':5,'end':5.5,'text':'здесь'}],
              'segments':[{'start':4.5,'end':5.5,'text':'Ключ здесь'}]}
        raw=selection_answer(event['units'],actions=[],reasons={'c000_u001':'causal_dialogue'})
        raw['selection_evidence'][1].update(frame_indices=[],speech_quote='Ключ здесь')
        vision=FakeVision([raw]); result=self.verify([event],vision,text)[0]
        prompt=vision.requests[0][0]
        payload=json.loads(prompt[prompt.index('\n{')+1:])
        self.assertEqual(payload['CURRENT']['units'][1]['text'],'Ключ здесь')
        self.assertEqual(result['selection_status'],'accepted')
        raw['selection_evidence'][1]['speech_quote']='Модель придумала эту фразу'
        self.clear_verifier_cache()
        result=self.verify([event],FakeVision([raw]),text)[0]
        self.assertTrue(result['selection_uncertain'])

    def test_specific_reaction_is_retained_but_neutral_scenery_cannot_pose_as_reaction(self):
        raw=selection_answer(self.event['units'],actions=[],reasons={'c000_u001':'character_reaction'})
        raw['selection_evidence'][1]['evidence']='Глаза расширяются, лицо меняется после услышанной реплики.'
        result=self.verify(vision=FakeVision([raw]))[0]
        self.assertEqual(result['selected_ranges'],[{'start':4,'end':8}])
        self.assertEqual(next(r['kind'] for r in result['unit_evidence'] if r['decision']=='keep'),'character_reaction')
        raw['selection_evidence'][1]['reason']='neutral_scenery'
        with self.assertRaises(ValueError):
            validate_global_visual(raw,self.event['units'],self.frames())

    def test_prior_specific_actions_and_reactions_need_explicit_visual_reassessment_to_drop(self):
        for kind,reassessment in (('physical_action','reassessed_action'),('character_reaction','reassessed_reaction')):
            with self.subTest(kind=kind):
                self.clear_verifier_cache()
                event={**self.event,'selected_ranges':[{'start':0,'end':12}],
                    'action_units':['c000_u000'] if kind=='physical_action' else [],
                    'unit_evidence':[{'unit':'c000_u000','kind':kind,'confidence':.95,'decision':'keep',
                        'evidence':'Конкретное действие или изменённое выражение подтверждено исходным кадром.',
                        'frame_indices':[1]}]}
                raw=selection_answer(event['units'])
                blocked=self.verify([event],FakeVision([raw]))[0]
                self.assertEqual(blocked['selected_ranges'],event['selected_ranges'])
                self.assertTrue(blocked['selection_uncertain'])
                raw['selection_evidence'][0].update(reason=reassessment,
                    evidence='Независимый кадр показывает пустые неподвижные руки и прежнее выражение; прежняя трактовка неверна.')
                self.clear_verifier_cache()
                resolved=self.verify([event],FakeVision([raw]))[0]
                self.assertEqual(resolved['selected_ranges'],[{'start':4,'end':8}])
                self.assertEqual(resolved['selection_status'],'accepted')
                self.assertNotIn('c000_u000',resolved['action_units'])

    def test_empty_verified_selection_removes_stale_protection_without_restoring_event(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}],
               'protected_atmosphere_units':['c000_u000'],'fallback':'minimal_safe_context',
               'whole_scene_last_resort':True,'action_units':['c000_u001'],
               'selection_needs_adjudication':True,'atmosphere_review_units':['c000_u000'],
               'unresolved_omission_units':['c000_u002'],'source_role_unresolved':True}
        raw=selection_answer(event['units'],keep=[],actions=[])
        result=self.verify([event],FakeVision([raw]))[0]
        self.assertEqual(result['selected_ranges'],[])
        self.assertEqual(result['action_units'],[])
        self.assertTrue(result['selection_empty_verified'])
        self.assertEqual(result['kind'],'filler')
        self.assertNotIn('protected_atmosphere_units',result)
        self.assertNotIn('whole_scene_last_resort',result)
        for key in ('selection_needs_adjudication','atmosphere_review_units','unresolved_omission_units'):
            self.assertNotIn(key,result)
        self.assertTrue(result['source_role_unresolved'])

    def test_failure_without_old_selection_never_adds_the_entire_event(self):
        event=copy.deepcopy(self.event); event.pop('selected_ranges')
        for error in (RuntimeError('model failure'),ValueError('invalid JSON')):
            result=self.verify([event],FakeVision([error]))[0]
            self.assertEqual(result['selected_ranges'],[])
            self.assertEqual(result['summary'],event['summary'])
            self.assertTrue(result['selection_uncertain'])
            self.assertTrue(result['analysis_unresolved'])

    def multi_page(self,event):
        image=self.visual/'event_0000_chunk_000.jpg'; pages=[]
        for number in range(9):
            page=self.visual/f'page-{number}.jpg'; Image.new('RGB',(64,36),'white').save(page); pages.append(str(page))
        frames=[{'time':(i+.5)*12/324,'unit_ids':[]} for i in range(324)]
        atomic_json(image.with_suffix('.storyboard.json'),{'pages':pages,'frames':frames})
        return frames

    def test_failed_later_page_cannot_delete_unseen_units(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}]}; self.multi_page(event)
        raw=selection_answer(event['units'][:2],indices={'c000_u000':[1],'c000_u001':[109]})
        result=self.verify([event],FakeVision([raw,RuntimeError('later page missing')]))[0]
        self.assertEqual(result['selected_ranges'],[{'start':4,'end':12}])
        self.assertEqual(result['global_selection_coverage'],[{'start':0,'end':8}])
        self.assertEqual(result['global_pending_selection_ranges'],[{'start':8,'end':12}])
        self.assertEqual(result['selection_status'],'pending')

    def test_conflicting_partial_views_of_one_unit_cannot_replace_full_unit(self):
        event={**self.event,'units':[{'id':'c000_u000','start':0,'end':12,'text':''}]}; self.multi_page(event)
        first=selection_answer(event['units'],keep=['c000_u000'],actions=['c000_u000'],indices={'c000_u000':[1]})
        last=selection_answer(event['units'],keep=[],actions=[],indices={'c000_u000':[217]})
        result=self.verify([event],FakeVision([first,last]))[0]
        self.assertEqual(result['selected_ranges'],event['selected_ranges'])
        self.assertEqual(result['global_selection_coverage'],[])
        self.assertEqual(result['selection_status'],'pending')

    def test_actual_source_model_schema_and_implementation_changes_invalidate_selection_cache(self):
        raw=selection_answer(self.event['units']); self.verify(vision=FakeVision([raw]))
        self.verify(vision=FakeVision([]))
        self.source.write_bytes(b'changed-source!')
        changed=FakeVision([raw]); self.verify(vision=changed); self.assertEqual(len(changed.requests),1)
        model=self.job/'model.gguf'; model.write_bytes(b'model v1')
        projector=self.job/'projector.gguf'; projector.write_bytes(b'projector')
        def provider():
            result=FakeVision([raw]); result.model=model; result.projector=projector; return result
        self.verify(vision=provider()); model.write_bytes(b'model v2')
        changed=provider(); self.verify(vision=changed); self.assertEqual(len(changed.requests),1)
        real_read=Path.read_text
        def altered(path,*args,**kwargs):
            value=real_read(path,*args,**kwargs)
            return value+'\n# prompt literal changed without version bump\n' if path.name in ('app_global_verification.py','global_verification.py') else value
        with patch.object(Path,'read_text',altered):
            changed=provider(); self.verify(vision=changed); self.assertEqual(len(changed.requests),1)
        real_schema=global_visual_schema
        with patch('app.global_verification.global_visual_schema',side_effect=lambda *args,**kw:{**real_schema(*args,**kw),'description':'new actual schema'}):
            changed=provider(); self.verify(vision=changed); self.assertEqual(len(changed.requests),1)

    def test_invalid_current_frames_and_corrupt_cache_structure_do_not_receive_authority(self):
        raw=selection_answer(self.event['units']); self.verify(vision=FakeVision([raw]))
        checkpoint=next((self.job/'global_verification').glob('*.json')); atomic_json(checkpoint,[])
        vision=FakeVision([raw]); self.verify(vision=vision); self.assertEqual(len(vision.requests),1)
        for time in (float('nan'),13,True):
            image=self.visual/'event_0000_chunk_000.jpg'
            board=load_json(image.with_suffix('.storyboard.json')); board['frames'][0]['time']=time
            atomic_json(image.with_suffix('.storyboard.json'),board)
            vision=FakeVision([]); result=self.verify(vision=vision)[0]
            self.assertFalse(vision.requests)
            self.assertTrue(result['selection_uncertain'])

    def test_cancel_after_query_and_budget_failure_propagate_without_selection_fallback(self):
        with self.assertRaises(BudgetExceeded):
            self.verify(vision=FakeVision([BudgetExceeded('budget')]))
        flag={'cancelled':False}
        class CancellingVision(FakeVision):
            def query(self,*args,**kwargs):
                result=super().query(*args,**kwargs); flag['cancelled']=True; return result
        with self.assertRaises(InterruptedError):
            verify_global_visual(self.source,[self.event],EMPTY,[],self.job,
                CancellingVision([selection_answer(self.event['units'])]),lambda *args:None,lambda:flag['cancelled'])

    def test_production_schema_is_strict_but_legacy_adapter_has_no_deletion_confidence(self):
        schema=global_visual_schema(self.event['units'],self.frames())
        for field in ('replace_selection','understanding_confidence','selection_confidence','keep_units','drop_units','selection_evidence'):
            self.assertIn(field,schema['required'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['selection_evidence']['items']['properties']['frame_indices']['items']['enum'],[1,2,3])
        legacy=validate_global_visual(answer(),self.event['units'])
        self.assertTrue(legacy['selection_legacy'])
        self.assertFalse(legacy['selection_authority'])
        self.assertEqual(legacy['selection_confidence'],0)

    def test_strict_selection_cannot_revive_confirmed_nonstory_ranges(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}],
               'excluded_credit_ranges':[{'start':4,'end':8}]}
        result=self.verify([event],FakeVision([selection_answer(event['units'])]))[0]
        self.assertEqual(result['selected_ranges'],[{'start':0,'end':4},{'start':8,'end':12}])
        self.assertTrue(result['selection_uncertain'])
        self.assertEqual(confirmed_exclusions(result),confirmed_exclusions(event))
        self.assertEqual(result['summary'],event['summary'])

    def test_current_story_ownership_exception_is_preserved_without_keeping_whole_credit_event(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}],
            'credit_montage':True,'contains_credits':True,'excluded_credit_ranges':[{'start':0,'end':12}],
            'verified_current_story_ranges':[{'start':4,'end':8}]}
        result=self.verify([event],FakeVision([selection_answer(event['units'])]))[0]
        self.assertEqual(result['selected_ranges'],[{'start':4,'end':8}])
        self.assertEqual(result['selection_status'],'accepted')
        self.assertEqual(confirmed_exclusions(result),[{'start':0,'end':4},{'start':8,'end':12}])
        self.assertEqual(result['verified_current_story_ranges'],event['verified_current_story_ranges'])

    def test_exclusion_trimming_never_cuts_an_actual_asr_word(self):
        event={**self.event,'selected_ranges':[{'start':0,'end':12}],
               'excluded_credit_ranges':[{'start':1.5,'end':2.5}]}
        self.board('event_0000_chunk_000',event['units'])
        path=self.visual/'event_0000_chunk_000.storyboard.json'
        board=load_json(path); board['frames'][0]['time']=.5; atomic_json(path,board)
        text={'words':[{'start':1,'end':2,'text':'Привет'}],
              'segments':[{'start':1,'end':2,'text':'Привет'}]}
        raw=selection_answer(event['units'],keep=['c000_u000'],actions=['c000_u000'])
        result=self.verify([event],FakeVision([raw]),text)[0]
        self.assertEqual(result['selected_ranges'],[{'start':0,'end':1},{'start':2.5,'end':4}])
        self.assertFalse(any(w['start']<r[k]<w['end'] for w in text['words'] for r in result['selected_ranges'] for k in ('start','end')))

    def test_cross_chunk_source_unit_is_not_replaced_with_invented_candidate_ids(self):
        event={**self.event,'units':[{'id':'actual_current_id','start':0,'end':12,'text':''}],
            'analysis_chunks':[{'id':'chunk_first','start':0,'end':6},{'id':'chunk_second','start':6,'end':12}]}
        vision=FakeVision([]); result=self.verify([event],vision)[0]
        self.assertFalse(vision.requests)
        self.assertEqual(result['selected_ranges'],event['selected_ranges'])
        self.assertTrue(result['selection_uncertain'])
        self.assertTrue(all('event.units' in r['error'] for r in result['global_verification_history']))


if __name__ == '__main__':
    unittest.main()
