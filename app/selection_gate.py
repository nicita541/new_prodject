"""Source-unit selection readiness; unresolved analysis cannot reach planning."""
from __future__ import annotations

import math

from .selection_adjudication import POSITIVE_KINDS, _concrete
from .source_roles import confirmed_exclusions, merge_ranges

VERSION = 1


def _covers(intervals, targets):
    merged = merge_ranges(intervals)
    return all(any(r['start'] <= t['start']+.002 and r['end'] >= t['end']-.002
                   for r in merged) for t in targets)


def positive_ranges(event):
    """A source ownership claim or a naked action ID is not a selection reason."""
    known = {u['id']: u for u in event.get('units', [])}
    result = []
    for record in event.get('unit_evidence', []):
        unit = known.get(record.get('unit'))
        confidence = record.get('confidence')
        if (not unit or record.get('decision') == 'drop' or record.get('kind') not in POSITIVE_KINDS
                or not _concrete(record) or type(confidence) not in (int, float)
                or not math.isfinite(confidence) or confidence < .9
                or not (record.get('frame_indices') or record.get('speech_quote'))):
            continue
        a = max(unit['start'], record.get('view_start', unit['start']))
        b = min(unit['end'], record.get('view_end', unit['end']))
        if a < b:
            result.append({'start': a, 'end': b})
    return merge_ranges(result)


def selection_problems(event):
    if _covers(confirmed_exclusions(event), [event]):
        return []
    reasons = [key for key in ('uncertain', 'selection_uncertain', 'analysis_unresolved',
        'global_verification_unresolved', 'source_role_unresolved', 'whole_scene_last_resort')
        if event.get(key)]
    if event.get('understanding_status') == 'unresolved':
        reasons.append('understanding_unresolved')
    if event.get('protected_atmosphere_units') or event.get('protected_atmosphere_ranges'):
        reasons.append('generic_atmosphere')
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


def selection_readiness(events):
    unresolved = [{'event': e['id'], 'problems': selection_problems(e)} for e in events]
    unresolved = [e for e in unresolved if e['problems']]
    return {'version': VERSION, 'status': 'unresolved' if unresolved else 'passed',
            'unresolved': unresolved, 'policy': 'specific_source_evidence_required'}


def adjudicate_selections(source, events, transcript, shots, job_dir, vision, report, cancelled):
    from .selection_adjudication import adjudicate_event, issues
    from .source_roles import apply_exclusions
    result = []
    for index, event in enumerate(events):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        problems = selection_problems(event)
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
        problems = selection_problems(event)
        event['analysis_unresolved'] = bool(problems)
        event['analysis_unresolved_reasons'] = problems
    return result
