"""Factual story arcs and bounded continuity context, without model or media I/O.

States and dependencies are supplied evidence, not instructions to keep an
entire scene. Unknown state stays unknown; summaries are never parsed to invent
actions. Restoring context grants positive selection only, never exclusion proof.
"""
from __future__ import annotations

import copy
import math

from .source_roles import confirmed_exclusions, merge_ranges, verified_story_ranges
from .titles import _subtract

STORY_STRUCTURE_VERSION = 1
CONTINUITY_VERSION = 1
ROLES = ('setup', 'development', 'turning_point', 'payoff', 'transition')
STATE_FIELDS = ('locations', 'character_state', 'objects', 'relationship', 'topic')
CONFIDENCE_FIELDS = ('semantic_confidence', 'visual_confidence', 'context_confidence')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _events(events, duration=None):
    result = sorted(copy.deepcopy(events), key=lambda event: event['start'])
    seen = set()
    for event in result:
        if (not isinstance(event.get('id'), str) or not event['id'] or event['id'] in seen
                or not _number(event.get('start')) or not _number(event.get('end'))
                or not 0 <= event['start'] < event['end']
                or duration is not None and event['end'] > duration + .002):
            raise ValueError('Некорректное исходное сюжетное событие')
        seen.add(event['id'])
    return result


def _confidence(event):
    dimensions = [event.get(field) for field in CONFIDENCE_FIELDS]
    if all(_number(value) and 0 <= value <= 1 for value in dimensions):
        value = min(dimensions)
    else:
        candidate = event.get('confidence')
        value = float(candidate) if _number(candidate) and 0 <= candidate <= 1 else 0.0
    return min(value, .55) if event.get('uncertain') is True else value


def _label(value):
    return ' '.join(value.casefold().replace('ё', 'е').split()) if isinstance(value, str) else ''


def _state(event, side):
    value = event.get(f'continuity_state_{side}', event.get(f'state_{side}', {}))
    if not isinstance(value, dict):
        value = {}
    result = {}
    for key in STATE_FIELDS:
        item = value.get(key)
        if key in ('locations', 'objects'):
            result[key] = tuple(sorted({_label(text) for text in item if _label(text)})) if isinstance(item, list) else ()
        else:
            result[key] = _label(item)
    return result


def _compare(before, after):
    same, changed, unknown = [], [], []
    for field in STATE_FIELDS:
        if not before[field] or not after[field]:
            unknown.append(field)
        elif before[field] == after[field]:
            same.append(field)
        else:
            changed.append(field)
    return {'matched_dimensions': same, 'changed_dimensions': changed, 'unknown_dimensions': unknown}


def _pure_credit(event):
    return event.get('credit_montage') is True and event.get('contains_credits') is True


def _phase(event):
    value = event.get('arc_role', event.get('story_phase', event.get('phase')))
    return value if value in ROLES else None


def _arc_key(event):
    value = event.get('arc_id', event.get('story_arc_id'))
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _words(transcript):
    result = []
    for word in sorted((transcript or {}).get('words', []), key=lambda row: row['start']):
        start, end = word.get('start'), word.get('end')
        if not _number(start) or not _number(end) or not 0 <= start < end:
            raise ValueError('Некорректные исходные границы ASR слова')
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def _safe(time, words):
    return not any(start < time < end for start, end in words)


def _endings(event, words):
    rows = []
    exclusions = confirmed_exclusions(event)
    for ending in event.get('part_endings', []):
        time, confidence = ending.get('time'), ending.get('confidence')
        if (not _number(time) or not event['start'] < time <= event['end']
                or ending.get('kind') not in ('closure', 'cliffhanger', 'transition')
                or not _number(confidence) or not .85 <= confidence <= 1 or not _safe(time, words)
                or any(piece['start'] < time <= piece['end'] for piece in exclusions)):
            continue
        proof = ending.get('verification', {})
        verified = bool(isinstance(proof, dict) and proof.get('supported') is True
                        and _number(proof.get('confidence')) and .85 <= proof['confidence'] <= 1)
        verified = verified or ending.get('verified') is True or ending.get('boundaries_verified') is True
        rows.append({**copy.deepcopy(ending), 'event_id': event['id'], 'verified': verified})
    return rows


