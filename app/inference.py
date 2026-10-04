"""Isolated ASR process: exiting releases all CUDA allocations."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import wave

from app.config import ASR_MODEL, TOOLS, setup_environment

_dll_handles = []
REPAIR_VERSION = 1


def _read_audio(audio: Path):
    import numpy as np
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('ASR requires 16kHz mono PCM16 audio')
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768.0


def _setup():
    setup_environment()
    if os.name == 'nt':
        _dll_handles.append(os.add_dll_directory(str(TOOLS / 'cuda' / 'bin')))


def _load_model(device):
    from faster_whisper import WhisperModel
    options = {'device': device, 'compute_type': 'int8_float16' if device == 'cuda' else 'int8',
               'local_files_only': True, 'num_workers': 1}
    if device == 'cpu':
        options['cpu_threads'] = 8
    return WhisperModel(str(ASR_MODEL), **options)


def _decode(model, samples, *, vad):
    segments, _ = model.transcribe(samples, language='ru', word_timestamps=True, vad_filter=vad,
                                   beam_size=5, condition_on_previous_text=False)
    return list(segments)


def _publish(destination: Path, result):
    partial = destination.with_suffix('.partial')
    try:
        with partial.open('w', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _tokens(text):
    # Ignore punctuation and isolated letter fragments, not Russian inflection.
    return [token for token in re.findall(r'[\w]+', text.lower().replace('ё', 'е'), re.UNICODE)
            if len(token) >= 2]


def repair_candidates(transcript):
    """Detect short unfinished prefixes stranded before a long VAD gap."""
    raw = transcript.get('raw_segments', transcript.get('segments', []))
    result = []
    for index, segment in enumerate(raw):
        left, right = segment['start'], segment['end']
        words = [word for word in transcript.get('words', [])
                 if left <= (word['start'] + word['end']) / 2 <= right]
        words.sort(key=lambda word: (word['start'], word['end']))
        for offset in range(min(2, len(words) - 1)):
            previous, following = words[offset:offset + 2]
            if (following['start'] - previous['end'] > 3 and
                    not re.search(r'[.!?…]', previous['text'])):
                result.append((index, segment, words))
                break
    return result


def repair_transcript(samples, transcript: dict, model) -> dict:
    """Repair only strongly matched, bounded local re-recognitions.

    Never insert a predicted prefix without a confident ASR re-recognition of
    the actual audio and matching the existing sentence's last three tokens.
    """
    if transcript.get('repair_version') == REPAIR_VERSION:
        return copy.deepcopy(transcript)
    duration = len(samples) / 16000.0
    result = copy.deepcopy(transcript)
    raw = copy.deepcopy(result.get('raw_segments', result.get('segments', [])))
    originals = list(result.get('repair_originals', []))
    log = list(result.get('repair_log', []))
    for index, original, words in repair_candidates(transcript):
        left, right = max(0.0, original['start']), min(duration, original['end'])
        window_left = max(0.0, left - 2)
        window_right = min(duration, right + 2, window_left + 35)
        first_sample, last_sample = int(window_left * 16000), min(len(samples), int(window_right * 16000))
        window_left = first_sample / 16000.0
        entry = {'start': left, 'end': right, 'window_start': window_left,
                 'window_end': last_sample / 16000.0, 'original_text': original['text']}
        expected_tokens = _tokens(' '.join(word['text'] for word in words))
        entry['expected_tail'] = expected_tokens[-3:]
        if len(expected_tokens) < 3 or window_right < right:
            entry.update(status='rejected', reason='insufficient_tail' if len(expected_tokens) < 3 else 'interval_too_long')
            log.append(entry)
            continue
        decoded = _decode(model, samples[first_sample:last_sample], vad=False)
        replacements = []
        for segment in decoded:
            if segment.no_speech_prob > 0.8 and segment.avg_logprob < -0.8:
                continue
            for word in segment.words or []:
                start, end = window_left + word.start, window_left + word.end
                probability = float(word.probability)
                if not all(math.isfinite(value) for value in (start, end, probability)) or not 0 <= probability <= 1:
                    continue
                if not left <= (start + end) / 2 <= right or not word.word.strip():
                    continue
                start = max(left, min(right, round(start, 3)))
                end = max(left, min(right, round(end, 3)))
                if end > start:
                    replacements.append({'start': start, 'end': end, 'text': word.word.strip(),
                                         'probability': round(probability, 3)})
        replacements.sort(key=lambda word: (word['start'], word['end']))
        text = ' '.join(word['text'] for word in replacements)
        actual_tokens = _tokens(text)
        entry.update(decoded_text=text, actual_tail=actual_tokens[-3:],
                     window_text=' '.join(segment.text.strip() for segment in decoded if segment.text.strip()))
        confidence = sum(word['probability'] for word in replacements) / max(1, len(replacements))
        matched = len(expected_tokens) >= 3 and actual_tokens[-3:] == expected_tokens[-3:]
        ordered = all(a['end'] <= b['start'] + .01 for a, b in zip(replacements, replacements[1:]))
        if replacements and confidence >= .5 and matched and ordered:
            # Only replace words whose centers were in this exact old raw
            # interval. Neighbouring questions/answers remain untouched.
            originals.append({'segment': copy.deepcopy(original), 'words': copy.deepcopy(words)})
            result['words'] = [word for word in result['words']
                               if not left <= (word['start'] + word['end']) / 2 <= right] + replacements
            raw[index] = {'start': replacements[0]['start'], 'end': replacements[-1]['end'], 'text': text}
            entry.update(status='accepted', repaired_text=text, average_probability=round(confidence, 3))
        else:
            reason = 'low_probability' if confidence < .5 else 'tail_mismatch' if not matched else 'overlapping_or_empty_words'
            entry.update(status='rejected', reason=reason, average_probability=round(confidence, 3))
        log.append(entry)
    result['words'].sort(key=lambda word: (word['start'], word['end']))
    result.update(raw_segments=raw, segments=copy.deepcopy(raw), repair_originals=originals,
                  repair_log=log, repair_version=REPAIR_VERSION)
    return result


def _repair_with_cpu_fallback(samples, result, model, device, warning):
    try:
        repaired = repair_transcript(samples, result, model)
    except RuntimeError as error:
        if device != 'cuda':
            raise
        warning = (warning + '; ' if warning else '') + f'GPU ASR repair unavailable; CPU int8 used: {str(error)[:300]}'
        model = _load_model('cpu')
        repaired = repair_transcript(samples, result, model)
        device = 'cpu'
    repaired.update(device=device, warning=warning)
    return repaired


def transcribe(audio: Path, destination: Path) -> dict:
    _setup()
    # FFmpeg already produces a verified 16kHz mono PCM file. Read PCM directly:
    # this also avoids the obsolete metadata_errors argument in faster-whisper's
    # PyAV file decoder (removed by PyAV 19).
    samples = _read_audio(audio)
    duration = len(samples) / 16000.0
    started = time.monotonic()
    warning = None
    try:
        model = _load_model('cuda')
        segments = _decode(model, samples, vad=True)
        device = 'cuda'
    except RuntimeError as error:
        # No heuristic transcript fallback: CPU still uses the same actual model.
        warning = f'GPU ASR unavailable; CPU int8 used: {str(error)[:300]}'
        model = _load_model('cpu')
        segments = _decode(model, samples, vad=True)
        device = 'cpu'
    result = {'language': 'ru', 'device': device, 'elapsed_seconds': round(time.monotonic() - started, 2),
              'warning': warning, 'words': [], 'segments': []}
    for segment in segments:
        # Whisper can hallucinate sentences over music/silence. Suppress strong no-speech predictions.
        if segment.no_speech_prob > 0.8 and segment.avg_logprob < -0.8:
            continue
        start, end = round(max(0.0, min(duration, segment.start)), 3), round(max(0.0, min(duration, segment.end)), 3)
        if end > start:
            result['segments'].append({'start': start, 'end': end, 'text': segment.text.strip()})
        for word in segment.words or []:
            start, end = round(max(0.0, min(duration, word.start)), 3), round(max(0.0, min(duration, word.end)), 3)
            if end > start and word.word.strip():
                result['words'].append({'start': start, 'end': end, 'text': word.word.strip(), 'probability': round(word.probability, 3)})
    result = _repair_with_cpu_fallback(samples, result, model, device, warning)
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    _publish(destination, result)
    print(json.dumps({'device': result['device'], 'words': len(result['words']), 'elapsed_seconds': result['elapsed_seconds'], 'warning': result['warning']}, ensure_ascii=False), flush=True)
    return result


def repair_only(audio: Path, destination: Path) -> dict:
    """Atomic upgrade of an existing transcript; failure leaves it unchanged."""
    _setup()
    result = json.loads(destination.read_text(encoding='utf-8'))
    if result.get('repair_version') == REPAIR_VERSION:
        return result
    samples = _read_audio(audio)
    started = time.monotonic()
    warning = result.get('warning')
    if not repair_candidates(result):
        result = repair_transcript(samples, result, None)
    else:
        device = 'cuda'
        try:
            model = _load_model(device)
        except RuntimeError as error:
            device = 'cpu'
            warning = (warning + '; ' if warning else '') + f'GPU ASR repair unavailable; CPU int8 used: {str(error)[:300]}'
            model = _load_model(device)
        result = _repair_with_cpu_fallback(samples, result, model, device, warning)
    result['repair_elapsed_seconds'] = round(time.monotonic() - started, 2)
    _publish(destination, result)
    print(json.dumps({'repair_version': REPAIR_VERSION,
                      'accepted': sum(item['status'] == 'accepted' for item in result['repair_log']),
                      'candidates': len(result['repair_log'])}, ensure_ascii=False), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--repair-only', action='store_true')
    args = parser.parse_args()
    (repair_only if args.repair_only else transcribe)(args.audio, args.destination)


if __name__ == '__main__':
    main()
