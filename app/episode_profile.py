"""Factual montage pace and source-bounded retention recommendations.

Measured intra-shot optical flow, accepted editing and ASR occupancy are separate.
Neither camera cuts nor optical flow assert that a semantic physical action occurred.
"""
from __future__ import annotations

import copy
import math
import re


EPISODE_PROFILE_VERSION = 2
POSITIVE_KINDS = {'character_reaction', 'emotional_pause', 'comedic_payoff', 'establishing_context',
                  'causal_dialogue', 'response', 'physical_action', 'state_transition'}
EPISODE_PROFILE_POLICY = {
    'classifier': {'speech_high': .55, 'motion_high': .55, 'motion_low': .2},
    'calibration': {'method': 'training_only_grid', 'training_clips': 8, 'holdout_clips': 4,
                    'purpose': 'short_source_clip_pace_not_semantic_action_quality'},
    'pause_minimum_seconds': .2,
    'budget': {'base_fraction': {'dialogue_slow': .27, 'balanced': .34, 'action_dense': .42, 'mixed': .38},
               'minimum_fraction': .18, 'maximum_fraction': .85, 'minimum_multiplier': .78,
               'maximum_multiplier': 1.2, 'dense_story_rate_per_minute': 3.0},
    'scene_settings': {
        'dialogue_slow': {'visual_change_threshold': .54, 'background_change_threshold': .47,
                         'dialogue_gap_seconds': .85, 'reverse_shot_lookahead': 6, 'feature_sample_interval': 6.0},
        'action_dense': {'visual_change_threshold': .74, 'background_change_threshold': .50,
                        'dialogue_gap_seconds': 1.75, 'reverse_shot_lookahead': 8, 'feature_sample_interval': 2.0},
        'mixed': {'visual_change_threshold': .68, 'background_change_threshold': .50,
                  'dialogue_gap_seconds': 1.15, 'reverse_shot_lookahead': 6, 'feature_sample_interval': 4.0},
        'balanced': {}}}


def _number(value, field, *, minimum=None, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or minimum is not None and value < minimum or maximum is not None and value > maximum):
        raise ValueError(f'Некорректная метрика серии: {field}')
    return float(value)


def _list(value, field):
    if not isinstance(value, list):
        raise ValueError(f'Некорректный список серии: {field}')
    return value


def _span(record, duration, field):
    if not isinstance(record, dict) or 'start' not in record or 'end' not in record:
        raise ValueError(f'Некорректный исходный интервал: {field}')
    start, end = _number(record['start'], field+'.start'), _number(record['end'], field+'.end')
    if end < start:
        raise ValueError(f'Обратный исходный интервал: {field}')
    left, right = max(0.0, start), min(duration, end)
    return (left, right) if right > left else None


def _spans(records, duration, field):
    return [span for index, record in enumerate(_list(records, field))
            if (span := _span(record, duration, f'{field}[{index}]')) is not None]


def _union(spans):
    result = []
    for left, right in sorted(set(spans)):
        if result and left <= result[-1][1]:
            result[-1] = (result[-1][0], max(right, result[-1][1]))
        else:
            result.append((left, right))
    return result


def _length(spans):
    return sum(right-left for left, right in _union(spans))


def _overlap(span, spans):
    return sum(max(0.0, min(span[1], right)-max(span[0], left)) for left, right in spans)


def _shot_records(shots, duration):
    shots = _list(shots, 'shots')
    ordered = []
    for shot in shots:
        if not isinstance(shot, dict) or 'start' not in shot:
            raise ValueError('Некорректный исходный shot')
        ordered.append((_number(shot['start'], 'shot.start'), shot))
    ordered.sort(key=lambda item: item[0])
    records = []
    for index, (start, shot) in enumerate(ordered):
        end = shot.get('end', ordered[index+1][0] if index+1 < len(ordered) else duration)
        span = _span({'start': start, 'end': end}, duration, 'shot')
        if shot.get('scene_score') is not None:
            _number(shot['scene_score'], 'shot.scene_score', minimum=0, maximum=1)
        if span:
            records.append((span, shot))
    return records


