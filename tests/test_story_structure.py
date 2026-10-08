"""Natural arc and minimal source continuity regressions, without model calls."""
import copy
import unittest

from app.source_roles import confirmed_exclusions
from app.story_structure import build_story_arcs, resolve_continuity


EMPTY = {'words': [], 'segments': []}


def state(location='street', character='free', objects=None, topic='rescue'):
    return {'locations': [location], 'character_state': character,
            'objects': ['coat'] if objects is None else objects, 'relationship': 'friends', 'topic': topic}


def event(identifier, start, end, before=None, after=None, **extra):
    return {'id': identifier, 'start': start, 'end': end, 'kind': 'story', 'importance': 3,
            'summary': 'Supplied factual description', 'confidence': .95, 'uncertain': False,
            'requires': [], 'state_before': before or {}, 'state_after': after or before or {},
            'selected_ranges': [{'start': start, 'end': end}], **extra}


def action(identifier, start, end, before, after):
    return {'id': identifier, 'start': start, 'end': end, 'state_before': before, 'state_after': after}


def ending(time, kind='closure', verified=True):
    return {'time': time, 'kind': kind, 'evidence': 'Supplied visible endpoint', 'confidence': .95,
            **({'verification': {'supported': True, 'confidence': .95, 'evidence': 'checked',
                                 'last_reply': 'complete', 'next_reply': ''}} if verified else {})}


class StoryArcTests(unittest.TestCase):
    def test_five_natural_arcs_preserve_supplied_roles_and_verified_complete_endings(self):
        events = []
        phases = ['setup', 'development', 'turning_point', 'transition', 'payoff']
        for arc_index in range(5):
            for phase_index, phase in enumerate(phases):
                start = (arc_index * 5 + phase_index) * 10
                events.append(event(f'a{arc_index}_{phase}', start, start + 10, state(),
                                    arc_id=f'plot_{arc_index}', phase=phase,
                                    part_endings=[ending(start + 10)] if phase == 'payoff' else []))
        original = copy.deepcopy(events)
        arcs = build_story_arcs(events, EMPTY)
        self.assertEqual(len(arcs), 5)
        self.assertTrue(all(arc['complete_ending'] and arc['ending_verified'] for arc in arcs))
        self.assertTrue(all([row['role'] for row in arc['roles']] == phases for arc in arcs))
        self.assertEqual([(arc['start'], arc['end']) for arc in arcs], [(i * 50, (i + 1) * 50) for i in range(5)])
        self.assertEqual([identifier for arc in arcs for identifier in arc['event_ids']], [row['id'] for row in events])
        self.assertEqual(events, original)
        self.assertEqual(arcs, build_story_arcs(events, EMPTY))

    def test_unrelated_legacy_scenes_do_not_become_one_indivisible_episode_arc(self):
        events = [event(f'e{i}', i * 30, (i + 1) * 30) for i in range(36)]
        arcs = build_story_arcs(events)
        self.assertEqual(len(arcs), 36)
        self.assertTrue(all(arc['fallback_scene_arc'] and arc['uncertain'] for arc in arcs))
        self.assertTrue(all(len(arc['event_ids']) == 1 for arc in arcs))

    def test_clear_filler_tail_does_not_create_nonplot_arcs_or_exclusion_authority(self):
        story = event('plot', 0, 20, arc_id='plot', phase='payoff', part_endings=[ending(20)])
        tail = [event(f'filler{i}', 20 + i * 10, 30 + i * 10, kind='filler', importance=1) for i in range(26)]
        original = copy.deepcopy(tail)
        arcs = build_story_arcs([story, *tail])
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0]['event_ids'], ['plot'])
        self.assertEqual(tail, original)
        tail[0]['narrative_bridge'] = True
        tail[1]['action_units'] = ['current_u']
        tail[2]['verified_current_story_ranges'] = [{'start': tail[2]['start'], 'end': tail[2]['end']}]
        ids = [identifier for arc in build_story_arcs([story, *tail]) for identifier in arc['event_ids']]
        self.assertTrue(all(identifier in ids for identifier in ['filler0', 'filler1', 'filler2']))

    def test_direct_causal_state_chain_groups_without_fixed_duration(self):
        events = [event('setup', 0, 20, state()),
                  event('binding', 20, 24, state(), state(character='bound'), requires=['setup'],
                        action_units=['bind'], units=[action('bind', 20, 24, state(), state(character='bound'))]),
                  event('payoff', 24, 120, state(character='bound'), requires=['binding'], part_endings=[ending(120)])]
        arcs = build_story_arcs(events)
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0]['end'], 120)
        self.assertEqual([row['role'] for row in arcs[0]['roles']], ['setup', 'turning_point', 'payoff'])
        self.assertTrue(arcs[0]['complete_ending'])

    def test_high_confidence_unverified_proposal_is_not_a_verified_arc_ending(self):
        arcs = build_story_arcs([event('a', 0, 10, part_endings=[ending(10, verified=False)])])
        self.assertFalse(arcs[0]['complete_ending'])
        self.assertFalse(arcs[0]['endings'][0]['verified'])
        self.assertEqual(arcs[0]['roles'][0]['role'], 'development')

    def test_crossing_word_or_confirmed_credit_cannot_authorize_complete_ending(self):
        transcript = {'words': [{'start': 9.8, 'end': 10.2, 'text': 'word'}], 'segments': []}
        events = [event('a', 0, 10, phase='payoff', part_endings=[ending(10)])]
        self.assertFalse(build_story_arcs(events, transcript)[0]['complete_ending'])
        events[0]['excluded_credit_ranges'] = [{'start': 8, 'end': 10}]
        self.assertFalse(build_story_arcs(events)[0]['complete_ending'])
        credits = event('credits', 10, 20, credit_montage=True, contains_credits=True)
        self.assertEqual([identifier for arc in build_story_arcs([*events, credits]) for identifier in arc['event_ids']], ['a'])


