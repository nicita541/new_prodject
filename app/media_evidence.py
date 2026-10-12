"""Measured local video/audio evidence; no supplied semantic labels are consumed.

Optical flow measures visible intra-shot movement, including camera movement.
Perceptual vectors describe image structure, not locations, people or actions.
Proposals require downstream semantic adjudication; they are not scene facts.
"""
from __future__ import annotations


import bisect
import hashlib
import json
import math
from pathlib import Path
import re
import wave

import cv2
import numpy as np
from PIL import Image

from app.content_identity import evidence_digest as _hash

from .config import FFMPEG, FFPROBE, ROOT
from .media import run_command
from .media_probe import atomic_json, load_json, raw_shot_evidence, run_process

VERSION = 1
POLICY = {'sample_interval': .2, 'frame_width': 160, 'frame_height': 90,
          'audio_rate': 16000, 'audio_window': .5, 'spectral_bands': 32,
          'embedding_jump': .22, 'audio_jump': .65, 'motion_jump': .18,
          'flow_method': 'normalized_farneback', 'subtitle_crop': .80,
          'embedding_method': 'normalized_luminance_dct_and_spatial_gradient_v1'}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _structure(shots, duration):
    result = []
    for index, shot in enumerate(shots):
        start, end = shot['start'], shot.get('end', shots[index + 1]['start'] if index + 1 < len(shots) else duration)
        if not _finite(start) or not _finite(end) or not 0 <= start < end <= duration + .002:
            raise ValueError('Некорректные исходные границы shot evidence')
        result.append({'id': str(shot.get('id', f'shot_{index:04d}')), 'start': start, 'end': min(end, duration)})
    raw = []
    for row in raw_shot_evidence(shots):
        timestamp = row['time']
        if not _finite(timestamp) or not 0 <= timestamp <= duration:
            raise ValueError('Некорректный исходный кандидат perception')
        score = row.get('scene_score', row.get('score'))
        if score is not None and (not _finite(score) or not 0 <= score <= 1):
            raise ValueError('Некорректный измеренный scene score')
        raw.append({'id': str(row.get('id', f'raw_{len(raw):05d}')), 'time': timestamp,
                    'scene_score': score, 'accepted': row.get('accepted') is True})
    return result or [{'id': 'shot_0000', 'start': 0, 'end': duration}], raw


def _speech(transcript, duration):
    result = {'words': [], 'segments': []}
    for key in result:
        for row in (transcript or {}).get(key, []):
            start, end = row['start'], row['end']
            if not _finite(start) or not _finite(end) or not 0 <= start < end <= duration + .002:
                raise ValueError('Некорректные ASR границы perception')
            result[key].append({'start': start, 'end': min(duration, end)})
    return result


def _normalize(vector):
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else np.zeros_like(vector)


def embedding_distance(left, right):
    """Cosine structural distance in [0,1]; a blank image cannot establish similarity."""
    a, b = np.asarray(left, dtype=np.float32), np.asarray(right, dtype=np.float32)
    if a.size == 0 or a.shape != b.shape or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return None
    if np.linalg.norm(a) < 1e-8 or np.linalg.norm(b) < 1e-8:
        return None
    return float(np.clip((1 - np.dot(_normalize(a), _normalize(b))) / 2, 0, 1))


def _hog(gray, mask):
    dx, dy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    magnitude, angle = cv2.cartToPolar(dx, dy)
    bins = np.floor(angle * (8 / (2 * math.pi))).astype(np.int32) % 8
    vector = []
    for y in np.array_split(np.arange(gray.shape[0]), 4):
        for x in np.array_split(np.arange(gray.shape[1]), 6):
            weights = (magnitude * mask)[np.ix_(y, x)].ravel()
            vector.extend(np.bincount(bins[np.ix_(y, x)].ravel(), weights=weights, minlength=8))
    return _normalize(vector)