def _candidate_records(candidates, duration):
    result = []
    for candidate in _list(candidates, 'raw_candidates'):
        if isinstance(candidate, dict):
            timestamp = next((candidate[key] for key in ('time', 'start', 'pts_time', 'source_time') if key in candidate), None)
            score = candidate.get('scene_score', candidate.get('score'))
        elif isinstance(candidate, (tuple, list)) and len(candidate) == 2:
            timestamp, score = candidate
        else:
            raise ValueError('Некорректный исходный кандидат shot')
        timestamp = _number(timestamp, 'candidate.time')
        score = _number(score, 'candidate.score', minimum=0, maximum=1) if score is not None else None
        if 0 < timestamp < duration:
            result.append((timestamp, score))
    unique = {}
    for timestamp, score in result:
        if timestamp not in unique or score is not None and (unique[timestamp] is None or score > unique[timestamp]):
            unique[timestamp] = score
    return sorted(unique.items())


def _confirmed(event):
    if type(event.get('uncertain', False)) is not bool:
        raise ValueError('Некорректный uncertain события')
    for field in ('confidence', 'global_confidence', 'semantic_confidence', 'visual_confidence', 'context_confidence',
                  'understanding_confidence', 'selection_confidence'):
        if event.get(field) is not None:
            _number(event[field], field, minimum=0, maximum=1)
    if (event.get('uncertain') or event.get('selection_uncertain') or event.get('analysis_unresolved')
            or event.get('source_role_unresolved') or event.get('understanding_status') in ('unresolved', 'needs_review', 'recovery_required')):
        return False
    return (event.get('selection_status') == 'accepted'
            and all(type(event.get(k)) in (int, float) and .9 <= event[k] <= 1
                    for k in ('understanding_confidence', 'selection_confidence')))


def _source_text(transcript, start, end):
    return ' '.join(str(w.get('text', '')) for w in (transcript.get('words') or transcript.get('segments', []))
                    if start <= w['start'] and w['end'] <= end)


def _tokens(text):
    return re.findall(r'\w+', text.casefold().replace('ё', 'е'))


def _quote_in(quote, text):
    q, t = _tokens(quote), _tokens(text)
    return bool(q) and any(t[i:i+len(q)] == q for i in range(len(t)-len(q)+1))


def _positive_evidence(record):
    evidence = record.get('evidence')
    return (record.get('kind') in POSITIVE_KINDS and isinstance(evidence, str) and len(evidence.strip()) >= 12
            and evidence.strip().casefold() not in {'generic atmosphere', 'emotional atmosphere',
                'атмосфера сцены', 'эмоциональная атмосфера', 'нужен контекст'})


