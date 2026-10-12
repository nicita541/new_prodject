"""Dramatic Shorts montage planner.

Condenses full anime episodes using a factual episode profile and retention budget,
using a three-beat dramatic structure:
1. Hook (0-3s): cut starts immediately on the opening line/action, trimming leading dead air.
2. Story Core: snappy conversational pacing (compressing pauses >1.2s down to ~0.5s while
   safeguarding speech lead/tail and action beats).
3. Ending: snaps to verified cliffhangers or punchline closures.
"""
from __future__ import annotations

import math
import copy
from bisect import bisect_left
from pathlib import Path

from .planner import (
    _number, _safe, _speech_lead, _speech_tail, _expand,
    validate_analysis, validate_plan,
    MAX_DURATION, SPEECH_LEAD, SPEECH_TAIL, SCHEMA_VERSION
)
from .subtitles import make_cues, remap_words
from .pacing import condense_beat
from .source_roles import apply_exclusions, confirmed_exclusions
from .titles import _subtract
from .episode_profile import build_episode_profile, adaptive_retention_budget

TARGET_SHORT_MIN = 60.0
TARGET_SHORT_OPTIMAL = 85.0
TARGET_SHORT_MAX = 105.0
MAX_SHORT_DURATION = 115.0
MIN_PARTS = 4
MAX_PARTS = 7


def _align_words_to_shot_boundaries(words: list[dict], shots: list[dict]) -> list[dict]:
    """Snap ASR word onsets that erroneously precede a shot change across silence/exclamations."""
    if not shots or not words:
        return words
    shot_starts = [_number(s['start']) for s in shots]
    aligned = []
    for w in words:
        w_copy = dict(w)
        w_st = _number(w_copy['start'])
        w_en = _number(w_copy['end'])
        snap = next((s for s in shot_starts if w_st + 0.05 <= s <= min(w_en - 0.15, w_st + 0.45)), None)
        if snap is not None:
            w_copy['start'] = snap
        aligned.append(w_copy)
    return aligned


def _event_dramatic_score(event: dict, segments: list[dict]) -> float:
    score = 0.0
    if event.get('narrative_bridge'):
        score += 25.0
    score += float(event.get('importance', 3)) * 6.0
    for ending in event.get('part_endings', []):
        kind = ending.get('kind')
        conf = float(ending.get('confidence', 0.9))
        if kind == 'cliffhanger':
            score += 15.0 * conf
        elif kind == 'closure':
            score += 10.0 * conf
        elif kind == 'transition':
            score += 4.0 * conf
    ev_start, ev_end = _number(event['start']), _number(event['end'])
    ev_speech = [s for s in segments if s['start'] < ev_end and s['end'] > ev_start]
    speech_dur = sum(s['end'] - s['start'] for s in ev_speech)
    ev_dur = max(0.1, ev_end - ev_start)
    score += min(15.0, (speech_dur / ev_dur) * 15.0)
    return score


def _normalize_shots(shots: list[dict], duration: float) -> list[dict]:
    """Ensure every shot has both start and end, inferring end from next shot or duration."""
    normalized = []
    for i, s in enumerate(shots):
        st = _number(s['start'])
        if 'end' in s:
            en = _number(s['end'])
        elif i + 1 < len(shots):
            en = _number(shots[i + 1]['start'])
        else:
            en = duration
        if en > st:
            normalized.append({'start': st, 'end': en})
    return normalized


