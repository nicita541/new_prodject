"""Dramatic Shorts montage planner.

Condenses full anime episodes into 5-8 punchy, high-impact Shorts (40-85s each)
using a three-beat dramatic structure:
1. Hook (0-3s): cut starts immediately on the opening line/action, trimming leading dead air.
2. Story Core: snappy conversational pacing (compressing pauses >1.2s down to ~0.5s while
   safeguarding speech lead/tail and action beats).
3. Ending: snaps to verified cliffhangers or punchline closures.
"""
from __future__ import annotations

import math
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

TARGET_SHORT_MIN = 60.0
TARGET_SHORT_OPTIMAL = 100.0
TARGET_SHORT_MAX = 115.0
MAX_SHORT_DURATION = 120.0
MIN_PARTS = 4
MAX_PARTS = 12


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
            selections = list(event.get('selected_ranges') or [event])
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
        # Group contiguous turns (gap <= 2.2s so natural speech pauses aren't cut out)
        while i + 1 < len(ev_speech) and ev_speech[i + 1]['start'] - turn_end <= 2.2:
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


def _build_dramatic_boundaries(
    intervals: list[dict],
    events: list[dict],
    segments: list[dict],
    words: list[dict],
    shots: list[dict],
    duration: float,
    target_part_count: int
) -> list[tuple[float, dict | None]]:
    """Determine part boundaries targeting 5-8 shorts using dynamic programming."""
    total = round(sum(r['end'] - r['start'] for r in intervals), 6)
    candidates: dict[float, tuple[float, dict | None]] = {0.0: (0.0, None)}
    shot_starts = [_number(s['start']) for s in shots]

    def add(time: float, cost: float, evidence: dict | None = None):
        if not _safe(time, words):
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

    # 1. Ending hooks (highest priority)
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
        add(interval['end'], 4.0)

    # 3. Speech tails
    for segment in segments:
        tail = _speech_tail(segment['end'], [*segments, *words], duration)
        add(tail, 7.0)

    # 4. Shot cuts
    for shot in shots:
        add(_number(shot['start']), 10.0)

    # 5. Fallback grid
    ideal_len = total / max(1, target_part_count)
    ideal_len = max(TARGET_SHORT_MIN, min(TARGET_SHORT_MAX, ideal_len))
    step_count = max(1, round(total / ideal_len))
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

    # DP optimization: find sequence of cuts matching target length & count
    scores: dict[float, float] = {0.0: 0.0}
    previous: dict[float, float] = {}

    for i, end in enumerate(times[1:], 1):
        choices = []
        has_ending = candidates[end][1] is not None
        min_allowed = 0.1 if total <= TARGET_SHORT_MIN else (8.0 if has_ending else TARGET_SHORT_MIN * 0.65)
        for start in reversed(times[:i]):
            length = end - start
            if length > MAX_SHORT_DURATION + 1e-6:
                break
            if length < min_allowed or start not in scores:
                continue

            # Length penalty: optimal is TARGET_SHORT_OPTIMAL (55-70s)
            if total <= TARGET_SHORT_MIN:
                length_cost = 0.0
            elif length < TARGET_SHORT_MIN:
                length_cost = ((TARGET_SHORT_MIN - length) / 5.0) ** 2 + (2.0 if has_ending else 10.0)
            elif length > TARGET_SHORT_MAX:
                length_cost = ((length - TARGET_SHORT_MAX) / 10.0) ** 2 + 5.0
            else:
                length_cost = ((length - TARGET_SHORT_OPTIMAL) / 25.0) ** 2

            boundary_cost = candidates[end][0]
            total_cost = scores[start] + length_cost + boundary_cost
            choices.append((total_cost, start))

        if choices:
            best_cost, best_start = min(choices)
            scores[end] = best_cost
            previous[end] = best_start

    if total not in scores:
        # Fallback if strict bounds failed: relax to MAX_DURATION
        for i, end in enumerate(times[1:], 1):
            choices = []
            for start in reversed(times[:i]):
                length = end - start
                if length > MAX_DURATION + 1e-6:
                    break
                if length < 5.0 or start not in scores:
                    continue
                length_cost = ((length - 60.0) / 30.0) ** 2
                choices.append((scores[start] + length_cost + candidates[end][0], start))
            if choices:
                best_cost, best_start = min(choices)
                scores[end] = best_cost
                previous[end] = best_start

    if total not in scores:
        raise ValueError(f'Невозможно разделить таймлайн на части до {MAX_DURATION:g} с')

    boundaries = []
    t = total
    while t > 0:
        boundaries.append((t, candidates[t][1]))
        t = previous[t]
    return list(reversed(boundaries))