def _event_metrics(events, duration, speech, transcript):
    actions, causal, silent, bridges, stories, proposed_stories, positive = {}, {}, set(), set(), {}, set(), []
    unknown_actions = set()
    for event in _list(events, 'events'):
        span = _span(event, duration, 'event')
        if span is None:
            continue
        key = (str(event.get('id', '')), *span)
        importance = _number(event.get('importance', 3), 'event.importance', minimum=1, maximum=5)
        if type(event.get('narrative_bridge', False)) is not bool:
            raise ValueError('Некорректный narrative_bridge события')
        confirmed = _confirmed(event)
        if event.get('kind', 'story') == 'story':
            proposed_stories.add(key)
        known = {}
        for unit in _list(event.get('units', []), 'event.units'):
            unit_span = _span(unit, duration, 'event.unit')
            if not isinstance(unit.get('id'), str):
                raise ValueError('Некорректный id CURRENT unit')
            if (unit_span is not None and span[0] <= unit['start'] < unit['end'] <= span[1]):
                known[unit['id']] = unit_span
        action_ids = _list(event.get('action_units', []), 'event.action_units')
        if any(not isinstance(unit_id, str) for unit_id in action_ids):
            raise ValueError('Некорректный список CURRENT action IDs')
        for unit_id in set(action_ids):
            if unit_id not in known:
                unknown_actions.add((key, unit_id))
        if not confirmed:
            continue
        from app.source_roles import confirmed_exclusions
        from app.selection_gate import _anchored
        selected = _spans(event.get('selected_ranges', []), duration, 'event.selected_ranges')
        exclusions = [(r['start'], r['end']) for r in confirmed_exclusions(event)]
        event_positive = []
        for record in _list(event.get('unit_evidence', []), 'event.unit_evidence'):
            if not isinstance(record, dict):
                raise ValueError('Некорректное CURRENT unit evidence')
            ident = record.get('unit')
            confidence = record.get('confidence')
            if confidence is not None:
                _number(confidence, 'unit_evidence.confidence', minimum=0, maximum=1)
            indices, quote = record.get('frame_indices', []), record.get('speech_quote', '')
            if (ident not in known or record.get('decision') != 'keep'
                    or not _positive_evidence(record)
                    or confidence is None or confidence < .9
                    or not isinstance(indices, list) or any(type(i) is not int or i <= 0 for i in indices)
                    or not isinstance(quote, str) or not (indices or quote.strip())):
                continue
            if record['kind'] in ('physical_action', 'state_transition', 'character_reaction', 'emotional_pause', 'establishing_context') and not indices:
                continue
            if quote.strip():
                if not _quote_in(quote, _source_text(transcript, *known[ident])):
                    continue
            unit_span = known[ident]
            view = _span({'start': record.get('view_start', unit_span[0]),
                          'end': record.get('view_end', unit_span[1])}, duration, 'unit_evidence.view')
            if view is None or not _anchored(record, {'text': _source_text(transcript, *unit_span)},
                    max(unit_span[0], view[0], span[0]), min(unit_span[1], view[1], span[1])):
                continue
            pieces = [(max(a, unit_span[0], view[0], span[0]), min(b, unit_span[1], view[1], span[1]))
                      for a, b in selected if a < min(unit_span[1], view[1], span[1])
                      and b > max(unit_span[0], view[0], span[0])]
            for left, right in exclusions:
                pieces = [(a, min(b, left)) for a, b in pieces if a < left] + [
                           (max(a, right), b) for a, b in pieces if b > right]
            pieces = _union([(a, b) for a, b in pieces if a < b])
            if not pieces:
                continue
            if quote.strip() and not any(_quote_in(quote, _source_text(transcript, a, b)) for a, b in pieces):
                continue
            # _anchored requires a source-derived board count, unique in-bound
            # indices and one finite CURRENT timestamp per cited frame. Also
            # require an actual cited frame in the retained source intersection.
            if indices and not any(a <= t < b for a, b in pieces for t in record['frame_times']):
                continue
            evidence_key = (*key, ident)
            event_positive.extend(pieces)
            if record['kind'] in ('causal_dialogue', 'response', 'physical_action', 'state_transition'):
                causal.setdefault(evidence_key, []).extend(pieces)
            if ident in action_ids and record['kind'] in ('physical_action', 'state_transition') and indices:
                actions.setdefault(evidence_key, []).extend(pieces)
                if sum(_overlap(piece, speech) for piece in pieces) <= .05:
                    silent.add(evidence_key)
        if event_positive:
            positive.extend(event_positive)
            if event.get('kind', 'story') == 'story':
                stories[key] = importance
            if event.get('narrative_bridge') and any(action_key[:3] == key for action_key in causal):
                bridges.add(key)
    duration_actions = _length([piece for pieces in actions.values() for piece in pieces])
    positive_duration = _length(positive)
    return {'story_events': len(stories), 'confirmed_story_events': len(stories),
            'proposed_story_events': len(proposed_stories),
            'importance_mean': sum(stories.values())/len(stories) if stories else 0.0,
            'high_importance_ratio': sum(value >= 4 for value in stories.values())/len(stories) if stories else 0.0,
            'action_units': len(actions), 'action_duration': duration_actions,
            'action_density': duration_actions/duration if duration else 0.0,
            'silent_action_units': len(silent), 'narrative_bridges': len(bridges),
            'unknown_action_ids': len(unknown_actions), 'causal_units': len(causal),
            'positive_story_duration': positive_duration,
            'story_density_score': positive_duration/duration if duration else 0.0}


