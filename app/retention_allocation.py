"""Reserve evidenced mandatory source material before ranked optional costs."""
from __future__ import annotations

from app.source_ranges import intersect_ranges as _intersect

import copy

from app.selection_gate import positive_ranges, selection_problems
from app.source_roles import confirmed_exclusions
from app.source_ranges import merge_ranges
from app.source_ranges import subtract_ranges as _subtract

VERSION = 4


def _cost(ranges):
    return sum(r['end']-r['start'] for r in merge_ranges(ranges))


def _source_candidates(events, candidate_ranges, ranked_ids, arcs, budget):
    """Rank real arc ranges rather than duplicating their shared parent scene."""
    rank = {identifier:index for index,identifier in enumerate(ranked_ids)}
    candidates, assigned = [], {}
    for arc in arcs:
        if not arc.get('source_unit_refs') or arc.get('uncertain', True):
            continue
        ranges = {identifier:_intersect(candidate_ranges.get(identifier, []), arc['source_ranges'])
                  for identifier in arc['event_ids'] if identifier in rank}
        ranges = {i:r for i,r in ranges.items() if r}
        if not ranges:
            continue
        candidates.append({'id':arc['id'], 'ranges':ranges, 'reason':'complete_inferred_source_arc',
                           'rank':min(rank[i] for i in ranges), 'start':arc['start']})
        for identifier, pieces in ranges.items():
            assigned[identifier] = merge_ranges([*assigned.get(identifier, []), *pieces])
    known = {event['id']:event for event in events}
    for identifier in ranked_ids:
        remainder = _subtract(candidate_ranges.get(identifier, []), assigned.get(identifier, []))
        # A remaining production unit is individually costed; the scene's full
        # envelope would combine unrelated source arcs again.
        for unit in known[identifier].get('units', []):
            pieces = _intersect(remainder, [unit])
            if pieces:
                candidates.append({'id':identifier+':'+unit['id'], 'ranges':{identifier:pieces},
                    'reason':'ranked_verified_source_unit', 'rank':rank[identifier], 'start':unit['start']})
    return sorted(candidates, key=lambda row:(row['rank'], row['start'], row['id']))


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
        for bridge in event.get('mandatory_continuity_units', []):
            unit = known.get(bridge.get('unit'))
            if unit is None:
                continue
            pieces = _intersect(_intersect(bridge.get('ranges', []),[unit]),event.get('selected_ranges', []))
            if not pieces or not _covers_positive(event,pieces):
                continue
            result.setdefault(event['id'], []).extend(pieces)
            proofs.append({'event':event['id'],'unit':unit['id'],'kind':'verified_required_continuity',
                           'checkpoint':bridge.get('checkpoint'),'ranges':pieces})
    return {i:merge_ranges(r) for i,r in result.items()}, proofs


def _covers_positive(event, pieces):
    from .selection_gate import _covers
    return _covers(positive_ranges(event),pieces)


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
    from .speech_handles import expand_ranges, barriers

    def actual_cost(ranges):
        core = [r for pieces in ranges.values() for r in pieces]
        return _cost(expand_ranges(core,transcript,duration,barriers(source,core)))

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
    oversized_seed = None
    source_scoped = any(arc.get('source_unit_refs') for arc in arcs)
    candidates = _source_candidates(source, candidate_ranges, ranked_ids, arcs, budget) if source_scoped else [
        {'id':identifier} for identifier in ranked_ids]
    for candidate in candidates:
        identifier = candidate['id']
        if chosen and actual_cost(chosen) >= budget['optimal']:
            break
        if not source_scoped and identifier not in candidate_ranges:
            continue
        additions = candidate.get('ranges', {identifier:candidate_ranges.get(identifier, [])})
        group = set(additions)
        arc = None if source_scoped else by_arc.get(identifier)
        if arc and not arc.get('uncertain', True):
            group = set(arc['event_ids']) & set(candidate_ranges)
            # A large optional arc cannot force an avoidable seed overflow.
            if _cost([r for member in group for r in candidate_ranges[member]]) > budget['max']+.002:
                group = {identifier}
                reasons.setdefault(identifier, []).append('complete_story_arc_exceeds_adaptive_max')
            additions = {member:candidate_ranges[member] for member in group}
        trial = copy.deepcopy(chosen)
        for member in group:
            trial[member] = merge_ranges([*trial.get(member, []),*additions[member]])
        next_events, next_ranges, next_continuity = evaluate(trial)
        cost = actual_cost(next_ranges)
        history.append({'candidate':identifier, 'group':sorted(group), 'duration_including_context':cost,
            'accepted':not chosen or cost <= budget['max']+.002,
            'required_bridges':copy.deepcopy(next_continuity['bridges'])})
        if source_scoped and not chosen and cost > budget['max']+.002:
            # Prefer another complete source arc that fits, including its real
            # continuity cost. Keep the indivisible first arc as a last seed.
            history[-1]['accepted']=False
            if oversized_seed is None:
                oversized_seed=(next_events,next_ranges,next_continuity,copy.deepcopy(candidate),len(history)-1)
            continue
        if chosen and cost > budget['max']+.002:
            for member in group:
                reasons.setdefault(member, []).append('adaptive_max_including_mandatory_context')
            continue
        if not chosen and cost > budget['max']+.002:
            seed_overflow = True
        current_events, chosen, continuity = next_events, next_ranges, next_continuity
        for bridge in continuity['bridges']:
            if bridge not in required_bridges:
                required_bridges.append(copy.deepcopy(bridge))
        for member in group:
            reasons.setdefault(member, []).append(candidate.get('reason') or (
                'complete_story_arc' if len(group)>1 else 'ranked_source_story'))

    if not chosen and oversized_seed is not None:
        current_events,chosen,continuity,candidate,history_index=oversized_seed
        seed_overflow=True
        history[history_index]['accepted']=True
        required_bridges=copy.deepcopy(continuity['bridges'])
        for member in candidate['ranges']:
            reasons.setdefault(member,[]).append(candidate['reason'])

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
    required_cost = actual_cost(required)
    total = actual_cost(chosen)
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
