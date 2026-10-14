"""Source-bounded audio handles, separate from semantic story selection."""
from __future__ import annotations
import math

from app.source_ranges import merge_ranges
from .source_roles import confirmed_exclusions
from app.source_ranges import subtract_ranges as _subtract

VERSION = 1
LEAD = .18
TAIL = .55


def validate_overrides(overrides, duration):
    if not isinstance(overrides, list) or len(overrides) > 512:
        raise ValueError('Некорректные уточнения границ речи')
    for row in overrides:
        if (not isinstance(row, dict) or set(row) != {'start', 'end', 'lead', 'tail'}
                or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in row)
                or not 0 <= row['start'] < row['end'] <= duration
                or not LEAD <= row['lead'] <= .6 or not TAIL <= row['tail'] <= 1.5):
            raise ValueError('Уточнение границ речи выходит за допустимые пределы')
    return overrides


def _margins(start, end, overrides):
    matches = [r for r in overrides if r['start'] < end and r['end'] > start]
    return max([LEAD]+[r['lead'] for r in matches]), max([TAIL]+[r['tail'] for r in matches])


def expand_ranges(ranges, transcript, duration, blocked=(), *, overrides=()):
    """Keep consonant margins without introducing any omitted ASR word."""
    words = transcript.get('words', [])
    overrides = validate_overrides(list(overrides), duration)
    result = []
    for piece in merge_ranges(ranges):
        start, end = piece['start'], piece['end']
        lead, tail = _margins(start, end, overrides)
        inside = [w for w in words if start-.002 <= w['start'] and w['end'] <= end+.002]
        left, right = start, end
        if inside and (inside[0]['start']-start < .12
                       or lead > LEAD and inside[0]['start']-start <= LEAD+.002):
            preceding = max((w['end'] for w in words if w['end'] <= start+.002), default=-1)
            left = min(start, max(0, inside[0]['start']-lead, preceding+.04))
        if inside and (end-inside[-1]['end'] < .12
                       or tail > TAIL and end-inside[-1]['end'] <= TAIL+.002):
            following = min((w['start'] for w in words if w['start'] >= end-.002), default=duration+.04)
            right = max(end, min(duration, inside[-1]['end']+tail, following-.04))
        # An exclusion is a barrier, not permission to retain a disconnected
        # fragment on its other side.
        for exclusion in blocked:
            if exclusion['start'] < start and exclusion['end'] > left:
                left = max(left, min(start, exclusion['end']))
            if exclusion['end'] > end and exclusion['start'] < right:
                right = min(right, max(end, exclusion['start']))
        result.append({'start':round(left,6),'end':round(right,6)})
    return merge_ranges(result)


def source_handles(events, transcript, duration, *, overrides=()):
    """Recompute permitted margins from original accepted source evidence."""
    from .selection_gate import positive_ranges
    core = merge_ranges([{'start':max(p['start'],s['start']), 'end':min(p['end'],s['end'])}
        for event in events for p in positive_ranges(event) for s in event.get('selected_ranges', [])
        if p['start'] < s['end'] and p['end'] > s['start']])
    excluded = [r for event in events for r in confirmed_exclusions(event)]
    return [{'start':round(r['start'],6),'end':round(r['end'],6)}
            for r in _subtract(expand_ranges(core,transcript,duration,excluded,overrides=overrides),core)
            if r['end']-r['start'] > .002]


def barriers(events, core):
    """Audio padding cannot acquire part of an omitted physical action."""
    from .selection_gate import positive_ranges
    actions = [r for event in events for record in event.get('unit_evidence', [])
               if record.get('kind') in ('physical_action','state_transition')
               for r in positive_ranges({**event,'unit_evidence':[record]})]
    return [*[r for event in events for r in confirmed_exclusions(event)],*_subtract(actions,core)]


def semantic_ranges(plan, events, transcript, duration, *, overrides=()):
    """Verify the derived story clock independently of claimed plan metadata."""
    from .selection_gate import _covers
    cuts = merge_ranges([c for p in plan['parts'] for c in p['cuts']])
    overrides = validate_overrides(list(overrides), duration)
    if plan.get('speech_handle_overrides', []) != overrides:
        raise ValueError('Speech margins must match the source analysis policy')
    core = plan.get('semantic_ranges')
    if core is None:
        return _subtract(cuts,source_handles(events,transcript,duration,overrides=overrides))
    if (not isinstance(core,list) or any(not isinstance(r,dict) or set(r) != {'start','end'}
            or any(type(r[k]) not in (int,float) or not math.isfinite(r[k]) for k in ('start','end'))
            or not 0 <= r['start'] < r['end'] <= duration for r in core)):
        raise ValueError('Invalid semantic source ranges')
    core = merge_ranges(core)
    expanded = expand_ranges(core,transcript,duration,barriers(events,core),overrides=overrides)
    if not (_covers(expanded,cuts) and _covers(cuts,expanded) and _covers(cuts,core)):
        raise ValueError('Speech handles do not match the original semantic ranges')
    return core


def ending_matches(time, boundary, transcript, cuts, *, overrides=()):
    """An independently verified ending may include its continuous audio tail."""
    tail = max([TAIL]+[r['tail'] for r in overrides if r['start'] <= time <= r['end']])
    return (0 <= boundary-time <= tail+.002
        and any(c['start'] <= time <= boundary <= c['end']+.002 for c in cuts)
        and not any(w['start'] < boundary-.002 and w['end'] > time+.002
                    for w in transcript.get('words', [])))