class ContinuityTests(unittest.TestCase):
    def test_kidnapping_restores_both_factual_binding_and_car_actions(self):
        free, bound, car = state(), state(character='bound'), state('car', 'bound')
        events = [event('a', 0, 30, free),
                  event('bind', 30, 34, free, bound, importance=2, action_units=['bind_u'],
                        units=[action('bind_u', 30, 34, free, bound)]),
                  event('car', 34, 38, bound, car, importance=2, action_units=['car_u'],
                        units=[action('car_u', 34, 38, bound, car)]),
                  event('payoff', 38, 68, car, importance=5)]
        original = copy.deepcopy(events)
        result = resolve_continuity(events, ['a', 'payoff'], EMPTY, 68)
        self.assertEqual(result['selected_ids'], ['a', 'bind', 'car', 'payoff'])
        self.assertEqual([row['source_event'] for row in result['bridges']], ['bind', 'car'])
        self.assertEqual([row['ranges'] for row in result['bridges']], [[{'start': 30, 'end': 34}], [{'start': 34, 'end': 38}]])
        self.assertEqual([(row['from'], row['to']) for row in result['transitions']],
                         [('a', 'bind'), ('bind', 'car'), ('car', 'payoff')])
        self.assertTrue(all(row['status'] == 'consistent' for row in result['transitions']))
        for restored in result['events'][1:3]:
            self.assertTrue(restored['minimal_context_ranges'])
            self.assertEqual(restored['unit_selection_version'], 1)
            audit = next(row for row in result['bridges'] if row['source_event'] == restored['id'])
            self.assertEqual(restored['selected_ranges'], audit['intervals'])
        self.assertEqual(events, original)

    def test_whole_short_action_unit_inherits_known_parent_endpoint_states(self):
        free, bound = state(), state(character='bound')
        unit = {'id': 'bind_u', 'start': 10, 'end': 14}
        events = [event('a', 0, 10, free), event('bind', 10, 14, free, bound, action_units=['bind_u'], units=[unit]),
                  event('b', 14, 24, bound)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 24)
        self.assertEqual(result['selected_ids'], ['a', 'bind', 'b'])
        self.assertEqual(result['events'][1]['continuity_state_before'], free)
        self.assertEqual(result['events'][1]['continuity_state_after'], bound)
        self.assertFalse(result['bridges'][0]['limitations'])
        self.assertTrue(all(row['status'] == 'consistent' for row in result['transitions']))

    def test_partial_action_excerpt_without_unit_states_does_not_assert_parent_endpoints(self):
        free, bound = state(), state(character='bound')
        unit = {'id': 'bind_u', 'start': 30, 'end': 34}
        events = [event('a', 0, 10, free), event('long', 10, 100, free, bound, action_units=['bind_u'], units=[unit]),
                  event('b', 100, 110, bound)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 110)
        self.assertEqual(result['events'][1]['selected_ranges'], [{'start': 30, 'end': 34}])
        self.assertEqual(result['events'][1]['continuity_state_before'], {})
        self.assertEqual(result['events'][1]['continuity_state_after'], {})
        self.assertIn('unit_specific_states_unavailable', result['bridges'][0]['limitations'])
        self.assertTrue(all(row['status'] == 'unknown' for row in result['transitions']))

    def test_object_handover_and_topic_change_need_two_separate_bounded_actions(self):
        a = state(objects=['key@hero'], topic='arrival')
        b = state(objects=['key@girl'], topic='arrival')
        c = state(objects=['key@girl'], topic='secret')
        events = [event('a', 0, 20, a),
                  event('handover', 20, 24, a, b, action_units=['give'], units=[action('give', 20, 24, a, b)]),
                  event('explanation', 24, 30, b, c, action_units=['explain'], units=[action('explain', 24, 30, b, c)]),
                  event('b', 30, 50, c)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 50)
        self.assertEqual([row['source_event'] for row in result['bridges']], ['handover', 'explanation'])
        self.assertEqual(result['bridges'][0]['dimensions'], ['objects'])
        self.assertEqual(result['bridges'][1]['dimensions'], ['topic'])
        self.assertFalse(any(row['reason'] == 'unresolved_state_discontinuity' for row in result['warnings']))

    def test_two_actions_in_one_long_event_keep_minimal_ranges_and_parent_id(self):
        free, bound, car = state(), state(character='bound'), state('car', 'bound')
        units = [action('c000_u001', 50, 54, free, bound), action('c003_u004', 190, 194, bound, car)]
        events = [event('a', 0, 30, free),
                  event('long', 30, 210, free, car, action_units=[unit['id'] for unit in units], units=units),
                  event('b', 210, 240, car)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 240)
        restored = result['events'][1]
        self.assertEqual(result['selected_ids'], ['a', 'long', 'b'])
        self.assertEqual(restored['selected_ranges'], [{'start': 50, 'end': 54}, {'start': 190, 'end': 194}])
        self.assertEqual(len(result['bridges']), 2)
        self.assertEqual(restored['continuity_state_before'], free)
        self.assertEqual(restored['continuity_state_after'], car)
        self.assertTrue(all(row['status'] == 'consistent' for row in result['transitions']))

    def test_erroneous_three_minute_dependency_requires_source_verification_without_endpoint_fallback(self):
        events = [event('junk', 0, 10), event('a', 10, 30),
                  event('long', 30, 210, requires=['junk']), event('b', 210, 240, requires=['long'])]
        transcript = {'segments': [{'start': 30, 'end': 210, 'text': 'one huge ASR reply'}],
                      'words': [{'start': 206.8, 'end': 207.3, 'text': 'crossing'}]}
        result = resolve_continuity(events, ['a', 'b'], transcript, 240)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertFalse(result['bridges'])
        task = next(w for w in result['warnings'] if w['reason'] == 'dependency_has_no_permitted_context')
        self.assertEqual(task['source_event'],'long')
        self.assertIn('source_unit_verification_required',task['limitations'])
        self.assertNotIn('junk', result['selected_ids'])

    def test_existing_state_avoids_redundant_direct_dependency(self):
        current = state()
        events = [event('a', 0, 10, current), event('redundant', 10, 190, current),
                  event('b', 190, 220, current, requires=['redundant'])]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 220)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertFalse(result['bridges'])

    def test_no_sandwich_fill_or_restoration_from_importance_alone(self):
        current = state()
        events = [event('a', 0, 10, current),
                  event('filler', 10, 180, current, importance=5, narrative_bridge=True),
                  event('b', 180, 200, current)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 200)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertFalse(result['bridges'])

    def test_unrelated_action_is_not_restored_merely_because_it_lies_between_scenes(self):
        current, final = state(), state(character='bound')
        unrelated = state(character='waving')
        events = [event('a', 0, 10, current),
                  event('wave', 10, 14, current, unrelated, action_units=['wave'], units=[action('wave', 10, 14, current, unrelated)]),
                  event('bind', 14, 18, current, final, action_units=['bind'], units=[action('bind', 14, 18, current, final)]),
                  event('b', 18, 30, final)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 30)
        self.assertEqual(result['selected_ids'], ['a', 'bind', 'b'])

    def test_confirmed_pure_credit_cannot_become_a_bridge(self):
        current, final = state(), state('car', 'bound')
        credits = event('credits', 10, 20, current, final, contains_credits=True, credit_montage=True,
                        action_units=['c'], units=[action('c', 10, 14, current, final)])
        events = [event('a', 0, 10, current), credits, event('b', 20, 30, final, requires=['credits'])]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 30)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertFalse(result['bridges'])
        self.assertTrue(any(row['reason'] == 'dependency_has_no_permitted_context' for row in result['warnings']))

    def test_mixed_parent_protected_source_exclusions_and_word_edges_survive(self):
        current, final = state(), state(character='bound')
        mixed = event('mixed', 10, 30, current, final, contains_credits=True, credit_montage=False,
                      action_units=['bind'], units=[action('bind', 21, 26, current, final)],
                      excluded_credit_ranges=[{'start': 26, 'end': 30}])
        transcript = {'words': [{'start': 25, 'end': 27, 'text': 'crossing banned boundary'}], 'segments': []}
        events = [event('a', 0, 10, current), mixed, event('b', 30, 40, final)]
        result = resolve_continuity(events, ['a', 'b'], transcript, 40)
        self.assertIn('mixed', result['selected_ids'])
        selected = result['events'][1]['selected_ranges']
        self.assertEqual(selected, [{'start': 21, 'end': 25}])
        self.assertTrue(all(row['end'] <= 26 for row in selected))
        self.assertFalse(any(25 < row[edge] < 27 for row in selected for edge in ('start', 'end')))
        self.assertEqual(result['events'][1]['excluded_credit_ranges'], mixed['excluded_credit_ranges'])
        self.assertEqual(result['bridges'][0]['preserved_exclusions'], confirmed_exclusions(mixed))
        self.assertEqual(selected, result['bridges'][0]['ranges'])

    def test_overlapping_words_use_complete_safe_span_and_never_full_asr_segment(self):
        events = [event('a', 0, 10), event('context', 10, 30), event('b', 30, 40, requires=['context'])]
        events[1].update(units=[{'id':'cause','start':27,'end':30}],keep_units=['cause'])
        transcript = {'words': [{'start': 26, 'end': 27.5, 'text': 'first'},
                                {'start': 27.3, 'end': 28.2, 'text': 'second'}],
                      'segments': [{'start': 10, 'end': 30, 'text': 'full reply'}]}
        result = resolve_continuity(events, ['a', 'b'], transcript, 40)
        self.assertEqual(result['events'][1]['selected_ranges'], [{'start': 26, 'end': 30}])
        self.assertFalse(any(word['start'] < row[edge] < word['end']
                             for row in result['events'][1]['selected_ranges']
                             for edge in ('start', 'end') for word in transcript['words']))

    def test_banned_crossing_word_cannot_shift_action_evidence_to_unrelated_context(self):
        current, final = state(), state(character='bound')
        mixed = event('mixed', 10, 30, current, final,
                      action_units=['bind'], units=[action('bind', 24, 26, current, final)],
                      excluded_credit_ranges=[{'start': 26, 'end': 30}])
        transcript = {'words': [{'start': 23, 'end': 28, 'text': 'crossing action and excluded credits'}], 'segments': []}
        result = resolve_continuity([event('a', 0, 10, current), mixed, event('b', 30, 40, final)], ['a', 'b'], transcript, 40)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertFalse(result['bridges'])
        self.assertTrue(any(row['reason'] == 'unresolved_state_discontinuity' for row in result['warnings']))

    def test_missing_state_remains_explicitly_unknown_and_does_not_restore_material(self):
        events = [event('a', 0, 10), event('middle', 10, 20), event('b', 20, 30)]
        result = resolve_continuity(events, ['a', 'b'], EMPTY, 30)
        self.assertEqual(result['selected_ids'], ['a', 'b'])
        self.assertEqual(result['transitions'][0]['status'], 'unknown')
        self.assertEqual(len(result['transitions'][0]['unknown_dimensions']), 5)
        self.assertTrue(any(row['reason'] == 'unknown_transition_state' for row in result['warnings']))

    def test_indivisible_word_over_cap_is_explicit_and_not_truncated(self):
        events = [event('a', 0, 10), event('context', 10, 30), event('b', 30, 40, requires=['context'])]
        events[1].update(units=[{'id':'cause','start':20,'end':30}],keep_units=['cause'])
        transcript = {'words': [{'start': 20, 'end': 30, 'text': 'indivisible'}], 'segments': []}
        result = resolve_continuity(events, ['a', 'b'], transcript, 40)
        self.assertEqual(result['events'][1]['selected_ranges'], [{'start': 20, 'end': 30}])
        self.assertTrue(any(row['reason'] == 'indivisible_word_exceeds_bridge_cap' for row in result['warnings']))

    def test_same_inputs_are_stable_and_unknown_selected_ids_are_rejected(self):
        events = [event('a', 0, 10), event('context', 10, 190), event('b', 190, 200, requires=['context'])]
        original = copy.deepcopy(events)
        first = resolve_continuity(events, ['a', 'b'], EMPTY, 200)
        second = resolve_continuity(events, ['b', 'a'], EMPTY, 200)
        self.assertEqual(first, second)
        self.assertEqual(events, original)
        with self.assertRaises(ValueError):
            resolve_continuity(events, ['fabricated'], EMPTY, 200)


if __name__ == '__main__':
    unittest.main()
