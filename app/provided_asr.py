"""Factual, source-bound preobtained ASR; no invented repair provenance."""
from __future__ import annotations

import copy
import math

VERSION = 1
SEMANTIC_FIELDS = {'location', 'characters', 'character_state', 'state_before', 'state_after',
    'action_units', 'narrative_bridge', 'requires', 'story_arc_id', 'story_phase', 'importance', 'summary'}


def validate_provided_transcript(transcript, settings, fingerprint, duration):
    if settings.get('transcript_source_sha256') != fingerprint:
        raise ValueError('Предоставленный ASR не привязан к исходному видео')
    if not isinstance(transcript, dict) or SEMANTIC_FIELDS & set(transcript):
        raise ValueError('ASR должен содержать только исходную речь и её временные отметки')
    for key in ('words', 'segments'):
        rows = transcript.get(key)
        if not isinstance(rows, list):
            raise ValueError('Некорректный предоставленный ASR')
        previous = -1
        for row in rows:
            if (not isinstance(row, dict) or SEMANTIC_FIELDS & set(row)
                    or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('start', 'end'))
                    or not 0 <= row['start'] < row['end'] <= duration+.002 or row['start'] < previous
                    or not isinstance(row.get('text'), str)):
                raise ValueError('Некорректные исходные временные отметки ASR')
            previous = row['start']
    result = copy.deepcopy(transcript)
    result['provenance'] = {'kind': 'provided', 'source_sha256': fingerprint, 'validation_version': VERSION,
                            'limitation': 'preobtained_text_not_verified_against_audio'}
    return result
