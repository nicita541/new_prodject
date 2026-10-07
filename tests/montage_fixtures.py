"""Long source episodes with explicit factual units, states and quota pressure."""
import copy


def finalized_profile(data, budget=None):
    """Exercise the production profile handoff; these remain authored mechanism inputs."""
    from app.episode_profile import build_episode_profile
    data['episode_profile'] = build_episode_profile(data['probe']['duration'], data['transcript'],
        data['shots'], data.get('scenes'), data['events'], perception=data.get('perception'))
    if budget is not None:
        data['episode_profile']['retention_budget'] = dict(budget)
    return data


def state(place='room', character='free', objects=None, topic='story'):
    return {'locations': [place], 'character_state': character, 'objects': objects or [],
            'relationship': 'known', 'topic': topic}


def event(identifier, start, end, importance=4, **extra):
    return {'id': identifier, 'start': start, 'end': end, 'kind': 'story', 'importance': importance,
            'summary': identifier, 'requires': [], 'uncertain': False, 'confidence': .95,
            'understanding_status': 'accepted', 'unit_selection_version': 1,
            'selected_ranges': [{'start': start, 'end': end}], 'focus': [], **extra}


def source_episode(events=None, duration=1440, transcript=None):
    if events is None:
        events = [event(f'e{i:03}', i*40, i*40+30,
                       selected_ranges=[{'start': i*40, 'end': i*40+25}]) for i in range(36)]
    events = copy.deepcopy(events)
    cursor = events[-1]['end'] if events else 0
    index = 0
    while cursor < duration:
        end = min(duration, cursor+40)
        events.append(event(f'filler_{index:03}', cursor, end, 1, kind='filler'))
        cursor, index = end, index+1
    return {'probe': {'duration': duration, 'width': 320, 'height': 180, 'has_audio': True, 'fps': 25},
            'events': events, 'transcript': transcript or {'words': [], 'segments': []}, 'shots': []}


def kidnapping_episode():
    free, bound, car = state('street'), state('street', 'bound'), state('car', 'bound')
    return source_episode([
        event('conversation', 0, 30, 5, state_before=free, state_after=free),
        event('binding', 30, 34, 2, state_before=free, state_after=bound,
              units=[{'id': 'bind', 'start': 30, 'end': 34}], action_units=['bind']),
        event('transport', 34, 38, 2, state_before=bound, state_after=car,
              units=[{'id': 'car', 'start': 34, 'end': 38}], action_units=['car']),
        event('payoff', 38, 68, 5, state_before=car, state_after=car, requires=['transport'])])


def five_arcs_episode():
    events = []
    for index in range(5):
        start = index*84.0
        common = {'story_arc_id': f'arc_{index}', 'state_before': state(topic=f'topic_{index}'),
                  'state_after': state(topic=f'topic_{index}')}
        events.append(event(f'setup_{index}', start, start+42, 5, story_phase='setup', **common))
        ending = {'time': start+84, 'kind': 'closure', 'confidence': .95, 'evidence': 'Завершён payoff',
                  'verification': {'supported': True, 'confidence': .95, 'evidence': 'Реакция завершена'}}
        events.append(event(f'payoff_{index}', start+42, start+84, 5, story_phase='payoff',
                            part_endings=[ending], **common))
    result = source_episode(events)
    result['preferred_part_count'] = 6
    return result
