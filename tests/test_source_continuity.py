"""Authored source-unit continuity mechanisms; no production quality claim."""
import copy
import unittest

from app.source_continuity import (compare_states, omitted_units, resolve_source_continuity,
                                   selected_nodes, source_nodes)


EMPTY = {'words': [], 'segments': []}


def facts(state='free', **fields):
    return {'location_id': 'place_room', 'character_ids': ['character_one'],
            'physical_state_ids': [state], 'object_ids': ['object_key'],
            'topic_id': 'topic_rescue', 'relationship_state_id': 'relation_friend', **fields}


def unknown():
    return {'location_id': None, 'character_ids': [], 'physical_state_ids': [],
            'object_ids': [], 'topic_id': None, 'relationship_state_id': None}


def ref(event, unit):
    return {'event': event, 'unit': unit}


def span(start, end):
    return {'start': start, 'end': end}


def event(identifier, specs, selected=None):
    """Source geometry, accepted CURRENT proofs, and authored canonical rows."""
    units, proofs, structure = [], [], []
    for index, (uid, start, end, before, after, roles) in enumerate(specs):
        units.append({'id': uid, 'start': start, 'end': end, 'text': ''})
        proofs.append({'unit': uid, 'kind': 'physical_action', 'decision': 'keep',
            'confidence': .95, 'evidence': 'В CURRENT персонаж передаёт видимый ключ другому персонажу.',
            'frame_indices': [index+1], 'frame_count': len(specs),
            'frame_times': [(start+end)/2], 'speech_quote': '', 'view_start': start, 'view_end': end,
            'checkpoint': 'authored-source-proof'})
        structure.append({'ref': ref(identifier, uid), 'before': before, 'after': after,
                          'roles': roles, 'arc_ids': ['source_arc'], 'status': 'accepted'})
    selected_ranges = [span(u['start'], u['end']) for u in units
                       if selected is None or u['id'] in selected]
    return {'id': identifier, 'scene_id': identifier, 'start': units[0]['start'], 'end': units[-1]['end'],
        'kind': 'story', 'importance': 3, 'units': units, 'unit_evidence': proofs,
        'selected_ranges': selected_ranges, 'unit_selection_version': 1,
        'selection_status': 'accepted', 'understanding_status': 'accepted',
        'understanding_confidence': .95, 'selection_confidence': .95,
        'uncertain': False, 'selection_uncertain': False, 'analysis_unresolved': False,
        'requires': [], 'story_structure': {'status': 'accepted', 'units': structure}}


def single(identifier, uid, start, end, before=None, after=None, selected=True):
    before = facts() if before is None else before
    after = before if after is None else after
    return event(identifier, [(uid, start, end, before, after, ['development'])],
                 selected=[uid] if selected else [])


def chain(bridge_end=12):
    return event('room', [('u0', 0, 4, facts(), facts(), ['setup']),
        ('u1', 4, bridge_end, facts(), facts('bound'), ['turning_point']),
        ('u2', bridge_end, bridge_end+4, facts('bound'), facts('bound'), ['payoff'])], selected=['u0', 'u2'])


def dialogue_fixture(kept):
    parent = event('room', [('question', 0, 4, facts(), facts(), ['setup']),
                            ('answer', 4, 8, facts(), facts(), ['payoff'])], selected=[])
    question, answer = [span(.5, 1.2)], [span(4.5, 6.2)]
    pair = {'status': 'confirmed', 'protect_bidirectional': True, 'requires_answer': True,
            'confidence': .95, 'question_refs': [ref('room', 'question')],
            'answer_refs': [ref('room', 'answer')], 'question_ranges': question, 'answer_ranges': answer,
            'checkpoint': 'authored-dialogue-proof'}
    parent['dialogue_relations'] = {'status': 'accepted', 'pairs': [pair]}
    parent['selected_ranges'] = copy.deepcopy(question if kept == 'question' else answer)
    transcript = {'words': [{'start': .5, 'end': 1.2, 'text': 'Почему?'},
                            {'start': 4.5, 'end': 6.2, 'text': 'Потому.'}]}
    transcript['segments'] = copy.deepcopy(transcript['words'])
    return parent, transcript, pair


