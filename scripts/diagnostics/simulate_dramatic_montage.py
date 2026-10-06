"""Diagnostic and simulation tool for dramatic Shorts montage.

Allows running and tuning dramatic montage parameters, event selection,
dialogue compression, and DP boundaries without modifying production database.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.planner import (
    _number, _safe, _speech_lead, _speech_tail,
    validate_analysis, validate_plan,
    SPEECH_LEAD, SPEECH_TAIL, SCHEMA_VERSION
)
from app.source_roles import apply_exclusions, confirmed_exclusions
from app.titles import _subtract
from app.pacing import condense_beat
from app.dramatic_planner import (
    _normalize_shots, _event_dramatic_score,
    _align_words_to_shot_boundaries
)


def load_job_data(job_dir: Path) -> dict:
    return {
        'events': json.load(open(job_dir / 'events.json', encoding='utf-8')),
        'probe': json.load(open(job_dir / 'probe.json', encoding='utf-8')),
        'transcript': json.load(open(job_dir / 'transcript.json', encoding='utf-8')),
        'shots': json.load(open(job_dir / 'shots.json', encoding='utf-8')),
        'source': json.load(open(job_dir / 'source.json', encoding='utf-8')),
    }


def simulate(
    analysis: dict,
    target_part_count: int = 8,
    target_short_min: float = 85.0,
    target_short_optimal: float = 120.0,
    target_short_max: float = 140.0,
    max_short_duration: float = 145.0,
    max_duration_ceiling: float = 150.0,
    turn_group_gap: float = 2.0,
    interval_merge_gap: float = 1.0,
    include_prologue: bool = False
):
    events = apply_exclusions(analysis["events"])
    probe = analysis["probe"]
    duration = _number(probe["duration"])
    raw_words = analysis["transcript"].get("words", [])
    segments = analysis["transcript"].get("segments", [])
    shots = analysis.get("shots", [])
    words = _align_words_to_shot_boundaries(raw_words, shots)
    speech_all = [*segments, *words]
    shot_starts = [_number(shot["start"]) for shot in shots]

    by_id = {event["id"]: event for event in events}

    # 1. Base eligibility: non-excluded story events and narrative bridges
    eligible = [
        e for e in events
        if not e.get('pacing_excluded') and not e.get('global_excluded')
        and (e.get('narrative_bridge') or (e["kind"] == "story" and e.get("importance", 3) >= 3) or e.get("importance", 3) >= 4)
        and (include_prologue or e["id"] != "event_0000")
    ]
    if not eligible:
        eligible = [e for e in events if e["kind"] == "story"
                    and not e.get('global_excluded') and not e.get('pacing_excluded')]

    def _get_all_prereqs(eid: str) -> set[str]:
        result = set()
        stack = [eid]
        while stack:
            curr = stack.pop()
            for req in by_id.get(curr, {}).get('requires', []):
                if req in by_id and req not in result:
                    r_ev = by_id[req]
                    if not r_ev.get('pacing_excluded') and not r_ev.get('global_excluded') and (include_prologue or req != 'event_0000'):
                        result.add(req)
                        stack.append(req)
        return result

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
    # fill any in-between story events where gap <= 160s
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

    # 2. Build compressed intervals
    norm_shots = _normalize_shots(shots, duration) if shots else []

    def _compress_turns(event: dict) -> list[dict]:
        ev_start, ev_end = _number(event['start']), _number(event['end'])
        ev_speech = sorted(
            [s for s in segments if s['start'] < ev_end and s['end'] > ev_start],
            key=lambda s: s['start']
        )
        if not ev_speech:
            ev_words = sorted(
                [w for w in words if w['start'] < ev_end and w['end'] > ev_start],
                key=lambda w: w['start']
            )
            if not ev_words:
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
            while i + 1 < len(ev_speech) and ev_speech[i + 1]['start'] - turn_end <= turn_group_gap:
                i += 1
                turn_end = max(turn_end, ev_speech[i]['end'])

            lead_t = _speech_lead(turn_start, speech_all)
            tail_t = _speech_tail(turn_end, speech_all, duration)
            turn_ranges.append({'start': round(lead_t, 6), 'end': round(tail_t, 6)})

            if i + 1 < len(ev_speech):
                next_start = ev_speech[i + 1]['start']
                gap_start = tail_t
                gap_end = _speech_lead(next_start, speech_all)
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
                        gap_shots = [s for s in norm_shots if s['start'] < gap_end and s['end'] > gap_start]
                        valid_shots = [
                            {'start': max(gap_start, s['start']), 'end': min(gap_end, s['end'])}
                            for s in gap_shots
                            if min(gap_end, s['end']) - max(gap_start, s['start']) >= 0.4
                        ]
                        if valid_shots:
                            action_start = valid_shots[0]['start']
                            action_end = min(valid_shots[-1]['end'], action_start + 9.0)
                            turn_ranges.append({'start': round(action_start, 6), 'end': round(action_end, 6)})
                        elif gap_end - gap_start > 3.0:
                            beats = condense_beat({'start': gap_start, 'end': gap_end}, max_hold=2.5)
                            for b in beats:
                                turn_ranges.append({'start': round(b['start'], 6), 'end': round(b['end'], 6)})
            i += 1

        if has_pre_action and ev_start < first_speech_time - 0.5:
            pre_len = min(2.5, first_speech_time - ev_start)
            turn_ranges.insert(0, {'start': round(ev_start, 6), 'end': round(ev_start + pre_len, 6)})

        return turn_ranges

    excluded_ranges = [r for event in events for r in confirmed_exclusions(event)]
    raw_intervals = []

    for event in sorted([by_id[i] for i in selected_ids], key=lambda e: e['start']):
        turn_ranges = _compress_turns(event)
        for tr in turn_ranges:
            raw_intervals.append({'start': tr['start'], 'end': tr['end'], 'event_id': event['id']})

    intervals = []
    for raw in sorted(raw_intervals, key=lambda r: r['start']):
        for piece in _subtract([{'start': raw['start'], 'end': raw['end']}], excluded_ranges):
            left, right = round(piece['start'], 6), round(piece['end'], 6)
            if right - left < 0.2:
                continue
            if intervals and left <= intervals[-1]['end'] + interval_merge_gap:
                intervals[-1]['end'] = max(right, intervals[-1]['end'])
                raw_eids = raw['event_id'] if isinstance(raw['event_id'], list) else [raw['event_id']]
                for eid in raw_eids:
                    if eid not in intervals[-1]['event_ids']:
                        intervals[-1]['event_ids'].append(eid)
            else:
                raw_eids = raw['event_id'] if isinstance(raw['event_id'], list) else [raw['event_id']]
                intervals.append({'start': left, 'end': right, 'event_ids': list(raw_eids)})

    total = round(sum(r['end'] - r['start'] for r in intervals), 6)
    candidates = {0.0: (0.0, None)}

    def add(time: float, cost: float, evidence: dict | None = None):
        if not _safe(time, words):
            return
        crossing = [s for s in segments if s['start'] < time < s['end']]
        if any(s['end'] - s['start'] <= max_short_duration for s in crossing):
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

    # Ending hooks
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

    for interval in intervals:
        add(interval['end'], 4.0)

    for segment in segments:
        tail = _speech_tail(segment['end'], [*segments, *words], duration)
        add(tail, 7.0)

    for shot in shots:
        add(_number(shot['start']), 10.0)

    ending_candidates = [(round(t, 1), cand[1]['kind']) for t, cand in sorted(candidates.items()) if cand[1] is not None]
    print(f"\nAvailable ending candidates ({len(ending_candidates)}): {ending_candidates}")


    ideal_len = total / max(1, target_part_count)
    ideal_len = max(target_short_min, min(target_short_max, ideal_len))
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

    # 2D k-stage DP: find sequence of cuts matching target length & EXACT part count
    # dp[k, end] = (min_cost, previous_time)
    max_k = min(12, max(target_part_count + 2, math.ceil(total / target_short_min)))
    min_k = max(1, min(target_part_count - 2, math.floor(total / max_short_duration)))

    dp: dict[tuple[int, float], tuple[float, float]] = {(0, 0.0): (0.0, 0.0)}

    for k in range(1, max_k + 1):
        for end in times[1:]:
            has_ending = candidates[end][1] is not None
            min_allowed = 10.0 if (has_ending and k > 1) else target_short_min * 0.55
            best_tuple = None

            for start in times:
                if start >= end:
                    break
                length = end - start
                if length > max_short_duration + 1e-6:
                    continue
                if length < min_allowed:
                    continue
                if (k - 1, start) not in dp:
                    continue

                if length < target_short_min:
                    length_cost = ((target_short_min - length) / 5.0) ** 2 + (2.0 if has_ending else 10.0)
                elif length > target_short_max:
                    length_cost = ((length - target_short_max) / 10.0) ** 2 + 5.0
                else:
                    length_cost = ((length - target_short_optimal) / 25.0) ** 2

                boundary_cost = candidates[end][0]
                total_cost = dp[(k - 1, start)][0] + length_cost + boundary_cost

                if best_tuple is None or total_cost < best_tuple[0]:
                    best_tuple = (total_cost, start)

            if best_tuple is not None:
                dp[(k, end)] = best_tuple

    # Prefer target_part_count (e.g. 8), then 8 +/- 1 (e.g. 9 or 7)
    reachable_k = [k for k in range(1, max_k + 1) if (k, total) in dp]
    print(f"Reachable part counts: {reachable_k}")
    candidates_k = [target_part_count]
    for delta in range(1, 5):
        if target_part_count - delta >= min_k:
            candidates_k.append(target_part_count - delta)
        if target_part_count + delta <= max_k:
            candidates_k.append(target_part_count + delta)

    chosen_k = None
    for k in candidates_k:
        if (k, total) in dp:
            chosen_k = k
            break

    if chosen_k is None:
        raise ValueError(f"Невозможно разделить таймлайн ({total:.1f}с) на части в пределах {max_short_duration}с")


    boundaries = []
    curr_k = chosen_k
    curr_t = total
    while curr_k > 0:
        prev_t = dp[(curr_k, curr_t)][1]
        boundaries.append((curr_t, candidates[curr_t][1]))
        curr_t = prev_t
        curr_k -= 1
    boundaries = list(reversed(boundaries))


    print(f"\nSimulation results:")
    print(f"Total timeline: {total:.1f}s ({total/60:.2f} min)")
    print(f"Parts count: {len(boundaries)} (Target was {target_part_count})")
    prev = 0.0
    for i, (b_t, ending) in enumerate(boundaries, 1):
        dur = b_t - prev
        prev = b_t
        end_info = ending['kind'] if ending else 'cut'
        print(f"Part {i:02d}: {dur:.1f}s ({dur/60:.2f} min) [{end_info}]")

    return boundaries


def print_events(job_dir: Path):
    events = json.load(open(job_dir / "events.json", encoding="utf-8"))
    transcript = json.load(open(job_dir / "transcript.json", encoding="utf-8"))
    words = transcript.get("words", [])
    print("\n--- Events Summary ---")
    for e in events:
        eid = e["id"]
        imp = e.get("importance", 3)
        kind = e.get("kind", "")
        bridge = e.get("narrative_bridge", False)
        dur = e["end"] - e["start"]
        endings = [p["kind"] for p in e.get("part_endings", [])]
        ev_words = [w["text"] for w in words if e["start"] <= w["start"] <= e["end"]]
        text_preview = " ".join(ev_words)[:60]
        print(f"{eid} [{kind}] imp={imp} dur={dur:5.1f}s bridge={bridge!s:5s} end={endings} | {text_preview}")


def main():
    parser = argparse.ArgumentParser(description="Simulate dramatic montage partitioning")
    parser.add_argument("--job", default="f328937d-214f-4978-9508-b075596794b1")
    parser.add_argument("--target-parts", type=int, default=8)
    parser.add_argument("--optimal-duration", type=float, default=125.0)
    parser.add_argument("--max-duration", type=float, default=145.0)
    parser.add_argument("--turn-gap", type=float, default=1.5)
    parser.add_argument("--list-events", action="store_true")
    parser.add_argument("--verify-real", action="store_true")
    args = parser.parse_args()

    job_dir = Path("data/jobs") / args.job
    if args.list_events:
        print_events(job_dir)
        return

    if args.verify_real:
        from app.dramatic_planner import build_dramatic_plan
        from app.planner import validate_plan
        data = load_job_data(job_dir)
        plan = build_dramatic_plan(data)
        validate_plan(plan, data)
        print(f"\nREAL PRODUCTION BUILD_DRAMATIC_PLAN:")
        print(f"Total parts: {len(plan['parts'])}")
        prev = 0.0
        for p in plan['parts']:
            ending = p.get('ending', {}).get('kind', 'cut')
            print(f"Part {p['index']:02d}: {p['duration']:.1f}s ({p['duration']/60:.2f} min) cuts={len(p['cuts'])} [{ending}]")
        return

    data = load_job_data(job_dir)
    simulate(
        data,
        target_part_count=args.target_parts,
        target_short_optimal=args.optimal_duration,
        max_short_duration=args.max_duration,
        turn_group_gap=args.turn_gap,
        include_prologue=False
    )


if __name__ == "__main__":
    main()

