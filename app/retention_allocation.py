"""Reserve evidenced mandatory source material before ranked optional costs."""
from __future__ import annotations

import copy

from app.selection_gate import positive_ranges, selection_problems
from app.source_roles import confirmed_exclusions, merge_ranges
from app.titles import _subtract

VERSION = 1


def _cost(ranges):
    return sum(r['end']-r['start'] for r in merge_ranges(ranges))


def mandatory_ranges(events):
    result, proofs = {}, []
    for event in events:
        if selection_problems(event):
            continue
        known = {u['id']: u for u in event.get('units', [])}
        for record in event.get('unit_evidence', []):
            if (record.get('kind') != 'state_transition' and not (
                    event.get('narrative_bridge') and record.get('kind') == 'physical_action')):
                continue
            unit = known.get(record.get('unit'))
            if unit is None:
                continue
            # Validate this individual CURRENT record, not a different positive
            # record in the same event. Only selected original material counts.
            positive = positive_ranges({**event, 'unit_evidence':[record]})
            pieces = merge_ranges([{'start':max(a['start'], b['start']),
                'end':min(a['end'], b['end'])} for a in positive
                for b in event.get('selected_ranges', [])
                if a['start'] < b['end'] and a['end'] > b['start']])
            pieces = _subtract(pieces, confirmed_exclusions(event))
            if pieces:
                result.setdefault(event['id'], []).extend(pieces)
                proofs.append({'event':event['id'], 'unit':unit['id'],
                    'kind':record['kind'], 'checkpoint':record.get('checkpoint'), 'ranges':pieces})
    return {i:merge_ranges(r) for i,r in result.items()}, proofs


def allocate_retention(events, candidate_ranges, ranked_ids, arcs, transcript, duration,
                       budget, resolve_continuity):
    """Evaluate each optional addition including its required continuity cost.

    Actual compressed ranges are supplied by the planner. This helper never
    creates source timestamps or substitutes an event envelope for interval cost.
    The continuity resolver's uncertainty remains visible for the final gate.
    """
    source = copy.deepcopy(events)
    mandatory, proofs = mandatory_ranges(source)
    chosen = copy.deepcopy(mandatory)
    reasons = {i:['verified_mandatory_transition'] for i in chosen}
    by_arc = {i:arc for arc in arcs for i in arc['event_ids']}

    def evaluate(ranges):
        prepared = copy.deepcopy(source)
        for event in prepared:
            if event['id'] in ranges:
                event.update(selected_ranges=copy.deepcopy(ranges[event['id']]),
                             unit_selection_version=1, minimal_context_ranges=True)
        if not ranges:
            return prepared, {}, {'events':prepared,'selected_ids':[], 'bridges':[],
                                  'warnings':[], 'transitions':[]}
        continuity = resolve_continuity(prepared, set(ranges), transcript, duration)
        allocation = {e['id']:merge_ranges(_subtract(e.get('selected_ranges', []),
            confirmed_exclusions(e))) for e in continuity['events']
            if e['id'] in continuity['selected_ids']}
        return continuity['events'], allocation, continuity

    current_events, chosen, continuity = evaluate(chosen)
    required_bridges = copy.deepcopy(continuity['bridges'])
    history = []
    seed_overflow = False
    for identifier in ranked_ids:
        if chosen and _cost([r for v in chosen.values() for r in v]) >= budget['optimal']:
            break
        if identifier not in candidate_ranges:
            continue
        group = {identifier}
        arc = by_arc.get(identifier)
        if arc and not arc.get('uncertain', True):
            group = set(arc['event_ids']) & set(candidate_ranges)
            # A large optional arc cannot force an avoidable seed overflow.
            if _cost([r for member in group for r in candidate_ranges[member]]) > budget['max']+.002:
                group = {identifier}
                reasons.setdefault(identifier, []).append('complete_story_arc_exceeds_adaptive_max')
        trial = copy.deepcopy(chosen)
        for member in group:
            trial[member] = merge_ranges([*trial.get(member, []),*candidate_ranges[member]])
        next_events, next_ranges, next_continuity = evaluate(trial)
        cost = _cost([r for v in next_ranges.values() for r in v])
        history.append({'candidate':identifier, 'group':sorted(group), 'duration_including_context':cost,
            'accepted':not chosen or cost <= budget['max']+.002,
            'required_bridges':copy.deepcopy(next_continuity['bridges'])})
        if chosen and cost > budget['max']+.002:
            reasons.setdefault(identifier, []).append('adaptive_max_including_mandatory_context')
            continue
        if not chosen and cost > budget['max']+.002:
            seed_overflow = True
        current_events, chosen, continuity = next_events, next_ranges, next_continuity
        for bridge in continuity['bridges']:
            if bridge not in required_bridges:
                required_bridges.append(copy.deepcopy(bridge))
        for member in group:
            reasons.setdefault(member, []).append('complete_story_arc' if len(group)>1 else 'ranked_source_story')

    # A bridge already present in chosen no longer appears as a new restoration
    # on the next trial. Keep its proof and mandatory cost while fully retained.
    retained_bridges = []
    for bridge in required_bridges:
        selected = chosen.get(bridge['source_event'], [])
        covered = [{'start':max(a['start'],b['start']), 'end':min(a['end'],b['end'])}
            for a in bridge['ranges'] for b in selected
            if a['start'] < b['end'] and a['end'] > b['start']]
        if _cost(covered) >= _cost(bridge['ranges'])-.002:
            retained_bridges.append(bridge)
    continuity = {**continuity, 'bridges':retained_bridges}
    required = copy.deepcopy(mandatory)
    for bridge in continuity['bridges']:
        identifier = bridge['source_event']
        required[identifier] = merge_ranges([*required.get(identifier, []), *bridge['ranges']])
        reasons.setdefault(identifier, []).append('required_continuity_context')
    required_cost = _cost([r for v in required.values() for r in v])
    total = _cost([r for v in chosen.values() for r in v])
    overflow = []
    if required_cost > budget['max']+.002:
        overflow.append({'reason':'mandatory_source_context_exceeds_max',
            'duration':required_cost, 'excess':required_cost-budget['max'],
            'events':sorted(required), 'proofs':proofs, 'bridges':continuity['bridges']})
    if seed_overflow:
        overflow.append({'reason':'minimum_complete_story_seed_exceeds_max',
                         'duration':total,'excess':max(0,total-budget['max'])})
    return {'version':VERSION, 'events':current_events, 'selected_ids':sorted(chosen),
        'selected_ranges':chosen, 'continuity':continuity, 'selection_reasons':reasons,
        'mandatory_ranges':required, 'mandatory_proofs':proofs,
        'mandatory_duration':required_cost, 'optional_budget':max(0,budget['max']-required_cost),
        'optional_duration':max(0,total-required_cost), 'retained_duration':total,
        'overflow_reasons':overflow, 'allocation_history':history}
