"""Group real montage shots into semantic scenes, independently of chunk length.

The detector is deliberately conservative about camera cuts. Local image
descriptors are evidence of background continuity, not object/character labels.
If that evidence cannot establish a scene boundary, uncertainty stays visible
and all original shot boundaries remain available to the unit/storyboard stage.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from pathlib import Path
import re

from .config import FFMPEG
from .media_probe import atomic_json, load_json, run_process

SCENE_DETECTOR_VERSION = 1
SCENE_GROUPING_VERSION = 1
VISUAL_FEATURE_VERSION = 1
DEFAULT_SETTINGS = {
    'visual_change_threshold': .62,
    'background_change_threshold': .53,
    'dialogue_gap_seconds': 1.25,
    'temporal_gap_seconds': 1.5,
    'reverse_shot_lookahead': 4,
    'short_transition_seconds': 6.0,
    'feature_sample_interval': 8.0,
}


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _settings(settings: dict | None) -> dict:
    result = {**DEFAULT_SETTINGS, **(settings or {})}
    for key in DEFAULT_SETTINGS:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Некорректная настройка детектора сцен: {key}')
    result['reverse_shot_lookahead'] = int(result['reverse_shot_lookahead'])
    return result


def _shots(shots: list[dict], duration: float) -> list[dict]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Некорректная длительность исходного видео')
    result = []
    for index, shot in enumerate(shots):
        start, end = float(shot['start']), float(shot['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end > duration + .001 or end <= start:
            raise ValueError('Некорректный исходный shot')
        if result and start < result[-1]['end'] - .001:
            raise ValueError('Исходные shots пересекаются или не отсортированы')
        result.append({**shot, 'id': str(shot.get('id', f'shot_{index:04d}')),
                       'start': start, 'end': min(end, duration)})
    if len({s['id'] for s in result}) != len(result):
        raise ValueError('Исходные shots содержат повторяющиеся id')
    return result or [{'id': 'shot_0000', 'start': 0.0, 'end': duration}]


def _feature_map(shots: list[dict], supplied) -> dict[str, dict]:
    if isinstance(supplied, list):
        supplied = {str(f.get('shot_id', f.get('id'))): f for f in supplied}
    supplied = supplied or {}
    keys = ('location', 'background', 'characters', 'character_state', 'state_transition',
            'action_transition', 'audio_state', 'music_state', 'descriptor', 'reliability', 'samples')
    features = {}
    for shot in shots:
        feature = {k: shot[k] for k in keys if k in shot}
        feature.update(shot.get('features') or shot.get('visual_features') or {})
        feature.update(supplied.get(shot['id'], {}))
        features[shot['id']] = feature
    return features


def _distance(left: dict, right: dict) -> float | None:
    """Border histograms tolerate foreground faces better than a whole frame."""
    a, b = left.get('descriptor'), right.get('descriptor')
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    ha, hb = a.get('histogram', []), b.get('histogram', [])
    sa, sb = a.get('spatial', []), b.get('spatial', [])
    if not ha or len(ha) != len(hb) or not sa or len(sa) != len(sb):
        return None
    histogram = sum(abs(float(x) - float(y)) for x, y in zip(ha, hb)) / 2
    spatial = sum(abs(float(x) - float(y)) for x, y in zip(sa, sb)) / len(sa)
    return min(1.0, max(0.0, .7 * histogram + .3 * spatial))


def _observed(feature: dict) -> bool:
    return bool(feature.get('location') is not None or feature.get('background') is not None
                or (feature.get('descriptor') and float(feature.get('reliability', 0)) >= .3))


def _related(left: dict, right: dict, threshold: float) -> bool:
    for key in ('location', 'background'):
        if left.get(key) is not None and right.get(key) is not None:
            return left[key] == right[key]
    distance = _distance(left, right)
    return distance is not None and distance < threshold


def _speech_signal(time: float, transcript: dict, gap_threshold: float) -> dict:
    spans = transcript.get('words') or transcript.get('segments') or []
    before, after, crossing = None, None, False
    for span in spans:
        start, end = float(span['start']), float(span['end'])
        if start < time < end:
            crossing = True
        if end <= time and (before is None or end > before):
            before = end
        if start >= time and (after is None or start < after):
            after = start
    gap = 0.0 if crossing or before is None or after is None else max(0.0, after - before)
    return {'speech_gap': round(gap, 6), 'speech_crosses_boundary': crossing,
            'dialogue_break': gap >= gap_threshold,
            'new_dialogue': gap >= gap_threshold and after is not None and after - time <= 1.5}


def _audio_state(feature: dict, audio_features, shot: dict):
    if 'audio_state' in feature or 'music_state' in feature:
        return feature.get('audio_state', feature.get('music_state'))
    if isinstance(audio_features, dict):
        entry = audio_features.get(shot['id'])
        return entry.get('state', entry.get('audio_state')) if isinstance(entry, dict) else entry
    for entry in audio_features or []:
        if entry['start'] <= (shot['start'] + shot['end']) / 2 < entry['end']:
            return entry.get('state', entry.get('audio_state'))
    return None


def detect_semantic_scenes(shots: list[dict], transcript: dict, duration: float, *,
                           visual_features=None, audio_features=None, settings: dict | None = None) -> list[dict]:
    """Pure grouping: outputs only source boundaries, never generated timestamps.

    Optional shot evidence can contain verified ``location``, ``background``,
    ``characters`` and ``character_state`` labels. Production callers should use
    :func:`scene_checkpoint`, which always obtains real image descriptors first.
    Camera recurrence within the current scene suppresses shot/reverse-shot
    fragmentation. A verified location/state transition overrides recurrence.
    """
    config = _settings(settings)
    source_shots = _shots(shots, float(duration))
    features = _feature_map(source_shots, visual_features)
    decisions = []
    groups = []
    group_start = 0
    boundary = {'reasons': ['source_start'], 'confidence': 1.0, 'uncertain': False}

    def close(last: int):
        group = source_shots[group_start:last]
        group_ids = {s['id'] for s in group}
        group_decisions = [d for d in decisions if d['right_shot_id'] in group_ids]
        observed = sum(_observed(features[s['id']]) for s in group)
        coverage = observed / len(group)
        ambiguous = any(d['uncertain'] and not d['accepted'] for d in group_decisions)
        uncertain = boundary['uncertain'] or coverage < .75 or ambiguous
        confidence = min(boundary['confidence'], .94 if coverage >= .75 else .55)
        if ambiguous:
            confidence = min(confidence, .74)
        uncertainty_reasons = (['weak_visual_evidence'] if coverage < .75 else [])
        if ambiguous:
            uncertainty_reasons.append('ambiguous_internal_boundary')
        if boundary['uncertain']:
            uncertainty_reasons.append('unverified_scene_boundary')
        groups.append({'id': f'scene_{len(groups):04d}', 'start': group[0]['start'],
                       'end': group[-1]['end'], 'shot_ids': [s['id'] for s in group],
                       'boundary_reason': list(boundary['reasons']), 'confidence': round(confidence, 4),
                       'uncertain': uncertain,
                       'evidence': {'algorithm': 'local_visual_continuity',
                                    'detector_version': SCENE_DETECTOR_VERSION,
                                    'grouping_version': SCENE_GROUPING_VERSION,
                                    'visual_coverage': round(coverage, 4),
                                    'uncertainty_reasons': uncertainty_reasons,
                                    'sampled_times': sorted({float(sample['time']) for s in group
                                        for sample in features[s['id']].get('samples', []) if 'time' in sample}),
                                    'boundary_decisions': group_decisions}})

    for index in range(1, len(source_shots)):
        previous, current = source_shots[index - 1], source_shots[index]
        left, right = features[previous['id']], features[current['id']]
        signal = _speech_signal(current['start'], transcript, config['dialogue_gap_seconds'])
        reasons = []
        location_change = (left.get('location') is not None and right.get('location') is not None
                           and left['location'] != right['location'])
        location_same = (left.get('location') is not None and right.get('location') is not None
                         and left['location'] == right['location'])
        background_change = (left.get('background') is not None and right.get('background') is not None
                             and left['background'] != right['background'])
        characters_left, characters_right = set(left.get('characters') or []), set(right.get('characters') or [])
        shared_characters = bool(characters_left & characters_right)
        character_change = bool(characters_left and characters_right and not shared_characters)
        state_change = (left.get('character_state') is not None and right.get('character_state') is not None
                        and left['character_state'] != right['character_state'])
        explicit_transition = bool(right.get('state_transition') or right.get('action_transition'))
        visual_distance = _distance(left, right)
        visual_strong = (visual_distance is not None and visual_distance >= config['visual_change_threshold']
                         and min(float(left.get('reliability', 0)), float(right.get('reliability', 0))) >= .3)
        recent = source_shots[max(group_start, index - 12):index]
        history_match = any(_related(features[s['id']], right, config['background_change_threshold']) for s in recent)
        lookahead = source_shots[index + 1:index + 1 + config['reverse_shot_lookahead']]
        return_to_context = any(any(_related(features[p['id']], features[n['id']], config['background_change_threshold'])
                                     for p in recent) for n in lookahead)
        stable_samples = right.get('samples', [])
        stable_shot = (current['end'] - current['start'] > config['short_transition_seconds']
                       and len(stable_samples) >= 2
                       and all((_distance(right, sample) or 0) < config['background_change_threshold']
                               for sample in stable_samples))
        persistent_novelty = (bool(lookahead) or stable_shot) and not return_to_context and not history_match
        temporal_gap = max(0.0, current['start'] - previous['end'])
        audio_left, audio_right = _audio_state(left, audio_features, previous), _audio_state(right, audio_features, current)
        audio_change = audio_left is not None and audio_right is not None and audio_left != audio_right
        local = [s for s in source_shots if abs(s['start'] - current['start']) <= 4]
        shot_density = len(local) / 8.0
        short_insert = (current['end'] - current['start'] <= config['short_transition_seconds']
                        and index + 1 < len(source_shots) and visual_strong
                        and (_distance(right, features[source_shots[index + 1]['id']]) or 0) >= config['visual_change_threshold'])

        cut, confidence, uncertain = False, .86, False
        if location_change:
            cut, confidence = True, .97
            reasons.append('location_change')
        elif state_change or explicit_transition:
            cut, confidence = True, .93
            reasons.append('physical_state_transition')
        elif temporal_gap >= config['temporal_gap_seconds']:
            cut, confidence, uncertain = True, .72, True
            reasons.append('temporal_discontinuity')
        elif (background_change and not location_same and not history_match and not return_to_context
              and (signal['dialogue_break'] or character_change or audio_change)):
            cut, confidence = True, .89
            reasons.append('background_change')
        elif visual_strong and not location_same and not history_match and not return_to_context:
            if persistent_novelty or signal['dialogue_break'] or audio_change or character_change:
                cut, confidence, uncertain = True, .78, True
                reasons.append('visual_context_change')
        elif short_insert and not location_same and not shared_characters and signal['dialogue_break']:
            # Preserve a short isolated transition instead of smoothing it out
            # as noise, but label the visual-only interpretation for recovery.
            cut, confidence, uncertain = True, .71, True
            reasons.append('short_visual_transition')

        if cut:
            if signal['dialogue_break']:
                reasons.append('dialogue_break')
            if signal['new_dialogue']:
                reasons.append('new_dialogue')
            if audio_change:
                reasons.append('audio_state_change')
            if character_change:
                reasons.append('character_change')
        else:
            if history_match or return_to_context or location_same:
                reasons.append('camera_or_background_continuity')
            else:
                reasons.append('insufficient_boundary_evidence')
                uncertain = True
                confidence = .55
        decision = {'time': current['start'], 'left_shot_id': previous['id'], 'right_shot_id': current['id'],
                    'accepted': cut, 'reasons': reasons, 'confidence': round(confidence, 4), 'uncertain': uncertain,
                    'signals': {**signal, 'visual_distance': round(visual_distance, 4) if visual_distance is not None else None,
                                'location_change': location_change, 'background_change': background_change,
                                'character_change': character_change, 'shared_characters': shared_characters,
                                'physical_state_change': state_change or explicit_transition,
                                'audio_state_change': audio_change, 'temporal_gap': round(temporal_gap, 6),
                                'shot_density': round(shot_density, 4), 'history_match': history_match,
                                'return_to_context': return_to_context, 'persistent_novelty': persistent_novelty,
                                'stable_shot_samples': stable_shot,
                                'short_insert': short_insert}}
        decisions.append(decision)
        if cut:
            close(index)
            group_start = index
            boundary = {'reasons': reasons, 'confidence': confidence, 'uncertain': uncertain}
    close(len(source_shots))
    return _word_safe_scene_boundaries(groups, transcript)


def _word_safe_scene_boundaries(scenes: list[dict], transcript: dict) -> list[dict]:
    """Move common scene edges jointly; preserve raw shot evidence separately.

    Joint assignment prevents two transitions inside one word from collapsing
    a short scene to zero duration. A large adjustment is flagged for recovery.
    If an indivisible ASR word covers an entire chain, safe scene subdivision is
    impossible: keep its candidate transitions in evidence and merge the chain.
    """
    intervals = []
    for word in sorted(transcript.get('words', []), key=lambda w: float(w['start'])):
        start, end = float(word['start']), float(word['end'])
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        if intervals and start < intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else:
            intervals.append((start, end))

    def safe(value):
        return not any(start < value < end for start, end in intervals)

    for scene in scenes:
        scene['evidence'].update({'raw_start': scene['start'], 'raw_end': scene['end'],
                                  'raw_boundary_time': scene['start']})
    result = []
    offset = 0
    while offset < len(scenes):
        stop = offset + 1
        while stop < len(scenes) and abs(scenes[stop - 1]['end'] - scenes[stop]['start']) < .000001:
            stop += 1
        chain = scenes[offset:stop]
        raw = [s['start'] for s in chain[1:]]
        if not raw or all(safe(time) for time in raw):
            result.extend(chain)
            offset = stop
            continue
        first, last = chain[0]['start'], chain[-1]['end']
        candidates = sorted({time for start, end in intervals for time in (start, end)
                             if first < time < last and safe(time)}
                            | {time for time in raw if safe(time)})
        if len(candidates) < len(raw):
            merged = chain[0]
            evidence = [{'scene_id': s['id'], 'raw_start': s['start'], 'raw_end': s['end'],
                         'shot_ids': s['shot_ids'], 'boundary_reason': s['boundary_reason']}
                        for s in chain]
            merged['end'] = last
            merged['shot_ids'] = [shot_id for s in chain for shot_id in s['shot_ids']]
            merged['uncertain'] = True
            merged['confidence'] = min(merged['confidence'], .5)
            merged['evidence']['raw_end'] = last
            merged['evidence']['unsplittable_scene_candidates'] = evidence
            merged['evidence']['uncertainty_reasons'].append('no_word_safe_scene_partition')
            merged['evidence']['boundary_decisions'] = [d for s in chain for d in s['evidence']['boundary_decisions']]
            merged['evidence']['sampled_times'] = sorted({t for s in chain for t in s['evidence']['sampled_times']})
            result.append(merged)
            offset = stop
            continue
        # Dynamic programming with prefix minima: O(scenes * word edges), not
        # O(word edges squared). Every assigned boundary must increase strictly.
        costs = [abs(time - raw[0]) for time in candidates]
        parents = [[-1] * len(candidates)]
        for boundary in raw[1:]:
            next_costs = [math.inf] * len(candidates)
            parent = [-1] * len(candidates)
            best, best_index = math.inf, -1
            for index, time in enumerate(candidates):
                if index > 0 and costs[index - 1] < best:
                    best, best_index = costs[index - 1], index - 1
                if best_index >= 0:
                    next_costs[index] = best + abs(time - boundary)
                    parent[index] = best_index
            costs = next_costs
            parents.append(parent)
        position = min(range(len(costs)), key=costs.__getitem__)
        assigned = [0.0] * len(raw)
        for index in range(len(raw) - 1, -1, -1):
            assigned[index] = candidates[position]
            position = parents[index][position]
        for index, (original, adjusted) in enumerate(zip(raw, assigned), 1):
            chain[index - 1]['end'] = adjusted
            chain[index]['start'] = adjusted
            if abs(original - adjusted) > .000001:
                large = abs(original - adjusted) > .75
                adjustment = {'raw_time': original, 'time': adjusted,
                              'shift': round(adjusted - original, 6),
                              'reason': 'asr_word_edge', 'uncertain': large}
                chain[index]['evidence']['word_safe_boundary'] = adjustment
                chain[index - 1]['evidence']['end_word_safe_boundary'] = adjustment
                chain[index]['boundary_reason'].append('asr_word_safe_adjustment')
                if large:
                    for scene in chain[index - 1:index + 1]:
                        scene['uncertain'] = True
                        scene['confidence'] = min(scene['confidence'], .6)
                        if 'large_word_safe_boundary_adjustment' not in scene['evidence']['uncertainty_reasons']:
                            scene['evidence']['uncertainty_reasons'].append('large_word_safe_boundary_adjustment')
        result.extend(chain)
        offset = stop
    for index, scene in enumerate(result):
        scene['id'] = f'scene_{index:04d}'
    return result


def analysis_chunks(scene: dict, transcript: dict, target: float = 40) -> list[dict]:
    """A technical size limit within a scene; never creates semantic scenes.

    Prefer an earlier phrase ending, then the start of a crossing word. Only an
    indivisible word longer than the limit may overflow it, explicitly marked.
    """
    start, end = float(scene['start']), float(scene['end'])
    if not math.isfinite(target) or target <= 0 or not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError('Некорректный интервал анализа сцены')
    words = sorted(transcript.get('words', []), key=lambda w: float(w['start']))
    chunks = []
    while start < end - .000001:
        limit = min(end, start + target)
        boundary = limit
        if limit < end:
            phrase_ends = [float(s['end']) for s in transcript.get('segments', [])
                          if max(start + target - 8, start + .000001) <= float(s['end']) <= limit
                          and not any(float(w['start']) < float(s['end']) < float(w['end']) for w in words)]
            if phrase_ends:
                boundary = max(phrase_ends)
            else:
                crossing = [w for w in words if float(w['start']) < boundary < float(w['end'])]
                # ASR timestamps may overlap. Follow the entire connected word
                # interval, rather than moving into another earlier word.
                while crossing:
                    earlier = min(float(w['start']) for w in crossing)
                    if earlier > start:
                        boundary = earlier
                    else:
                        boundary = max(float(w['end']) for w in crossing)
                        while True:
                            overlaps = [w for w in words if float(w['start']) < boundary < float(w['end'])]
                            if not overlaps:
                                break
                            boundary = max(float(w['end']) for w in overlaps)
                        break
                    crossing = [w for w in words if float(w['start']) < boundary < float(w['end'])]
        boundary = min(end, boundary)
        if boundary <= start:
            raise ValueError('Невозможно получить безопасную границу анализа')
        chunks.append({'id': f"{scene['id']}_chunk_{len(chunks):03d}", 'parent_scene_id': scene['id'],
                       'start': start, 'end': boundary, 'technical_chunk': True,
                       'oversize_word': boundary - start > target + .000001})
        start = boundary
    return chunks


def _image_feature(frame: Path) -> dict:
    import numpy as np
    from PIL import Image
    with Image.open(frame) as image:
        rgb = np.asarray(image.convert('RGB').resize((64, 36)), dtype=np.float32) / 255.0
    # Top/sides carry more environment and fewer central faces/subtitles.
    mask = np.zeros(rgb.shape[:2], dtype=bool)
    mask[:9, :] = True
    mask[:28, :13] = True
    mask[:28, -13:] = True
    border = rgb[mask]
    bins = np.minimum((border * 4).astype(int), 3)
    quantized = bins[:, 0] * 16 + bins[:, 1] * 4 + bins[:, 2]
    histogram = np.bincount(quantized, minlength=64).astype(float) / len(border)
    spatial = []
    for y, x in ((0, 0), (0, 22), (0, 43), (12, 0), (12, 51)):
        spatial.extend(rgb[y:y + 9, x:x + 13].mean(axis=(0, 1)).tolist())
    # Blank/black frames cannot confirm a location, even with valid timestamps.
    reliability = min(1.0, float(border.std()) * 4 + float(np.ptp(border.mean(axis=1))) * 2)
    if float(border.max()) < .035:
        reliability = 0.0
    return {'descriptor': {'histogram': [round(float(v), 6) for v in histogram],
                           'spatial': [round(float(v), 6) for v in spatial]},
            'reliability': round(reliability, 4)}


def extract_visual_features(source: Path, shots: list[dict], duration: float, job_dir: Path, cancelled,
                            *, settings: dict | None = None) -> dict[str, dict]:
    """Decode all requested samples in one local FFmpeg pass, recording PTS.

    A filter script avoids Windows command-line length limits on long episodes.
    The sample labels use showinfo's actual PTS, not the requested seek times.
    """
    config = _settings(settings)
    source_shots = _shots(shots, duration)
    if cancelled():
        raise InterruptedError('Обработка отменена')
    directory = job_dir / 'scene-features'
    directory.mkdir(parents=True, exist_ok=True)
    requests = {}
    for shot in source_shots:
        length = shot['end'] - shot['start']
        count = max(3, int(math.ceil(length / config['feature_sample_interval'])))
        requests[shot['id']] = [shot['start'] + length * (i + .5) / count for i in range(count)]
    times = sorted({round(t, 6) for group in requests.values() for t in group})
    # Select the first decoded frame crossing each requested sample time. If
    # two requests map to one decoded frame, both refer to that actual frame.
    expression = '+'.join(f'(gte(t,{t:.6f})*(isnan(prev_selected_t)+lt(prev_selected_t,{t:.6f})))' for t in times)
    script = directory / 'samples.filter'
    script.write_text(f"select='{expression}',scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2,showinfo", encoding='utf-8')
    log = directory / 'extract.log'
    run_process([FFMPEG, '-y', '-hide_banner', '-i', source, '-map', '0:v:0', '-an',
                 '-filter_script:v', script, '-fps_mode', 'vfr', '-threads', '1',
                 '-q:v', '3', directory / 'frame-%06d.jpg'], log, cancelled)
    actual = [float(match.group(1)) for match in re.finditer(r'\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.eE+-]+)', log.read_text('utf-8', errors='replace'))]
    actual = [t for t in actual if math.isfinite(t)]
    if not actual:
        raise ValueError('Детектор сцен не получил исходные видеокадры')
    image_features = []
    for index, timestamp in enumerate(actual):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        frame = directory / f'frame-{index + 1:06d}.jpg'
        if not frame.is_file():
            raise ValueError('FFmpeg не создал визуальный образец сцены')
        image_features.append({**_image_feature(frame), 'time': timestamp,
                               'frame': frame.relative_to(job_dir).as_posix()})
    result = {}
    for shot in source_shots:
        samples = []
        for requested in requests[shot['id']]:
            position = min(bisect.bisect_left(actual, requested - .000001), len(actual) - 1)
            sample = image_features[position]
            # Do not attribute a next-shot frame or audio EOF frame to this shot.
            if shot['start'] <= sample['time'] < shot['end'] and sample['time'] <= duration:
                if not samples or samples[-1]['time'] != sample['time']:
                    samples.append(sample)
        if samples:
            representative = min(samples, key=lambda candidate: sum(_distance(candidate, other) or 0 for other in samples))
            result[shot['id']] = {'shot_id': shot['id'], 'descriptor': representative['descriptor'],
                                 'reliability': sum(s['reliability'] for s in samples) / len(samples),
                                 'samples': samples, 'origin': 'source_frames',
                                 'feature_version': VISUAL_FEATURE_VERSION}
        else:
            result[shot['id']] = {'shot_id': shot['id'], 'samples': [], 'reliability': 0.0,
                                 'origin': 'source_frames', 'warning': 'no_video_frame_in_shot'}
    return result


def _cached(path: Path, metadata: Path, identity):
    if path.is_file() and metadata.is_file():
        try:
            if load_json(metadata) == identity:
                return load_json(path)
        except (OSError, ValueError):
            # A truncated cache is rebuildable; media extraction errors are not.
            pass
    return None


def scene_checkpoint(source: Path, fingerprint: str, duration: float, shots: list[dict], transcript: dict,
                     job_dir: Path, cancelled, *, settings: dict | None = None, audio_features=None,
                     cache_status: dict | None = None) -> list[dict]:
    """Production boundary: real source frames are mandatory, separately cached."""
    if cancelled():
        raise InterruptedError('Обработка отменена')
    source, job_dir = Path(source), Path(job_dir)
    config = _settings(settings)
    stat = source.stat()
    source_identity = {'fingerprint': fingerprint, 'path': str(source.resolve()),
                       'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'duration': duration}
    feature_identity = {'source': source_identity, 'shots': _hash(shots), 'version': VISUAL_FEATURE_VERSION,
                        'sample_interval': config['feature_sample_interval']}
    feature_path, feature_meta = job_dir / 'scene-features.json', job_dir / 'scene-features.meta.json'
    features = _cached(feature_path, feature_meta, feature_identity)
    feature_hit = features is not None
    if not feature_hit:
        features = extract_visual_features(source, shots, duration, job_dir, cancelled, settings=config)
        atomic_json(feature_path, features)
        atomic_json(feature_meta, feature_identity)
    identity = {'source': source_identity, 'features': _hash(features), 'shots': _hash(shots),
                'transcript': _hash({'words': transcript.get('words', []), 'segments': transcript.get('segments', [])}),
                'audio': _hash(audio_features), 'settings': config,
                'detector_version': SCENE_DETECTOR_VERSION, 'grouping_version': SCENE_GROUPING_VERSION}
    path, meta = job_dir / 'scenes.json', job_dir / 'scenes.meta.json'
    scenes = _cached(path, meta, identity)
    scene_hit = scenes is not None
    if not scene_hit:
        scenes = detect_semantic_scenes(shots, transcript, duration, visual_features=features,
                                        audio_features=audio_features, settings=config)
        atomic_json(path, scenes)
        atomic_json(meta, identity)
    if cache_status is not None:
        cache_status.update({'cache_hit': scene_hit, 'visual_cache_hit': feature_hit})
    for scene in scenes:
        scene['evidence']['checkpoint'] = {'visual_origin': 'source_frames', 'identity': _hash(identity)}
    return scenes