def _compress_dialogue_turns(
    event: dict,
    segments: list[dict],
    words: list[dict],
    speech_all: list[dict],
    duration: float,
    shots: list[dict] | None = None
) -> list[dict]:
    """Compress dialogue turns within an event: trim dead pauses >1.2s down to ~0.5s."""
    ev_start, ev_end = _number(event['start']), _number(event['end'])
    if event.get('unit_selection_version') == 1 and event.get('selected_ranges'):
        # Accepted source-unit decisions already distinguish action from waiting.
        # Rescanning all ASR here would restore omitted exchanges and erase recovery fallback.
        protected = []
        for selection in event['selected_ranges']:
            left, right = _number(selection['start']), _number(selection['end'])
            for word in words:
                if word['start'] < left < word['end']:
                    left = word['start']
                if word['start'] < right < word['end']:
                    right = word['end']
            if not event.get('minimal_context_ranges') and 'story_structure' not in event:
                if any(abs(w['start']-left)<.12 for w in words):
                    left = max(ev_start, _speech_lead(left, speech_all))
                right = min(ev_end, _speech_tail(right, speech_all, duration))
            protected.append({'start': left, 'end': right})
        from .source_roles import merge_ranges
        return merge_ranges(protected)
    norm_shots = _normalize_shots(shots, duration) if shots else []
    ev_speech = sorted(
        [s for s in segments if s['start'] < ev_end and s['end'] > ev_start],
        key=lambda s: s['start']
    )
    if not ev_speech:
        # Check words
        ev_words = sorted(
            [w for w in words if w['start'] < ev_end and w['end'] > ev_start],
            key=lambda w: w['start']
        )
        if not ev_words:
            # Silent event / narrative bridge: return selected ranges or condensed beats
            selections = list(event.get('selected_ranges', [event]))
            ranges = []
            for sel in selections:
                s_st, s_en = _number(sel['start']), _number(sel['end'])
                if s_en - s_st > 3.0:
                    beats = condense_beat({'start': s_st, 'end': s_en}, max_hold=2.5)
                    ranges.extend(beats)
                else:
                    ranges.append({'start': s_st, 'end': s_en})
            return ranges
        ev_speech = ev_words

    # Hook trimming: start right before first spoken word (max 0.25s dead air)
    first_speech_time = ev_speech[0]['start']
    has_pre_action = event.get('narrative_bridge') or any(
        r['start'] < first_speech_time and r['end'] > ev_start
        for r in event.get('protected_atmosphere_ranges', [])
    )

    turn_ranges = []
    i = 0
    while i < len(ev_speech):
        turn_start = ev_speech[i]['start']
        turn_end = ev_speech[i]['end']
        # Group contiguous turns (gap <= 1.4s so natural speech pauses aren't cut out)
        while i + 1 < len(ev_speech) and ev_speech[i + 1]['start'] - turn_end <= 1.4:
            i += 1
            turn_end = max(turn_end, ev_speech[i]['end'])

        lead_t = _speech_lead(turn_start, speech_all)
        tail_t = _speech_tail(turn_end, speech_all, duration)
        turn_ranges.append({'start': round(lead_t, 6), 'end': round(tail_t, 6)})

        # Check gap before next turn
        if i + 1 < len(ev_speech):
            next_start = ev_speech[i + 1]['start']
            gap_start = tail_t
            gap_end = _speech_lead(next_start, speech_all)
            # If gap > 1.2s, look for verified action beat or narrative bridge
            if gap_end - gap_start > 1.2:
                action_in_gap = [
                    r for r in event.get('protected_atmosphere_ranges', [])
                    if r['start'] < gap_end and r['end'] > gap_start
                ]
                if action_in_gap:
                    for act in action_in_gap:
                        act_s = max(gap_start, act['start'])
                        act_e = min(gap_end, act['end'])
                        if act_e - act_s > 0.5:
                            turn_ranges.append({'start': round(act_s, 6), 'end': round(act_e, 6)})
                elif event.get('narrative_bridge') and gap_end - gap_start > 2.5:
                    # Narrative action beat within dialogue gap: preserve visual action continuity
                    # as one unbroken span rather than choppy isolated frames.
                    gap_shots = [
                        s for s in norm_shots
                        if s['start'] < gap_end and s['end'] > gap_start
                    ]
                    valid_shots = [
                        {'start': max(gap_start, s['start']), 'end': min(gap_end, s['end'])}
                        for s in gap_shots
                        if min(gap_end, s['end']) - max(gap_start, s['start']) >= 0.4
                    ]
                    if valid_shots:
                        # Keep a continuous unbroken action beat (up to 9s) across contiguous action shots
                        action_start = valid_shots[0]['start']
                        action_end = min(valid_shots[-1]['end'], action_start + 9.0)
                        turn_ranges.append({'start': round(action_start, 6), 'end': round(action_end, 6)})
                    elif gap_end - gap_start > 3.0:
                        beats = condense_beat({'start': gap_start, 'end': gap_end}, max_hold=2.5)
                        for b in beats:
                            turn_ranges.append({'start': round(b['start'], 6), 'end': round(b['end'], 6)})
        i += 1

    # If event has pre-action before the first speech line, retain a brief initiation beat
    if has_pre_action and ev_start < first_speech_time - 0.5:
        pre_len = min(2.5, first_speech_time - ev_start)
        turn_ranges.insert(0, {'start': round(ev_start, 6), 'end': round(ev_start + pre_len, 6)})

    return turn_ranges


