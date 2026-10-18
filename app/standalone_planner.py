"""Compile independently qualified Shorts from existing source-unit arcs.

Pure first-stage compiler: no new interpretation, model calls, persistence or
episode-wide retention budget. A declined candidate cannot veto another clip.
Source analyses remain untouched; each plan has its own range-scoped view.
"""
from __future__ import annotations

import copy
import math

from .content_identity import digest
from .source_ranges import merge_ranges, intersect_ranges, subtract_ranges
from .selection_gate import positive_ranges, selection_problems, selection_readiness
from .source_roles import confirmed_exclusions
from .story_structure import build_story_arcs
from .story_structure_pass import source_units
from .planner import validate_analysis, validate_plan, SCHEMA_VERSION
from .final_quality import inspect_final_quality
from .speech_handles import expand_ranges, barriers
from .subtitles import make_cues, remap_words

VERSION = 1
DEFAULT_SETTINGS = {'max_clips': 3, 'preferred_min_duration': 45.0,
                    'preferred_max_duration': 90.0, 'max_duration': 120.0}
REQUIRED_RELATIONS = {'cause', 'response', 'setup_payoff', 'state_transition'}


class _Declined(ValueError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason, self.details = reason, details


def _key(ref):
    return ref['event'], ref['unit']


def _duration(ranges):
    return sum(r['end']-r['start'] for r in merge_ranges(ranges))


def _settings(value):
    if value is not None and (not isinstance(value, dict) or set(value)-set(DEFAULT_SETTINGS)):
        raise ValueError('Unknown standalone planning settings')
    result = {**DEFAULT_SETTINGS, **(value or {})}
    if type(result['max_clips']) is not int or not 1 <= result['max_clips'] <= 64:
        raise ValueError('max_clips must be an integer from 1 to 64')
    for name in ('preferred_min_duration', 'preferred_max_duration', 'max_duration'):
        if type(result[name]) not in (int, float) or not math.isfinite(result[name]):
            raise ValueError('Standalone durations must be finite numbers')
    if not 0 < result['preferred_min_duration'] <= result['preferred_max_duration'] <= result['max_duration'] <= 120:
        raise ValueError('Standalone duration preferences must be ordered and at most 120 seconds')
    return result


def _source(analysis):
    probe = analysis['probe']
    for key in ('duration', 'width', 'height'):
        value = probe[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid source media geometry')
    if not probe.get('has_audio') or probe['width'] < 2 or probe['height'] < 2:
        raise ValueError('Source audio or video is unavailable')
    from .source_text import source_text
    for container in ('words', 'segments'):
        previous = -1.0
        for row in analysis['transcript'].get(container, []):
            if (any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('start', 'end'))
                    or not 0 <= row['start'] < row['end'] <= probe['duration']+.002
                    or row['start'] < previous or not isinstance(row.get('text'), str)):
                raise ValueError('Invalid source transcript timing')
            previous = row['start']
    known = {}
    for original in analysis['events']:
        event = copy.deepcopy(original)
        if event['id'] in known:
            raise ValueError('Duplicate source event identity')
        for unit in event.get('units', []):
            unit['text'] = source_text(analysis['transcript'], unit['start'], unit['end'])
        known[event['id']] = event
    return known


def _qualified_unit(known, ref):
    event = known.get(ref['event'])
    if event is None:
        raise _Declined('required_source_missing', ref=ref)
    problems = selection_problems(event)
    if problems:
        raise _Declined('required_source_unresolved', ref=ref, problems=problems)
    unit = next((u for u in event.get('units', []) if u['id'] == ref['unit']), None)
    if unit is None:
        raise _Declined('required_unit_missing', ref=ref)
    if event.get('global_excluded') or event.get('pacing_excluded') or event.get('source_role_excluded'):
        raise _Declined('required_source_excluded', ref=ref)
    return event, unit


def _closure(analysis, known, arc):
    selected = {}

    def add(ref, requested=None):
        event, unit = _qualified_unit(known, ref)
        pieces = intersect_ranges([unit], requested if requested is not None else event['selected_ranges'])
        if not pieces or subtract_ranges(pieces, positive_ranges(event)):
            raise _Declined('required_unit_has_no_complete_proof', ref=ref)
        if intersect_ranges(pieces, confirmed_exclusions(event)):
            raise _Declined('required_source_excluded', ref=ref)
        if unit['id'] in event.get('action_units', []):
            action = subtract_ranges([unit], confirmed_exclusions(event))
            if subtract_ranges(action, positive_ranges(event)):
                raise _Declined('required_action_unproved', ref=ref)
            pieces = merge_ranges([*pieces, *action])
        key = _key(ref)
        before = selected.get(key, [])
        after = merge_ranges([*before, *pieces])
        selected[key] = after
        return before != after

    for ref in arc['source_unit_refs']:
        add(ref, arc['source_ranges'])
    relations = [*analysis.get('story_structure', {}).get('relations', []),
                 *(r for e in known.values() for r in e.get('story_relations', []))]
    pairs = [*analysis.get('dialogue_relations', {}).get('pairs', []),
             *(p for e in known.values() for p in e.get('dialogue_relations', {}).get('pairs', []))]
    # Every successful iteration adds a finite source range or owner. No model
    # judgment or retry is hidden inside dependency closure.
    while True:
        changed = False
        owners = {key[0] for key in selected}
        for owner in list(owners):
            for required in known[owner].get('requires', []):
                dependency = known.get(required)
                if dependency is None or dependency['start'] >= known[owner]['start']:
                    raise _Declined('required_source_missing_or_nonchronological', event=owner, requires=required)
                for unit in dependency.get('units', []):
                    if intersect_ranges([unit], dependency.get('selected_ranges', [])):
                        changed = add({'event': required, 'unit': unit['id']}) or changed
                if required not in {key[0] for key in selected}:
                    raise _Declined('required_source_empty', event=owner, requires=required)
        for relation in relations:
            if relation.get('type') in REQUIRED_RELATIONS and _key(relation['to']) in selected:
                changed = add(relation['from']) or changed
        retained = merge_ranges([r for rows in selected.values() for r in rows])
        for pair in pairs:
            if pair.get('status') != 'confirmed' or not pair.get('requires_answer'):
                continue
            ranges = [*pair.get('question_ranges', []), *pair.get('answer_ranges', [])]
            if not intersect_ranges(retained, ranges):
                continue
            for side in ('question', 'answer'):
                for ref in pair[side+'_refs']:
                    # Existing qualified units own the complete reply/context;
                    # shrinking a prerequisite to its quote would invent a new
                    # edit and could omit the reaction around the response.
                    changed = add(ref) or changed
        if not changed:
            return selected


def _project(analysis, selected, known):
    events = []
    refs = set(selected)
    for original in known.values():
        units = {key[1] for key in refs if key[0] == original['id']}
        if not units:
            continue
        event = copy.deepcopy(original)
        event['units'] = [u for u in event.get('units', []) if u['id'] in units]
        event['selected_ranges'] = merge_ranges([r for key, rows in selected.items() if key[0] == event['id'] for r in rows])
        event['unit_evidence'] = [r for r in event.get('unit_evidence', []) if r.get('unit') in units]
        event['action_units'] = [u for u in event.get('action_units', []) if u in units]
        event['story_structure']['units'] = [u for u in event['story_structure'].get('units', []) if _key(u['ref']) in refs]
        event['dialogue_relations']['coverage'] = [u for u in event['dialogue_relations'].get('coverage', []) if _key(u['ref']) in refs]
        event['dialogue_relations']['pairs'] = [p for p in event['dialogue_relations'].get('pairs', [])
            if any(_key(r) in refs for r in [*p.get('question_refs', []), *p.get('answer_refs', [])])]
        event['story_relations'] = [r for r in event.get('story_relations', [])
                                   if _key(r['from']) in refs and _key(r['to']) in refs]
        event['inferred_story_arcs'] = [a for a in event.get('inferred_story_arcs', [])
                                      if all(_key(r) in refs for r in a.get('source_unit_refs', []))]
        events.append(event)
    result = {key: copy.deepcopy(analysis[key]) for key in
              ('probe', 'transcript', 'shots', 'speech_handle_overrides', 'review_scope') if key in analysis}
    result.update(events=events, quality_policy='source_proved_v1', selection_gate=selection_readiness(events))
    scene_ids = {event.get('scene_id') for event in events}
    result['scenes'] = [copy.deepcopy(s) for s in analysis.get('scenes', []) if s['id'] in scene_ids]
    return result


def _plan(analysis, core, *, draft=False):
    from .review_scope import scope_barriers
    duration = analysis['probe']['duration']
    events = analysis['events']
    blocked = [*barriers(events, core), *scope_barriers(analysis)]
    expanded = expand_ranges(core, analysis['transcript'], duration, blocked,
                             overrides=analysis.get('speech_handle_overrides', []))
    technical_normalizations = []
    audio_observations = None
    if analysis.get('audio_boundary_evidence') is not None:
        from .audio_boundaries import adjust_ranges
        expanded, audio_observations = adjust_ranges(core, expanded, analysis['transcript'], duration,
                                                     analysis['audio_boundary_evidence'], blocked)
    if analysis.get('quality_policy') == 'standalone_candidate_proved_v1':
        from .edit_integrity import _tiny, timing
        clock = timing(analysis)
        speech = [*analysis['transcript'].get('words', []), *analysis['transcript'].get('segments', [])]
        joined = []
        for piece in expanded:
            gap = {'start': joined[-1]['end'], 'end': piece['start']} if joined else None
            if (gap and _tiny(gap['start'], gap['end'], clock)
                    and not any(row['start'] < gap['end'] and row['end'] > gap['start']
                                for row in [*speech, *blocked])):
                # This new contract has no legacy unit proof yet. Restore only
                # an introduced tiny silent hole before native QA; the reviewer
                # observes these actual cuts and may still reject the candidate.
                joined[-1]['end'] = piece['end']
                technical_normalizations.append({'reason': 'restore_tiny_silent_gap_before_native_review',
                                                  'range': gap, **clock})
            else:
                joined.append(copy.deepcopy(piece))
        expanded = joined
    cuts = []
    for piece in expanded:
        owners = [e for e in events if e['start'] < piece['end'] and e['end'] > piece['start']]
        anchors = sorted([copy.deepcopy(a) for e in owners for a in e.get('focus', [])
                          if piece['start'] <= a['time'] <= piece['end']], key=lambda a: a['time'])
        if not anchors:
            previous = [a for e in owners for a in e.get('focus', []) if a['time'] <= piece['start']]
            anchor = max(previous, key=lambda a: a['time']) if previous else {'x': .5, 'y': .5, 'confidence': 0.0}
            anchors = [{**copy.deepcopy(anchor), 'time': piece['start']}]
        for anchor in anchors:
            anchor['hard_cut'] = any(abs(anchor['time']-shot['start']) <= .002 for shot in analysis.get('shots', []))
        cuts.append({**piece, 'event_ids': [e['id'] for e in owners], 'focus': anchors})
    plan = {'schema_version': SCHEMA_VERSION, 'source': {k: analysis['probe'][k] for k in ('duration', 'width', 'height')},
            'selected_event_ids': [e['id'] for e in events], 'events': copy.deepcopy(events),
            'semantic_ranges': copy.deepcopy(core), 'parts': [{'index': 1, 'duration': round(_duration(cuts), 6),
                'cuts': cuts, 'subtitles': make_cues(remap_words(analysis['transcript'].get('words', []), cuts))}],
            'warnings': [], 'standalone': True}
    if technical_normalizations:
        plan['technical_normalizations'] = technical_normalizations
    if audio_observations is not None:
        plan['audio_boundary_observations'] = audio_observations
        plan['audio_boundary_evidence_digest'] = digest(analysis['audio_boundary_evidence'])
    if analysis.get('speech_handle_overrides'):
        plan['speech_handle_overrides'] = copy.deepcopy(analysis['speech_handle_overrides'])
    if draft:
        plan.update(draft=True, export_eligible=False, editorial_status='not_approved')
    return plan


def _candidate(analysis, known, arc, settings):
    if (not arc.get('source_unit_refs') or arc.get('uncertain') is not False
            or not arc.get('complete_ending') or not arc.get('ending_verified')):
        raise _Declined('unqualified_source_arc')
    roles = arc.get('roles', [])
    premise = [r['ref'] for r in roles if r['role'] == 'setup']
    payoff = [r['ref'] for r in roles if r['role'] == 'payoff']
    if not premise or arc.get('anchor') not in premise or arc.get('closing_unit') not in payoff:
        raise _Declined('missing_supported_beginning_or_payoff')
    selected = _closure(analysis, known, arc)
    scoped = _project(analysis, selected, known)
    validate_analysis(scoped)
    nodes, _, _ = source_units(scoped['events'], scoped['transcript'])
    supported = {_key(n['ref']): n for n in nodes}
    proof = arc.get('verification', {})
    for ref in arc['source_unit_refs']:
        node = supported.get(_key(ref))
        supports = [s for s in proof.get('proofs', []) if s.get('ref') == ref]
        from .source_text import quote_in
        if not node or not any(s.get('proof') == p['id'] and
                (not s.get('quote') or quote_in(s['quote'], node['ASR']))
                for s in supports for p in node['proofs']):
            raise _Declined('arc_member_has_no_native_source_support', ref=ref)
    order = sorted(arc['source_unit_refs'], key=lambda ref: supported[_key(ref)]['start'])
    if order[0] != arc['anchor'] or order[-1] != arc['closing_unit']:
        raise _Declined('beginning_or_payoff_is_not_at_arc_boundary')
    core = merge_ranges([r for rows in selected.values() for r in rows])
    first = min(selected, key=lambda key: selected[key][0]['start'])
    first_roles = next((row.get('roles', []) for e in scoped['events']
                       for row in e.get('story_structure', {}).get('units', []) if _key(row['ref']) == first), [])
    if first != _key(arc['anchor']) and 'setup' not in first_roles:
        raise _Declined('missing_supported_context_opening', ref={'event': first[0], 'unit': first[1]})
    if core[-1]['end'] > arc['end']+.002:
        raise _Declined('required_context_continues_after_payoff')
    plan = _plan(scoped, core)
    if plan['parts'][0]['duration'] > settings['max_duration']+.000001:
        raise _Declined('complete_story_exceeds_duration', duration=plan['parts'][0]['duration'])
    validate_plan(plan, scoped)
    quality = inspect_final_quality(scoped, plan)
    if quality['status'] != 'passed':
        raise _Declined('native_quality_unresolved', problems=quality['problems'])
    from .viewer_interest import score_source
    score = score_source(scoped['events'], {e['id']: e['selected_ranges'] for e in scoped['events']}, scoped['transcript'])
    source_contract = digest({'probe': scoped['probe'], 'source_nodes': nodes})
    ident = 'short_'+digest({'arc': arc['id'], 'ranges': core, 'source_contract': source_contract})[:20]
    plan.update(quality_gate=quality, export_eligible=True, candidate_id=ident)
    return {'id': ident, 'arc_id': arc['id'], 'status': 'ready', 'export_eligible': True,
            'source_ranges': core, 'source_contract_digest': source_contract,
            'duration': plan['parts'][0]['duration'], 'score': score,
            'premise_refs': premise, 'development_refs': [r['ref'] for r in roles if r['role'] in ('development', 'turning_point')],
            'payoff_refs': payoff, 'required_refs': [{'event': key[0], 'unit': key[1]} for key in selected],
            'plan': plan, 'scoped_analysis': scoped}


def _drafts(analysis, declined, settings):
    """Suggest bounded continuous source scenes, never claim editorial approval."""
    result = []
    for event in analysis['events']:
        if (event.get('kind') != 'story' or event.get('credit_montage')
                or event.get('global_excluded') or event.get('pacing_excluded')):
            continue
        if event['end']-event['start'] > settings['max_duration'] or confirmed_exclusions(event):
            continue
        if not any(r.get('event') == event['id'] or event['id'] in r.get('event_ids', []) for r in declined):
            continue
        scoped = {key: copy.deepcopy(analysis[key]) for key in
                  ('probe', 'transcript', 'shots', 'speech_handle_overrides', 'review_scope') if key in analysis}
        scoped['events'] = [copy.deepcopy(event)]
        try:
            plan = _plan(scoped, [{'start': event['start'], 'end': event['end']}], draft=True)
            validate_plan(plan, scoped, allow_draft=True)
            from .edit_integrity import inspect_edits
            if inspect_edits(scoped, plan):
                continue
            if plan['parts'][0]['duration'] > settings['max_duration']:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        result.append({'id': 'draft_'+digest({'event': event['id'], 'cuts': plan['parts'][0]['cuts']})[:20],
                       'status': 'needs_editorial_review', 'export_eligible': False,
                       'reason': 'continuous_source_not_editorially_approved', 'plan': plan})
        if len(result) >= settings['max_clips']:
            break
    return result


def build_standalone_candidates(analysis, settings=None):
    """Return ready independent plans, explicit declines and unapproved draft plans."""
    from .story_candidates import CONTRACT, compile_candidates
    if analysis.get('analysis_contract') == CONTRACT:
        return compile_candidates(analysis, settings)
    settings = _settings(settings)
    known = _source(analysis)
    arcs = build_story_arcs(analysis['events'], analysis['transcript'])
    ready, declined = [], []
    covered_events = set()
    for arc in arcs:
        covered_events.update(arc.get('event_ids', []))
        try:
            ready.append(_candidate(analysis, known, arc, settings))
        except _Declined as error:
            declined.append({'arc_id': arc['id'], 'event_ids': arc.get('event_ids', []),
                             'reason': error.reason, **error.details, 'export_eligible': False})
        except (ValueError, KeyError, TypeError) as error:
            declined.append({'arc_id': arc['id'], 'event_ids': arc.get('event_ids', []),
                             'reason': 'invalid_candidate_contract', 'error': str(error), 'export_eligible': False})
    for event in analysis['events']:
        if event['id'] not in covered_events:
            declined.append({'event': event['id'], 'reason': 'no_qualified_source_arc', 'export_eligible': False})
    chosen, retained = [], []
    while ready and len(chosen) < settings['max_clips']:
        def rank(candidate):
            shared = _duration(intersect_ranges(candidate['source_ranges'], retained))
            novelty = 1-shared/max(_duration(candidate['source_ranges']), .000001)
            duration = candidate['duration']
            distance = max(settings['preferred_min_duration']-duration, duration-settings['preferred_max_duration'], 0)
            return (-candidate['score']['total']*novelty, distance, candidate['source_ranges'][0]['start'], candidate['id'])
        candidate = min(ready, key=rank)
        ready.remove(candidate)
        if not subtract_ranges(candidate['source_ranges'], retained):
            declined.append({'arc_id': candidate['arc_id'], 'reason': 'duplicate_source_selection', 'export_eligible': False})
            continue
        candidate['rank'] = len(chosen)+1
        candidate['overlap_seconds'] = _duration(intersect_ranges(candidate['source_ranges'], retained))
        chosen.append(candidate)
        retained = merge_ranges([*retained, *candidate['source_ranges']])
    declined.extend({'arc_id': c['arc_id'], 'reason': 'requested_count_reached', 'export_eligible': False} for c in ready)
    return {'version': VERSION, 'settings': settings, 'candidates': chosen, 'declined': declined,
            'drafts': _drafts(analysis, declined, settings)}
