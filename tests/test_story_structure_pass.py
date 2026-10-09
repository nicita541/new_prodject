"""Authored source-unit mechanisms with a fake provider; no semantic quality claim."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import ssl
import unittest
import urllib.error
import uuid
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parents[1]
# CI and clean Linux worktrees use the active Python interpreter rather than
# a bundled Windows tools/python/python.exe; retain multi-worktree comparison
# when the bundled runtime is available.
ROOT = next((p for p in (HERE, *HERE.parents) if (p/'tools/python/python.exe').is_file()), HERE)
if HERE == ROOT:
    from app import story_structure_pass as structure
else:
    spec = importlib.util.spec_from_file_location('candidate_story_structure_pass', HERE/'app/story_structure_pass.py')
    structure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(structure)


def facts(**fields):
    return {'location_id': None, 'topic_id': None, 'relationship_state_id': None,
            'character_ids': [], 'physical_state_ids': [], 'object_ids': [], **fields}


def fixture(count=2, identifier='room', start=0):
    units, records, words = [], [], []
    for i in range(count):
        a = start+i*4
        phrase = 'Где ключ?' if i % 2 == 0 else 'Вот ключ.'
        units.append({'id': f'c000_u{i:03d}', 'start': a, 'end': a+4, 'text': 'not trusted authored unit text'})
        words.append({'start': a+1, 'end': a+2, 'text': phrase})
        records.append({'unit': units[-1]['id'], 'kind': 'causal_dialogue' if i % 2 == 0 else 'response',
                        'decision': 'keep', 'confidence': .95, 'speech_quote': phrase,
                        'frame_indices': [], 'frame_times': [], 'view_start': a, 'view_end': a+4,
                        'checkpoint': 'a'*64, 'evidence': 'The source speaker asks for the key.' if i % 2 == 0 else
                        'The source response supplies the requested key.'})
    event = {'id': identifier, 'scene_id': identifier, 'start': start, 'end': start+count*4,
        'summary': 'Internally generated accepted source description; no oracle arc metadata.',
        'understanding_confidence': .95, 'selection_confidence': .95, 'selection_status': 'accepted',
        'uncertain': False, 'selection_uncertain': False, 'analysis_unresolved': False,
        'units': units, 'unit_evidence': records, 'action_units': [],
        'selected_ranges': [{'start': start, 'end': start+count*4}],
        'source_identity': {'sha256': 'authored-mechanism-source', 'version': 1}}
    return event, {'words': words, 'segments': copy.deepcopy(words)}


def visual_fixture():
    event, transcript = fixture()
    for unit, record in zip(event['units'], event['unit_evidence']):
        record.update(kind='physical_action', speech_quote='', frame_count=1,
                      frame_indices=[1], frame_times=[unit['start']+.5],
                      evidence='The source character visibly ties the other character wrists with rope.')
    return event, transcript


def nodes(payload):
    return list({tuple(n['ref'].values()): n for n in [*payload['CURRENT'], *payload['CONTEXT_ONLY'],
                 *(m['source'] for m in payload['MEMORY'])]}.values())


def support(node):
    return {'ref': node['ref'], 'proof': node['proofs'][0]['id'], 'quote': node['ASR']}


def response(payload):
    all_nodes = {(n['ref']['event'], n['ref']['unit']): n for n in nodes(payload)}
    current = {(n['ref']['event'], n['ref']['unit']) for n in payload['CURRENT']}
    output = {'resolved': True, 'understanding_confidence': .95, 'structure_confidence': .95,
              'units': [], 'relations': [], 'arcs': [], 'canonical_entities': [], 'limitations': []}
    for node in payload['CURRENT']:
        odd = int(node['ref']['unit'][-3:]) % 2
        output['units'].append({'ref': node['ref'], 'roles': ['payoff' if odd else 'setup'],
            'before': facts(), 'after': facts(), 'confidence': .95,
            'evidence': 'The source question or its actual response supplies this story role.', 'support': [support(node)]})
    for (event, unit), left in all_nodes.items():
        index = int(unit[-3:])
        if index % 2:
            continue
        right_key = (event, unit[:-3]+f'{index+1:03d}')
        right = all_nodes.get(right_key)
        if right is None or not {(event, unit), right_key}.intersection(current):
            continue
        evidence = [support(left), support(right)]
        output['relations'].append({'type': 'setup_payoff', 'from': left['ref'], 'to': right['ref'],
            'confidence': .95, 'evidence': 'The accepted response resolves the directly supplied source question.', 'support': evidence})
        output['arcs'].append({'anchor': left['ref'], 'members': [{'ref': left['ref'], 'role': 'setup'},
            {'ref': right['ref'], 'role': 'payoff'}], 'closed': True, 'closing_unit': right['ref'],
            'confidence': .95, 'evidence': 'The question is resolved by its exact observed response.', 'support': evidence})
    return output


class FakeProvider:
    model = 'authored_mechanism_model'
    projector = 'authored_mechanism_text_profile'
    thinking = False

    def __init__(self, callback=response, token_counter=None):
        self.callback = callback
        self.token_counter = token_counter or (lambda text: len(text)//4)
        self.calls, self.payloads, self.prompts = [], [], []

    def token_count(self, prompt):
        return self.token_counter(prompt)

    def query(self, prompt, image=None, max_tokens=None, schema=None):
        payload = json.loads(prompt.rsplit('\n', 1)[1])
        self.calls.append({'image': image, 'max_tokens': max_tokens, 'schema': schema})
        self.payloads.append(payload); self.prompts.append(prompt)
        return self.callback(payload)


class StoryStructurePassTests(unittest.TestCase):
    def setUp(self):
        self.job = ROOT/'temp'/('story-structure-mechanism-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.job)

    def infer(self, events=None, transcript=None, vision=None, cancelled=lambda: False):
        if events is None:
            e, transcript = fixture()
            events = [e]
        return structure.infer_story_structure(events, transcript, self.job, vision or FakeProvider(), cancelled)

    def test_genuine_provider_api_is_text_only_and_selection_unchanged(self):
        event, transcript = fixture()
        old = copy.deepcopy((event, transcript))
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(vision.calls), 1)
        self.assertIsNone(vision.calls[0]['image'])
        self.assertEqual(result['events'][0]['selected_ranges'], event['selected_ranges'])
        self.assertEqual(result['events'][0]['selection_confidence'], .95)
        self.assertEqual(result['events'][0]['understanding_confidence'], .95)
        self.assertEqual((event, transcript), old)
        self.assertEqual(result['arcs'][0]['source_ranges'], [{'start': 0, 'end': 8}])
        self.assertTrue(result['arcs'][0]['complete_ending'])
        self.assertEqual(result['arcs'][0]['verification']['method'], 'source_proof_text_relation')
        self.assertIn('no_positional_arcs', vision.payloads[0]['coverage_contract'])
        self.assertNotIn('story_arc_id', json.dumps(vision.payloads))

    def test_generation_covers_each_current_owner_and_builds_dependencies_before_assignments(self):
        event, transcript = fixture(4)
        original, _, _ = structure.source_units([event], transcript)
        current = original[:3]
        schema = structure.structure_schema(original, current)
        fields = schema['properties']
        self.assertLess(list(fields).index('canonical_entities'), list(fields).index('units'))
        self.assertLess(list(fields).index('arcs'), list(fields).index('units'))
        self.assertLess(list(fields).index('units'), list(fields).index('resolved'))
        rows = fields['units']
        self.assertEqual((rows['minItems'], rows['maxItems']), (3, 3))
        self.assertNotIn('items', rows)
        for slot, n in zip(rows['prefixItems'], current):
            self.assertEqual(slot['properties']['ref']['enum'], [n['ref']])
        source_support = fields['relations']['items']['properties']['support']['items']['oneOf']
        for branch, n in zip(source_support, original):
            self.assertEqual(branch['properties']['proof']['enum'], [p['id'] for p in n['proofs']])
            self.assertEqual(branch['properties']['ref']['enum'], [n['ref']])
        self.assertEqual(fields['canonical_entities']['items']['properties']['mentions']['minItems'], 1)


    def test_bulky_audit_provenance_is_retained_but_not_sent_to_text_provider(self):
        event, transcript = fixture(4)
        event['source_identity']['audit_history'] = 'opaque provenance ' * 2000
        event['source_identity']['path'] = 'F:/private-media/source.mp4'
        before = copy.deepcopy(event)
        original, _, snapshots = structure.source_units([event], transcript)
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(event, before)
        self.assertIn('audit_history', snapshots[0]['source']['source_identity'])
        sent = [n for p in vision.payloads for n in p['CURRENT']]
        self.assertEqual([n['ref'] for n in sent], [n['ref'] for n in original])
        for node, full in zip(sent, original):
            self.assertEqual(node['proofs'][0]['id'], full['proofs'][0]['id'])
            self.assertEqual(node['proofs'][0]['ASR_ranges'], full['proofs'][0]['ASR_ranges'])
            self.assertNotIn('source', node['proofs'][0])
            self.assertNotIn('checkpoint', node['proofs'][0])
        self.assertNotIn('private-media', json.dumps(vision.payloads))


    def test_five_closed_arcs_are_inferred_inside_one_semantic_event(self):
        event, transcript = fixture(10)
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['id'], 'room')
        self.assertEqual(len(result['arcs']), 5)
        self.assertEqual([(a['start'], a['end']) for a in result['arcs']], [(i*8, i*8+8) for i in range(5)])
        self.assertTrue(all(a['complete_ending'] for a in result['arcs']))
        self.assertEqual(len(result['events'][0]['inferred_story_arcs']), 5)
        self.assertEqual(len(result['units']), 10)

    def test_fifty_source_units_have_bounded_complete_current_coverage(self):
        event, transcript = fixture(50)
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        owned = [u['ref'] for p in vision.payloads for u in p['CURRENT']]
        self.assertEqual(len(owned), 50)
        self.assertEqual(len({structure._key(r) for r in owned}), 50)
        self.assertGreater(len(vision.calls), 1)
        self.assertTrue(all(len(p['CURRENT']) <= structure.POLICY['max_current_units'] for p in vision.payloads))
        self.assertTrue(all(len(p['CONTEXT_ONLY']) <= 4 and len(p['MEMORY']) <= 4 for p in vision.payloads))
        self.assertTrue(all(len(prompt)//4 <= structure.POLICY['local_input_tokens'] for prompt in vision.prompts))
        self.assertTrue(all(r['structure_status'] == 'accepted' for r in result['coverage']))

    def test_same_unit_id_in_different_events_is_scoped(self):
        first, t1 = fixture(identifier='a')
        second, t2 = fixture(identifier='b', start=8)
        transcript = {'words': t1['words']+t2['words'], 'segments': t1['segments']+t2['segments']}
        result = self.infer([first, second], transcript)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(result['arcs']), 2)
        self.assertEqual(len({structure._key(u['ref']) for u in result['units']}), 4)

    def test_schema_and_validator_reject_invented_timestamps_and_unknown_unit(self):
        for mutate in (lambda d: d['arcs'][0].update(start=0),
                       lambda d: d['units'][0]['ref'].update(unit='invented')):
            def bad(payload):
                decision = response(payload); mutate(decision); return decision
            with self.subTest(mutation=mutate):
                result = self.infer(vision=FakeProvider(bad))
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['arcs'], [])
                self.assertTrue(result['events'][0]['analysis_unresolved'])

    def test_duplicate_or_missing_current_roles_are_invalid(self):
        for mutate in (lambda d: d['units'].pop(), lambda d: d['units'].append(copy.deepcopy(d['units'][0]))):
            def bad(payload):
                decision = response(payload); mutate(decision); return decision
            with self.subTest(mutation=mutate):
                result = self.infer(vision=FakeProvider(bad))
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['arcs'], [])

    def test_context_only_unit_cannot_receive_a_current_assignment(self):
        e, transcript = fixture(4)
        def bad(payload):
            decision = response(payload)
            decision['units'][0]['ref'] = payload['CONTEXT_ONLY'][0]['ref']
            return decision
        with patch.dict(structure.POLICY, max_current_units=2):
            result = self.infer([e], transcript, FakeProvider(bad))
        self.assertEqual(result['status'], 'unresolved')

    def test_each_confidence_dimension_must_meet_threshold(self):
        for dimension in ('understanding_confidence', 'structure_confidence'):
            def uncertain(payload):
                decision = response(payload); decision[dimension] = .89; return decision
            with self.subTest(dimension=dimension):
                result = self.infer(vision=FakeProvider(uncertain))
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['arcs'], [])
                self.assertEqual(result['events'][0]['selected_ranges'], [{'start': 0, 'end': 8}])

    def test_nonfinite_confidence_and_truthy_nonboolean_flags_are_invalid(self):
        changes = [('understanding_confidence', True), ('structure_confidence', float('nan')),
                   ('structure_confidence', float('inf')), ('resolved', 'true')]
        for key, value in changes:
            def malformed(payload):
                decision = response(payload); decision[key] = value; return decision
            with self.subTest(key=key, value=value):
                result = self.infer(vision=FakeProvider(malformed))
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['arcs'], [])

    def test_missing_causal_resolution_does_not_create_closed_ending(self):
        def bad(payload):
            decision = response(payload); decision['relations'] = []; return decision
        result = self.infer(vision=FakeProvider(bad))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])

    def test_partial_arc_is_explicitly_unresolved_not_closed_at_batch_end(self):
        def partial(payload):
            decision = response(payload)
            decision['arcs'][0].update(closed=False, closing_unit=None)
            return decision
        result = self.infer(vision=FakeProvider(partial))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(len(result['arcs']), 1)
        self.assertFalse(result['arcs'][0]['complete_ending'])
        self.assertIn('partial_arc_context_unresolved', result['arcs'][0]['boundary_reason'])

    def test_unknown_roles_and_facts_stay_unknown(self):
        def unknown(payload):
            decision = response(payload)
            decision.update(arcs=[], relations=[])
            for row in decision['units']:
                row.update(roles=['unknown'], confidence=0, support=[])
            return decision
        result = self.infer(vision=FakeProvider(unknown))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])
        self.assertEqual(result['canonical_facts'], [])
        self.assertTrue(all(u.get('before', facts()) == facts() for u in result['units']))

    def test_roles_without_source_arc_membership_remain_unresolved(self):
        def no_arcs(payload):
            decision = response(payload); decision['arcs'] = []; return decision
        result = self.infer(vision=FakeProvider(no_arcs))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(len(result['unresolved_refs']), 2)

    def test_relation_support_cannot_borrow_another_unit_proof_or_invent_quote(self):
        for mutate in (lambda d: d['relations'][0]['support'][0].update(quote='Несуществующая реплика'),
                       lambda d: d['relations'][0]['support'][0].update(proof=d['relations'][0]['support'][1]['proof'])):
            def bad(payload):
                decision = response(payload); mutate(decision); return decision
            with self.subTest(mutation=mutate):
                result = self.infer(vision=FakeProvider(bad))
                self.assertEqual(result['status'], 'unresolved')

    def test_canonical_location_synonyms_require_actual_mention_links(self):
        a, t1 = fixture(identifier='a')
        b, t2 = fixture(identifier='b', start=8)
        a.update(state_before={'locations': ['в машине']}, state_after={'locations': ['в машине']})
        b.update(state_before={'locations': ['салон автомобиля']}, state_after={'locations': ['салон автомобиля']})
        transcript = {'words': t1['words']+t2['words'], 'segments': t1['segments']+t2['segments']}
        def canonical(payload):
            decision = response(payload)
            mentions = []
            for node in payload['CURRENT']:
                field = next(f for f in node['mentions'] if f.startswith('state_'))
                observed = node['mentions'][field]
                mentions.append({'ref': node['ref'], 'field': field, 'text': observed['text'], 'proof': observed['proof_ids'][0]})
            decision['canonical_entities'] = [{'id': 'car_interior', 'kind': 'location', 'label': 'в машине',
                'mentions': mentions, 'confidence': .95}]
            for row in decision['units']:
                node = next(n for n in payload['CURRENT'] if n['ref'] == row['ref'])
                for side in ('before', 'after'):
                    if any(f.startswith('state_'+side+'.') for f in node['mentions']):
                        row[side]['location_id'] = 'car_interior'
            return decision
        result = self.infer([a, b], transcript, FakeProvider(canonical))
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(result['canonical_facts']), 1)
        self.assertEqual({u[side]['location_id'] for u in result['units'] for side in ('before', 'after')}, {'car_interior', None})
        self.assertEqual({m['text'] for m in result['canonical_facts'][0]['mentions']}, {'в машине', 'салон автомобиля'})

    def test_after_endpoint_fact_cannot_be_relabelled_as_before_without_current_proof(self):
        event, transcript = fixture()
        event['state_after'] = {'character_state': 'связан'}
        def borrowed(payload):
            decision = response(payload); node = payload['CURRENT'][-1]
            field = 'state_after.character_state.0'
            mention = node['mentions'][field]
            decision['canonical_entities'] = [{'id': 'bound', 'kind': 'physical_state', 'label': 'связан',
                'confidence': .95, 'mentions': [{'ref': node['ref'], 'field': field, 'text': 'связан',
                                               'proof': mention['proof_ids'][0]}]}]
            decision['units'][-1]['before']['physical_state_ids'] = ['bound']
            return decision
        result = self.infer([event], transcript, FakeProvider(borrowed))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['canonical_facts'], [])

    def test_invented_canonical_mention_or_entity_name_is_rejected(self):
        for label, phrase in (('invented_person_name', 'Где'), ('Где', 'несуществующее место')):
            def invented(payload):
                decision = response(payload); n = payload['CURRENT'][0]
                decision['canonical_entities'] = [{'id': 'person', 'kind': 'character', 'label': label, 'confidence': .95,
                    'mentions': [{'ref': n['ref'], 'field': 'ASR', 'text': phrase, 'proof': n['proofs'][0]['id']}]}]
                return decision
            with self.subTest(label=label):
                result = self.infer(vision=FakeProvider(invented))
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['canonical_facts'], [])

    def test_physical_action_without_actual_frame_proof_is_not_structure_input(self):
        event, transcript = fixture()
        event['unit_evidence'][0]['kind'] = 'physical_action'
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(any(r['status'] == 'unresolved_source_proof' for r in result['coverage']))
        self.assertFalse(any(p['kind'] == 'physical_action' for n in result['units'] for p in n['proofs']))

    def test_accepted_actual_current_frame_references_are_inherited_without_new_images(self):
        event, transcript = fixture()
        event['unit_evidence'][0].update(kind='physical_action', speech_quote='',
            frame_indices=[1, 2], frame_times=[.5, 2.5], frame_count=2,
            evidence='The source character visibly ties the other character wrists with rope.')
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        inherited = result['units'][0]['proofs'][0]
        self.assertEqual(inherited['frame_times'], [.5, 2.5])
        self.assertEqual(inherited['source_frame_indices'], [1, 2])
        self.assertEqual(inherited['frame_count'], 2)
        self.assertEqual(inherited['checkpoint'], 'a'*64)
        self.assertTrue(all(c['image'] is None for c in vision.calls))
        self.assertFalse(result['arcs'][0]['verification']['visual_reverification'])

    def test_context_or_excluded_frame_cannot_support_current_canonical_fact(self):
        event, transcript = fixture()
        event['unit_evidence'][0].update(kind='physical_action', speech_quote='',
            frame_indices=[1, 2], frame_times=[.5, 5.5], frame_count=2,
            evidence='The source character visibly ties the other character wrists with rope.')
        result = self.infer([event], transcript)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(any(r['status'] == 'unresolved_source_proof' for r in result['coverage']))
        self.assertFalse(any(p['kind'] == 'physical_action' for n in result['units'] for p in n['proofs']))

    def test_visual_proof_without_source_frame_count_cannot_create_arcs_or_facts(self):
        event, transcript = visual_fixture()
        for record in event['unit_evidence']:
            record.pop('frame_count')
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])
        self.assertEqual(result['canonical_facts'], [])
        self.assertEqual(vision.calls, [])

    def test_out_of_domain_or_repeated_visual_indices_do_not_enter_canonical_input(self):
        for changes in ({'frame_indices': [999]}, {'frame_count': 0}, {'frame_count': True}, {'frame_count': 1.0},
                        {'frame_indices': [1, 1], 'frame_times': [.5, 1.5]}):
            event, transcript = visual_fixture()
            event['unit_evidence'][0].update(changes)
            with self.subTest(changes=changes):
                current, coverage, snapshots = structure.source_units([event], transcript)
                self.assertFalse(any(n['ref']['unit'] == 'c000_u000' for n in current))
                self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')

    def test_missing_mismatched_or_nonfinite_source_times_do_not_enter_canonical_input(self):
        changes = [{'frame_times': []}, {'frame_times': [.5, 1.5]}, {'frame_times': [float('nan')]},
                   {'frame_times': [float('inf')]}, {'frame_times': [True]}, {'frame_times': ['.5']}]
        for change in changes:
            event, transcript = visual_fixture()
            event['unit_evidence'][0].update(change)
            with self.subTest(change=change):
                current, coverage, snapshots = structure.source_units([event], transcript)
                self.assertFalse(any(n['ref']['unit'] == 'c000_u000' for n in current))
                self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')
        event, transcript = visual_fixture()
        event['unit_evidence'][0].pop('frame_times')
        current, coverage, snapshots = structure.source_units([event], transcript)
        self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')

    def test_every_visual_time_belongs_to_exact_current_unit_and_view(self):
        cases = [{'frame_indices': [1, 2], 'frame_count': 2, 'frame_times': [.5, 4]},
                 {'frame_indices': [1, 2], 'frame_count': 2, 'frame_times': [.5, 5.5]},
                 {'frame_indices': [1, 2], 'frame_count': 2, 'frame_times': [.5, 2.5], 'view_start': 0, 'view_end': 2}]
        for change in cases:
            event, transcript = visual_fixture()
            event['unit_evidence'][0].update(change)
            with self.subTest(change=change):
                current, coverage, snapshots = structure.source_units([event], transcript)
                self.assertFalse(any(n['ref']['unit'] == 'c000_u000' for n in current))
                self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')

    def test_speech_only_source_quote_uses_actual_asr_instead_of_authored_unit_text(self):
        event, transcript = fixture()
        event['unit_evidence'][0]['speech_quote'] = event['units'][0]['text']
        current, coverage, snapshots = structure.source_units([event], transcript)
        self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')
        self.assertFalse(any(n['ref']['unit'] == 'c000_u000' for n in current))
        event['unit_evidence'][0]['speech_quote'] = transcript['words'][0]['text']
        result = self.infer([event], transcript)
        self.assertEqual(result['status'], 'accepted')

    def test_partial_positive_view_cannot_authorize_whole_selected_unit_asr(self):
        event, transcript = visual_fixture()
        event['unit_evidence'][0].update(view_start=0, view_end=1)
        current, coverage, _ = structure.source_units([event], transcript)
        self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')
        self.assertFalse(any(n['ref']['unit'] == 'c000_u000' for n in current))
        result = self.infer([event], transcript)
        self.assertEqual(result['status'], 'unresolved')
        self.assertFalse(any(u['ref']['unit'] == 'c000_u000' for u in result['units']))
        self.assertEqual(result['events'][0]['selected_ranges'], event['selected_ranges'])

    def test_partial_proof_can_cover_exact_selected_piece_without_envelope_asr(self):
        event, transcript = visual_fixture()
        event['selected_ranges'] = [{'start': 0, 'end': 1}, {'start': 4, 'end': 8}]
        event['unit_evidence'][0].update(view_start=0, view_end=1)
        current, coverage, _ = structure.source_units([event], transcript)
        self.assertEqual(coverage[0]['status'], 'CURRENT')
        self.assertEqual(current[0]['source_ranges'], [{'start': 0, 'end': 1}])
        self.assertEqual(current[0]['ASR'], '')
        self.assertEqual(self.infer([event], transcript)['status'], 'accepted')

    def split_proof_fixture(self):
        event, transcript = fixture()
        transcript['words'].append({'start': 2.5, 'end': 3, 'text': 'Ответ получен.'})
        transcript['words'].sort(key=lambda w: w['start'])
        transcript['segments'] = copy.deepcopy(transcript['words'])
        event['unit_evidence'][0].update(view_start=0, view_end=2)
        event['unit_evidence'].append({**event['unit_evidence'][0], 'view_start': 2, 'view_end': 4,
                                      'speech_quote': 'Ответ получен.', 'checkpoint': 'b'*64})
        return event, transcript

    def split_proof_response(self, payload):
        result = response(payload)
        by_ref = {structure._key(n['ref']): n for n in nodes(payload)}
        rows = [*result['units'], *result['relations'], *result['arcs']]
        for row in rows:
            for citation in row['support']:
                proof = next(p for p in by_ref[structure._key(citation['ref'])]['proofs']
                             if p['id'] == citation['proof'])
                citation['quote'] = proof['speech_quote']
        return result

    def test_union_of_multiple_accepted_proofs_covers_whole_selected_unit(self):
        event, transcript = self.split_proof_fixture()
        current, coverage, _ = structure.source_units([event], transcript)
        self.assertEqual(coverage[0]['status'], 'CURRENT')
        self.assertEqual(len(current[0]['proofs']), 2)
        self.assertEqual(current[0]['proofs'][0]['ASR_ranges'], [{'start': 0, 'end': 2, 'text': 'Где ключ?'}])
        result = self.infer([event], transcript, FakeProvider(self.split_proof_response))
        self.assertEqual(result['status'], 'accepted')

    def test_support_quote_cannot_borrow_asr_from_another_proof_of_same_unit(self):
        event, transcript = self.split_proof_fixture()
        def wrong(payload):
            result = self.split_proof_response(payload)
            result['units'][0]['support'][0]['quote'] = 'Ответ получен'
            return result
        result = self.infer([event], transcript, FakeProvider(wrong))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])

    def test_canonical_asr_mention_must_belong_to_cited_proof_interval(self):
        event, transcript = self.split_proof_fixture()
        def wrong(payload):
            result = self.split_proof_response(payload)
            node = payload['CURRENT'][0]
            result['canonical_entities'] = [{'id': 'answer', 'kind': 'topic', 'label': 'Ответ получен',
                'confidence': .95, 'mentions': [{'ref': node['ref'], 'field': 'ASR',
                    'text': 'Ответ получен', 'proof': node['proofs'][0]['id']}]}]
            return result
        result = self.infer([event], transcript, FakeProvider(wrong))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['canonical_facts'], [])

    def test_whole_confirmed_credits_never_enter_arc_or_context(self):
        a, t1 = fixture(identifier='plot')
        b, t2 = fixture(identifier='credits', start=8)
        b['excluded_credit_ranges'] = [{'start': 8, 'end': 16}]
        transcript = {'words': t1['words']+t2['words'], 'segments': t1['segments']+t2['segments']}
        vision = FakeProvider()
        result = self.infer([a, b], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(result['arcs']), 1)
        self.assertEqual(result['arcs'][0]['event_ids'], ['plot'])
        self.assertTrue(all(n['ref']['event'] != 'credits' for p in vision.payloads for n in nodes(p)))
        self.assertEqual(result['events'][1]['selected_ranges'], b['selected_ranges'])

    def test_missing_actual_units_does_not_create_endpoint_context_or_positional_arc(self):
        event, transcript = fixture()
        event['units'] = []
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])
        self.assertEqual(vision.calls, [])
        self.assertEqual(result['events'][0]['selected_ranges'], event['selected_ranges'])

    def test_empty_verified_selection_does_not_generate_an_arc(self):
        event, transcript = fixture()
        event.update(selected_ranges=[], selection_empty_verified=True)
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['arcs'], [])
        self.assertEqual(vision.calls, [])
        self.assertEqual(result['events'][0]['selected_ranges'], [])

    def test_word_crossing_source_units_are_rejected(self):
        event, transcript = fixture()
        transcript['words'].append({'start': 3.8, 'end': 4.2, 'text': 'crossing'})
        result = self.infer([event], transcript)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])

    def test_oversized_source_unit_remains_unresolved_with_coverage_not_truncated(self):
        vision = FakeProvider(token_counter=lambda prompt: 99999)
        result = self.infer(vision=vision)
        self.assertEqual(vision.calls, [])
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(len(result['unresolved_refs']), 2)
        self.assertTrue(all(h['reason'] == 'source_unit_exceeds_text_context' for h in result['history']))

    def test_optional_neighbors_cannot_hide_a_current_unit_that_fits_alone(self):
        event, transcript = fixture(4)
        original = copy.deepcopy((event, transcript))
        vision = FakeProvider()
        limit = structure._context_limit(vision)
        def count(prompt):
            payload = json.loads(prompt.rsplit('\n', 1)[1])
            return limit+1 if (len(payload['CURRENT']) > 1 or payload['CONTEXT_ONLY']
                               or payload['MEMORY'] or payload['CANONICAL_REGISTRY']) else limit
        vision.token_counter = count
        result = self.infer([event], transcript, vision)
        # Missing relationship context stays unresolved, but no actual CURRENT
        # evidence is silently skipped or reported as too large.
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(all(h['status'] == 'accepted' for h in result['history']))
        self.assertEqual(len(vision.calls), 4)
        self.assertEqual([p['CURRENT'][0]['ref']['unit'] for p in vision.payloads],
                         [u['id'] for u in event['units']])
        self.assertTrue(all(not p['CONTEXT_ONLY'] for p in vision.payloads))
        self.assertEqual((event, transcript), original)

    def test_rejected_structure_is_reasked_with_same_owned_evidence(self):
        calls = 0
        def first_invalid(payload):
            nonlocal calls
            calls += 1
            decision = response(payload)
            if calls == 1:
                decision['units'].pop()
            return decision
        vision = FakeProvider(first_invalid)
        result = self.infer(vision=vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(vision.calls), 2)
        self.assertEqual(vision.payloads[0], vision.payloads[1])
        self.assertIn('previous response failed source validation', vision.prompts[1])
        self.assertEqual(len(result['units']), 2)

    def test_local_input_output_and_template_reserve_fit_8192_context(self):
        vision = FakeProvider()
        policy = structure.POLICY
        self.assertLessEqual(policy['local_input_tokens']+policy['output_tokens']+policy['template_reserve'], 8192)
        self.assertLessEqual(structure._context_limit(vision)+policy['output_tokens']+policy['template_reserve'], 8192)
        with patch.dict(policy, template_reserve=1000):
            self.assertLessEqual(structure._context_limit(vision)+policy['output_tokens']+policy['template_reserve'], 8192)

    def test_provider_token_count_at_boundary_is_submitted_and_above_boundary_is_unresolved(self):
        vision = FakeProvider()
        limit = structure._context_limit(vision)
        vision.token_counter = lambda text: limit
        result = self.infer(vision=vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(vision.calls), 1)
        other = FakeProvider(token_counter=lambda text: limit+1)
        result = self.infer(vision=other)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(other.calls, [])

    def test_local_thinking_boundary_reserves_actual_adapter_extra_output(self):
        from app.vision import LocalVision

        vision = FakeProvider()
        vision.thinking = True
        limit = structure._context_limit(vision)
        self.assertEqual(limit, 3680)
        vision.token_counter = lambda prompt: limit
        result = self.infer(vision=vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(vision.calls), 1)

        # Exercise the real HTTP-body builder with a mocked response, no server/GPU.
        adapter = object.__new__(LocalVision)
        adapter.thinking, adapter.port, adapter.api_key = True, 1, 'authored-mechanism'
        adapter.cancelled = lambda: False
        adapter.opener = Mock()
        adapter.opener.open.return_value = io.BytesIO(json.dumps({
            'choices': [{'message': {'content': '{}'}}]}).encode('utf-8'))
        adapter.query('authored prompt', max_tokens=vision.calls[0]['max_tokens'])
        body = json.loads(adapter.opener.open.call_args.args[0].data)
        self.assertEqual(body['max_tokens'], 3712)
        self.assertEqual(limit+body['max_tokens']+structure.POLICY['template_reserve'], 8192)

        oversized = FakeProvider(token_counter=lambda prompt: limit+1)
        oversized.thinking = True
        result = self.infer(vision=oversized)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(oversized.calls, [])
        self.assertEqual(structure._context_limit(FakeProvider()), 4096)

    def test_remote_thinking_reserves_extra_budget(self):
        vision = FakeProvider()
        vision.text_budget, vision.thinking = 64000, True
        self.assertEqual(structure._context_limit(vision), 59488)
        vision.text_budget = 20000
        self.assertEqual(structure._context_limit(vision), 15488)
        self.assertEqual(structure._context_limit(vision)+structure.POLICY['output_tokens']
                         +structure.POLICY['template_reserve']+structure.POLICY['reasoning_reserve'], 20000)
        vision.thinking = False
        self.assertEqual(structure._context_limit(vision), 16000)

    def test_cache_reuse_is_stable_and_semantic_source_changes_invalidate(self):
        event, transcript = fixture()
        vision = FakeProvider()
        first = self.infer([event], transcript, vision)
        second = self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 1)
        self.assertEqual(first, second)
        event['summary'] += ' New internally generated hypothesis.'
        self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 2)
        event['unit_evidence'][0]['checkpoint'] = 'b'*64
        self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 3)

    def test_normalized_prompt_model_and_source_proof_cache_identity(self):
        event, transcript = fixture()
        vision = FakeProvider()
        self.infer([event], transcript, vision)
        with patch.object(structure, 'STORY_STRUCTURE_PROMPT', structure.STORY_STRUCTURE_PROMPT.replace('\n', '\r\n')):
            self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 1)
        with patch.object(structure, 'STORY_STRUCTURE_PROMPT', structure.STORY_STRUCTURE_PROMPT+'\nNew factual verification rule.'):
            self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 2)
        vision.model = 'another_authored_mechanism_model'
        self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 3)

    def test_volatile_cache_flags_do_not_change_source_identity(self):
        event, transcript = fixture()
        vision = FakeProvider()
        first = self.infer([event], transcript, vision)
        event['unit_evidence'][0]['cache_hit'] = True
        event['source_identity']['visual_cache_hit'] = True
        second = self.infer([event], transcript, vision)
        self.assertEqual(len(vision.calls), 1)
        self.assertEqual(first['arcs'], second['arcs'])

    def test_corrupt_or_invalid_checkpoint_is_rebuilt(self):
        vision = FakeProvider()
        self.infer(vision=vision)
        checkpoint = next(p for p in (self.job/'story-structure').glob('*.json') if p.name != 'story_structure.json')
        checkpoint.write_text('{corrupt', encoding='utf-8')
        self.infer(vision=vision)
        self.assertEqual(len(vision.calls), 2)
        saved = json.loads(checkpoint.read_text('utf-8'))
        saved['decision']['units'].pop()
        checkpoint.write_text(json.dumps(saved), encoding='utf-8')
        self.infer(vision=vision)
        self.assertEqual(len(vision.calls), 3)

    def test_quality_error_is_redacted_explicit_unresolved_and_diagnostic_saved(self):
        def failed(payload):
            raise RuntimeError('Synthetic failure Bearer test-secret')
        result = self.infer(vision=FakeProvider(failed))
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['arcs'], [])
        self.assertEqual(result['history'][0]['reason'], 'model_failure')
        self.assertNotIn('test-secret', result['history'][0]['error'])
        saved = json.loads((self.job/'story-structure/story_structure.json').read_text('utf-8'))
        self.assertEqual(saved['status'], 'unresolved')
        self.assertEqual(saved['events'][0]['selected_ranges'], [{'start': 0, 'end': 8}])

    def test_temporary_structure_failure_can_retry_without_invalidating_primary_selection(self):
        event, transcript = fixture()
        def failed(payload):
            raise RuntimeError('temporary authored mechanism error')
        first = self.infer([event], transcript, FakeProvider(failed))
        self.assertTrue(first['events'][0]['analysis_unresolved'])
        second = self.infer(first['events'], transcript, FakeProvider())
        self.assertEqual(second['status'], 'accepted')
        self.assertFalse(second['events'][0]['analysis_unresolved'])
        self.assertEqual(second['events'][0]['analysis_unresolved_reasons'], [])
        self.assertEqual(second['events'][0]['selected_ranges'], event['selected_ranges'])

    def test_primary_unresolved_analysis_is_never_cleared_by_structure_pass(self):
        event, transcript = fixture()
        event.update(analysis_unresolved=True, analysis_unresolved_reasons=['source_selection_uncertain'])
        vision = FakeProvider()
        result = self.infer([event], transcript, vision)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(vision.calls, [])
        self.assertTrue(result['events'][0]['analysis_unresolved'])
        self.assertIn('source_selection_uncertain', result['events'][0]['analysis_unresolved_reasons'])

    def test_downstream_only_unresolved_does_not_invalidate_accepted_source_proofs(self):
        event, transcript = fixture()
        event.update(analysis_unresolved=True,
                     analysis_unresolved_reasons=['story_structure_unresolved', 'dialogue_relations_unresolved'])
        result = self.infer([event], transcript)
        self.assertEqual(result['status'], 'accepted')
        updated = result['events'][0]
        self.assertTrue(updated['analysis_unresolved'])
        self.assertEqual(updated['analysis_unresolved_reasons'], ['dialogue_relations_unresolved'])
        self.assertEqual(updated['selected_ranges'], event['selected_ranges'])
        self.assertEqual(updated['selection_status'], 'accepted')
        self.assertEqual(updated['selection_confidence'], .95)

    def test_downstream_reasons_never_override_primary_selection_flags(self):
        for flag in ('uncertain', 'selection_uncertain', 'source_role_unresolved',
                     'global_verification_unresolved', 'selection_needs_adjudication'):
            event, transcript = fixture()
            event.update(analysis_unresolved=True, analysis_unresolved_reasons=['dialogue_relations_unresolved'])
            event[flag] = True
            vision = FakeProvider()
            with self.subTest(flag=flag):
                result = self.infer([event], transcript, vision)
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(vision.calls, [])
                self.assertTrue(result['events'][0][flag])

    def test_provider_control_errors_and_wrapped_tls_propagate(self):
        from app.deepseek import BudgetExceeded, RemoteError
        from app.jobs import BusyError
        errors = [BudgetExceeded('mechanism budget'), RemoteError('mechanism remote'), BusyError('mechanism busy'),
                  urllib.error.HTTPError('http://example.invalid', 401, 'mechanism auth', {}, None),
                  ssl.SSLError('mechanism TLS'), InterruptedError('mechanism cancel')]
        wrapped = RuntimeError('wrapped mechanism control')
        wrapped.__cause__ = ssl.SSLError('underlying mechanism TLS')
        errors.append(wrapped)
        for error in errors:
            def failure(payload):
                raise error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.infer(vision=FakeProvider(failure))

    def test_cancellation_before_provider_call_propagates(self):
        vision = FakeProvider()
        with self.assertRaises(InterruptedError):
            self.infer(vision=vision, cancelled=lambda: True)
        self.assertEqual(vision.calls, [])


if __name__ == '__main__':
    unittest.main()