def _protected_boundary(time, events, segments, words, intervals):
    """An ending label cannot cut an evidenced action or immediate question/answer."""
    for event in events:
        for pair in event.get('dialogue_relations', {}).get('pairs', []):
            if pair.get('status') != 'confirmed' or not pair.get('protect_bidirectional'):
                continue
            ranges = [*pair['question_ranges'], *pair['answer_ranges']]
            if (min(r['start'] for r in ranges)+.002 < time < max(r['end'] for r in ranges)-.002
                    and all(any(i['start'] <= r['start']+.002 and i['end'] >= r['end']-.002
                                for i in intervals) for r in ranges)):
                return 'verified_question_response_relation'
        action_ids = set(event.get('action_units', []))
        protected = [*event.get('protected_story_ranges', []), *event.get('causal_ranges', []),
                     *[u for u in event.get('units', []) if u['id'] in action_ids]]
        if any(r['start']+.002 < time < r['end']-.002 and r['end']-r['start'] <= MAX_SHORT_DURATION for r in protected):
            return 'inside_consequential_action'
    kept_speech = [s for s in segments if any(r['start'] <= s['start'] and s['end'] <= r['end'] for r in intervals)]
    before = next((s for s in reversed(kept_speech) if s['end'] <= time+.002), None)
    after = next((s for s in kept_speech if s['start'] >= time-.002), None)
    if (before and after and before['text'].strip().endswith('?')
            and 0 <= after['start']-before['end'] <= 3
            and after['end']-before['start'] <= MAX_SHORT_DURATION
            and before['end']-.002 <= time <= after['start']+.002):
        return 'immediate_question_answer'
    return None


