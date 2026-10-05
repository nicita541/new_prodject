"""Audio analysis for music detection and smart ducking."""
from __future__ import annotations

import math
from pathlib import Path


MUSIC_INDICATORS = ('♪', '♫', '♬', '♩', 'ла-ла', 'ля-ля', 'песня', 'поёт', 'поет', 'поют', 'концерт')


def detect_transcript_music_intervals(transcript: dict) -> list[tuple[float, float]]:
    """Find intervals in the transcript that represent songs or singing."""
    intervals = []
    for segment in transcript.get('segments', []):
        text = segment.get('text', '').lower()
        if any(ind in text for ind in MUSIC_INDICATORS):
            intervals.append((float(segment['start']), float(segment['end'])))
    return merge_intervals(intervals)


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or adjacent intervals."""
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    for current in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        cur_start, cur_end = current
        if cur_start <= prev_end + 0.2:
            merged[-1] = (prev_start, max(prev_end, cur_end))
        else:
            merged.append((cur_start, cur_end))
    return [(round(s, 6), round(e, 6)) for s, e in merged if e > s]


def map_cuts_to_part_duck_intervals(
    cuts: list[dict],
    source_music_intervals: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Map source-level music intervals to rendered part timeline coordinates."""
    if not cuts or not source_music_intervals:
        return []
    part_intervals = []
    current_out_time = 0.0
    for cut in cuts:
        c_start = float(cut['start'])
        c_end = float(cut['end'])
        c_dur = c_end - c_start
        for m_start, m_end in source_music_intervals:
            overlap_start = max(c_start, m_start)
            overlap_end = min(c_end, m_end)
            if overlap_end > overlap_start:
                out_start = current_out_time + (overlap_start - c_start)
                out_end = current_out_time + (overlap_end - c_start)
                part_intervals.append((out_start, out_end))
        current_out_time += c_dur
    return merge_intervals(part_intervals)


def build_volume_expression(
    duck_intervals: list[tuple[float, float]],
    base_volume: float = 0.15,
    duck_volume: float = 0.015
) -> str:
    """Build FFmpeg audio filter volume expression with frame-level evaluation.

    When duck_intervals is empty, returns a constant float string.
    When intervals exist, evaluates per frame with escaped commas for FFmpeg script compatibility.
    """
    if not duck_intervals:
        return f"{base_volume:.6f}"
    conditions = '+'.join(f'between(t\\,{s:.6f}\\,{e:.6f})' for s, e in duck_intervals)
    return f"if(gt({conditions}\\,0)\\,{duck_volume:.6f}\\,{base_volume:.6f}):eval=frame"