def build_dramatic_plan(analysis: dict) -> dict:
    """Build a 5-8 part dramatic Shorts plan with conversational pacing and cliffhangers."""
    validate_analysis(analysis)
    events = apply_exclusions(analysis["events"])
    probe = analysis["probe"]
    duration = _number(probe["duration"])
    raw_words = analysis["transcript"].get("words", [])
    segments = analysis["transcript"].get("segments", [])
    shots = analysis.get("shots", [])
    words = _align_words_to_shot_boundaries(raw_words, shots)
    speech_all = [*segments, *words]
    shot_starts = [_number(shot["start"]) for shot in shots]

    if segments and not raw_words:
        raise ValueError("Распознавание должно содержать временные отметки слов")

    by_id = {event["id"]: event for event in events}

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

    # Transitive prerequisite closure helper
    def _get_all_prereqs(eid: str) -> set[str]:
        result = set()
        stack = [eid]
        while stack:
            curr = stack.pop()
            for req in by_id.get(curr, {}).get('requires', []):
                if req in by_id and req not in result:
                    r_ev = by_id[req]
                    if not r_ev.get('pacing_excluded') and not r_ev.get('global_excluded'):
                        result.add(req)
                        stack.append(req)
        return result

    # Initial selection: narrative bridges, cliffhanger/closure events, and high importance events
    selected_ids = {
        e['id'] for e in eligible
        if e.get('narrative_bridge') or e.get('part_endings') or e.get('importance', 3) >= 4
    }
    if not selected_ids:
        selected_ids = {e['id'] for e in eligible}

    for eid in list(selected_ids):
        selected_ids.update(_get_all_prereqs(eid))

    scored_events = sorted(
        eligible,
        key=lambda e: _event_dramatic_score(e, segments),
        reverse=True
    )
    for ev in scored_events:
        selected_ids.add(ev['id'])
        selected_ids.update(_get_all_prereqs(ev['id']))

    # Contiguous Sequence Closure: if event A and event B are selected,
    # fill any in-between story events where gap <= 160s to prevent Swiss cheese plot jumps
    sorted_eligible = sorted([e for e in eligible], key=lambda e: e['start'])
    changed = True
    while changed:
        changed = False
        sorted_sel = sorted([by_id[eid] for eid in selected_ids if eid in by_id], key=lambda e: e['start'])
        for i in range(len(sorted_sel) - 1):
            e_a = sorted_sel[i]
            e_b = sorted_sel[i + 1]
            if 0 < e_b['start'] - e_a['end'] <= 160.0:
                for cand in sorted_eligible:
                    if e_a['end'] <= cand['start'] and cand['end'] <= e_b['start']:
                        if cand['id'] not in selected_ids:
                            selected_ids.add(cand['id'])
                            selected_ids.update(_get_all_prereqs(cand['id']))
                            changed = True

    # 2. Build snappy intervals for each selected event
    excluded_ranges = [r for event in events for r in confirmed_exclusions(event)]
    raw_intervals = []

    for event in sorted([by_id[i] for i in selected_ids], key=lambda e: e['start']):
        turn_ranges = _compress_dialogue_turns(event, segments, words, speech_all, duration, shots=shots)
        for tr in turn_ranges:
            raw_intervals.append({'start': tr['start'], 'end': tr['end'], 'event_id': event['id']})

    # Subtract confirmed exclusions and merge close sub-cuts (gap <= 1.2s)
    intervals = []
    for raw in sorted(raw_intervals, key=lambda r: r['start']):
        for piece in _subtract([{'start': raw['start'], 'end': raw['end']}], excluded_ranges):
            left, right = round(piece['start'], 6), round(piece['end'], 6)
            if right - left < 0.2:
                continue
            if intervals and left <= intervals[-1]['end'] + 1.2:
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

    # 3. Target optimal parts
    total_retained = sum(r['end'] - r['start'] for r in intervals)
    target_parts = max(MIN_PARTS, min(MAX_PARTS, round(total_retained / TARGET_SHORT_OPTIMAL)))

    boundaries = _build_dramatic_boundaries(
        intervals, events, segments, words, shots, duration, target_parts
    )

    # 4. Form parts and cuts
    parts = []
    current_cuts = []
    current_duration = 0.0
    elapsed = 0.0
    warnings = [f"{event['id']}: {w}" for event in events for key in ("focus_warnings", "story_warnings")
                for w in event.get(key, []) if isinstance(w, str)]

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
        "warnings": list(dict.fromkeys(warnings)),
        "dramatic_montage": True
    }
    validate_plan(plan, analysis)
    return plan