def build_story_arcs(events, transcript=None):
    """Group linked events; use uncertain scene arcs when causal evidence is absent.

    Explicit arc IDs/roles, known topic/state continuity and direct dependencies
    are grouping signals. A location change alone does not assert a new plot.
    A confidence-only legacy ending remains a candidate, not a verified ending.
    """
    words = _words(transcript)
    source = []
    for event in _events(events):
        if _pure_credit(event) or not _subtract([event], confirmed_exclusions(event)):
            continue
        # Low-value nonplot tail does not create artificial story arcs. This
        # changes only arc membership, never source-role exclusion authority.
        clear_filler = (event.get('kind') == 'filler' and _number(event.get('importance'))
                        and event['importance'] <= 2 and event.get('uncertain') is not True
                        and not event.get('narrative_bridge') and not event.get('action_units')
                        and _arc_key(event) is None and _phase(event) is None and not verified_story_ranges(event))
        if not clear_filler:
            source.append(event)
    arcs, group = [], []
    boundary_reason = ['source_start']

    def close():
        endings = [ending for event in group for ending in _endings(event, words)]
        terminal = [row for row in endings if row['verified'] and row['kind'] in ('closure', 'cliffhanger')
                    and row['event_id'] == group[-1]['id'] and group[-1]['end'] - row['time'] <= 1.5]
        roles = []
        for index, event in enumerate(group):
            role, reason = _phase(event), 'explicit_phase'
            if role is None:
                event_endings = [row for row in endings if row['event_id'] == event['id'] and row['verified']]
                state_delta = _compare(_state(event, 'before'), _state(event, 'after'))['changed_dimensions']
                if any(row['kind'] == 'closure' for row in event_endings):
                    role, reason = 'payoff', 'verified_closure'
                elif any(row['kind'] == 'cliffhanger' for row in event_endings):
                    role, reason = 'turning_point', 'verified_cliffhanger'
                elif event.get('narrative_bridge') is True:
                    role, reason = 'transition', 'explicit_narrative_bridge'
                elif state_delta and event.get('action_units'):
                    role, reason = 'turning_point', 'supplied_action_and_state_delta'
                elif index == 0 and len(group) > 1:
                    role, reason = 'setup', 'position_in_linked_arc'
                else:
                    role, reason = 'development', 'unclassified_factual_event'
            roles.append({'event_id': event['id'], 'role': role, 'reason': reason})
        explicit = any(_arc_key(event) is not None or _phase(event) is not None for event in group)
        fallback = len(group) == 1 and not explicit and not terminal
        confidence = min((_confidence(event) or .5 for event in group), default=.5)
        arcs.append({'id': f'arc_{len(arcs):04d}', 'event_ids': [event['id'] for event in group],
                     'start': group[0]['start'], 'end': group[-1]['end'], 'roles': roles,
                     'boundary_reason': list(boundary_reason), 'endings': endings,
                     'complete_ending': bool(terminal), 'ending_verified': bool(terminal),
                     'fallback_scene_arc': fallback, 'confidence': round(confidence, 4),
                     'uncertain': fallback or confidence < .85 or any(event.get('uncertain') for event in group),
                     'structure_version': STORY_STRUCTURE_VERSION})

    for event in source:
        if group:
            previous = group[-1]
            prior_key, current_key = _arc_key(previous), _arc_key(event)
            ids = {row['id'] for row in group}
            comparison = _compare(_state(previous, 'after'), _state(event, 'before'))
            same_topic = 'topic' in comparison['matched_dimensions']
            same_state = len(comparison['matched_dimensions']) >= 2 and not comparison['changed_dimensions']
            direct_link = bool(ids.intersection(event.get('requires', [])))
            phases_link = (_phase(previous) is not None and _phase(event) is not None
                           and _phase(event) != 'setup' and _phase(previous) != 'payoff')
            terminal = any(row['verified'] and row['kind'] in ('closure', 'cliffhanger')
                           and previous['end'] - row['time'] <= 1.5 for row in _endings(previous, words))
            if current_key is not None and current_key != prior_key:
                split, reason = True, 'explicit_arc_change'
            elif current_key is not None and current_key == prior_key:
                split, reason = False, 'explicit_arc_continuity'
            elif terminal:
                split, reason = True, 'verified_ending'
            elif _phase(event) == 'setup' and _phase(previous) in ('payoff', 'transition'):
                split, reason = True, 'explicit_phase_restart'
            elif direct_link or same_topic or same_state or phases_link:
                split, reason = False, ('direct_dependency' if direct_link else 'topic_continuity' if same_topic
                                        else 'state_continuity' if same_state else 'explicit_phase_progression')
            else:
                split, reason = True, 'insufficient_arc_link'
            if split:
                close()
                group = []
                boundary_reason = [reason]
        group.append(event)
    if group:
        close()
    return arcs