def _motion_metrics(perception):
    unavailable = {'motion_density': 0.0, 'physical_motion_density': None, 'motion_score': None,
                   'motion_evidence': 'unavailable', 'motion_available': False, 'motion_reliable': False,
                   'motion_measurement_coverage': 0.0, 'global_camera_motion_density': None,
                   'residual_motion_density': None}
    if perception is None:
        return unavailable
    if not isinstance(perception, dict) or not isinstance(perception.get('motion', {}), dict):
        raise ValueError('Некорректные измерения perception.motion')
    motion = perception.get('motion', {})
    if motion.get('evidence') != 'source_optical_flow':
        return unavailable
    for flag in ('available', 'adequate_coverage'):
        if flag in motion and type(motion[flag]) is not bool:
            raise ValueError('Некорректный флаг source motion: '+flag)
    density = motion.get('physical_motion_density')
    if density is None or motion.get('available') is not True:
        return unavailable
    density = _number(density, 'physical_motion_density', minimum=0, maximum=1)
    coverage = _number(motion.get('measurement_coverage', 0), 'motion_measurement_coverage', minimum=0, maximum=1)
    available = motion.get('available') is True
    reliable = available and coverage >= .35 and motion.get('adequate_coverage') is True
    result = {**unavailable, 'motion_density': density, 'physical_motion_density': density,
              'motion_score': density, 'motion_evidence': 'source_optical_flow',
              'motion_available': available, 'motion_reliable': reliable, 'motion_measurement_coverage': coverage}
    for key in ('global_camera_motion_density', 'residual_motion_density'):
        if motion.get(key) is not None:
            result[key] = _number(motion[key], key, minimum=0, maximum=1)
    return result


