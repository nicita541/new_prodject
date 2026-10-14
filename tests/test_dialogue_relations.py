"""Authored mechanism tests only; fake responses are not semantic quality proof."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import ssl
import unittest
import urllib.error
import uuid
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in (HERE, *HERE.parents) if (p/'tools/python/python.exe').is_file())
spec = importlib.util.spec_from_file_location('candidate_dialogue_relations', HERE/'app/dialogue_relations.py')
dialogue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dialogue)


def load_structure():
    path = HERE/'app/story_structure_pass.py'
    module_spec = importlib.util.spec_from_file_location('dialogue_compat_structure', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def transcript_rows(phrases, gap=1.0, speakers=None):
    words, segments, start = [], [], .5
    for i, text in enumerate(phrases):
        entries = text.split()
        speaker = speakers[i] if speakers is not None else None
        for j, word in enumerate(entries):
            words.append({'start': start+j*.4, 'end': start+j*.4+.3,
                          'text': word, 'speaker': speaker})
        end = words[-1]['end']
        segments.append({'start': start, 'end': end, 'text': text, 'speaker': speaker})
        start = end+gap
    return {'words': words, 'segments': segments}


def fixture(count=2):
    phrases = ['Где лежит папка' if i % 2 == 0 else 'Она в нижнем ящике' for i in range(count)]
    transcript = transcript_rows(phrases)
    units, records, previous = [], [], 0
    for i, segment in enumerate(transcript['segments']):
        end = transcript['segments'][i+1]['start']-.1 if i+1 < count else segment['end']+.2
        uid = f'u{i:03d}'
        units.append({'id': uid, 'start': previous, 'end': end, 'text': 'Authored cached text must be ignored'})
        records.append({'unit': uid, 'decision': 'keep', 'kind': 'causal_dialogue' if i % 2 == 0 else 'response',
            'confidence': .95, 'evidence': 'Accepted source speech is anchored to this actual source unit.',
            'speech_quote': segment['text'], 'frame_indices': [], 'frame_times': [],
            'view_start': previous, 'view_end': end, 'checkpoint': 'a'*64})
        previous = end
    event = {'id': 'scene', 'start': 0, 'end': previous, 'selection_status': 'accepted',
        'understanding_status': 'accepted', 'selection_confidence': .95, 'understanding_confidence': .95,
        'selected_ranges': [{'start': 0, 'end': previous}], 'units': units, 'unit_evidence': records,
        'source_identity': {'sha256': 'authored-source-mechanism', 'size': 10}}
    return [event], transcript


def support(node, quote=None):
    return {'ref': node['ref'], 'proof': node['proofs'][0]['id'], 'quote': node['ASR'] if quote is None else quote}


def provider_response(payload):
    nodes = sorted([*payload['CURRENT'], *payload['CONTEXT_ONLY']], key=lambda n: n['start'])
    current = {(n['ref']['event'], n['ref']['unit']) for n in payload['CURRENT']}
    pairs, participants = [], set()
    for i, node in enumerate(nodes[:-1]):
        answer = nodes[i+1]
        if not node['ASR'].startswith('Где') or not answer['ASR'].startswith('Она'):
            continue
        refs = {(n['ref']['event'], n['ref']['unit']) for n in (node, answer)}
        if not refs.intersection(current):
            continue
        participants.update(refs)
        pairs.append({'question': node['ref'], 'answer': answer['ref'],
            'question_quote': node['ASR'], 'answer_quote': answer['ASR'], 'requires_answer': True,
            'confidence': .95, 'evidence': 'The actual response supplies the location requested in the source question.',
            'support': [support(node), support(answer)]})
    return {'resolved': True, 'understanding_confidence': .95, 'relation_confidence': .95,
        'pairs': pairs, 'coverage': [{'ref': n['ref'], 'decision': 'paired' if (n['ref']['event'], n['ref']['unit']) in participants
            else 'not_dialogue_dependency', 'confidence': .95,
            'evidence': 'The exact supplied source speech supports this explicit dialogue assessment.',
            'support': [support(n)]} for n in payload['CURRENT']], 'limitations': []}


class FakeProvider:
    model = 'authored-mechanism-model'
    projector = 'authored-text-profile'
    thinking = False

    def __init__(self, callback=provider_response, counter=None):
        self.callback, self.counter = callback, counter or (lambda prompt: len(prompt)//4)
        self.calls, self.prompts, self.payloads = [], [], []

    def token_count(self, prompt):
        return self.counter(prompt)

    def query(self, prompt, image=None, max_tokens=None, schema=None):
        payload = json.loads(prompt.rsplit('\n', 1)[1])
        self.calls.append({'image': image, 'max_tokens': max_tokens, 'schema': schema})
        self.prompts.append(prompt); self.payloads.append(payload)
        return self.callback(payload)


class DialogueCandidateTests(unittest.TestCase):
    def test_unpunctuated_question_and_concrete_location_answer(self):
        transcript = transcript_rows(['Где лежит папка', 'Она в нижнем ящике'])
        rows = dialogue.dialogue_pairs(transcript)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['status'], 'confirmed')
        self.assertTrue(row['requires_answer']); self.assertTrue(row['protect_bidirectional'])
        self.assertEqual(row['question_ranges'], [{'start': .5, 'end': 1.6}])
        self.assertEqual(row['answer_ranges'], [{k: transcript['segments'][1][k] for k in ('start', 'end')}])
        self.assertFalse(row['selection_authority'])

    def test_question_marks_are_optional_for_other_syntax(self):
        examples = [('Почему дверь закрыта', 'Потому что идёт ремонт'), ('Когда начнётся поездка', 'Завтра утром'),
                    ('Сколько осталось билетов', 'Три билета'), ('Работает ли лампа', 'Да работает')]
        for question, answer in examples:
            with self.subTest(question=question):
                self.assertEqual(dialogue.dialogue_pairs(transcript_rows([question, answer]))[0]['status'], 'confirmed')

    def test_question_mark_does_not_confirm_unrelated_following_turn(self):
        row = dialogue.dialogue_pairs(transcript_rows(['Где папка?', 'Сегодня хорошая погода']))[0]
        self.assertEqual(row['status'], 'ambiguous'); self.assertFalse(row['requires_answer'])

    def test_split_question_joins_actual_words_across_segments(self):
        transcript = transcript_rows(['Где лежит', 'папка', 'Она в нижнем ящике'], gap=.2)
        row = dialogue.dialogue_pairs(transcript)[0]
        self.assertEqual(row['status'], 'confirmed')
        self.assertEqual(row['evidence']['question_text'], 'Где лежит папка')
        self.assertEqual(row['question_ranges'][0]['end'], transcript['segments'][1]['end'])

    def test_merged_question_and_answer_split_only_at_actual_word_boundaries(self):
        transcript = transcript_rows(['Где лежит папка Она в нижнем ящике'])
        row = dialogue.dialogue_pairs(transcript)[0]
        self.assertEqual(row['status'], 'confirmed')
        self.assertEqual(row['question_ranges'][0]['end'], transcript['words'][2]['end'])
        self.assertEqual(row['answer_ranges'][0]['start'], transcript['words'][3]['start'])

    def test_merged_segment_without_words_is_explicitly_ambiguous(self):
        transcript = transcript_rows(['Где лежит папка Она в нижнем ящике'])
        transcript['words'] = []
        row = dialogue.dialogue_pairs(transcript)[0]
        self.assertEqual(row['status'], 'ambiguous'); self.assertEqual(row['answer_ranges'], [])
        self.assertEqual(row['question_ranges'], [{k: transcript['segments'][0][k] for k in ('start', 'end')}])

    def test_two_segment_quotes_without_word_times_use_whole_actual_segments(self):
        transcript = transcript_rows(['Где лежит папка', 'Она в нижнем ящике'])
        transcript['words'] = []
        row = dialogue.dialogue_pairs(transcript)[0]
        self.assertEqual(row['status'], 'confirmed'); self.assertFalse(row['evidence']['word_timed'])

    def test_known_same_speaker_is_conservative(self):
        row = dialogue.dialogue_pairs(transcript_rows(['Где лежит папка', 'Она в нижнем ящике'], speakers=['A', 'A']))[0]
        self.assertEqual(row['status'], 'ambiguous')
        self.assertIn('same_speaker_or_self_answer', row['reasons'])

    def test_known_speaker_change_supports_source_turn(self):
        row = dialogue.dialogue_pairs(transcript_rows(['Где лежит папка', 'Она в нижнем ящике'], speakers=['A', 'B']))[0]
        self.assertEqual(row['status'], 'confirmed')

    def test_quoted_rhetorical_and_reported_questions_do_not_confirm(self):
        for text in ['«Где папка»', 'Кто бы мог подумать', 'Он спросил где папка?']:
            with self.subTest(text=text):
                rows = dialogue.dialogue_pairs(transcript_rows([text, 'Она в нижнем ящике']))
                self.assertFalse(any(r['requires_answer'] for r in rows))

    def test_far_answer_remains_unresolved_instead_of_keeping_all_speech(self):
        row = dialogue.dialogue_pairs(transcript_rows(['Где лежит папка', 'Она в нижнем ящике'], gap=30))[0]
        self.assertEqual(row['status'], 'ambiguous'); self.assertEqual(row['answer_ranges'], [])

    def test_exact_source_words_are_sorted_without_inventing_timestamps(self):
        transcript = transcript_rows(['Где лежит папка', 'Она в нижнем ящике'])
        expected = dialogue.dialogue_pairs(transcript)
        transcript['words'].reverse(); transcript['segments'].reverse()
        actual = dialogue.dialogue_pairs(transcript)
        self.assertEqual(actual[0]['question_ranges'], expected[0]['question_ranges'])
        self.assertEqual(actual[0]['answer_ranges'], expected[0]['answer_ranges'])
        self.assertEqual(actual[0]['question_asr_refs'][0]['index'], len(transcript['words'])-1)

    def test_invalid_finite_boolean_overlap_and_empty_source_rejected(self):
        for mutation in ('nan', 'boolean', 'overlap', 'empty'):
            transcript = transcript_rows(['Где папка', 'Она в ящике'])
            if mutation == 'nan': transcript['words'][0]['start'] = float('nan')
            if mutation == 'boolean': transcript['words'][0]['start'] = True
            if mutation == 'overlap': transcript['words'][1]['start'] = transcript['words'][0]['start']
            if mutation == 'empty': transcript['words'][0]['text'] = ''
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                dialogue.dialogue_pairs(transcript)

    def test_no_question_does_not_create_a_dependency(self):
        self.assertEqual(dialogue.dialogue_pairs(transcript_rows(['Сегодня дождь', 'Пойдём домой'])), [])
        self.assertEqual(dialogue.dialogue_pairs({'words': [], 'segments': []}), [])

    def test_authoritative_exclusion_outranks_spoken_question_and_answer(self):
        events, transcript = fixture()
        events[0]['excluded_review_ranges'] = [copy.deepcopy(events[0]['units'][0])]
        row = dialogue.dialogue_pairs(transcript, events)[0]
        self.assertEqual(row['status'], 'excluded'); self.assertFalse(row['requires_answer'])

    def test_accepted_source_required_when_events_supplied(self):
        events, transcript = fixture()
        events[0]['selection_status'] = 'pending'
        row = dialogue.dialogue_pairs(transcript, events)[0]
        self.assertEqual(row['status'], 'ambiguous'); self.assertFalse(row['requires_answer'])

    def test_accepted_source_proof_survives_downstream_structure_uncertainty(self):
        events, transcript = fixture()
        events[0].update(analysis_unresolved=True, analysis_unresolved_reasons=['story_structure_unresolved'])
        row = dialogue.dialogue_pairs(transcript, events)[0]
        self.assertEqual(row['status'], 'confirmed')
        events[0]['analysis_unresolved_reasons'].append('selection_confidence_insufficient')
        self.assertEqual(dialogue.dialogue_pairs(transcript, events)[0]['status'], 'ambiguous')

    def test_proof_ids_match_current_structure_pass_and_scope(self):
        structure = load_structure()
        events, transcript = fixture()
        ours, _, _ = dialogue.source_units(events, transcript)
        theirs, _, _ = structure.source_units(events, transcript)
        self.assertEqual([n['ref'] for n in ours], [n['ref'] for n in theirs])
        self.assertEqual([p['id'] for n in ours for p in n['proofs']], [p['id'] for n in theirs for p in n['proofs']])
        self.assertEqual([p['ASR_ranges'] for n in ours for p in n['proofs']],
                         [p['ASR_ranges'] for n in theirs for p in n['proofs']])

    def test_pure_pass_has_exact_original_asr_refs_and_no_provider_or_file_io(self):
        transcript = transcript_rows(['Где лежит папка', 'Она в нижнем ящике'])
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected I/O')):
            row = dialogue.dialogue_pairs(transcript)[0]
        self.assertEqual(row['question_asr_refs'], [{'container': 'words', 'index': i} for i in range(3)])
        self.assertEqual(row['answer_asr_refs'], [{'container': 'words', 'index': i} for i in range(3, 7)])

    def test_source_unit_ref_scope_and_actual_asr_ignore_cached_text(self):
        events, transcript = fixture()
        row = dialogue.dialogue_pairs(transcript, events)[0]
        self.assertEqual(row['question_refs'], [{'event': 'scene', 'unit': 'u000'}])
        self.assertEqual(row['answer_refs'], [{'event': 'scene', 'unit': 'u001'}])
        self.assertEqual(row['status'], 'confirmed')

    def test_supported_structure_response_can_resolve_non_lexical_answer(self):
        events, transcript = fixture()
        segment = transcript['segments'][1]
        answer = 'Поищи нижний ящик'
        for word, text in zip([w for w in transcript['words'] if w['start'] >= segment['start']], answer.split()):
            word['text'] = text
        # Keep the fourth actual source token; the quote still matches whole source words.
        transcript['words'][-1]['text'] = 'стола'
        segment['text'] = answer+' стола'; events[0]['unit_evidence'][1]['speech_quote'] = segment['text']
        nodes, _, _ = dialogue.source_units(events, transcript)
        relation = {'type': 'response', 'from': nodes[0]['ref'], 'to': nodes[1]['ref'], 'confidence': .95,
            'evidence': 'The internally inferred source reply directs the speaker to the requested object.',
            'support': [support(n) for n in nodes]}
        row = dialogue.dialogue_pairs(transcript, events, {'status': 'accepted', 'relations': [relation]})[0]
        self.assertEqual(row['status'], 'confirmed'); self.assertEqual(row['method'], 'inherited_structure_response')

    def test_unknown_proof_or_unaccepted_structure_relation_cannot_authorize(self):
        events, transcript = fixture()
        nodes, _, _ = dialogue.source_units(events, transcript)
        relation = {'type': 'response', 'from': nodes[0]['ref'], 'to': nodes[1]['ref'], 'confidence': .95,
            'evidence': 'An internally inferred supported source response.', 'support': [support(n) for n in nodes]}
        relation['support'][1]['proof'] = 'foreign'
        self.assertEqual(dialogue._relation_pairs([relation], nodes), [])
        relation['support'][1] = support(nodes[1])
        self.assertEqual(dialogue._relation_pairs({'status': 'unresolved', 'relations': [relation]}, nodes), [])


class DialogueProviderTests(unittest.TestCase):
    def test_partial_batch_preserves_independently_supported_dialogue_rows(self):
        events, transcript = fixture(3)
        current, _, _ = dialogue.source_units(events, transcript)
        raw = provider_response({'CURRENT': current, 'CONTEXT_ONLY': [], 'INHERITED_RESPONSE_RELATIONS': []})
        raw['coverage'][-1].update(decision='unresolved', support=[])
        checked = dialogue.validate_dialogue(raw, current, current)
        self.assertFalse(checked['accepted'])
        self.assertEqual([r['ref'] for r in checked['accepted_coverage']], [n['ref'] for n in current[:-1]])
        self.assertTrue(all(p['status'] == 'confirmed' for p in checked['pairs']))
        raw['resolved'] = False
        checked = dialogue.validate_dialogue(raw, current, current)
        self.assertEqual(checked['accepted_coverage'], [])
        self.assertTrue(all(p['status'] == 'ambiguous' for p in checked['pairs']))

    def test_generation_requires_a_row_for_the_answer_and_each_other_current_ref(self):
        events, transcript = fixture(5)
        source, _, _ = dialogue.source_units(events, transcript)
        schema = dialogue.dialogue_schema(source, source)
        fields = schema['properties']
        self.assertLess(list(fields).index('pairs'), list(fields).index('coverage'))
        self.assertLess(list(fields).index('coverage'), list(fields).index('resolved'))
        coverage = fields['coverage']
        self.assertEqual((coverage['minItems'], coverage['maxItems']), (5, 5))
        for slot, n in zip(coverage['prefixItems'], source):
            self.assertEqual(slot['properties']['ref']['enum'], [n['ref']])

    def setUp(self):
        self.job = ROOT/'temp'/('dialogue-mechanism-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.job)

    def infer(self, events=None, transcript=None, vision=None, cancelled=lambda: False, **kwargs):
        if events is None:
            events, transcript = fixture()
        return dialogue.infer_dialogue_relations(events, transcript, self.job, vision or FakeProvider(), cancelled, **kwargs)

    def test_real_provider_contract_has_source_only_input_and_no_selection_mutation(self):
        events, transcript = fixture(); original = copy.deepcopy((events, transcript))
        vision = FakeProvider()
        result = self.infer(events, transcript, vision)
        self.assertEqual(result['status'], 'accepted'); self.assertEqual(len(result['pairs']), 1)
        self.assertEqual(result['pairs'][0]['question_ranges'][0]['start'], transcript['words'][0]['start'])
        self.assertIsNone(vision.calls[0]['image'])
        self.assertFalse(result['pairs'][0]['visual_reverification'])
        self.assertNotIn('summary', vision.payloads[0]['CURRENT'][0])
        self.assertEqual((events, transcript), original)
        self.assertEqual(result['pairs'][0]['method'], 'source_proof_text_relation')

    def test_actual_structure_pass_output_adapts_without_authored_unit_answers(self):
        structure = load_structure()
        events, transcript = fixture()
        def structure_response(payload):
            nodes = sorted([*payload['CURRENT'], *payload['CONTEXT_ONLY']], key=lambda n: n['start'])
            q, a = nodes[:2]
            facts = {'location_id': None, 'topic_id': None, 'relationship_state_id': None,
                'character_ids': [], 'physical_state_ids': [], 'object_ids': []}
            cited = [support(q), support(a)]
            evidence = 'The actual accepted source response resolves the observed source question.'
            return {'resolved': True, 'understanding_confidence': .95, 'structure_confidence': .95,
                'units': [{'ref': n['ref'], 'roles': ['setup' if n['ref'] == q['ref'] else 'payoff'],
                    'viewer_interest': [],
                    'before': copy.deepcopy(facts), 'after': copy.deepcopy(facts), 'confidence': .95,
                    'evidence': evidence, 'support': [support(n)]} for n in payload['CURRENT']],
                'relations': [{'type': 'response', 'from': q['ref'], 'to': a['ref'], 'confidence': .95,
                    'evidence': evidence, 'support': cited}],
                'arcs': [{'anchor': q['ref'], 'members': [{'ref': q['ref'], 'role': 'setup'},
                    {'ref': a['ref'], 'role': 'payoff'}], 'closed': True, 'closing_unit': a['ref'],
                    'confidence': .95, 'evidence': evidence, 'support': cited}],
                'canonical_entities': [], 'limitations': []}
        inherited = structure.infer_story_structure(events, transcript, self.job, FakeProvider(structure_response), lambda: False)
        self.assertEqual(inherited['status'], 'accepted')
        rows = dialogue.dialogue_pairs(transcript, inherited['events'], inherited)
        self.assertEqual(rows[0]['method'], 'inherited_structure_response')
        self.assertEqual(rows[0]['status'], 'confirmed')
        vision = FakeProvider()
        result = self.infer(inherited['events'], transcript, vision, relations=inherited)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(vision.payloads[0]['INHERITED_RESPONSE_RELATIONS']), 1)
        self.assertEqual(result['pairs'][0]['question_refs'], [{'event': 'scene', 'unit': 'u000'}])

    def test_schema_cannot_receive_timestamps_or_fixture_semantic_fields(self):
        vision = FakeProvider(); self.infer(vision=vision)
        schema = vision.calls[0]['schema']
        fields = schema['properties']['pairs']['items']['properties']
        self.assertNotIn('start', fields); self.assertNotIn('end', fields)
        self.assertFalse(schema['additionalProperties'])
        self.assertTrue(vision.payloads[0]['coverage_contract']['inspect_answers_and_questions'])

    def test_frame_domain_and_exact_asr_are_rechecked_through_live_gate(self):
        from app import selection_gate
        events, transcript = fixture()
        with patch.object(selection_gate, '_anchored', wraps=selection_gate._anchored) as guard:
            result = self.infer(events, transcript)
        self.assertEqual(result['status'], 'accepted'); self.assertGreaterEqual(guard.call_count, 2)
        self.assertEqual(guard.call_args_list[0].args[1]['text'], 'Где лежит папка')

    def test_partial_positive_proof_cannot_cover_a_whole_accepted_unit(self):
        events, transcript = fixture()
        record = events[0]['unit_evidence'][0]
        record.update(view_end=transcript['words'][0]['end'], speech_quote=transcript['words'][0]['text'])
        nodes, coverage, _ = dialogue.source_units(events, transcript)
        self.assertEqual(coverage[0]['status'], 'unresolved_source_proof')
        self.assertEqual(len(nodes), 1)
        result = self.infer(events, transcript)
        self.assertEqual(result['status'], 'unresolved'); self.assertEqual(result['pairs'], [])

    def test_cited_partial_proof_needs_other_cited_proof_to_cover_quote(self):
        events, transcript = fixture()
        first = events[0]['unit_evidence'][0]
        first.update(view_end=transcript['words'][0]['end'], speech_quote=transcript['words'][0]['text'])
        second = {**first, 'view_start': first['view_end'], 'view_end': events[0]['units'][0]['end'],
                  'speech_quote': 'лежит папка', 'checkpoint': 'b'*64}
        events[0]['unit_evidence'].append(second)
        nodes, _, _ = dialogue.source_units(events, transcript)
        known = {dialogue._key(n['ref']): n for n in nodes}
        node = nodes[0]
        with self.assertRaises(ValueError):
            dialogue._support([support(node)], known, [dialogue._key(node['ref'])])
        bad_support = [{**support(node), 'proof': p['id']} for p in node['proofs']]
        with self.assertRaises(ValueError):
            dialogue._support(bad_support, known, [dialogue._key(node['ref'])])
        all_support = [{**support(node, p['speech_quote']), 'proof': p['id']} for p in node['proofs']]
        self.assertEqual(len(dialogue._support(all_support, known, [dialogue._key(node['ref'])])), 2)

    def test_question_supported_in_multiple_proof_parts_retains_exact_source_words(self):
        events, transcript = fixture()
        first = events[0]['unit_evidence'][0]
        first.update(view_end=transcript['words'][0]['end'], speech_quote=transcript['words'][0]['text'])
        events[0]['unit_evidence'].append({**first, 'view_start': first['view_end'],
            'view_end': events[0]['units'][0]['end'], 'speech_quote': 'лежит папка', 'checkpoint': 'b'*64})
        def split_proof(payload):
            output = provider_response(payload)
            question = payload['CURRENT'][0]
            parts = [{**support(question, p['speech_quote']), 'proof': p['id']} for p in question['proofs']]
            output['pairs'][0]['support'] = [*parts, support(payload['CURRENT'][1])]
            output['coverage'][0]['support'] = parts
            return output
        result = self.infer(events, transcript, FakeProvider(split_proof))
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['pairs'][0]['question_asr_refs'], [{'container': 'words', 'index': i} for i in range(3)])

    def test_dropped_question_with_accepted_answer_stays_pending_after_provider_acceptance(self):
        events, transcript = fixture()
        event = events[0]; answer_unit = event['units'][1]
        event['selected_ranges'] = [{'start': answer_unit['start'], 'end': answer_unit['end']}]
        event['unit_evidence'][0].update(decision='drop', kind='static_neutral_view')
        original = copy.deepcopy(events)
        candidate = dialogue.dialogue_pairs(transcript, events)[0]
        self.assertEqual(candidate['status'], 'ambiguous'); self.assertFalse(candidate['requires_answer'])
        self.assertEqual(candidate['question_refs'], [{'event': 'scene', 'unit': 'u000'}])
        self.assertIn('source_selection_or_proof_unresolved', candidate['reasons'])
        vision = FakeProvider()
        result = self.infer(events, transcript, vision)
        self.assertEqual(result['history'][0]['status'], 'accepted')
        self.assertEqual(result['history'][0]['decision']['coverage'][0]['decision'], 'not_dialogue_dependency')
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn({'event': 'scene', 'unit': 'u000'}, result['unresolved_refs'])
        self.assertEqual(result['pairs'], [])
        self.assertEqual([n['ref']['unit'] for n in vision.payloads[0]['CURRENT']], ['u001'])
        self.assertEqual(events, original)

    def test_confirmed_nonstory_question_is_not_restored_as_pending_dependency(self):
        events, transcript = fixture()
        question, answer = events[0]['units']
        events[0]['selected_ranges'] = [{'start': answer['start'], 'end': answer['end']}]
        events[0]['excluded_review_ranges'] = [{'start': question['start'], 'end': question['end']}]
        result = self.infer(events, transcript)
        self.assertEqual(result['candidates'][0]['status'], 'excluded')
        self.assertEqual(result['status'], 'accepted'); self.assertEqual(result['unresolved_refs'], [])
        self.assertEqual(result['pairs'], [])

    def test_semantic_metadata_in_source_rows_never_enters_provider_input(self):
        events, transcript = fixture()
        events[0]['summary'] = 'UNTRUSTED_OPERATOR_ARCS'
        events[0]['requires_answer'] = 'UNTRUSTED_OPERATOR_ARCS'
        transcript['words'][0]['arc_id'] = 'UNTRUSTED_OPERATOR_ARCS'
        vision = FakeProvider(); result = self.infer(events, transcript, vision)
        self.assertEqual(result['status'], 'accepted')
        self.assertNotIn('UNTRUSTED_OPERATOR_ARCS', vision.prompts[0])

    def test_invalid_actual_frame_indices_times_and_confidence_fail_closed(self):
        for kind in ('out_of_domain', 'outside_unit', 'duplicates', 'missing_count', 'nonfinite'):
            events, transcript = fixture()
            record = events[0]['unit_evidence'][0]
            record.update(kind='physical_action', frame_indices=[1], frame_times=[.6], frame_count=1)
            if kind == 'out_of_domain': record['frame_indices'] = [2]
            if kind == 'outside_unit': record['frame_times'] = [events[0]['end']]
            if kind == 'duplicates': record.update(frame_indices=[1, 1], frame_times=[.6, .7])
            if kind == 'missing_count': record.pop('frame_count')
            if kind == 'nonfinite': record['confidence'] = float('nan')
            vision = FakeProvider()
            with self.subTest(kind=kind):
                if kind == 'nonfinite':
                    with self.assertRaises(ValueError): self.infer(events, transcript, vision)
                else:
                    result = self.infer(events, transcript, vision)
                    self.assertEqual(result['status'], 'unresolved')
                    self.assertFalse(any(p['requires_answer'] for p in result['pairs']))

    def test_split_and_same_unit_pair_use_distinct_actual_word_quotes(self):
        events, transcript = fixture()
        events[0]['units'] = [{'id': 'u', 'start': 0, 'end': events[0]['end']}]
        events[0]['unit_evidence'] = [{**events[0]['unit_evidence'][0], 'unit': 'u',
            'view_end': events[0]['end'], 'speech_quote': ' '.join(w['text'] for w in transcript['words'])}]
        def merged(payload):
            node = payload['CURRENT'][0]
            question, answer = transcript['segments'][0]['text'], transcript['segments'][1]['text']
            return {'resolved': True, 'understanding_confidence': .95, 'relation_confidence': .95,
                'pairs': [{'question': node['ref'], 'answer': node['ref'], 'question_quote': question,
                    'answer_quote': answer, 'requires_answer': True, 'confidence': .95,
                    'evidence': 'Two distinct observed utterances occur inside this actual source unit.',
                    'support': [support(node, question), support(node, answer)]}],
                'coverage': [{'ref': node['ref'], 'decision': 'paired', 'confidence': .95,
                    'evidence': 'The actual source unit contains a question and its responsive answer.',
                    'support': [support(node, question)]}], 'limitations': []}
        result = self.infer(events, transcript, FakeProvider(merged))
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['pairs'][0]['question_refs'], result['pairs'][0]['answer_refs'])
        self.assertLess(result['pairs'][0]['question_ranges'][0]['end'], result['pairs'][0]['answer_ranges'][0]['start'])

    def test_answer_then_question_is_supported_only_by_exact_provider_relation(self):
        events, transcript = fixture()
        for container in ('words', 'segments'):
            texts = [r['text'] for r in transcript[container]]
            # Preserve source timings, but reverse the two complete utterances.
            if container == 'segments':
                transcript[container][0]['text'], transcript[container][1]['text'] = texts[1], texts[0]
        # Rebuild ordinary ASR so its actual word counts match the reversed utterances.
        reversed_asr = transcript_rows(['Она в нижнем ящике', 'Где лежит папка'])
        events[0]['end'] = reversed_asr['segments'][-1]['end']+.2
        boundary = reversed_asr['segments'][1]['start']-.1
        for i, record in enumerate(events[0]['unit_evidence']):
            a, b = (0, boundary) if i == 0 else (boundary, events[0]['end'])
            events[0]['units'][i].update(start=a, end=b)
            record.update(view_start=a, view_end=b, speech_quote=reversed_asr['segments'][i]['text'])
        events[0]['selected_ranges'] = [{'start': 0, 'end': events[0]['end']}]
        def backwards(payload):
            output = provider_response(payload)
            answer, question = payload['CURRENT']
            output['pairs'] = [{'question': question['ref'], 'answer': answer['ref'],
                'question_quote': question['ASR'], 'answer_quote': answer['ASR'], 'requires_answer': True,
                'confidence': .95, 'evidence': 'The observed later question explicitly refers back to the earlier supplied answer.',
                'support': [support(question), support(answer)]}]
            for row in output['coverage']: row['decision'] = 'paired'
            return output
        result = self.infer(events, reversed_asr, FakeProvider(backwards))
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['pairs'][0]['source_order'], 'answer_then_question')
        self.assertTrue(result['pairs'][0]['protect_bidirectional'])

    def test_partial_coverage_cannot_mark_episode_accepted(self):
        def incomplete(payload):
            output = provider_response(payload); output['coverage'].pop()
            return output
        result = self.infer(vision=FakeProvider(incomplete))
        self.assertEqual(result['status'], 'unresolved'); self.assertEqual(result['pairs'], [])
        self.assertEqual(result['history'][0]['reason'], 'invalid_dialogue_contract')

    def test_duplicate_foreign_and_self_overlapping_quotes_rejected(self):
        for kind in ('duplicate', 'foreign_ref', 'foreign_proof', 'invented_quote', 'overlap', 'timestamp', 'bool_confidence', 'low_confidence'):
            def malformed(payload, kind=kind):
                output = provider_response(payload); pair = output['pairs'][0]
                if kind == 'duplicate': output['pairs'].append(copy.deepcopy(pair))
                if kind == 'foreign_ref': pair['answer']['event'] = 'foreign'
                if kind == 'foreign_proof': pair['support'][1]['proof'] = 'foreign'
                if kind == 'invented_quote': pair['answer_quote'] = 'Ответа в источнике нет'
                if kind == 'overlap': pair['answer'] = pair['question']; pair['answer_quote'] = pair['question_quote']
                if kind == 'timestamp': pair['start'] = 0
                if kind == 'bool_confidence': pair['confidence'] = True
                if kind == 'low_confidence': pair['confidence'] = .89
                return output
            with self.subTest(kind=kind):
                result = self.infer(vision=FakeProvider(malformed))
                self.assertEqual(result['status'], 'unresolved'); self.assertEqual(result['pairs'], [])

    def test_legacy_or_uncertain_response_has_no_required_pair_authority(self):
        for kind in ('legacy', 'unresolved', 'weak_dimension'):
            def uncertain(payload, kind=kind):
                output = provider_response(payload)
                if kind == 'legacy': output.pop('coverage')
                if kind == 'unresolved': output['resolved'] = False
                if kind == 'weak_dimension': output['relation_confidence'] = .6
                return output
            with self.subTest(kind=kind):
                result = self.infer(vision=FakeProvider(uncertain))
                self.assertEqual(result['status'], 'unresolved')
                self.assertFalse(any(p['requires_answer'] for p in result['pairs']))

    def test_many_units_bounded_and_episode_tail_not_lost(self):
        events, transcript = fixture(30); vision = FakeProvider(counter=lambda _: 1000)
        result = self.infer(events, transcript, vision)
        self.assertEqual(result['status'], 'accepted'); self.assertEqual(len(result['pairs']), 15)
        owned = [r for p in vision.payloads for r in p['coverage_contract']['CURRENT_refs']]
        self.assertEqual(len(owned), 30); self.assertEqual(len({(r['event'], r['unit']) for r in owned}), 30)
        self.assertLessEqual(max(len(p['CURRENT']) for p in vision.payloads), 6)
        self.assertEqual(result['pairs'][-1]['answer_refs'], [{'event': 'scene', 'unit': 'u029'}])

    def test_answer_current_with_question_context_has_own_coverage(self):
        events, transcript = fixture(4); vision = FakeProvider(counter=lambda _: 1000)
        with patch.dict(dialogue.POLICY, max_current_units=1):
            result = self.infer(events, transcript, vision)
        self.assertEqual(result['status'], 'accepted'); self.assertEqual(len(result['pairs']), 2)
        self.assertEqual(vision.payloads[1]['CURRENT'][0]['ref']['unit'], 'u001')
        self.assertEqual(result['coverage'][1]['dialogue_status'], 'paired')

    def test_context_pair_needs_agreement_from_endpoint_owner(self):
        events, transcript = fixture(4)
        def contradiction(payload):
            output = provider_response(payload)
            if payload['CURRENT'][0]['ref']['unit'] == 'u001':
                output['pairs'] = []
                output['coverage'][0]['decision'] = 'not_dialogue_dependency'
            return output
        with patch.dict(dialogue.POLICY, max_current_units=1):
            result = self.infer(events, transcript, FakeProvider(contradiction, counter=lambda _: 1000))
        self.assertEqual(result['status'], 'unresolved')
        first = result['pairs'][0]
        self.assertEqual(first['status'], 'ambiguous'); self.assertFalse(first['requires_answer'])

    def test_large_source_unit_fails_closed_without_token_or_episode_truncation(self):
        vision = FakeProvider(counter=lambda _: 5000)
        result = self.infer(vision=vision)
        self.assertEqual(result['status'], 'unresolved'); self.assertEqual(vision.calls, [])
        self.assertEqual(len(result['unresolved_refs']), 2)
        self.assertTrue(all(h['reason'] == 'source_unit_exceeds_text_context' for h in result['history']))

    def test_repeated_source_quote_is_ambiguous_not_arbitrarily_timestamped(self):
        events, transcript = fixture()
        transcript['words'][2]['text'] = 'Где'; transcript['segments'][0]['text'] = 'Где лежит Где'
        events[0]['unit_evidence'][0]['speech_quote'] = transcript['segments'][0]['text']
        def repeated(payload):
            output = provider_response(payload)
            output['pairs'][0]['question_quote'] = 'Где'
            output['pairs'][0]['support'][0]['quote'] = 'Где'
            return output
        result = self.infer(events, transcript, FakeProvider(repeated))
        self.assertEqual(result['status'], 'unresolved'); self.assertEqual(result['pairs'], [])

    def test_source_unit_ids_can_repeat_between_events(self):
        events, transcript = fixture()
        e = events[0]; left, right = copy.deepcopy(e), copy.deepcopy(e)
        for i, event in enumerate((left, right)):
            unit = copy.deepcopy(e['units'][i]); unit['id'] = 'u'
            record = copy.deepcopy(e['unit_evidence'][i]); record['unit'] = 'u'
            event.update(id=f'event{i}', start=unit['start'], end=unit['end'], units=[unit], unit_evidence=[record],
                         selected_ranges=[{'start': unit['start'], 'end': unit['end']}])
        result = self.infer([left, right], transcript)
        self.assertEqual(result['status'], 'accepted')
        self.assertNotEqual(result['pairs'][0]['question_refs'], result['pairs'][0]['answer_refs'])

    def test_source_units_cutting_actual_words_are_rejected(self):
        events, transcript = fixture()
        events[0]['units'][0]['end'] = transcript['words'][1]['start']+.1
        with self.assertRaises(ValueError): self.infer(events, transcript)

    def test_no_speech_visual_unit_can_be_explicitly_not_a_dialogue_dependency(self):
        events, transcript = fixture(1); transcript = {'words': [], 'segments': []}
        record = events[0]['unit_evidence'][0]
        record.update(kind='physical_action', speech_quote='', frame_indices=[1], frame_times=[.5], frame_count=1)
        result = self.infer(events, transcript)
        self.assertEqual(result['status'], 'accepted'); self.assertEqual(result['pairs'], [])

    def test_cache_revalidates_raw_response_and_stable_identity(self):
        events, transcript = fixture(); vision = FakeProvider()
        first = self.infer(events, transcript, vision)
        self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 1)
        events[0]['unit_evidence'][0]['cache_hit'] = True
        self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 1)
        checkpoint = self.job/'dialogue-relations'/(first['history'][0]['checkpoint']+'.json')
        cached = json.loads(checkpoint.read_text('utf-8'))
        cached['decision']['pairs'][0]['answer_quote'] = 'invented'
        checkpoint.write_text(json.dumps(cached), 'utf-8')
        result = self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 2); self.assertEqual(result['status'], 'accepted')

    def test_prompt_policy_model_source_and_asr_invalidate_cache(self):
        events, transcript = fixture(); vision = FakeProvider()
        self.infer(events, transcript, vision)
        with patch.object(dialogue, 'DIALOGUE_PROMPT', dialogue.DIALOGUE_PROMPT+'\nRuntime prompt changed.'):
            self.infer(events, transcript, vision)
        with patch.dict(dialogue.POLICY, max_current_units=5):
            self.infer(events, transcript, vision)
        vision.model = 'second-model'; self.infer(events, transcript, vision)
        events[0]['source_identity']['sha256'] = 'changed-source'; self.infer(events, transcript, vision)
        transcript['words'][0]['text'] = 'Где?'
        self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 5)

    def test_embedded_code_change_invalidates_without_manual_version_bump(self):
        events, transcript = fixture(); vision = FakeProvider(); self.infer(events, transcript, vision)
        original = Path.read_text
        def changed(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return value+'\n# Changed embedded prompt policy\n' if path == Path(dialogue.__file__) else value
        with patch.object(Path, 'read_text', changed):
            self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 2)

    def test_source_proof_geometry_and_checkpoint_invalidate_cache(self):
        events, transcript = fixture(); vision = FakeProvider(); self.infer(events, transcript, vision)
        events[0]['unit_evidence'][0]['checkpoint'] = 'b'*64
        self.infer(events, transcript, vision)
        self.assertEqual(len(vision.calls), 2)

    def test_corrupt_cache_rebuilds_without_treating_previous_summary_as_proof(self):
        vision = FakeProvider(); result = self.infer(vision=vision)
        checkpoint = self.job/'dialogue-relations'/(result['history'][0]['checkpoint']+'.json')
        checkpoint.write_text('{broken', 'utf-8')
        self.infer(vision=vision); self.assertEqual(len(vision.calls), 2)

    def test_cancellation_auth_tls_budget_and_busy_errors_propagate(self):
        from app.deepseek import BudgetExceeded, RemoteError
        from app.jobs import BusyError
        failures = [InterruptedError('cancel'), ssl.SSLError('TLS'), BudgetExceeded('budget'), BusyError('busy'),
                    RemoteError('auth', category='auth'), urllib.error.HTTPError('http://local', 401, 'auth', None, None)]
        for error in failures:
            def raises(payload, error=error): raise error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.infer(vision=FakeProvider(raises))
        with self.assertRaises(InterruptedError): self.infer(cancelled=lambda: True)

    def test_quality_failure_has_explicit_unresolved_audit_without_keep_all(self):
        def failure(payload): raise RuntimeError('provider failure Bearer do-not-log-secret')
        events, transcript = fixture(); original = copy.deepcopy(events)
        result = self.infer(events, transcript, FakeProvider(failure))
        self.assertEqual(result['status'], 'unresolved'); self.assertEqual(result['pairs'], [])
        self.assertEqual(result['history'][0]['reason'], 'model_failure')
        self.assertEqual(events, original)
        persisted = (self.job/'dialogue-relations/dialogue_relations.json').read_text('utf-8')
        self.assertNotIn('do-not-log-secret', persisted)

    def test_attach_accepted_retry_clears_only_own_reason_and_keeps_source_selection(self):
        events, transcript = fixture()
        events[0].update(analysis_unresolved=True, analysis_unresolved_reasons=[dialogue.OWN_REASON])
        result = self.infer(events, transcript)
        original = copy.deepcopy(events)
        updated = dialogue.attach_dialogue_result(events, result)
        self.assertFalse(updated[0]['analysis_unresolved'])
        self.assertEqual(updated[0]['analysis_unresolved_reasons'], [])
        self.assertEqual(updated[0]['dialogue_relations']['status'], 'accepted')
        self.assertEqual(updated[0]['selected_ranges'], events[0]['selected_ranges'])
        self.assertEqual(events, original)

    def test_attach_preserves_other_downstream_primary_and_opaque_uncertainty(self):
        events, transcript = fixture(); result = self.infer(events, transcript)
        for reason in ('story_structure_unresolved', 'source_role_unresolved', None):
            event = copy.deepcopy(events[0])
            event.update(analysis_unresolved=True,
                analysis_unresolved_reasons=[dialogue.OWN_REASON, reason] if reason else [])
            updated = dialogue.attach_dialogue_result([event], result)[0]
            self.assertTrue(updated['analysis_unresolved'])
            if reason: self.assertEqual(updated['analysis_unresolved_reasons'], [reason])

    def test_attach_pending_dropped_question_marks_event_without_restoring_source(self):
        events, transcript = fixture(); answer = events[0]['units'][1]
        events[0]['selected_ranges'] = [{'start': answer['start'], 'end': answer['end']}]
        events[0]['unit_evidence'][0].update(decision='drop', kind='static_neutral_view')
        result = self.infer(events, transcript)
        updated = dialogue.attach_dialogue_result(events, result)[0]
        self.assertEqual(updated['dialogue_relations']['status'], 'unresolved')
        self.assertIn(dialogue.OWN_REASON, updated['analysis_unresolved_reasons'])
        self.assertEqual(updated['selected_ranges'], events[0]['selected_ranges'])
        self.assertIn({'event': 'scene', 'unit': 'u000'}, updated['dialogue_relations']['unresolved_refs'])

    def test_attach_foreign_ref_rejects_and_missing_coverage_stays_pending(self):
        events, transcript = fixture(); result = self.infer(events, transcript)
        result['coverage'].pop()
        updated = dialogue.attach_dialogue_result(events, result)[0]
        self.assertEqual(updated['dialogue_relations']['status'], 'unresolved')
        result['unresolved_refs'] = [{'event': 'foreign', 'unit': 'u'}]
        with self.assertRaises(ValueError): dialogue.attach_dialogue_result(events, result)


if __name__ == '__main__':
    unittest.main()