def _units(event):
    result = {}
    for unit in event.get('units', []):
        if (isinstance(unit, dict) and isinstance(unit.get('id'), str)
                and _number(unit.get('start')) and _number(unit.get('end'))
                and event['start'] <= unit['start'] < unit['end'] <= event['end']):
            result[unit['id']] = unit
    return result


def _bounded_range(request, allowed, words, cap, *, endpoint=False):
    """Keep word edges within allowed source; a truly indivisible word may exceed cap."""
    limitations = []
    length = request['end'] - request['start']
    if endpoint or length > cap:
        target = min(3.0 if endpoint else cap, cap, length)
        start, end = request['end'] - target, request['end']
        if length > cap and not endpoint:
            limitations.append('long_action_unit_reduced_to_result_context')
    else:
        start, end = request['start'], request['end']
        padding = max(0.0, 3.0 - (end - start)) / 2
        start, end = max(allowed['start'], start - padding), min(allowed['end'], end + padding)
    # Endpoint padding may enter an overlapping word. Expand to its complete
    # connected word span only when that span does not enter an exclusion.
    for word_start, word_end in words:
        if word_start < start < word_end:
            start = word_start
        if word_start < end < word_end:
            end = word_end
    if start < allowed['start'] or end > allowed['end']:
        # Confirmed exclusions outrank a crossing word. Trim only the affected
        # edge; shifting to unrelated earlier material would mislabel context
        # as the action unit that was requested.
        edges = [time for pair in words for time in pair
                 if allowed['start'] <= time <= allowed['end'] and _safe(time, words)]
        edges += [time for time in (allowed['start'], allowed['end']) if _safe(time, words)]
        if start < allowed['start']:
            start = min((time for time in edges if time >= request['start']), default=None)
        if end > allowed['end']:
            end = max((time for time in edges if time <= request['end']), default=None)
        if start is None or end is None or start >= end:
            return None, ['no_word_safe_context_outside_exclusions']
        limitations.append('context_trimmed_at_word_safe_exclusion_edge')
    if end - start > cap + .000001:
        crossing = [(a, b) for a, b in words if a < end and b > start and b - a > cap]
        if crossing:
            limitations.append('indivisible_word_exceeds_bridge_cap')
        else:
            # Do not exceed the cap merely because normal short words straddle
            # both ends. Move the start forward to the next safe word edge.
            edges = [time for pair in words for time in pair if end - cap <= time < end and _safe(time, words)]
            if not edges:
                return None, ['no_bounded_word_safe_context']
            start = min(edges)
            limitations.append('word_safe_context_shortened')
    if end <= start or not _safe(start, words) or not _safe(end, words):
        return None, ['no_word_safe_context']
    if end - start < 3 - .000001:
        limitations.append('source_context_shorter_than_three_seconds')
    return {'start': start, 'end': end}, limitations