def build_episode_profile(duration, transcript, shots, scenes=None, events=None, *, raw_candidates=None, perception=None):
    """Derive initial/refined metrics without mutating evidence or invoking models."""
    duration = _number(duration, 'source_duration', minimum=0)
    if not isinstance(transcript, dict):
        raise ValueError('Некорректный transcript серии')
    words = _spans(transcript.get('words', []), duration, 'words')
    utterances = _spans(transcript.get('segments', []), duration, 'segments')
    speech = _union(words or utterances)
    speech_duration = _length(speech)
    pauses, previous = [], 0.0
    for start, end in speech:
        if start-previous >= EPISODE_PROFILE_POLICY['pause_minimum_seconds']:
            pauses.append(start-previous)
        previous = end
    if duration-previous >= EPISODE_PROFILE_POLICY['pause_minimum_seconds']:
        pauses.append(duration-previous)
    shot_records = _shot_records(shots, duration)
    shot_count = len({span[0] for span, _ in shot_records})
    candidates = _candidate_records(raw_candidates, duration) if raw_candidates is not None else [
        (span[0], _number(shot['scene_score'], 'shot.scene_score', minimum=0, maximum=1) if shot.get('scene_score') is not None else None)
        for span, shot in shot_records if span[0] > 0]
    minutes = duration/60
    rate = lambda count: count/minutes if minutes else 0.0
    # Retain legacy field validation but never reinterpret unknown shot scalars
    # or camera scene-change scores as measured intra-shot physical activity.
    for span, shot in shot_records:
        features = shot.get('features', {})
        if not isinstance(features, dict):
            raise ValueError('Некорректные признаки shot')
        motion = next((container[key] for container in (shot, features) for key in ('motion_score', 'motion_density')
                       if container.get(key) is not None), None)
        if motion is not None:
            _number(motion, 'shot.motion', minimum=0, maximum=1)
    motion = _motion_metrics(perception)
    scene_spans = _spans([] if scenes is None else scenes, duration, 'scenes')
    scene_spans = list(set(scene_spans))
    metrics = {'speech_density': speech_duration/duration if duration else 0.0,
        'speech_duration': speech_duration, 'speech_timing_source': 'words' if words else 'segments' if utterances else 'unavailable',
        'average_utterance_duration': sum(end-start for start, end in set(utterances))/len(set(utterances)) if utterances else 0.0,
        'average_pause_duration': sum(pauses)/len(pauses) if pauses else 0.0, 'pause_count': len(pauses),
        'pause_duration': duration-speech_duration, 'shots': shot_count, 'shots_per_minute': rate(shot_count),
        'raw_candidates': len(candidates), 'raw_candidates_per_minute': rate(len(candidates)),
        'raw_candidate_evidence': 'raw_candidates' if raw_candidates is not None else 'accepted_cut_fallback',
        'accepted_cuts': len({span[0] for span, _ in shot_records if span[0] > 0}),
        'accepted_cuts_per_minute': rate(len({span[0] for span, _ in shot_records if span[0] > 0})),
        'accepted_editing_density': min(1.0, len({span[0] for span, _ in shot_records if span[0] > 0})/duration) if duration else 0.0,
        **motion,
        'semantic_scenes': len(scene_spans), 'semantic_scenes_per_minute': rate(len(scene_spans)),
        'average_scene_duration': sum(end-start for start, end in scene_spans)/len(scene_spans) if scene_spans else 0.0,
        **_event_metrics([] if events is None else events, duration, speech, transcript)}
    thresholds = EPISODE_PROFILE_POLICY['classifier']
    active = duration > 0 and metrics['motion_reliable'] and metrics['motion_score'] >= thresholds['motion_high']
    if active and metrics['speech_density'] >= thresholds['speech_high']:
        kind, reasons = 'mixed', ['speech_and_visual_activity']
    elif active:
        kind, reasons = 'action_dense', ['dense_visual_activity']
    elif (metrics['motion_reliable'] and metrics['motion_score'] <= thresholds['motion_low']
          and metrics['speech_density'] >= thresholds['speech_high']):
        kind, reasons = 'dialogue_slow', ['speech_dominates', 'low_visual_activity']
    else:
        kind, reasons = 'balanced', ['moderate_or_incomplete_pace_evidence']
    if not metrics['motion_available']:
        reasons.append('motion_measurement_unavailable')
    elif not metrics['motion_reliable']:
        reasons.append('insufficient_intra_shot_motion_coverage')
    if metrics['action_units']:
        reasons.append('confirmed_current_actions')
    if metrics['narrative_bridges']:
        reasons.append('confirmed_narrative_bridges')
    metrics.update(speech_score=metrics['speech_density'], editing_score=metrics['accepted_editing_density'],
                   action_score=metrics['action_density'], causal_units_per_minute=rate(metrics['causal_units']))
    scores = {k: metrics[k] for k in ('speech_score', 'editing_score', 'motion_score', 'action_score', 'story_density_score')}
    evidence_count = sum((bool(speech), bool(shot_count), metrics['motion_reliable'], scenes is not None,
                          bool(metrics['confirmed_story_events'])))
    result = {'version': EPISODE_PROFILE_VERSION, 'policy': copy.deepcopy(EPISODE_PROFILE_POLICY),
              'profile': kind, 'confidence': (min(.95 if metrics['motion_reliable'] else .5,
                                               .35 + .12*evidence_count) if duration else 0.0),
              'duration': duration, 'source_duration': duration,
              'phase': 'refined' if events is not None else 'initial', 'reason': reasons,
              'metrics': metrics, 'scores': scores, **scores,
              'perception_identity': ({k: copy.deepcopy(perception.get(k)) for k in ('version', 'signature', 'source')}
                                      if isinstance(perception, dict) else None),
              'limitations': ['optical_flow_includes_camera_motion', 'pace_category_is_not_semantic_action',
                  'speech_score_is_asr_occupancy_not_acoustic_vad', 'action_confidence_is_model_self_reported',
                  '12_short_source_clips_not_episode_semantic_benchmark']}
    result['planner_budget'] = adaptive_retention_budget(result)
    return result


