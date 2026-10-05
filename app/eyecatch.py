"""Detection of mid-episode TV commercial bumpers and eyecatches."""
from __future__ import annotations


def detect_eyecatches(
    events: list[dict],
    transcript: dict,
    shots: list[dict],
    duration: float | None = None
) -> list[int]:
    """Identify indices of events that represent mid-episode TV eyecatches/bumpers.

    Characteristics of anime eyecatches:
    - Located around the middle of the episode (35% to 65% of total runtime).
    - Very short duration (typically 2 to 12 seconds).
    - No real dialogue (or at most series title mention / sound effect).
    - Framed by shot transitions.
    """
    if not events:
        return []
    total_duration = duration or max((e['end'] for e in events), default=0)
    if total_duration < 300:  # Short test clips don't have mid-episode commercial bumpers
        return []

    mid_start = total_duration * 0.35
    mid_end = total_duration * 0.65

    eyecatch_indices = []
    words = transcript.get('words', [])

    for i, event in enumerate(events):
        e_start = float(event['start'])
        e_end = float(event['end'])
        e_dur = e_end - e_start

        # Must be in mid-episode zone and short (< 14 seconds)
        if not (mid_start <= e_start and e_end <= mid_end and 1.5 <= e_dur <= 14.0):
            continue

        # Check speech density
        event_words = [w for w in words if w['start'] < e_end and w['end'] > e_start]
        speech_dur = sum(max(0, min(w['end'], e_end) - max(w['start'], e_start)) for w in event_words)
        if speech_dur / e_dur > 0.15:
            continue

        # Check shot transitions nearby
        has_shot_start = any(abs(s['start'] - e_start) < 0.5 for s in shots)
        has_shot_end = any(abs(s['end'] - e_end) < 0.5 for s in shots)
        if has_shot_start or has_shot_end or len(event_words) == 0:
            eyecatch_indices.append(i)

    return eyecatch_indices


def apply_eyecatch_exclusions(events: list[dict], eyecatch_indices: list[int]) -> list[dict]:
    """Mark detected eyecatches with kind='eyecatch' and zero importance."""
    import copy
    result = copy.deepcopy(events)
    for idx in eyecatch_indices:
        if 0 <= idx < len(result):
            event = result[idx]
            event['kind'] = 'eyecatch'
            event['importance'] = 0
            event['contains_credits'] = False
            event['credit_montage'] = False
            event['selected_ranges'] = []
            event.setdefault('story_warnings', []).append('Исключена ТВ-заставка (айкетч) между частями')
    return result