def _material(event, words, exclusions, cap, unit=None, dependency=False):
    allowed = [] if _pure_credit(event) else _subtract([event], exclusions)
    if not allowed:
        return [], ['confirmed_nonstory_source'], []
    known = _units(event)
    actions = [known[identifier] for identifier in event.get('action_units', []) if identifier in known]
    unknown_actions = [identifier for identifier in event.get('action_units', []) if identifier not in known]
    limitations = ['unrecognized_action_unit_ids'] if unknown_actions else []
    if unit is not None:
        sources, kind = [unit], 'action_unit'
    elif actions:
        sources, kind = actions, 'action_unit'
    else:
        positive = [known[identifier] for identifier in event.get('keep_units', []) if identifier in known]
        positive += verified_story_ranges(event)
        if not positive and event.get('unit_selection_version') == 1:
            positive = event.get('selected_ranges', [])
        if positive:
            sources, kind = [max(positive, key=lambda row: row['end'])], 'selected_context_unit'
        elif not dependency and event.get('narrative_bridge') is True and event['end'] - event['start'] <= cap:
            sources, kind = [event], 'short_state_transition'
        else:
            sources, kind = [allowed[-1]], 'endpoint_context'
            limitations.extend(['unverified_dependency_context' if dependency else 'state_endpoint_context',
                                'endpoint_context_does_not_prove_action'])
    ranges, evidence = [], []
    for source in sorted(sources, key=lambda row: row['start']):
        if (not _number(source.get('start')) or not _number(source.get('end'))
                or not event['start'] <= source['start'] < source['end'] <= event['end']):
            limitations.append('invalid_context_range_ignored')
            continue
        for piece in _subtract([source], exclusions):
            container = next((row for row in allowed if row['start'] <= piece['start'] < piece['end'] <= row['end']), None)
            if container is None:
                continue
            interval, notes = _bounded_range(piece, container, words, cap, endpoint=kind == 'endpoint_context')
            limitations.extend(notes)
            if interval:
                ranges.append(interval)
                evidence.append({'kind': kind, 'unit_id': source.get('id') if kind != 'endpoint_context' else None,
                                 'source_start': source['start'], 'source_end': source['end'], **interval})
    return ranges, list(dict.fromkeys(limitations)), evidence


def _transition_nodes(events, selected, left, right):
    nodes = []
    for event in events:
        if (event['id'] in selected or event['start'] < left['end'] - .002
                or event['end'] > right['start'] + .002 or _pure_credit(event)):
            continue
        units = _units(event)
        actions = [units[identifier] for identifier in event.get('action_units', []) if identifier in units]
        stateful = [unit for unit in actions if isinstance(unit.get('state_before'), dict)
                    and isinstance(unit.get('state_after'), dict)]
        if actions and len(stateful) == len(actions):
            for unit in stateful:
                nodes.append({'event': event, 'unit': unit, 'before': _state(unit, 'before'), 'after': _state(unit, 'after')})
        elif actions or event.get('narrative_bridge') is True or event.get('state_transition_verified') is True:
            nodes.append({'event': event, 'unit': None, 'before': _state(event, 'before'), 'after': _state(event, 'after')})
    return sorted(nodes, key=lambda row: (row['unit'] or row['event'])['start'])


def _state_path(nodes, field, initial, target):
    """A chronological path of evidenced actions, never a requires closure."""
    best = {initial: (0.0, [])}
    for node in nodes:
        before, after = node['before'][field], node['after'][field]
        if not before or not after or before == after or before not in best or not node['ranges']:
            continue
        old_cost, path = best[before]
        cost = old_cost + sum(row['end'] - row['start'] for row in node['ranges']) + (1 - node['confidence']) * 3
        if after not in best or cost < best[after][0]:
            best[after] = (cost, [*path, node])
    return best.get(target, (0, []))[1]