def adaptive_retention_budget(profile):
    """A soft story-aware range; source evidence can exceed its preferred target."""
    if not isinstance(profile, dict) or profile.get('profile') not in EPISODE_PROFILE_POLICY['budget']['base_fraction']:
        raise ValueError('Неизвестный монтажный профиль')
    duration = _number(profile.get('source_duration', profile.get('duration')), 'source_duration', minimum=0)
    metrics = profile.get('metrics', {})
    if not isinstance(metrics, dict):
        raise ValueError('Некорректные метрики профиля')
    values = {key: _number(metrics.get(key, 0), key, minimum=0) for key in
              ('speech_density', 'action_density', 'high_importance_ratio', 'importance_mean', 'story_events',
               'narrative_bridges', 'silent_action_units', 'action_duration')}
    for key in ('speech_density', 'action_density', 'high_importance_ratio'):
        if values[key] > 1:
            raise ValueError(f'Некорректная доля {key}')
    if values['importance_mean'] > 5 or values['action_duration'] > duration:
        raise ValueError('Метрика профиля превышает исходный материал')
    for key in ('story_events', 'narrative_bridges', 'silent_action_units'):
        if not values[key].is_integer():
            raise ValueError(f'Некорректное число {key}')
    policy = EPISODE_PROFILE_POLICY['budget']
    story_rate = values['story_events']/(duration/60) if duration else 0.0
    narrative_density = min(1.0, story_rate/policy['dense_story_rate_per_minute'])
    bridge_ratio = min(1.0, values['narrative_bridges']/max(1, values['story_events']))
    silent_rate = min(1.0, values['silent_action_units']/max(1, duration/60)/3)
    fraction = (policy['base_fraction'][profile['profile']] + .10*narrative_density
                + .08*values['high_importance_ratio'] + .03*values['importance_mean']/5
                + .03*values['speech_density'] + .10*values['action_density'] + .06*bridge_ratio + .03*silent_rate)
    fraction = min(policy['maximum_fraction'], max(policy['minimum_fraction'], fraction))
    optimal = min(duration, max(duration*fraction, values['action_duration']))
    reasons = [profile['profile'], 'high_story_density' if narrative_density >= .5 else 'source_scaled_story_density']
    if values['high_importance_ratio'] >= .5:
        reasons.append('high_importance')
    if values['narrative_bridges']:
        reasons.append('narrative_bridges')
    if values['action_duration']:
        reasons.append('confirmed_action_context')
    return {'min': optimal*policy['minimum_multiplier'], 'optimal': optimal,
            'max': min(duration, optimal*policy['maximum_multiplier']), 'reason': '/'.join(reasons),
            'source_duration': duration, 'retention_fraction': optimal/duration if duration else 0.0,
            'policy_version': EPISODE_PROFILE_VERSION}


def scene_settings(profile):
    """Adapt camera/continuity handling; location/state evidence still overrides it."""
    kind = profile.get('profile') if isinstance(profile, dict) else profile
    if kind not in EPISODE_PROFILE_POLICY['scene_settings']:
        raise ValueError('Неизвестный монтажный профиль')
    return copy.deepcopy(EPISODE_PROFILE_POLICY['scene_settings'][kind])
