"""Continuity over CURRENT source units and accepted canonical relations.

This pure resolver never invents timestamps or adds an unverified endpoint.
Unexplained omitted gaps become concrete tasks for original-video verification.
"""
from __future__ import annotations

import copy

from .selection_gate import positive_ranges, _covers
from .source_roles import confirmed_exclusions, merge_ranges
from .titles import _subtract

VERSION = 1
FACTS = ('location_id', 'character_ids', 'physical_state_ids', 'object_ids',
         'topic_id', 'relationship_state_id')


def _key(ref):
    return ref['event'], ref['unit']


def _intersect(left, right):
    return merge_ranges([{'start':max(a['start'],b['start']), 'end':min(a['end'],b['end'])}
        for a in left for b in right if a['start'] < b['end'] and a['end'] > b['start']])


def source_nodes(events):
    """Keep unit identity even when both endpoints belong to one parent event."""
    nodes = []
    for event in events:
        structure = {u['ref']['unit']:u for u in event.get('story_structure', {}).get('units', [])
                     if u.get('ref', {}).get('event') == event['id']}
        for unit in event.get('units', []):
            value = structure.get(unit['id'])
            if not value or value.get('status') != 'accepted':
                continue
            ranges = _subtract(_intersect([unit], positive_ranges(event)), confirmed_exclusions(event))
            if not ranges:
                continue
            nodes.append({'ref':{'event':event['id'], 'unit':unit['id']}, 'event':event, 'unit':unit,
                'ranges':ranges, 'before':copy.deepcopy(value.get('before', {})),
                'after':copy.deepcopy(value.get('after', {})), 'roles':value.get('roles', []),
                'arc_ids':value.get('arc_ids', []),
                'confidence':min(event.get('understanding_confidence', 0), event.get('selection_confidence', 0))})
    return sorted(nodes, key=lambda n:(n['ranges'][0]['start'], n['ranges'][-1]['end'], _key(n['ref'])))


def selected_nodes(events, selected_ids):
    result = []
    for node in source_nodes(events):
        if node['ref']['event'] not in selected_ids:
            continue
        pieces = _intersect(node['ranges'], node['event'].get('selected_ranges', []))
        if pieces:
            result.append({**node, 'selected_ranges':pieces, 'start':pieces[0]['start'], 'end':pieces[-1]['end']})
    return sorted(result, key=lambda n:(n['start'], n['end'], _key(n['ref'])))


def compare_states(left, right):
    matched, changed, unknown = [], [], []
    for field in FACTS:
        a, b = left.get(field), right.get(field)
        if not a or not b:
            unknown.append(field)
        elif (sorted(a) if isinstance(a,list) else a) == (sorted(b) if isinstance(b,list) else b):
            matched.append(field)
        else:
            changed.append(field)
    return {'matched_dimensions':matched, 'changed_dimensions':changed, 'unknown_dimensions':unknown}


def gap_key(left, right):
    return {'left':left['ref'], 'left_end':left['end'], 'right':right['ref'], 'right_start':right['start']}


def omitted_units(events, left, right):
    """Inspect omitted units inside retained parent scenes as well as other scenes."""
    candidates = []
    for event in events:
        for unit in event.get('units', []):
            if unit['start'] < left['end']-.002 or unit['end'] > right['start']+.002:
                continue
            pieces = _subtract([unit], confirmed_exclusions(event))
            retained = event.get('selected_ranges', []) if event.get('_continuity_selected') else []
            if pieces and not _covers(retained, pieces):
                candidates.append({'ref':{'event':event['id'], 'unit':unit['id']}, 'unit':unit,
                                   'ranges':pieces, 'event':event})
    return sorted(candidates, key=lambda n:n['unit']['start'])