def _build_dramatic_boundaries(
    intervals: list[dict],
    events: list[dict],
    segments: list[dict],
    words: list[dict],
    shots: list[dict],
    duration: float,
    target_part_count: int,
    *, arcs=None, diagnostics=None, count_preference=False, max_part_duration=MAX_SHORT_DURATION
) -> list[tuple[float, dict | None]]:
    """Choose complete story exits; part count is a soft preference."""
    total = round(sum(r['end'] - r['start'] for r in intervals), 6)
    candidates: dict[float, tuple[float, dict | None]] = {0.0: (0.0, None)}
    rejected = []
    shot_starts = [_number(s['start']) for s in shots]

    def add(time: float, cost: float, evidence: dict | None = None):
        if not _safe(time, words):
            return
        protected = _protected_boundary(time, events, segments, words, intervals)
        if protected:
            rejected.append({'source_time': time, 'reason': protected})
            return
        crossing = [s for s in segments if s['start'] < time < s['end']]
        if any(s['end'] - s['start'] <= MAX_SHORT_DURATION for s in crossing):
            return
        if crossing:
            if not any(abs(w['end'] - time) < 0.002 for w in words):
                return
            cost, evidence = 60.0, None

        elapsed = 0.0
        for interval in intervals:
            if interval['start'] < time <= interval['end']:
                if (0 < interval['end'] - time <= 0.75 and _safe(interval['end'], words)
                        and not any(time < s['start'] < interval['end'] or s['start'] < interval['end'] < s['end']
                                    for s in segments)):
                    time = interval['end']
                    if evidence:
                        evidence = {**evidence, 'time': time,
                                    'output_time': round(elapsed + time - interval['start'], 6)}
                output_time = round(elapsed + time - interval['start'], 6)
                if output_time not in candidates or cost < candidates[output_time][0]:
                    candidates[output_time] = (cost, evidence)
                return
            elapsed += interval['end'] - interval['start']

    # Story arcs exist before Shorts, and provide complete candidate exits.
    for arc in arcs or []:
        if not arc.get('uncertain', True):
            verified = next((e for e in arc.get('endings', []) if e.get('verified') and abs(e['time']-arc['end']) < .002), None)
            add(arc['end'], .5, verified or {'kind': 'transition', 'time': arc['end'],
                'evidence': ', '.join(arc['boundary_reason']) if isinstance(arc['boundary_reason'], list) else arc['boundary_reason'],
                'confidence': arc.get('confidence', .85), 'arc_id': arc['id']})

    # Verified/supplied endings still pass action and dialogue guards.
    for event in events:
        for ending in event.get('part_endings', []):
            kind = ending.get('kind', 'transition')
            cost = {'cliffhanger': 0.0, 'closure': 1.0, 'transition': 3.0}.get(kind, 3.0)
            end_t = _number(ending['time'])
            shot_snap = next((s for s in shot_starts if end_t - 0.02 <= s <= end_t + 0.85), None)
            if shot_snap and _safe(shot_snap, words):
                add(shot_snap, cost, {**ending, 'time': shot_snap})
            else:
                add(end_t, cost, ending)

    # 2. Interval ends (scene cuts)
    for interval in intervals:
        add(interval['end'], 8.0)

    # 3. Speech tails
    for segment in segments:
        tail = _speech_tail(segment['end'], [*segments, *words], duration)
        add(tail, 14.0)

    # 4. Shot cuts
    for shot in shots:
        add(_number(shot['start']), 20.0)

    # 5. Fallback grid
    ideal_len = total / max(1, target_part_count)
    ideal_len = max(TARGET_SHORT_MIN, min(max_part_duration if count_preference else TARGET_SHORT_MAX, ideal_len))
    step_count = max(1, round(total / ideal_len),math.ceil(total/max_part_duration))
    for i in range(1, step_count):
        target_out = (total * i) / step_count
        elapsed = 0.0
        for interval in intervals:
            span = interval['end'] - interval['start']
            if elapsed < target_out <= elapsed + span:
                add(interval['start'] + target_out - elapsed, 20.0)
                break
            elapsed += span

    if total not in candidates:
        candidates[total] = (0.0, None)
    times = sorted(candidates)
    inside_strong_arc = set()
    for output_time in times:
        elapsed = 0.0
        for interval in intervals:
            span = interval['end']-interval['start']
            if elapsed < output_time <= elapsed+span+.000001:
                source_time = interval['start']+output_time-elapsed
                if any(not a.get('uncertain', True) and a['start'] < source_time < a['end'] for a in arcs or []):
                    inside_strong_arc.add(output_time)
                break
            elapsed += span

    # Consider all useful counts; semantic cost decides before a weak count penalty.
    max_k = max(1, math.ceil(total/max_part_duration),
                min(max(target_part_count + 3, len(arcs or [])), max(1, math.ceil(total/10))))
    min_k = max(1, math.ceil(total/max_part_duration))

    dp: dict[tuple[int, float], tuple[float, float]] = {(0, 0.0): (0.0, 0.0)}

    for k in range(1, max_k + 1):
        for end in times[1:]:
            has_ending = candidates[end][1] is not None
            min_allowed = 0.1 if total <= TARGET_SHORT_MIN else (10.0 if (has_ending and k > 1) else TARGET_SHORT_MIN * 0.55)
            best_tuple = None

            for start in times[bisect_left(times,end-max_part_duration-1e-6):bisect_left(times,end)]:
                length = end - start
                if length > max_part_duration + 1e-6:
                    continue
                if length < min_allowed:
                    continue
                if (k - 1, start) not in dp:
                    continue

                if total <= TARGET_SHORT_MIN:
                    length_cost = 0.0
                elif length < TARGET_SHORT_MIN:
                    length_cost = ((TARGET_SHORT_MIN - length) / 5.0) ** 2 + (2.0 if has_ending else 10.0)
                elif count_preference:
                    length_cost = ((length - ideal_len) / 25.0) ** 2
                elif length > TARGET_SHORT_MAX:
                    length_cost = ((length - TARGET_SHORT_MAX) / 10.0) ** 2 + 5.0
                else:
                    length_cost = ((length - TARGET_SHORT_OPTIMAL) / 25.0) ** 2

                boundary_cost = candidates[end][0]
                # A known complete arc fitting one part should not acquire an arbitrary inner cut.
                if end != total and end in inside_strong_arc:
                    ending = candidates[end][1] or {}
                    verification = ending.get('verification') or {}
                    if not (verification.get('supported') is True and verification.get('confidence', 0) >= .9):
                        boundary_cost += 35
                total_cost = dp[(k - 1, start)][0] + length_cost + boundary_cost

                if best_tuple is None or total_cost < best_tuple[0]:
                    best_tuple = (total_cost, start)

            if best_tuple is not None:
                dp[(k, end)] = best_tuple

    valid_k = [k for k in range(min_k, max_k + 1) if (k, total) in dp]
    # Explicit preferences mean "try at most N", not "force exactly N".
    # A strong-arc penalty (35) still outweighs one additional part (10).
    count_penalty = lambda k: 10.0*max(0,k-target_part_count) if count_preference else .6*abs(k-target_part_count)
    chosen_k = min(valid_k, key=lambda k: dp[(k, total)][0] + count_penalty(k)) if valid_k else None
    if diagnostics is not None:
        diagnostics.update(preferred_part_count=target_part_count, chosen_part_count=chosen_k,
            count_policy='semantic_cost_then_soft_count_penalty', rejected_boundaries=rejected,
            alternatives=[{'parts': k, 'semantic_and_length_cost': dp[(k,total)][0],
                           'soft_count_penalty': count_penalty(k)} for k in valid_k])

    if chosen_k is None:
        # Fallback if strict bounds failed
        scores: dict[float, float] = {0.0: 0.0}
        previous: dict[float, float] = {}
        for i, end in enumerate(times[1:], 1):
            choices = []
            for start in reversed(times[:i]):
                length = end - start
                if length > MAX_DURATION + 1e-6:
                    break
                if length < 5.0 or start not in scores:
                    continue
                length_cost = ((length - TARGET_SHORT_OPTIMAL) / 30.0) ** 2
                choices.append((scores[start] + length_cost + candidates[end][0], start))
            if choices:
                scores[end], previous[end] = min(choices)
        if total not in scores:
            raise ValueError(f'Невозможно разделить таймлайн на части до {MAX_DURATION:g} с без обрыва слова')
        boundaries, t = [], total
        while t > 0:
            boundaries.append((t, candidates[t][1]))
            t = previous[t]
        if diagnostics is not None:
            diagnostics.update(chosen_part_count=len(boundaries), fallback='word_safe_processing_ceiling')
        return list(reversed(boundaries))

    boundaries = []
    curr_k = chosen_k
    curr_t = total
    while curr_k > 0:
        prev_t = dp[(curr_k, curr_t)][1]
        boundaries.append((curr_t, candidates[curr_t][1]))
        curr_t = prev_t
        curr_k -= 1
    return list(reversed(boundaries))



