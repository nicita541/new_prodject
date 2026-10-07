"""Deterministic explanations for every kept or omitted source interval."""
from __future__ import annotations

from .source_roles import confirmed_exclusions

PLANNER_AUDIT_VERSION = 1


def planner_audit(analysis, plan, *, candidates=None, arcs=None, continuity=None, part_policy=None):
    events = analysis['events']
    cuts = [cut for part in plan['parts'] for cut in part['cuts']]
    retained = set(plan['selected_event_ids'])
    candidates = candidates or [{'event_id': event['id'], 'score': event.get('importance', 3),
        'selected': event['id'] in retained,
        'reasons': ['selected_story' if event['id'] in retained else 'below_story_threshold']} for event in events]
    by_candidate = {row['event_id']: row for row in candidates}
    boundaries = {0.0, float(analysis['probe']['duration'])}
    for record in [*events, *cuts, *(unit for e in events for unit in e.get('units', [])),
                   *(r for e in events for r in confirmed_exclusions(e))]:
        boundaries.update((float(record['start']), float(record['end'])))
    points = sorted(boundaries)
    decisions = []
    for left, right in zip(points, points[1:]):
        if right-left <= 1e-7:
            continue
        owners = [e for e in events if e['start'] < right and e['end'] > left]
        kept = any(c['start'] <= left + 1e-6 and c['end'] >= right - 1e-6 for c in cuts)
        reasons, evidence, unit_ids = [], [], []
        for event in owners:
            if not kept and any(r['start'] < right and r['end'] > left for r in confirmed_exclusions(event)):
                reasons.append('confirmed_source_exclusion')
            elif kept and event['id'] not in retained:
                reasons.append('speech_handle_or_joined_selected_boundary')
            elif event['id'] not in retained:
                reasons.extend(by_candidate.get(event['id'], {}).get('reasons', ['not_selected']))
            elif not kept:
                reasons.append('outside_selected_source_units_or_speech_handles')
            elif event.get('minimal_context_ranges'):
                reasons.append('minimal_causal_context')
            else:
                reasons.append('selected_source_unit_or_complete_reply')
                reasons.extend(by_candidate.get(event['id'], {}).get('reasons', []))
            evidence.append({'event_id': event['id'], 'summary_source': event.get('summary_source', 'local'),
                'scene_id': event.get('scene_id'),
                'summary': event.get('final_summary', event.get('summary', '')),
                'confidence': event.get('confidence'), 'uncertainty_reasons': event.get('uncertainty_reasons', []),
                'local_summary': event.get('local_summary'), 'recovery_summary': event.get('recovery_summary'),
                'global_summary': event.get('global_summary'),
                'state_before': event.get('state_before'), 'state_after': event.get('state_after'),
                'omission': event.get('global_omission'), 'fallback': event.get('fallback'),
                'bridge_evidence': [b for b in (continuity or {}).get('bridges', []) if b['source_event'] == event['id']],
                'unit_omissions': [u for u in event.get('omitted_story_units', [])
                                  if isinstance(u, dict) and u.get('start', left) < right and u.get('end', right) > left]})
            unit_ids.extend(u['id'] for u in event.get('units', []) if u['start'] < right and u['end'] > left)
        if not owners:
            reasons.append('speech_handle' if kept else 'outside_analyzed_story')
        decisions.append({'source_start': left, 'source_end': right, 'duration': right-left,
            'selected': kept, 'event_ids': [e['id'] for e in owners], 'unit_ids': unit_ids,
            'reasons': list(dict.fromkeys(reasons)), 'evidence': evidence})
    return {'version': PLANNER_AUDIT_VERSION, 'candidates': candidates, 'arcs': arcs or [],
        'bridges': (continuity or {}).get('bridges', []),
        'transitions': (continuity or {}).get('transitions', []),
        'continuity_warnings': (continuity or {}).get('warnings', []),
        'retention_budget': plan.get('retention_budget'),
        'retained_duration': sum(p['duration'] for p in plan['parts']),
        'part_policy': part_policy or {'chosen_part_count': len(plan['parts'])},
        'part_endings': [{'part': p['index'], 'source_time': p['cuts'][-1]['end'],
            'ending': p.get('ending'), 'reason': ('verified_ending' if p.get('ending', {}).get('verification', {}).get('supported') is True else
            'derived_arc_boundary' if p.get('ending', {}).get('arc_id') else 'supplied_ending_candidate') if p.get('ending') else
            'safe_complete_reply_or_arc_boundary'} for p in plan['parts']], 'decisions': decisions}
