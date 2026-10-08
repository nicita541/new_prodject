"""Source-unit selection readiness; unresolved analysis cannot reach planning."""
from __future__ import annotations

import math
import re

from .selection_adjudication import POSITIVE_KINDS, _concrete
from .source_roles import confirmed_exclusions, merge_ranges

VERSION = 4
DOWNSTREAM_REASONS = {'story_structure_unresolved', 'dialogue_relations_unresolved'}


def _covers(intervals, targets):
    merged = merge_ranges(intervals)
    return all(any(r['start'] <= t['start']+.002 and r['end'] >= t['end']-.002
                   for r in merged) for t in targets)


def _anchored(record, unit, start, end):
    """Check persisted CURRENT geometry, rather than trusting an index label."""
    indices, times, quote = (record.get('frame_indices', []), record.get('frame_times', []),
                             record.get('speech_quote', ''))
    frame_count = record.get('frame_count')
    if (not isinstance(indices, list) or any(type(i) is not int or i < 1 for i in indices)
            or indices and (type(frame_count) is not int or frame_count < max(indices))
            or len(indices) != len(set(indices)) or not isinstance(times, list)
            or len(times) != len(indices) or any(type(t) not in (int, float)
                or not math.isfinite(t) or not start <= t < end for t in times)
            or not isinstance(quote, str)):
        return False
    tokens = lambda text: re.findall(r'\w+', text.casefold().replace('ё', 'е'))
    q, text = tokens(quote), tokens(str(unit.get('text', '')))
    if q and not any(text[i:i+len(q)] == q for i in range(len(text)-len(q)+1)):
        return False
    if record.get('kind') in ('causal_dialogue', 'response') and not q:
        return False
    if record.get('kind') in {'character_reaction', 'emotional_pause', 'establishing_context',
                              'physical_action', 'state_transition'} and not indices:
        return False
    return bool(indices or q)


def positive_ranges(event):
    """A source ownership claim or a naked action ID is not a selection reason."""
    known = {u['id']: u for u in event.get('units', [])}
    result = []
    for record in event.get('unit_evidence', []):
        if not isinstance(record, dict):
            continue
        unit = known.get(record.get('unit'))
        confidence = record.get('confidence')
        if (not unit or record.get('decision') == 'drop' or record.get('kind') not in POSITIVE_KINDS
                or not _concrete(record) or type(confidence) not in (int, float)
                or not math.isfinite(confidence) or not .9 <= confidence <= 1
                or not (record.get('frame_indices') or record.get('speech_quote'))):
            continue
        bounds = (unit.get('start'), unit.get('end'), record.get('view_start', unit.get('start')),
                  record.get('view_end', unit.get('end')))
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in bounds):
            continue
        a = max(bounds[0], bounds[2])
        b = min(bounds[1], bounds[3])
        if a < b and _anchored(record, unit, a, b):
            result.append({'start': a, 'end': b})
    return merge_ranges(result)


def selection_problems(event):
    if _covers(confirmed_exclusions(event), [event]):
        return []
    reasons = [key for key in ('uncertain', 'selection_uncertain', 'analysis_unresolved',
        'global_verification_unresolved', 'source_role_unresolved', 'whole_scene_last_resort',
        'selection_needs_adjudication')
        if event.get(key)]
    if event.get('understanding_status') == 'unresolved':
        reasons.append('understanding_unresolved')
    if event.get('protected_atmosphere_units') or event.get('protected_atmosphere_ranges'):
        reasons.append('generic_atmosphere')
    if event.get('atmosphere_review_units'):
        reasons.append('atmosphere_requires_specific_evidence')
    if event.get('fallback'):
        reasons.append('fallback_requires_adjudication')
    known = {u['id'] for u in event.get('units', [])}
    if not set(event.get('action_units', [])) <= known:
        reasons.append('unknown_action_ownership')
    for field in ('understanding_confidence', 'selection_confidence'):
        value = event.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not .9 <= value <= 1:
            reasons.append(field+'_insufficient')
    if event.get('selection_status') != 'accepted':
        reasons.append('selection_not_adjudicated')
    selected = event.get('selected_ranges', [])
    if selected and not _covers(positive_ranges(event), selected):
        reasons.append('unexplained_selected_ranges')
    if not selected and not event.get('selection_empty_verified'):
        reasons.append('empty_selection_not_verified')
    return list(dict.fromkeys(reasons))


def source_selection_problems(event):
    """Project only downstream administrative failure out of source readiness.

    The original failure stays on the event until its responsible pass succeeds.
    Missing proof, selection/understanding uncertainty and all other flags remain.
    """
    reasons = event.get('analysis_unresolved_reasons')
    if (event.get('analysis_unresolved') and isinstance(reasons, list) and reasons
            and all(isinstance(r, str) for r in reasons) and set(reasons) <= DOWNSTREAM_REASONS):
        event = {**event, 'analysis_unresolved': False}
    return selection_problems(event)


def source_selection_readiness(events):
    unresolved = [{'event': e['id'], 'problems': source_selection_problems(e)} for e in events]
    return {'version': VERSION, 'status': 'unresolved' if any(r['problems'] for r in unresolved) else 'passed',
            'unresolved': [r for r in unresolved if r['problems']]}


def selection_readiness(events):
    unresolved = [{'event': e['id'], 'problems': selection_problems(e)} for e in events]
    unresolved = [e for e in unresolved if e['problems']]
    return {'version': VERSION, 'status': 'unresolved' if unresolved else 'passed',
            'unresolved': unresolved, 'policy': 'specific_source_evidence_required'}


def adjudicate_selections(source, events, transcript, shots, job_dir, vision, report, cancelled, *, source_only=False):
    from .selection_adjudication import adjudicate_event, issues
    from .source_roles import apply_exclusions
    result = []
    for index, event in enumerate(events):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        problems = source_selection_problems(event) if source_only else selection_problems(event)
        if problems:
            report('analyze', .5, f'Проверка конкретного выбора: событие {index+1} из {len(events)}')
            event = adjudicate_event(source, event, transcript, shots, job_dir, vision, cancelled,
                questions=[*issues(event), 'Проверить спорные решения: '+', '.join(problems)])
            if event.get('selection_status') == 'accepted' and event.get('selected_ranges'):
                # Positive evidence, rather than old filler importance, determines
                # eligibility. Later ranking still decides optional retention.
                event.update(kind='story', importance=max(3, event.get('importance', 1)))
                if any(r.get('kind') == 'state_transition' and r.get('decision') == 'keep'
                       for r in event.get('unit_evidence', [])):
                    event['narrative_bridge'] = True
        result.append(event)
    result = apply_exclusions(result)
    for event in result:
        if source_only and not source_selection_problems(event) and selection_problems(event):
            # Preserve the downstream failure; source acceptance cannot clear it.
            continue
        problems = selection_problems(event)
        event['analysis_unresolved'] = bool(problems)
        event['analysis_unresolved_reasons'] = problems
    return result