class SourceContinuityTests(unittest.TestCase):
    def test_omitted_tail_of_retained_unit_is_a_bounded_original_candidate(self):
        value = single('left','u0',0,4,before=unknown(),after=unknown())
        value['_continuity_selected'] = True
        value['selected_ranges'] = [span(0,1)]
        right = single('right','u0',4,8,before=unknown(),after=unknown())
        left_node = selected_nodes([value],{'left'})[0]
        right_node = selected_nodes([right],{'right'})[0]
        omitted = omitted_units([value,right],left_node,right_node)
        self.assertEqual(len(omitted),1)
        self.assertEqual(omitted[0]['ref'],ref('left','u0'))
        self.assertEqual(omitted[0]['ranges'],[span(1,4)])
        self.assertEqual((omitted[0]['unit']['start'],omitted[0]['unit']['end']),(1,4))
        self.assertEqual((value['units'][0]['start'],value['units'][0]['end']),(0,4))

    def test_retained_consequential_action_restores_only_its_proved_span(self):
        value = single('action','u0',0,4,before=unknown(),after=unknown())
        value['action_units'] = ['u0']
        value['selected_ranges'] = [span(1,2)]
        result = self.resolve([value],['action'])
        self.assertEqual(result['events'][0]['selected_ranges'],[span(0,4)])
        self.assertEqual(result['bridges'][0]['reason'],'verified_consequential_action')
        value['unit_evidence'][0].update(view_start=1,view_end=3)
        result = self.resolve([value],['action'])
        self.assertEqual(result['events'][0]['selected_ranges'],[span(1,3)])

    def test_naked_action_id_does_not_restore_unproved_footage(self):
        value = single('action','u0',0,4,before=unknown(),after=unknown())
        value['action_units'] = ['u0']
        value['selected_ranges'] = [span(1,2)]
        value['unit_evidence'][0]['confidence'] = .5
        result = self.resolve([value],['action'])
        self.assertEqual(result['events'][0]['selected_ranges'],[span(1,2)])
        self.assertEqual(result['bridges'],[])

    def omission_fixture(self):
        value = event('room', [('left',0,4,unknown(),unknown(),['development']),
            ('gap',4,8,unknown(),unknown(),['transition']),('right',8,12,unknown(),unknown(),['development'])],
            selected=['left','right'])
        proof = value['unit_evidence'][1]
        proof.update(decision='drop',kind='waiting',
                     evidence='CURRENT shows a routine still pause without a new action, dialogue or emotional outcome.')
        return value

    def test_frame_verified_omission_is_reused_without_inventing_canonical_identity(self):
        value = self.omission_fixture()
        original = copy.deepcopy(value)
        result = self.resolve([value],['room'])
        row = result['transitions'][0]
        self.assertEqual(row['status'],'consistent')
        self.assertEqual(row['reason'],'accepted_source_omission_proofs')
        self.assertTrue(row['unknown_dimensions'])
        self.assertEqual(row['verification']['source_proofs'][0]['ref'],ref('room','gap'))
        self.assertEqual(value,original)

    def test_silence_or_invalid_incomplete_drop_evidence_cannot_resolve_gap(self):
        for changes in ({'confidence':.89},{'frame_indices':[],'frame_times':[]},
                        {'frame_times':[100]},{'checkpoint':None},{'view_start':5},
                        {'kind':'physical_action'},{'evidence':'no'}):
            value = self.omission_fixture()
            value['unit_evidence'][1].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(self.resolve([value],['room'])['transitions'][0]['status'],'unresolved')

    def test_drop_proof_cannot_erase_real_speech_or_known_state_change(self):
        value = self.omission_fixture()
        speech = {'words':[{'start':5,'end':6,'text':'Стой!'}]}
        self.assertEqual(self.resolve([value],['room'],speech)['transitions'][0]['status'],'unresolved')
        value['story_structure']['units'][0]['after'] = facts('free')
        value['story_structure']['units'][-1]['before'] = facts('bound')
        self.assertEqual(self.resolve([value],['room'])['transitions'][0]['status'],'unresolved')

    def test_existing_positive_action_proof_blocks_negative_gap_shortcut(self):
        value = self.omission_fixture()
        positive = copy.deepcopy(value['unit_evidence'][1])
        positive.update(decision='keep',kind='physical_action',
                        evidence='The source character visibly ties the other character wrists with rope.')
        value['unit_evidence'].append(positive)
        self.assertEqual(self.resolve([value],['room'])['transitions'][0]['status'],'unresolved')

    def resolve(self, events, selected, transcript=EMPTY, duration=100):
        return resolve_source_continuity(events, selected, transcript, duration)

    def test_synonyms_with_same_canonical_ids_keep_state_without_redundant_restore(self):
        left = single('left', 'u0', 0, 4)
        right = single('right', 'u0', 8, 12)
        left['state_after'] = {'locations': ['комната'], 'character_state': 'свободен'}
        right['state_before'] = {'locations': ['помещение'], 'character_state': 'не связан'}
        comparison = compare_states(left['story_structure']['units'][0]['after'],
                                    right['story_structure']['units'][0]['before'])
        self.assertEqual(comparison['changed_dimensions'], [])
        result = self.resolve([left, right], ['left', 'right'])
        self.assertEqual(result['bridges'], [])
        self.assertEqual(result['transitions'][0]['status'], 'consistent')
        self.assertEqual(result['transitions'][0]['reason'], 'canonical_state_continuity')

    def test_state_path_restores_source_unit_inside_same_retained_parent(self):
        source = chain()
        before = copy.deepcopy(source)
        result = self.resolve([source], ['room'])
        self.assertEqual(result['selected_ids'], ['room'])
        self.assertEqual(result['events'][0]['selected_ranges'], [span(0, 16)])
        self.assertEqual(len(result['bridges']), 1)
        bridge = result['bridges'][0]
        self.assertEqual((bridge['source_event'], bridge['source_unit']), ('room', 'u1'))
        self.assertEqual(bridge['ranges'], [span(4, 12)])
        self.assertEqual(bridge['reason'], 'verified_canonical_state_transition')
        self.assertTrue(result['events'][0]['minimal_context_ranges'])
        self.assertEqual(source, before)
        self.assertTrue(all(t['status'] == 'consistent' for t in result['transitions']))

    def test_full_consequential_action_longer_than_seven_seconds_is_not_end_capped(self):
        source = chain(24)
        transcript = {'words': [{'start': 5, 'end': 7, 'text': 'Первая часть действия'},
                                {'start': 20, 'end': 23, 'text': 'Завершение действия'}], 'segments': []}
        result = self.resolve([source], ['room'], transcript)
        self.assertEqual(result['bridges'][0]['ranges'], [span(4, 24)])
        self.assertEqual(result['events'][0]['selected_ranges'], [span(0, 28)])
        self.assertGreater(result['bridges'][0]['ranges'][0]['end']-result['bridges'][0]['ranges'][0]['start'], 7)
        self.assertEqual(result['bridges'][0]['limitations'], [])

    def test_state_path_restores_each_necessary_action_without_parent_envelope_substitution(self):
        street_free = facts(location_id='place_street')
        street_bound = facts('bound', location_id='place_street')
        car_bound = facts('bound', location_id='place_car')
        source = event('scene', [('setup', 0, 4, street_free, street_free, ['setup']),
            ('binding', 4, 8, street_free, street_bound, ['turning_point']),
            ('car', 8, 12, street_bound, car_bound, ['transition']),
            ('payoff', 12, 16, car_bound, car_bound, ['payoff'])], selected=['setup', 'payoff'])
        result = self.resolve([source], ['scene'])
        bridges = sorted(result['bridges'], key=lambda b: b['ranges'][0]['start'])
        self.assertEqual([b['source_unit'] for b in bridges], ['binding', 'car'])
        self.assertEqual([b['ranges'] for b in bridges], [[span(4, 8)], [span(8, 12)]])
        self.assertEqual(result['events'][0]['selected_ranges'], [span(0, 16)])
        self.assertEqual([n['ref']['unit'] for n in selected_nodes(result['events'], {'scene'})],
                         ['setup', 'binding', 'car', 'payoff'])
        self.assertTrue(all(t['status'] == 'consistent' for t in result['transitions']))

    def test_confirmed_excluded_action_cannot_restore_canonical_state_transition(self):
        source = chain()
        source['excluded_credit_ranges'] = [span(4, 12)]
        result = self.resolve([source], ['room'])
        self.assertEqual(result['events'][0]['selected_ranges'], [span(0, 4), span(12, 16)])
        self.assertEqual(result['bridges'], [])
        task = next(w for w in result['warnings'] if w['reason'] == 'unresolved_state_discontinuity')
        self.assertEqual(task['candidate_refs'], [])
        self.assertEqual(task['gap']['left_end'], 4)
        self.assertEqual(task['gap']['right_start'], 12)

    def test_omitted_units_include_dropped_unit_in_retained_parent(self):
        source = chain()
        source['unit_evidence'][1]['decision'] = 'drop'
        source['_continuity_selected'] = True
        left, right = selected_nodes([source], {'room'})
        omitted = omitted_units([source], left, right)
        self.assertEqual([n['ref'] for n in omitted], [ref('room', 'u1')])
        self.assertEqual(omitted[0]['ranges'], [span(4, 12)])
        result = self.resolve([source], ['room'])
        self.assertEqual(result['bridges'], [])
        self.assertEqual(result['warnings'][0]['candidate_refs'], [ref('room', 'u1')])

    def test_unrelated_unknown_states_produce_concrete_bounded_verification_task(self):
        left = single('left', 'u0', 0, 4, unknown())
        omitted = single('omitted', 'u0', 4, 9, unknown(), selected=False)
        omitted['unit_evidence'][0]['decision'] = 'drop'
        right = single('right', 'u0', 9, 13, unknown())
        result = self.resolve([left, omitted, right], ['left', 'right'])
        self.assertEqual(result['selected_ids'], ['left', 'right'])
        self.assertEqual(result['bridges'], [])
        task = next(w for w in result['warnings'] if w['reason'] == 'unknown_transition_state')
        self.assertEqual(task['status'], 'unresolved')
        self.assertEqual(task['gap'], {'left': ref('left', 'u0'), 'left_end': 4,
                                      'right': ref('right', 'u0'), 'right_start': 9})
        self.assertEqual(task['candidate_refs'], [ref('omitted', 'u0')])
        self.assertEqual(task['from_ref'], ref('left', 'u0'))
        self.assertEqual(task['to_ref'], ref('right', 'u0'))

    def test_question_or_answer_restores_only_exact_opposite_dialogue_ranges(self):
        for kept in ('question', 'answer'):
            parent, transcript, pair = dialogue_fixture(kept)
            with self.subTest(kept=kept):
                result = self.resolve([parent], ['room'], transcript)
                self.assertEqual(result['events'][0]['selected_ranges'], [*pair['question_ranges'], *pair['answer_ranges']])
                self.assertEqual(len(result['bridges']), 1)
                missing = 'answer' if kept == 'question' else 'question'
                self.assertEqual(result['bridges'][0]['source_unit'], missing)
                self.assertEqual(result['bridges'][0]['ranges'], pair[missing+'_ranges'])
                self.assertEqual(result['bridges'][0]['reason'], 'verified_question_response')
                self.assertEqual(result['events'][0]['unit_selection_version'], 1)

    def test_confirmed_excluded_dialogue_quote_cannot_be_restored_either_direction(self):
        for kept in ('question', 'answer'):
            parent, transcript, pair = dialogue_fixture(kept)
            missing = 'answer' if kept == 'question' else 'question'
            parent['excluded_credit_ranges'] = copy.deepcopy(pair[missing+'_ranges'])
            with self.subTest(kept=kept):
                result = self.resolve([parent], ['room'], transcript)
                self.assertEqual(result['events'][0]['selected_ranges'], parent['selected_ranges'])
                self.assertEqual(result['bridges'], [])
                task = next(w for w in result['warnings'] if w['reason'] == 'source_dependency_verification_required')
                self.assertEqual(task['ranges'], pair[missing+'_ranges'])

    def test_direct_relation_restores_exact_scoped_ref_and_does_not_fill_other_units(self):
        cause = event('cause', [('u0', 0, 4, facts(), facts(), ['setup']),
            ('u1', 4, 8, facts(), facts(), ['development'])], selected=[])
        payoff = single('payoff', 'u0', 10, 14)
        payoff['story_relations'] = [{'type': 'cause', 'from': ref('cause', 'u0'),
            'to': ref('payoff', 'u0'), 'confidence': .95, 'evidence': 'Accepted exact source-unit dependency.'}]
        result = self.resolve([cause, payoff], ['payoff'])
        restored = next(e for e in result['events'] if e['id'] == 'cause')
        self.assertEqual(restored['selected_ranges'], [span(0, 4)])
        self.assertEqual(result['selected_ids'], ['cause', 'payoff'])
        self.assertEqual(result['bridges'][0]['source_unit'], 'u0')
        self.assertEqual(result['bridges'][0]['reason'], 'verified_causal_source_unit')

    def test_foreign_direct_relation_ref_cannot_borrow_same_unit_id(self):
        cause = single('cause', 'u0', 0, 4, selected=False)
        payoff = single('payoff', 'u0', 8, 12)
        payoff['story_relations'] = [{'type': 'cause', 'from': ref('foreign', 'u0'),
            'to': ref('payoff', 'u0'), 'confidence': .95, 'evidence': 'Unknown source event reference.'}]
        result = self.resolve([cause, payoff], ['payoff'])
        self.assertEqual(result['selected_ids'], ['payoff'])
        self.assertEqual(result['bridges'], [])

    def test_legacy_parent_requires_is_not_source_relation_authority(self):
        omitted = single('omitted', 'u0', 0, 50, selected=False)
        payoff = single('payoff', 'u0', 60, 64)
        payoff['requires'] = ['omitted']
        result = self.resolve([omitted, payoff], ['payoff'])
        self.assertEqual(result['selected_ids'], ['payoff'])
        self.assertEqual(result['bridges'], [])
        self.assertEqual(result['events'][0]['selected_ranges'], [])

    def test_foreign_structure_row_cannot_supply_current_parent_canonical_facts(self):
        source = single('current', 'u0', 0, 4)
        source['story_structure']['units'][0]['ref']['event'] = 'foreign'
        self.assertEqual(source_nodes([source]), [])

    def test_already_retained_transition_is_not_restored_again(self):
        source = chain()
        source['selected_ranges'] = [span(0, 16)]
        result = self.resolve([source], ['room'])
        self.assertEqual(result['bridges'], [])
        self.assertEqual(result['events'][0]['selected_ranges'], [span(0, 16)])
        self.assertTrue(all(t['status'] == 'consistent' for t in result['transitions']))


if __name__ == '__main__':
    unittest.main()
