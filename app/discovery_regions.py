"""Cheap source partitions for discovery; never evidence of semantic boundaries."""
from __future__ import annotations

import math

from .content_identity import digest

VERSION = 2


def _speech_envelopes(transcript, duration):
    """Protect complete ASR utterances as well as words crossing their edges."""
    speech = []
    for name in ('segments', 'words'):
        rows = transcript.get(name, [])
        if not isinstance(rows, list):
            raise ValueError('Invalid discovery speech geometry')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid discovery speech geometry')
            a, b = row.get('start'), row.get('end')
            if (any(type(t) not in (int, float) or not math.isfinite(t) for t in (a, b))
                    or not 0 <= a < b <= duration + .002):
                raise ValueError('Invalid discovery speech geometry')
            speech.append((a, min(b, duration)))
    merged = []
    for a, b in sorted(speech):
        # Touching complete utterances have a real shared boundary. Only
        # overlapping ASR spans form one indivisible source envelope.
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def source_regions(probe, transcript, shots, source_sha):
    from .episode_survey import POLICY
    duration = probe.get('duration')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid discovery source duration')
    if (not isinstance(source_sha, str) or len(source_sha) != 64
            or any(c not in '0123456789abcdef' for c in source_sha)):
        raise ValueError('Invalid discovery source SHA')
    # Reuse the survey's sampling/context bound. This does not constrain story
    # length, retention, deep-analysis chunks, or final edit duration.
    window = POLICY['max_window_seconds']
    merged = _speech_envelopes(transcript, duration)
    regions, start = [], 0.
    while start < duration:
        end = min(duration, start + window)
        crossing = next(((a, b) for a, b in merged if a < end < b), None)
        if crossing:
            a, b = crossing
            end = a if a > start else b  # Preserve the complete source utterance.
        identity = {'version': VERSION, 'source': source_sha, 'start': start, 'end': end}
        segments = [{'id': s['id'], 'shot_id': s['id'],
                     'start': max(start, s['start']), 'end': min(end, s['end'])}
                    for s in shots if s['start'] < end and start < s['end']]
        regions.append({'id': 'region_' + digest(identity)[:24],
            'start': start, 'end': end, 'shot_ids': [s['shot_id'] for s in segments],
            'boundary_reason': ['technical_discovery_window'], 'confidence': 0.,
            'uncertain': True, 'technical_region': True,
            'evidence': {'algorithm': 'source_partition', 'semantic_authority': False,
                'source_sha256': source_sha, 'source_segments': segments,
                'speech_boundary_policy': 'complete_asr_utterances_and_words',
                'sampled_times': [], 'boundary_decisions': [], 'uncertainty_reasons': [],
                'indivisible_speech_over_context_window': end - start > window}})
        start = end
    return regions