def resolve_source_continuity(events, selected_ids, transcript, duration):
    source = copy.deepcopy(events)
    selected = set(selected_ids)
    known = {e['id']:e for e in source}
    if not selected <= set(known):
        raise ValueError('Unknown CURRENT source event')
    bridges, warnings = [], []
    nodes = source_nodes(source)
    by_ref = {_key(n['ref']):n for n in nodes}

    def restore(ref, ranges, reason, evidence, endpoint=None):
        node = by_ref.get(_key(ref))
        if not node or not _covers(node['ranges'], ranges):
            warnings.append({'reason':'source_dependency_verification_required', 'ref':ref,
                             'ranges':ranges, 'endpoint':endpoint})
            return False
        event = known[ref['event']]
        retained = event.get('selected_ranges', []) if ref['event'] in selected else []
        if _covers(retained, ranges):
            return False
        event['selected_ranges'] = merge_ranges([*retained, *ranges])
        event.update(minimal_context_ranges=True, unit_selection_version=1, continuity_restored=True)
        selected.add(ref['event'])
        bridges.append({'source_event':ref['event'], 'source_unit':ref['unit'], 'ranges':copy.deepcopy(ranges),
            'reason':reason, 'evidence':copy.deepcopy(evidence), 'confidence':node['confidence'],
            'uncertain':False, 'limitations':[], 'endpoint':endpoint, 'continuity_version':VERSION})
        return True

    pairs = {}
    relations = {}
    for event in source:
        for pair in event.get('dialogue_relations', {}).get('pairs', []):
            if pair.get('status') == 'confirmed' and pair.get('protect_bidirectional'):
                identity = repr((pair['question_ranges'], pair['answer_ranges']))
                pairs[identity] = pair
        for relation in event.get('story_relations', []):
            relations[repr(relation)] = relation
    # Only exact, proved source dependencies can cost mandatory material.
    # Re-evaluate newly restored units, with a finite source-node bound.
    for _ in range(len(nodes)+1):
        changed = False
        retained = merge_ranges([r for e in source if e['id'] in selected for r in e.get('selected_ranges', [])])
        for pair in pairs.values():
            q, a = _covers(retained,pair['question_ranges']), _covers(retained,pair['answer_ranges'])
            touched = any(r['start'] < kept['end'] and r['end'] > kept['start']
                          for r in [*pair['question_ranges'],*pair['answer_ranges']] for kept in retained)
            if q and a or not touched:
                continue
            for side,covered in (('question',q),('answer',a)):
                if covered:
                    continue
                refs,ranges = pair[side+'_refs'],pair[side+'_ranges']
                for ref in refs:
                    node = by_ref.get(_key(ref))
                    needed = _intersect(ranges, [node['unit']]) if node else ranges
                    changed = restore(ref,needed,'verified_question_response',pair,pair.get('checkpoint')) or changed
        for relation in relations.values():
            if relation.get('type', relation.get('relation')) not in ('cause','setup_payoff','state_transition'):
                continue
            left, right = by_ref.get(_key(relation['from'])), by_ref.get(_key(relation['to']))
            if left and right and _covers(retained,right['ranges']) and not _covers(retained,left['ranges']):
                changed = restore(left['ref'],left['ranges'],'verified_causal_source_unit',relation,right['ref']) or changed
        if not changed:
            break

    # Find real accepted transition units connecting canonical states. A long
    # indivisible action remains complete; the allocator explains its cost.
    for _ in range(len(nodes)+1):
        changed = False
        current = selected_nodes(source,selected)
        for left,right in zip(current,current[1:]):
            comparison = compare_states(left['after'],right['before'])
            for field in comparison['changed_dimensions']:
                initial, target = left['after'][field], right['before'][field]
                initial = tuple(sorted(initial)) if isinstance(initial,list) else initial
                target = tuple(sorted(target)) if isinstance(target,list) else target
                paths = {initial:(0,[])}
                for node in nodes:
                    if (node['ranges'][0]['start'] < left['end']-.002 or node['ranges'][-1]['end'] > right['start']+.002
                            or not set(node['roles']).intersection({'transition','turning_point'})):
                        continue
                    a,b = node['before'].get(field),node['after'].get(field)
                    a = tuple(sorted(a)) if isinstance(a,list) else a
                    b = tuple(sorted(b)) if isinstance(b,list) else b
                    if not a or not b or a == b or a not in paths:
                        continue
                    cost,path = paths[a]
                    cost += sum(r['end']-r['start'] for r in node['ranges'])
                    if b not in paths or cost < paths[b][0]:
                        paths[b] = cost,[*path,node]
                for node in paths.get(target,(0,[]))[1]:
                    changed = restore(node['ref'],node['ranges'],'verified_canonical_state_transition',
                        {'before':node['before'],'after':node['after'],'dimension':field},right['ref']) or changed
        if not changed:
            break

    for event in source:
        event['_continuity_selected'] = event['id'] in selected
    current, transitions = selected_nodes(source,selected), []
    verifications = [v for e in source for v in e.get('continuity_verifications', [])]
    for left,right in zip(current,current[1:]):
        comparison = compare_states(left['after'],right['before'])
        omitted_gap = right['start']-left['end'] > .002
        verification = next((v for v in verifications if gap_key(left,right) in v.get('chain_gaps',[v.get('gap')])
            and v.get('status') == 'accepted' and v.get('coherent') is True and v.get('confidence',0) >= .9),None)
        natural_exit = ('payoff' in left['roles'] and 'setup' in right['roles']
                        and left['arc_ids'] and right['arc_ids'] and not set(left['arc_ids']) & set(right['arc_ids']))
        if verification:
            status, reason = 'consistent','original_video_continuity_verified'
        elif not omitted_gap:
            status, reason = 'consistent','consecutive_original_source_units'
        elif natural_exit:
            status, reason = 'consistent','verified_arc_resolution_and_new_setup'
        elif not comparison['changed_dimensions'] and comparison['matched_dimensions'] and (
                'topic_id' in comparison['matched_dimensions'] or
                any(r.get('type') in ('cause','response','setup_payoff','state_transition')
                    and r.get('from') == left['ref'] and r.get('to') == right['ref'] for r in relations.values()) or
                all(field in comparison['matched_dimensions'] for field in ('location_id','physical_state_ids'))):
            status, reason = 'consistent','canonical_state_continuity'
        else:
            status, reason = 'unresolved','unresolved_state_discontinuity' if comparison['changed_dimensions'] else 'unknown_transition_state'
        row = {'from':left['ref']['event'], 'to':right['ref']['event'], 'from_ref':left['ref'], 'to_ref':right['ref'],
            'gap':gap_key(left,right), 'state_after':left['after'], 'state_before':right['before'],
            **comparison,'status':status,'reason':reason,'verification':verification,'continuity_version':VERSION}
        transitions.append(row)
        if status != 'consistent':
            warnings.append({'reason':reason, **row, 'candidate_refs':[n['ref'] for n in omitted_units(source,left,right)]})
    for event in source:
        event.pop('_continuity_selected',None)
    return {'events':source,'selected_ids':sorted(selected),'bridges':bridges,'transitions':transitions,'warnings':warnings}