def resolve_continuity(events, selected_ids, transcript, duration, *, max_bridge_seconds=7):
    """Return immutable-input selections and audited minimal causal context.

    Only direct dependencies and evidenced state paths can restore material.
    Long dependencies use selected action units or an uncertain three-second
    end context. ASR segments never expand this to a full reply or scene.
    """
    if not _number(duration) or duration <= 0 or not _number(max_bridge_seconds) or max_bridge_seconds <= 0:
        raise ValueError('Некорректное ограничение сюжетной связки')
    source, words = _events(events, duration), _words(transcript)
    by_id = {event['id']: event for event in source}
    selected = set(selected_ids)
    if any(identifier not in by_id for identifier in selected):
        raise ValueError('Выбрано неизвестное исходное событие')
    exclusions = merge_ranges([piece for event in source for piece in confirmed_exclusions(event)])
    warnings, bridges = [], []
    for identifier in list(selected):
        if _pure_credit(by_id[identifier]) or not _subtract([by_id[identifier]], exclusions):
            selected.remove(identifier)
            warnings.append({'reason': 'confirmed_nonstory_selection_removed', 'event_id': identifier})
    initial = [event for event in source if event['id'] in selected]
    original_selected = set(selected)
    restored_nodes = set()

    def restore(node, left, right, reason, dimensions):
        event, unit = node['event'], node.get('unit')
        key = (event['id'], unit.get('id') if unit else None)
        if key in restored_nodes or not node['ranges']:
            return
        restored_nodes.add(key)
        first_restore = event['id'] not in selected
        retained = [] if first_restore else event.get('selected_ranges', [])
        event['selected_ranges'] = merge_ranges([*retained, *node['ranges']])
        event.update(minimal_context_ranges=True, unit_selection_version=1, continuity_restored=True)
        event.setdefault('continuity_bridge_ranges', []).extend(copy.deepcopy(node['ranges']))
        limitations = list(node['limitations'])
        coverage = merge_ranges(node['ranges'])
        full_coverage = (len(coverage) == 1 and coverage[0]['start'] <= event['start'] + .000001
                         and coverage[0]['end'] >= event['end'] - .000001)
        partial_unit = not full_coverage and any(row['kind'] == 'action_unit' for row in node['evidence'])
        if partial_unit and (unit is None or not unit.get('state_before') or not unit.get('state_after')):
            limitations.append('unit_specific_states_unavailable')
        if reason == 'direct_dependency_context' or limitations:
            event['selection_uncertain'] = True
        before = unit.get('state_before') if unit else None
        after = unit.get('state_after') if unit else None
        if not before:
            before = event.get('state_before', {}) if coverage[0]['start'] <= event['start'] + .000001 else {}
        if not after:
            after = event.get('state_after', {}) if coverage[-1]['end'] >= event['end'] - .000001 else {}
        if first_restore:
            event['continuity_state_before'] = copy.deepcopy(before or {})
        event['continuity_state_after'] = copy.deepcopy(after or {})
        audit = {'from': left['id'] if left else None, 'to': right['id'], 'source_event': event['id'],
                 'ranges': copy.deepcopy(node['ranges']), 'intervals': copy.deepcopy(node['ranges']),
                 'reason': reason, 'dimensions': list(dimensions), 'confidence': round(node['confidence'], 4),
                 'uncertain': bool(limitations) or node['confidence'] < .85,
                 'evidence': copy.deepcopy(node['evidence']), 'preserved_exclusions': copy.deepcopy(exclusions),
                 'limitations': list(dict.fromkeys(limitations)), 'continuity_version': CONTINUITY_VERSION}
        event.setdefault('continuity_decisions', []).append(copy.deepcopy(audit))
        bridges.append(audit)
        selected.add(event['id'])
        for limitation in audit['limitations']:
            warnings.append({'reason': limitation, 'from': audit['from'], 'to': audit['to'],
                             'source_event': event['id'], 'ranges': copy.deepcopy(node['ranges'])})

    for offset, right in enumerate(initial):
        left = initial[offset - 1] if offset else None
        comparison = _compare(_state(left, 'after'), _state(right, 'before')) if left else None
        changed = comparison['changed_dimensions'] if comparison else []
        if left and changed:
            nodes = _transition_nodes(source, original_selected, left, right)
            for node in nodes:
                ranges, limitations, evidence = _material(node['event'], words, exclusions, max_bridge_seconds, unit=node['unit'])
                node.update(ranges=ranges, limitations=limitations, evidence=evidence,
                            confidence=_confidence(node['event']) or .5)
                if 'endpoint_context_does_not_prove_action' in limitations:
                    node['confidence'] = min(node['confidence'], .55)
            needed = {}
            for field in changed:
                for node in _state_path(nodes, field, _state(left, 'after')[field], _state(right, 'before')[field]):
                    key = (node['event']['id'], node['unit'].get('id') if node['unit'] else None)
                    if key not in needed:
                        needed[key] = (node, [])
                    needed[key][1].append(field)
            for node, fields in sorted(needed.values(), key=lambda pair: (pair[0]['unit'] or pair[0]['event'])['start']):
                restore(node, left, right, 'evidenced_state_transition', fields)
        target = _state(right, 'before')
        prior = max((event for event in source if event['id'] in selected and event['end'] <= right['start'] + .002
                     and event['id'] != right['id']), key=lambda event: event['end'], default=None)
        provided = _state(prior, 'after') if prior else {key: None for key in STATE_FIELDS}
        known_target = [key for key in STATE_FIELDS if target[key]]
        satisfied = bool(known_target) and all(provided[key] == target[key] for key in known_target)
        if satisfied:
            continue
        dependencies = [by_id[identifier] for identifier in right.get('requires', []) if identifier in by_id
                        and identifier not in selected]
        dependencies.sort(key=lambda event: event['end'], reverse=True)
        for dependency in dependencies:
            if dependency['end'] > right['start'] + .002 or left and dependency['start'] < left['end'] - .002:
                warnings.append({'reason': 'dependency_outside_selected_gap', 'from': left['id'] if left else None,
                                 'to': right['id'], 'source_event': dependency['id']})
                continue
            ranges, limitations, evidence = _material(dependency, words, exclusions, max_bridge_seconds, dependency=True)
            if not ranges:
                warnings.append({'reason': 'dependency_has_no_permitted_context', 'to': right['id'],
                                 'source_event': dependency['id'], 'limitations': limitations})
                continue
            node = {'event': dependency, 'unit': None, 'ranges': ranges, 'limitations': limitations, 'evidence': evidence,
                    'confidence': min(_confidence(dependency) or .4, .55) if limitations else _confidence(dependency) or .5}
            restore(node, left, right, 'direct_dependency_context', known_target)
            # A dependency is a contextual signal. One bounded direct witness is
            # enough when its sub-action states do not justify more restoration.
            break
    final = [event for event in source if event['id'] in selected]
    transitions = []
    for left, right in zip(final, final[1:]):
        comparison = _compare(_state(left, 'after'), _state(right, 'before'))
        status = ('unresolved' if comparison['changed_dimensions'] else
                  'unknown' if not comparison['matched_dimensions'] else 'consistent')
        if left.get('selection_uncertain') or right.get('selection_uncertain'):
            if status == 'consistent':
                status = 'uncertain_context'
        row = {'from': left['id'], 'to': right['id'], **comparison, 'status': status,
               'state_after': copy.deepcopy(left.get('continuity_state_after', left.get('state_after', {}))),
               'state_before': copy.deepcopy(right.get('continuity_state_before', right.get('state_before', {}))),
               'confidence': round(min(_confidence(left), _confidence(right)), 4),
               'continuity_version': CONTINUITY_VERSION}
        transitions.append(row)
        if comparison['changed_dimensions']:
            warnings.append({'reason': 'unresolved_state_discontinuity', 'from': left['id'], 'to': right['id'],
                             'dimensions': comparison['changed_dimensions']})
        if comparison['unknown_dimensions']:
            warnings.append({'reason': 'unknown_transition_state', 'from': left['id'], 'to': right['id'],
                             'dimensions': comparison['unknown_dimensions']})
    return {'events': source, 'selected_ids': [event['id'] for event in final],
            'bridges': bridges, 'transitions': transitions, 'warnings': warnings}