def build_dramatic_plan(analysis: dict) -> dict:
    """Build a source-evidenced montage with adaptive retention and complete replies."""
    validate_analysis(analysis)
    events = apply_exclusions(analysis["events"])
    probe = analysis["probe"]
    duration = _number(probe["duration"])
    raw_words = analysis["transcript"].get("words", [])
    segments = analysis["transcript"].get("segments", [])
    shots = analysis.get("shots", [])
    words = raw_words
    speech_all = [*segments, *words]
    shot_starts = [_number(shot["start"]) for shot in shots]

    if segments and not raw_words:
        raise ValueError("Распознавание должно содержать временные отметки слов")

    by_id = {event["id"]: event for event in events}
    from .media_probe import raw_shot_evidence
    # Production finalizes one profile after semantic adjudication. Reuse that
    # snapshot exactly; old saved analyses without a profile remain readable.
    episode_profile = copy.deepcopy(analysis.get('episode_profile'))
    if episode_profile is None:
        episode_profile = build_episode_profile(duration, analysis['transcript'], shots,
            analysis.get('scenes'), events, raw_candidates=raw_shot_evidence(shots) or None,
            perception=analysis.get('perception'))
    if not isinstance(episode_profile, dict) or abs(_number(episode_profile['source_duration'])-duration) > .002:
        raise ValueError('Монтажный профиль не соответствует исходной серии')
    retention_budget = copy.deepcopy(episode_profile.get('retention_budget') or
                                    episode_profile.get('planner_budget'))
    if retention_budget is None:
        retention_budget = adaptive_retention_budget(episode_profile)
    budget_min, budget_optimal, budget_max = (_number(retention_budget[key]) for key in ('min','optimal','max'))
    if not 0 <= budget_min <= budget_optimal <= budget_max <= duration+.002:
        raise ValueError('Некорректный бюджет финального профиля серии')
    preferred = analysis.get('preferred_part_count')
    if preferred is not None:
        if type(preferred) is not int or not 1 <= preferred <= 64:
            raise ValueError('Некорректное предпочтительное количество частей')
        # A count preference must influence retention before partitioning.
        # Required context and indivisible source arcs can still exceed it.
        retention_budget['max'] = min(budget_max,preferred*MAX_SHORT_DURATION)
        retention_budget['optimal'] = min(budget_optimal,preferred*TARGET_SHORT_OPTIMAL,retention_budget['max'])
        retention_budget['min'] = min(budget_min,retention_budget['optimal'])
        retention_budget['preferred_part_count'] = preferred
    from .story_structure import build_story_arcs, resolve_continuity
    arcs = build_story_arcs(events, analysis['transcript'])
    arc_by_event = {identifier: [arc for arc in arcs if identifier in arc['event_ids']] for identifier in by_id}

    # 1. Base eligibility: non-excluded story events and narrative bridges
    eligible = [
        e for e in events
        if not e.get('pacing_excluded') and not e.get('global_excluded')
        and (e.get('narrative_bridge') or (e["kind"] == "story" and e.get("importance", 3) >= 3) or e.get("importance", 3) >= 4)
    ]
    if not eligible:
        eligible = [e for e in events if e["kind"] == "story"
                    and not e.get('global_excluded') and not e.get('pacing_excluded')]
    if not eligible:
        raise ValueError("В серии не найдены сюжетные сцены для драматического монтажа")

    # Scored dramatic events
    scored_events = sorted(
        eligible,
        key=lambda e: _event_dramatic_score(e, segments),
        reverse=True
    )

    # Measure candidate cost after actual dialogue compression, not the scene envelope.
    candidate_ranges = {e['id']: _compress_dialogue_turns(e, segments, words, speech_all, duration, shots)
                        for e in eligible}
    from .retention_allocation import allocate_retention
    allocation = allocate_retention(events, candidate_ranges, [event['id'] for event in scored_events],
        arcs, analysis['transcript'], duration, retention_budget, resolve_continuity)
    continuity = allocation['continuity']
    selection_reasons = allocation['selection_reasons']
    events, selected_ids = continuity['events'], set(continuity['selected_ids'])
    by_id = {event['id']: event for event in events}
    for bridge in continuity['bridges']:
        selection_reasons[bridge['source_event']] = ['minimal_causal_bridge', bridge.get('reason', 'continuity')]

    # 2. Build snappy intervals for each selected event
    excluded_ranges = [r for event in events for r in confirmed_exclusions(event)]
    raw_intervals = []

    for event in sorted([by_id[i] for i in selected_ids], key=lambda e: e['start']):
        turn_ranges = _compress_dialogue_turns(event, segments, words, speech_all, duration, shots=shots)
        for tr in turn_ranges:
            raw_intervals.append({'start': tr['start'], 'end': tr['end'], 'event_id': event['id']})

    # Preserve real omitted gaps and confirmed exclusions, even when they are short.
    intervals = []
    for raw in sorted(raw_intervals, key=lambda r: r['start']):
        for piece in _subtract([{'start': raw['start'], 'end': raw['end']}], excluded_ranges):
            left, right = round(piece['start'], 6), round(piece['end'], 6)
            if right - left < 0.2:
                continue
            if intervals and left <= intervals[-1]['end'] + 0.002:
                intervals[-1]['end'] = max(right, intervals[-1]['end'])
                raw_eids = raw['event_id'] if isinstance(raw['event_id'], list) else [raw['event_id']]
                for eid in raw_eids:
                    if eid not in intervals[-1]['event_ids']:
                        intervals[-1]['event_ids'].append(eid)
            else:
                raw_eids = raw['event_id'] if isinstance(raw['event_id'], list) else [raw['event_id']]
                intervals.append({'start': left, 'end': right, 'event_ids': list(raw_eids)})

    if not intervals:
        raise ValueError("После исключений не осталось фрагментов для монтажа")

    from .speech_handles import expand_ranges, barriers
    semantic_ranges = [{'start':r['start'],'end':r['end']} for r in intervals]
    excluded_ranges = barriers(events,semantic_ranges)
    expanded = []
    for interval in intervals:
        for piece in expand_ranges([interval],analysis['transcript'],duration,excluded_ranges):
            if expanded and piece['start'] <= expanded[-1]['end']+.002:
                expanded[-1]['end'] = max(expanded[-1]['end'],piece['end'])
                expanded[-1]['event_ids'] = list(dict.fromkeys([*expanded[-1]['event_ids'],*interval['event_ids']]))
            else:
                expanded.append({**piece,'event_ids':interval['event_ids']})
    intervals = expanded

    # 3. Target optimal parts
    total_retained = sum(r['end'] - r['start'] for r in intervals)
    if total_retained <= TARGET_SHORT_MIN:
        target_parts = max(1, round(total_retained / TARGET_SHORT_OPTIMAL))
    else:
        target_parts = max(1, round(total_retained / TARGET_SHORT_OPTIMAL))
    preferred = analysis.get('preferred_part_count', target_parts)
    if type(preferred) is not int or preferred < 1:
        raise ValueError('Некорректное предпочтительное количество частей')
    target_parts = preferred
    part_policy = {}

    boundaries = _build_dramatic_boundaries(
        intervals, events, segments, words, shots, duration, target_parts, arcs=arcs, diagnostics=part_policy,
        count_preference='preferred_part_count' in analysis
    )

    # 4. Form parts and cuts
    parts = []
    current_cuts = []
    current_duration = 0.0
    elapsed = 0.0
    warnings = [f"{event['id']}: {w}" for event in events for key in ("focus_warnings", "story_warnings")
                for w in event.get(key, []) if isinstance(w, str)]
    warnings.extend('Связность: '+str(w.get('reason', 'unknown'))+
                    (f" ({w.get('from')} → {w.get('to')})" if w.get('to') else '')
                    for w in continuity['warnings'] if w.get('reason') != 'unknown_transition_state')

    def finish_part():
        nonlocal current_cuts, current_duration
        if current_cuts:
            part_index = len(parts) + 1
            cues = make_cues(remap_words(raw_words, current_cuts))
            ending = boundaries[len(parts)][1]
            part = {
                "index": part_index,
                "duration": round(current_duration, 6),
                "cuts": current_cuts,
                "subtitles": cues
            }
            if ending:
                part['ending'] = dict(ending)
            parts.append(part)
        current_cuts, current_duration = [], 0.0

    for interval in intervals:
        start = interval["start"]
        while start < interval["end"] - 1e-7:
            room = boundaries[len(parts)][0] - elapsed
            end = min(interval['end'], start + room)
            ids = [e["id"] for e in events if e["start"] < end and e["end"] > start and e["id"] in selected_ids]
            if not ids:
                ids = interval["event_ids"]

            anchors = sorted(
                [dict(a) for e in events if e["id"] in ids for a in e.get("focus", [])
                 if start <= a["time"] <= end],
                key=lambda a: a["time"]
            )
            if not anchors:
                preceding = [a for e in events for a in e.get("focus", []) if a["time"] <= start]
                anchor = max(preceding, key=lambda a: a["time"]) if preceding else {"x": 0.5, "y": 0.5, "confidence": 0.0}
                anchors = [{**anchor, "time": start}]

            for anchor in anchors:
                anchor['time'] = min(round(end, 6), max(round(start, 6), round(anchor['time'], 6)))
                anchor["hard_cut"] = any(abs(anchor["time"] - b) <= 0.002 + 1e-9 for b in shot_starts)

            current_cuts.append({
                "start": round(start, 6),
                "end": round(end, 6),
                "event_ids": ids,
                "focus": anchors
            })
            span = end - start
            current_duration += span
            elapsed += span
            start = end
            if elapsed >= boundaries[len(parts)][0] - 1e-6:
                finish_part()

    finish_part()

    retained_ids = {identifier for part in parts for cut in part["cuts"] for identifier in cut["event_ids"]}
    plan = {
        "schema_version": SCHEMA_VERSION,
        "source": {key: probe[key] for key in ("duration", "width", "height")},
        "selected_event_ids": [e["id"] for e in events if e["id"] in selected_ids],
        "events": [dict(e) for e in events if e["id"] in retained_ids],
        "parts": parts,
        "semantic_ranges":semantic_ranges,
        "warnings": list(dict.fromkeys(warnings)),
        "dramatic_montage": True,
        "episode_profile": episode_profile,
        "retention_budget": retention_budget,
        "retention_allocation": allocation,
        "retention_budget_exceeded": total_retained > retention_budget['max'] + 0.002
    }
    from .planner_audit import planner_audit
    eligible_ids = {e['id'] for e in eligible}
    candidates = []
    for event in events:
        reasons = selection_reasons.get(event['id'])
        if reasons is None:
            reasons = ['adaptive_optimal_budget_reached' if event['id'] in eligible_ids else
                       'global_omission' if event.get('global_excluded') else
                       'confirmed_nonstory' if event.get('credit_montage') or event['kind'] != 'story' else 'below_story_threshold']
        candidates.append({'event_id': event['id'], 'score': _event_dramatic_score(event, segments),
            'selected': event['id'] in retained_ids, 'arc_ids': [a['id'] for a in arc_by_event.get(event['id'], [])],
            'arc_id': next((a['id'] for a in arc_by_event.get(event['id'], [])), None),
            'reasons': reasons, 'candidate_duration': sum(r['end']-r['start'] for r in candidate_ranges.get(event['id'], []))})
    plan['planner_diagnostics'] = planner_audit({**analysis, 'events': events}, plan,
        candidates=candidates, arcs=arcs, continuity=continuity, part_policy=part_policy)
    plan['planner_diagnostics']['retention_allocation'] = allocation
    validate_plan(plan, analysis)
    return plan
