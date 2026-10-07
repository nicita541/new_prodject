"""Factual, source-bound preobtained ASR; no invented repair provenance."""
from __future__ import annotations

import copy
import math

VERSION = 2
ROOT_FIELDS = {'words', 'segments', 'language', 'language_probability', 'device',
               'elapsed_seconds', 'warning', 'raw_segments', 'provenance'}
ROW_FIELDS = {'start', 'end', 'text', 'probability', 'speaker'}


def _optional_metadata(transcript):
    for key in ('language', 'device', 'warning'):
        if key in transcript and transcript[key] is not None and not isinstance(transcript[key], str):
            raise ValueError('Некорректные метаданные ASR')
    for key in ('language_probability', 'elapsed_seconds'):
        if key in transcript and (type(transcript[key]) not in (int, float)
                or not math.isfinite(transcript[key]) or transcript[key] < 0
                or key == 'language_probability' and transcript[key] > 1):
            raise ValueError('Некорректные метаданные ASR')


def validate_provided_transcript(transcript, settings, fingerprint, duration):
    if settings.get('transcript_source_sha256') != fingerprint:
        raise ValueError('Предоставленный ASR не привязан к исходному видео')
    if not isinstance(transcript, dict) or set(transcript) - ROOT_FIELDS:
        raise ValueError('ASR должен содержать только исходную речь и её временные отметки')
    _optional_metadata(transcript)
    if 'provenance' in transcript:
        previous = transcript['provenance']
        if (not isinstance(previous, dict)
                or set(previous) != {'kind','source_sha256','validation_version','limitation'}
                or previous['kind'] != 'provided' or previous['source_sha256'] != fingerprint
                or type(previous['validation_version']) is not int
                or not 1 <= previous['validation_version'] <= VERSION
                or previous['limitation'] != 'preobtained_text_not_verified_against_audio'):
            raise ValueError('Некорректная привязка сохранённого ASR')
    for key in ('words', 'segments', *(['raw_segments'] if 'raw_segments' in transcript else [])):
        rows = transcript.get(key)
        if not isinstance(rows, list):
            raise ValueError('Некорректный предоставленный ASR')
        previous = -1
        for row in rows:
            if (not isinstance(row, dict) or set(row) - ROW_FIELDS
                    or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('start', 'end'))
                    or not 0 <= row['start'] < row['end'] <= duration+.002 or row['start'] < previous
                    or not isinstance(row.get('text'), str)):
                raise ValueError('Некорректные исходные временные отметки ASR')
            probability = row.get('probability', 1)
            speaker = row.get('speaker')
            if (type(probability) not in (int, float) or not math.isfinite(probability)
                    or not 0 <= probability <= 1
                    or speaker is not None and type(speaker) not in (str, int)):
                raise ValueError('Некорректные исходные метаданные слова ASR')
            previous = row['start']
    result = copy.deepcopy(transcript)
    result['provenance'] = {'kind': 'provided', 'source_sha256': fingerprint, 'validation_version': VERSION,
                            'limitation': 'preobtained_text_not_verified_against_audio'}
    return result
