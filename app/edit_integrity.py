"""Deterministic checks for tiny edits, independent of semantic confidence.

The current analysis contract supplies average FPS, not a complete frame-PTS
index. Report that estimate honestly; legacy analyses use an explicit 30 FPS
fallback. Shot boundaries distinguish a complete fast source shot from a new
fragment cut out of a longer shot.
"""
from __future__ import annotations

import copy
import math

from .source_ranges import merge_ranges

VERSION = 1
LEGACY_FPS = 30.0
MAX_EDIT_FRAMES = 2
TIME_EPSILON = 1e-6


def timing(analysis):
    fps = analysis.get('probe', {}).get('fps', analysis.get('fps'))
    if type(fps) in (int, float) and math.isfinite(fps) and fps > 0:
        return {'fps': float(fps), 'timing_basis': 'source_average_fps'}
    return {'fps': LEGACY_FPS, 'timing_basis': 'legacy_assumed_30fps'}


def _tiny(start, end, clock):
    return TIME_EPSILON < end-start <= MAX_EDIT_FRAMES/clock['fps']+TIME_EPSILON


def _whole_source_shots(start, end, analysis):
    duration = analysis['probe']['duration']
    # A complete run of original shots may itself contain a fast flash. Merely
    # matching one boundary is insufficient to exempt a truncated shot.
    boundaries = {0.0, float(duration)}
    for shot in analysis.get('shots', []):
        for key in ('start', 'end'):
            value = shot.get(key)
            if type(value) in (int, float) and math.isfinite(value):
                boundaries.add(float(value))
    return all(any(abs(edge-boundary) <= TIME_EPSILON for boundary in boundaries)
               for edge in (start, end))


def inspect_edits(analysis, plan):
    """Report introduced tiny holes/islands within each independently played part."""
    clock = timing(analysis)
    problems = []
    for part in plan.get('parts', []):
        # A renderer may split continuous source for focus or part bookkeeping.
        # Such adjacent cut records do not introduce a visual edit.
        spans = merge_ranges(part['cuts'])
        for left, right in zip(spans, spans[1:]):
            if _tiny(left['end'], right['start'], clock):
                problems.append({'code': 'introduced_micro_gap', 'part': part['index'],
                    'range': {'start': left['end'], 'end': right['start']}, **clock})
        for span in spans:
            if _tiny(span['start'], span['end'], clock) and not _whole_source_shots(
                    span['start'], span['end'], analysis):
                problems.append({'code': 'introduced_micro_fragment', 'part': part['index'],
                    'range': span, **clock})
    return problems


def normalize_proved_gaps(intervals, analysis, events):
    """Join only tiny silent gaps already covered by positive source evidence.

    Never invent an omission decision, restore excluded content, acquire an
    omitted action, or expand outside reviewed footage. Unresolved cases remain
    intact for an explicit edit-integrity failure, not an automatic deletion.
    """
    from .selection_gate import positive_ranges
    from .source_roles import confirmed_exclusions
    from .speech_handles import barriers
    from .review_scope import scope_barriers

    clock = timing(analysis)
    proofs = {event['id']: positive_ranges(event) for event in events}
    blocked = [r for event in events for r in confirmed_exclusions(event)]
    blocked.extend(barriers(events, intervals))
    blocked.extend(scope_barriers(analysis))
    for event in events:
        units = {u['id']: u for u in event.get('units', [])}
        for record in event.get('unit_evidence', []):
            unit = units.get(record.get('unit'))
            if record.get('decision') == 'drop' and unit:
                blocked.append({'start': record.get('view_start', unit['start']),
                                'end': record.get('view_end', unit['end'])})
    # Segments also cover speech whose individual word timing is incomplete.
    speech = [*analysis.get('transcript', {}).get('words', []),
              *analysis.get('transcript', {}).get('segments', [])]
    result = []
    for interval in intervals:
        current = copy.deepcopy(interval)
        if result:
            gap = {'start': result[-1]['end'], 'end': current['start']}
            # A tiny intervening event is still a different source owner. Do
            # not silently select it or bypass its dependency checks.
            common_owners = set(result[-1]['event_ids']) & set(current['event_ids'])
            covered = any(r['start'] <= gap['start']+TIME_EPSILON
                          and r['end'] >= gap['end']-TIME_EPSILON
                          for owner in common_owners for r in proofs.get(owner, []))
            if (_tiny(gap['start'], gap['end'], clock) and covered
                    and not any(r['start'] < gap['end'] and r['end'] > gap['start']
                                for r in [*blocked, *speech])):
                result[-1]['end'] = current['end']
                result[-1]['event_ids'] = list(dict.fromkeys(
                    [*result[-1]['event_ids'], *current['event_ids']]))
                continue
        result.append(current)
    return result
