"""Factual montage pace and source-bounded retention recommendations.

Visual scene-change scores are a motion proxy, explicitly labelled as such.
Silence and camera density alone never assert that a physical action occurred.
"""
from __future__ import annotations

import copy
import math


EPISODE_PROFILE_VERSION = 1
EPISODE_PROFILE_POLICY = {
    'classifier': {'speech_high': .6, 'speech_action_mix': .55, 'fast_shots_per_minute': 35,
                   'motion_high': .45, 'action_high': .18, 'minimum_fast_shots': 4},
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
    for field in ('confidence', 'global_confidence', 'semantic_confidence', 'visual_confidence', 'context_confidence'):
        if event.get(field) is not None:
            _number(event[field], field, minimum=0, maximum=1)
    if event.get('uncertain') or event.get('understanding_status') in ('unresolved', 'needs_review', 'recovery_required'):
        return False
    if event.get('understanding_status') == 'accepted' or event.get('confidence_status') == 'accepted':
        return True
    if event.get('global_confidence') is not None:
        return event['global_confidence'] >= .85
    dimensions = [event.get(field) for field in ('semantic_confidence', 'visual_confidence', 'context_confidence')]
    if all(value is not None for value in dimensions):
        return min(dimensions) >= .85
    return event.get('confidence', 0) is not None and event.get('confidence', 0) >= .85


def _event_metrics(events, duration, speech):
    actions, silent, bridges, stories, confirmed_stories, unknown_actions = {}, set(), set(), {}, set(), 0
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
            stories[key] = importance
            if confirmed:
                confirmed_stories.add(key)
        known = {}
        for unit in _list(event.get('units', []), 'event.units'):
            unit_span = _span(unit, duration, 'event.unit')
            if not isinstance(unit.get('id'), str):
                raise ValueError('Некорректный id CURRENT unit')
            if unit_span is not None and span[0] <= unit_span[0] < unit_span[1] <= span[1]:
                known[unit['id']] = unit_span
        action_ids = _list(event.get('action_units', []), 'event.action_units')
        if any(not isinstance(unit_id, str) for unit_id in action_ids):
            raise ValueError('Некорректный список CURRENT action IDs')
        if not confirmed:
            continue
        if event.get('narrative_bridge'):
            bridges.add(key)
        for unit_id in set(action_ids):
            if unit_id not in known:
                unknown_actions += 1
                continue
            action_key = (unit_id, *known[unit_id])
            actions[action_key] = known[unit_id]
            if _overlap(known[unit_id], speech) <= .05:
                silent.add(action_key)
    duration_actions = _length(list(actions.values()))
    return {'story_events': len(stories), 'confirmed_story_events': len(confirmed_stories),
            'importance_mean': sum(stories.values())/len(stories) if stories else 0.0,
            'high_importance_ratio': sum(value >= 4 for value in stories.values())/len(stories) if stories else 0.0,
            'action_units': len(actions), 'action_duration': duration_actions,
            'action_density': duration_actions/duration if duration else 0.0,
            'silent_action_units': len(silent), 'narrative_bridges': len(bridges),
            'unknown_action_ids': unknown_actions}


def build_episode_profile(duration, transcript, shots, scenes=None, events=None, *, raw_candidates=None):
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
    motions = []
    for span, shot in shot_records:
        features = shot.get('features', {})
        if not isinstance(features, dict):
            raise ValueError('Некорректные признаки shot')
        motion = next((container[key] for container in (shot, features) for key in ('motion_score', 'motion_density')
                       if container.get(key) is not None), None)
        if motion is not None:
            motions.append((_number(motion, 'shot.motion', minimum=0, maximum=1), span[1]-span[0]))
    scores = [score for _, score in candidates if score is not None]
    if motions:
        motion_density = sum(score*weight for score, weight in motions)/sum(weight for _, weight in motions)
        motion_evidence = 'supplied_motion_score'
    elif scores:
        motion_density = sum(scores)/len(scores)*min(1.0, rate(len(candidates))/30)
        motion_evidence = 'scene_change_score_proxy'
    else:
        motion_density, motion_evidence = 0.0, 'unavailable'
    scene_spans = _spans([] if scenes is None else scenes, duration, 'scenes')
    scene_spans = list(set(scene_spans))
    metrics = {'speech_density': speech_duration/duration if duration else 0.0,
        'speech_duration': speech_duration, 'speech_timing_source': 'words' if words else 'segments' if utterances else 'unavailable',
        'average_utterance_duration': sum(end-start for start, end in set(utterances))/len(set(utterances)) if utterances else 0.0,
        'average_pause_duration': sum(pauses)/len(pauses) if pauses else 0.0, 'pause_count': len(pauses),
        'pause_duration': duration-speech_duration, 'shots': shot_count, 'shots_per_minute': rate(shot_count),
        'raw_candidates': len(candidates), 'raw_candidates_per_minute': rate(len(candidates)),
        'motion_density': motion_density, 'motion_evidence': motion_evidence,
        'semantic_scenes': len(scene_spans), 'semantic_scenes_per_minute': rate(len(scene_spans)),
        'average_scene_duration': sum(end-start for start, end in scene_spans)/len(scene_spans) if scene_spans else 0.0,
        **_event_metrics([] if events is None else events, duration, speech)}
    thresholds = EPISODE_PROFILE_POLICY['classifier']
    fast = max(metrics['shots_per_minute'], metrics['raw_candidates_per_minute']) >= thresholds['fast_shots_per_minute'] and max(shot_count, len(candidates)) >= thresholds['minimum_fast_shots']
    active = metrics['action_density'] >= thresholds['action_high'] or motion_density >= thresholds['motion_high'] or fast
    if active and metrics['speech_density'] >= thresholds['speech_action_mix']:
        kind, reasons = 'mixed', ['speech_and_visual_activity']
    elif active:
        kind, reasons = 'action_dense', ['dense_visual_activity']
    elif metrics['speech_density'] >= thresholds['speech_high']:
        kind, reasons = 'dialogue_slow', ['speech_dominates', 'low_visual_activity']
    else:
        kind, reasons = 'balanced', ['moderate_or_incomplete_pace_evidence']
    if metrics['action_units']:
        reasons.append('confirmed_current_actions')
    if metrics['narrative_bridges']:
        reasons.append('confirmed_narrative_bridges')
    evidence_count = sum((bool(speech), bool(shot_count), motion_evidence != 'unavailable', scenes is not None, events is not None))
    result = {'version': EPISODE_PROFILE_VERSION, 'policy': copy.deepcopy(EPISODE_PROFILE_POLICY),
              'profile': kind, 'confidence': min(.95, .35 + .12*evidence_count) if duration else 0.0,
              'duration': duration, 'source_duration': duration,
              'phase': 'refined' if events is not None else 'initial', 'reason': reasons,
              'metrics': metrics}
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