def image_evidence(image):
    """Lighting-normalized structure plus an explicitly separate cheap RGB signal."""
    rgb = np.asarray(image.convert('RGB').resize((160, 90)), dtype=np.float32) / 255
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    top = gray[:int(gray.shape[0] * POLICY['subtitle_crop'])]
    mean, contrast = float(top.mean()), float(top.std())
    normalized = (top - mean) / max(contrast, .015)
    normalized = np.clip(normalized, -3, 3).astype(np.float32)
    resized = cv2.resize(normalized, (32, 24), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(resized)[:8, :8].copy()
    dct[0, 0] = 0
    full_mask = np.ones(top.shape, dtype=np.float32)
    background_mask = full_mask.copy()
    # A central face/foreground and subtitle strip should not dominate the
    # background signal. The separate full-image vector still observes them.
    background_mask[int(top.shape[0] * .18):int(top.shape[0] * .85),
                    int(top.shape[1] * .25):int(top.shape[1] * .75)] = 0
    perceptual = _normalize(np.concatenate([_normalize(dct), _hog(normalized, full_mask)]))
    background = _hog(normalized, background_mask)
    border = rgb[:top.shape[0]][background_mask.astype(bool)]
    bins = np.minimum((border * 4).astype(np.int32), 3)
    histogram = np.bincount(bins[:, 0] * 16 + bins[:, 1] * 4 + bins[:, 2], minlength=64).astype(float)
    histogram /= max(1, histogram.sum())
    regions = [rgb[:18], rgb[18:36, :40], rgb[18:36, 120:], rgb[36:72, :40], rgb[36:72, 120:]]
    spatial = np.concatenate([region.mean(axis=(0, 1)) for region in regions])
    black_fraction = float((gray < .035).mean())
    edges = cv2.Sobel(top, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(top, cv2.CV_32F, 0, 1) ** 2
    edge_density = float((edges > .008).mean())
    reliability = float(np.clip(contrast * 5 + edge_density, 0, 1)) if black_fraction < .98 else 0.0
    rounded = lambda values: [round(float(value), 6) for value in values]
    return {'descriptor': {'histogram': rounded(histogram), 'spatial': rounded(spatial)},
            'perceptual_embedding': rounded(perceptual), 'background_embedding': rounded(background),
            'reliability': round(reliability, 6), 'luminance': round(float(gray.mean()), 6),
            'contrast': round(contrast, 6), 'black_fraction': round(black_fraction, 6),
            'black': black_fraction >= .98, 'edge_density': round(edge_density, 6)}


def _motion(previous, current, elapsed):
    def normalize(image):
        gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY).astype(np.float32)
        gray = cv2.resize(gray[:int(gray.shape[0] * .8)], (80, 45))
        gray = (gray - gray.mean()) / max(float(gray.std()), 5)
        return np.clip(gray * 40 + 128, 0, 255).astype(np.uint8)
    left, right = normalize(previous), normalize(current)
    flow = cv2.calcOpticalFlowFarneback(left, right, None, .5, 2, 9, 2, 5, 1.1, 0)
    magnitude = np.linalg.norm(flow, axis=2)
    global_vector = np.median(flow.reshape(-1, 2), axis=0)
    residual = np.linalg.norm(flow - global_vector, axis=2)
    mean_flow = float(magnitude.mean())
    coherence = float(np.linalg.norm(flow.mean(axis=(0, 1))) / max(mean_flow, 1e-8))
    speed = max(.01, elapsed) * 45 * .10
    density = float(np.mean(np.clip(magnitude / speed, 0, 1)))
    score = float(np.clip(max(density, float(np.quantile(magnitude, .90)) / (speed * 2)), 0, 1))
    return {'flow_magnitude': round(mean_flow, 6), 'flow_coherence': round(coherence, 6),
            'global_motion_score': round(float(np.clip(np.linalg.norm(global_vector) / speed, 0, 1)), 6),
            'residual_motion_score': round(float(np.mean(np.clip(residual / speed, 0, 1))), 6),
            'physical_motion_score': round(score, 6),
            'normalized_frame_difference': round(float(np.abs(left.astype(float) - right).mean() / 255), 6)}


def _expression(parts):
    # A balanced sum avoids FFmpeg expression-parser recursion on long videos.
    while len(parts) > 1:
        parts = [f'({parts[index]}+{parts[index + 1]})' if index + 1 < len(parts) else parts[index]
                 for index in range(0, len(parts), 2)]
    return parts[0]


def _video(source, duration, shots, raw, directory, cancelled):
    frames = directory / 'frames'
    frames.mkdir(parents=True, exist_ok=True)
    targets = sorted({round(max(0.0, min(duration, row['time'] + delta)), 6)
                      for row in raw for delta in (-.15, 0, .15) if 0 < row['time'] < duration})
    parts = [f'(isnan(prev_selected_t)+gte(t-prev_selected_t,{POLICY["sample_interval"]}))']
    parts += [f'(gte(t,{time:.6f})*(isnan(prev_selected_t)+lt(prev_selected_t,{time:.6f})))' for time in targets]
    script = directory / 'frames.filter'
    script.write_text(f"select='gt({_expression(parts)},0)',scale=160:90,showinfo", encoding='utf-8')
    log = directory / 'frames.log'
    run_process([FFMPEG, '-y', '-hide_banner', '-copyts', '-protocol_whitelist', 'file,pipe', '-i', source,
                 '-map', '0:v:0', '-an', '-filter_script:v', script, '-fps_mode', 'vfr',
                 '-threads', '1', '-q:v', '3', frames / 'frame-%06d.jpg'], log, cancelled)
    times = [float(match.group(1)) for match in re.finditer(r'\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.eE+-]+)',
                                                          log.read_text('utf-8', errors='replace'))]
    if not times:
        raise ValueError('Perception не получил исходные кадры')
    cuts = sorted({shot['start'] for shot in shots if shot['start'] > 0}
                  | {row['time'] for row in raw if 0 < row['time'] < duration})
    samples, previous_image = [], None
    for index, timestamp in enumerate(times):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        if not math.isfinite(timestamp):
            raise ValueError('Некорректный исходный PTS кадра')
        if not 0 <= timestamp < duration:
            continue
        path = frames / f'frame-{index + 1:06d}.jpg'
        with Image.open(path) as image:
            current_image = image.copy()
        features = image_evidence(current_image)
        sample = {'time': timestamp, 'frame': path.relative_to(directory.parent).as_posix(),
                  'sample_number': index, 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  **features, 'motion_score': 0.0}
        if samples:
            previous = samples[-1]
            elapsed = timestamp - previous['time']
            if elapsed <= 0:
                raise ValueError('Perception получил повторный/обратный PTS')
            motion = _motion(previous_image, current_image, elapsed)
            distance = embedding_distance(previous['perceptual_embedding'], features['perceptual_embedding'])
            cut = any(previous['time'] < time <= timestamp + 1e-6 for time in cuts)
            abrupt_cut = (distance is not None and distance >= .35
                          and motion['normalized_frame_difference'] >= .16 and motion['flow_coherence'] < .3)
            sample.update(motion, motion_start=previous['time'], motion_duration=elapsed,
                          crosses_cut=cut or abrupt_cut, motion_exclusion_reason='source_shot_or_raw_cut_candidate' if cut else
                          'abrupt_incoherent_appearance_change' if abrupt_cut else None,
                          motion_score=0.0 if cut or abrupt_cut else motion['physical_motion_score'])
        samples.append(sample)
        previous_image = current_image
    if not samples:
        raise ValueError('Perception не получил кадры в исходных границах')
    return samples


def _audio(source, duration, audio_stream, speech, directory, cancelled):
    info = json.loads(run_command([str(FFPROBE), '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                  '-show_streams', '-of', 'json', str(source)], directory, cancelled, 45))
    streams = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'audio']
    if not streams:
        return [], False, ['source_has_no_audio']
    if audio_stream >= len(streams):
        raise ValueError('Выбрана отсутствующая исходная аудиодорожка')
    path, log = directory / 'audio.wav', directory / 'audio.log'
    run_process([FFMPEG, '-y', '-hide_banner', '-copyts', '-protocol_whitelist', 'file,pipe', '-i', source,
                 '-map', f'0:a:{audio_stream}', '-vn', '-ac', '1', '-ar', str(POLICY['audio_rate']),
                 '-af', 'aresample=16000,ashowinfo', '-c:a', 'pcm_s16le', path], log, cancelled)
    packet_rows = re.findall(r'\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.eE+-]+).*?\bnb_samples:(\d+)',
                             log.read_text('utf-8', errors='replace'))
    offset = float(packet_rows[0][0]) if packet_rows else float(streams[audio_stream].get('start_time', 0))
    if not math.isfinite(offset):
        raise ValueError('Некорректный исходный audio PTS')
    # WAV stores PCM order, not timestamps. Track discontinuities in ashowinfo
    # so a source packet gap cannot shift all subsequent evidence/ASR alignment.
    segments, packet_cursor = [(0, offset)], 0
    for pts, sample_count in packet_rows:
        timestamp = float(pts)
        expected = segments[-1][1] + (packet_cursor - segments[-1][0]) / POLICY['audio_rate']
        if not math.isfinite(timestamp):
            raise ValueError('Некорректный исходный PCM PTS')
        if packet_cursor and abs(timestamp - expected) > .04:
            segments.append((packet_cursor, timestamp))
        packet_cursor += int(sample_count)
    spans = speech['words'] or speech['segments']
    rows, previous = [], None
    with wave.open(str(path), 'rb') as audio:
        rate = audio.getframerate()
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate != POLICY['audio_rate']:
            raise ValueError('Некорректный измеренный PCM формат')
        cursor, segment_number = 0, 0
        while True:
            if cancelled():
                raise InterruptedError('Обработка отменена')
            if segment_number + 1 < len(segments) and cursor >= segments[segment_number + 1][0]:
                segment_number += 1
            count = int(rate * POLICY['audio_window'])
            if segment_number + 1 < len(segments):
                count = min(count, segments[segment_number + 1][0] - cursor)
            buffer = audio.readframes(count)
            if not buffer:
                break
            pcm = np.frombuffer(buffer, dtype='<i2').astype(np.float32) / 32768
            segment_start, timestamp = segments[segment_number]
            raw_start = timestamp + (cursor - segment_start) / rate
            raw_end = timestamp + (cursor + len(pcm) - segment_start) / rate
            cursor += len(pcm)
            start, end = max(0.0, raw_start), min(duration, raw_end)
            if end <= start:
                continue
            pcm = pcm[max(0, int((start - raw_start) * rate)):min(len(pcm), int((end - raw_start) * rate))]
            if len(pcm) < 2:
                continue
            rms = float(np.sqrt(np.mean(pcm ** 2)))
            dbfs = max(-120.0, 20 * math.log10(max(rms, 1e-6)))
            power = np.abs(np.fft.rfft(pcm * np.hanning(len(pcm)))) ** 2
            frequencies = np.fft.rfftfreq(len(pcm), 1 / rate)
            bands = [float(power[(frequencies >= left) & (frequencies < right)].sum())
                     for left, right in zip(np.linspace(0, rate / 2, POLICY['spectral_bands'] + 1)[:-1],
                                            np.linspace(0, rate / 2, POLICY['spectral_bands'] + 1)[1:])]
            signature = np.asarray(bands) / max(1e-12, sum(bands))
            spectral_flux = float(np.abs(signature - np.asarray(previous['spectral_signature'])).sum() / 2) if previous else 0.0
            # Union overlap prevents overlapping ASR words from exceeding one.
            overlaps = sorted((max(start, span['start']), min(end, span['end'])) for span in spans
                              if span['start'] < end and span['end'] > start)
            merged = []
            for left, right in overlaps:
                if merged and left <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
                else:
                    merged.append((left, right))
            ratio = sum(right - left for left, right in merged) / (end - start)
            silence = dbfs < -48
            delta = abs(dbfs - previous['dbfs']) if previous else 0.0
            timestamp_gap = max(0.0, start - previous['end']) if previous else 0.0
            discontinuity = max(spectral_flux * .85, min(1.0, delta / 36), min(1.0, timestamp_gap / .5))
            continuity = any(span['start'] < start < span['end'] for span in speech['segments'])
            row = {'start': start, 'end': end, 'rms': round(rms, 7), 'dbfs': round(dbfs, 5),
                   'spectral_centroid': round(float(np.dot(power, frequencies) / max(1e-12, power.sum())), 3),
                   'spectral_signature': [round(float(value), 7) for value in signature],
                   'band_energy': [round(value / max(1, len(pcm) ** 2), 9) for value in bands],
                   'spectral_flux': round(spectral_flux, 6), 'rms_delta_db': round(delta, 5),
                   'source_timestamp_gap': round(timestamp_gap, 6),
                   'silence': silence, 'speech': ratio > .1, 'speech_overlap_ratio': round(ratio, 6),
                   'speech_continuity': continuity, 'discontinuity_score': round(discontinuity, 6),
                   'ambient_change_score': round(spectral_flux if ratio < .1 and previous and not previous['speech'] else 0.0, 6),
                   'origin': 'source_pcm', 'sample_rate': rate}
            rows.append(row)
            previous = row
    return rows, True, ['audio_pts_metadata_unavailable'] if not packet_rows else []


def _proposals(samples, audio, raw, duration):
    proposals = {}
    def add(timestamp, origin, reason, scores):
        if not _finite(timestamp) or not 0 < timestamp < duration:
            return
        key = round(timestamp, 6)
        row = proposals.setdefault(key, {'time': timestamp, 'origins': [], 'reasons': [], 'scores': {}})
        if origin not in row['origins']:
            row['origins'].append(origin)
        if reason not in row['reasons']:
            row['reasons'].append(reason)
        row['scores'].update(scores)
    for row in raw:
        add(row['time'], 'ffmpeg_scene_score', 'original_raw_candidate', {'scene_score': row['scene_score'], 'accepted_shot': row['accepted']})
    for index in range(1, len(samples)):
        left, right = samples[index - 1], samples[index]
        distance = embedding_distance(left['perceptual_embedding'], right['perceptual_embedding'])
        background = embedding_distance(left['background_embedding'], right['background_embedding'])
        scores = {'perceptual_distance': distance, 'background_distance': background,
                  'motion_score': right['motion_score'], 'luminance_delta': right['luminance'] - left['luminance']}
        if distance is not None and distance >= POLICY['embedding_jump']:
            add(right['time'], 'perceptual_discontinuity', 'normalized_image_structure_change', scores)
        if left['black'] != right['black']:
            add(right['time'], 'fade_black', 'black_frame_entry' if right['black'] else 'black_frame_exit', scores)
        if index >= 3:
            sequence = samples[index - 3:index + 1]
            luminance = [sample['luminance'] for sample in sequence]
            if (sequence[-1]['time'] - sequence[0]['time'] <= 2.0
                    and abs(luminance[-1] - luminance[0]) >= .16
                    and (all(a > b + .01 for a, b in zip(luminance, luminance[1:]))
                         or all(a < b - .01 for a, b in zip(luminance, luminance[1:])))):
                add(right['time'], 'fade_black', 'monotonic_luminance_fade_candidate', scores)
        if (not right.get('crosses_cut') and abs(right['motion_score'] - left['motion_score']) >= POLICY['motion_jump']
                and max(right['motion_score'], left['motion_score']) >= .22):
            add(right['time'], 'motion_change', 'intra_shot_motion_onset_or_offset', scores)
    for row in audio:
        if row['discontinuity_score'] >= POLICY['audio_jump'] and (not row['speech_continuity'] or row['rms_delta_db'] > 20):
            add(row['start'], 'audio_discontinuity', 'measured_pcm_energy_or_spectral_change',
                {'audio_discontinuity': row['discontinuity_score'], 'audio_flux': row['spectral_flux'],
                 'audio_rms_delta_db': row['rms_delta_db'], 'speech_continuity': row['speech_continuity']})
    result = sorted(proposals.values(), key=lambda row: row['time'])
    return [{'id': f'perception_{index:05d}', **row} for index, row in enumerate(result)]


def _cluster_proposals(rows):
    """Bound secondary review targets; keep original raw FFmpeg evidence intact."""
    keep = {row['id'] for row in rows if 'ffmpeg_scene_score' in row['origins']}
    annotations = {}
    for origin in ('perceptual_discontinuity', 'fade_black', 'motion_change', 'audio_discontinuity'):
        candidates = [row for row in rows if origin in row['origins']]
        groups = []
        for row in candidates:
            if groups and row['time'] - groups[-1][-1]['time'] <= .65:
                groups[-1].append(row)
            else:
                groups.append([row])
        for index, group in enumerate(groups):
            def strength(row):
                scores = row['scores']
                return max((abs(value) for key, value in scores.items() if _finite(value)
                            and key != 'audio_rms_delta_db'), default=0.0)
            peak = max(group, key=strength)
            representatives = {group[0]['id'], peak['id'], group[-1]['id']}
            representatives.update(row['id'] for row in group if any(reason in row['reasons']
                for reason in ('black_frame_entry', 'black_frame_exit')))
            for row in group:
                if row['id'] in representatives:
                    keep.add(row['id'])
                    annotations.setdefault(row['id'], []).append({'origin': origin,
                        'cluster_id': f'{origin}_{index:04d}', 'start': group[0]['time'], 'end': group[-1]['time'],
                        'candidate_count': len(group), 'peak_time': peak['time'],
                        'selection': 'onset_peak_offset_or_black_edge'})
    return [{**row, **({'clusters': annotations[row['id']]} if row['id'] in annotations else {})}
            for row in rows if row['id'] in keep]


def visual_feature_map(perception, intervals):
    """Map arbitrary source/internal IDs to measured frames inside that interval."""
    duration = perception['source']['duration']
    samples = perception.get('samples', [])
    times = [sample['time'] for sample in samples]
    result = {}
    for index, interval in enumerate(intervals):
        start, end = interval['start'], interval['end']
        identifier = str(interval.get('id', f'interval_{index:04d}'))
        if not _finite(start) or not _finite(end) or not 0 <= start < end <= duration + .002 or identifier in result:
            raise ValueError('Некорректный исходный интервал visual evidence')
        observed = samples[bisect.bisect_left(times, start):bisect.bisect_left(times, min(end, duration))]
        feature = {'shot_id': identifier, 'samples': observed, 'origin': 'source_frames', 'feature_version': VERSION,
                   'reliability': sum(row['reliability'] for row in observed) / len(observed) if observed else 0.0,
                   'motion_score': 0.0, 'motion_evidence': 'source_optical_flow'}
        if observed:
            representative = max(observed, key=lambda row: row['reliability'])
            feature.update({key: representative[key] for key in ('descriptor', 'perceptual_embedding', 'background_embedding')})
            usable = [row for row in observed if row.get('motion_start', -1) >= start and not row.get('crosses_cut')]
            weight = sum(row['motion_duration'] for row in usable)
            feature['motion_score'] = sum(row['motion_score'] * row['motion_duration'] for row in usable) / weight if weight else 0.0
        else:
            feature['warning'] = 'no_source_sample_in_interval'
        result[identifier] = feature
    return result


def perception_checkpoint(source, duration, shots, transcript, job_dir, cancelled, *, audio_stream=0):
    """Decode actual PTS frames/PCM with a content- and policy-addressed cache."""
    if cancelled():
        raise InterruptedError('Обработка отменена')
    if not _finite(duration) or duration <= 0 or type(audio_stream) is not int or audio_stream < 0:
        raise ValueError('Некорректные параметры исходного perception')
    source, job_dir = Path(source).resolve(), Path(job_dir).resolve()
    try:
        job_dir.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError('Perception cache должен находиться внутри workspace') from error
    structure, raw = _structure(shots, duration)
    speech = _speech(transcript, duration)
    stat, digest = source.stat(), hashlib.sha256()
    with source.open('rb') as handle:
        while block := handle.read(1024 * 1024):
            if cancelled():
                raise InterruptedError('Обработка отменена')
            digest.update(block)
    identity = {'source': {'path': str(source), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                           'sha256': digest.hexdigest(), 'duration': duration},
                'shots': structure, 'raw_candidates': raw, 'speech': speech, 'audio_stream': audio_stream,
                'version': VERSION, 'policy': POLICY,
                'implementation': hashlib.sha256(Path(__file__).read_text('utf-8').replace('\r\n', '\n').encode()).hexdigest(),
                'ffmpeg': {'size': FFMPEG.stat().st_size, 'mtime_ns': FFMPEG.stat().st_mtime_ns}}
    signature = _hash(identity)
    path, meta = job_dir / 'media-evidence.json', job_dir / 'media-evidence.meta.json'
    if path.is_file() and meta.is_file():
        try:
            cached = load_json(path)
            if load_json(meta) == identity and cached.get('signature') == signature:
                if cancelled():
                    raise InterruptedError('Обработка отменена')
                intact = True
                for sample in cached.get('samples', []):
                    if cancelled():
                        raise InterruptedError('Обработка отменена')
                    frame = (job_dir / sample['frame']).resolve()
                    frame.relative_to(job_dir)
                    if not frame.is_file() or hashlib.sha256(frame.read_bytes()).hexdigest() != sample.get('image_sha256'):
                        intact = False
                        break
                if intact and cached.get('samples'):
                    return cached
        except InterruptedError:
            raise
        except (OSError, ValueError):
            pass
    directory = job_dir / 'media-evidence'
    directory.mkdir(parents=True, exist_ok=True)
    samples = _video(source, duration, structure, raw, directory, cancelled)
    audio, audio_available, limitations = _audio(source, duration, audio_stream, speech, directory, cancelled)
    usable = [row for row in samples if row.get('motion_duration') and not row.get('crosses_cut')]
    measured_time = sum(row['motion_duration'] for row in usable)
    cuts = len({shot['start'] for shot in structure if shot['start'] > 0})
    raw_count = len({row['time'] for row in raw if 0 < row['time'] < duration})
    motion = {'physical_motion_density': sum(row['motion_score'] * row['motion_duration'] for row in usable) / measured_time if measured_time else 0.0,
              'global_camera_motion_density': sum(row['global_motion_score'] * row['motion_duration'] for row in usable) / measured_time if measured_time else 0.0,
              'residual_motion_density': sum(row['residual_motion_score'] * row['motion_duration'] for row in usable) / measured_time if measured_time else 0.0,
              'editing_density': min(1.0, raw_count / duration) if raw else min(1.0, cuts / duration),
              'cuts_per_minute': cuts * 60 / duration, 'accepted_cuts_per_minute': cuts * 60 / duration,
              'raw_cut_candidates_per_minute': raw_count * 60 / duration,
              'accepted_editing_density': min(1.0, cuts / duration),
              'editing_evidence': 'raw_ffmpeg_candidate_rate' if raw else 'accepted_shot_boundary_rate',
              'measured_duration': measured_time, 'measurement_coverage': measured_time / duration,
              'excluded_cut_pairs': sum(bool(row.get('crosses_cut')) for row in samples),
              'evidence': 'source_optical_flow', 'physical_semantics_known': False,
              'available': measured_time > 0, 'adequate_coverage': measured_time / duration >= .35}
    proposal_evidence = _proposals(samples, audio, raw, duration)
    if not motion['adequate_coverage']:
        limitations.append('insufficient_intra_shot_motion_coverage')
    if source.stat().st_size != stat.st_size or source.stat().st_mtime_ns != stat.st_mtime_ns:
        raise ValueError('Источник изменился во время измерения perception')
    result = {'version': VERSION, 'source': identity['source'], 'signature': signature,
              'samples': samples, 'proposals': _cluster_proposals(proposal_evidence), 'proposal_evidence': proposal_evidence,
              'audio_features': audio, 'audio_available': audio_available, 'motion': motion,
              'limitations': [*limitations, 'optical_flow_includes_camera_motion', 'structural_embeddings_are_not_semantic_labels']}
    atomic_json(path, result)
    atomic_json(meta, identity)
    return result
