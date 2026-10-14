"""Native excluded bumpers survive profile/planner validation without widening story acceptance."""
import copy

import pytest

from app.episode_profile import build_episode_profile
from app.eyecatch import apply_eyecatch_exclusions
from app.planner import validate_analysis


def analysis():
    events = [{'id': 'bumper', 'start': 40., 'end': 45., 'kind': 'story',
               'importance': 4, 'selected_ranges': [{'start': 40., 'end': 45.}]}]
    return {'probe': {'duration': 100., 'has_audio': True, 'width': 1920, 'height': 1080},
            'transcript': {'words': [], 'segments': []}, 'shots': [],
            'events': apply_eyecatch_exclusions(events, [0])}


def test_native_excluded_eyecatch_is_valid_and_has_no_story_density():
    value = analysis()
    original = copy.deepcopy(value)
    validate_analysis(value)
    profile = build_episode_profile(100., value['transcript'], [], events=value['events'])
    assert profile['metrics']['confirmed_story_events'] == 0
    assert profile['metrics']['positive_story_duration'] == 0
    assert value == original


@pytest.mark.parametrize('kind,selected', [('story', []), ('filler', []),
    ('eyecatch', [{'start': 40., 'end': 45.}]), ('eyecatch', None)])
def test_zero_importance_still_requires_an_explicit_excluded_eyecatch(kind, selected):
    value = analysis()
    value['events'][0].update(kind=kind, selected_ranges=selected)
    with pytest.raises(ValueError, match='важность'):
        validate_analysis(value)
    with pytest.raises(ValueError, match='event.importance'):
        build_episode_profile(100., value['transcript'], [], events=value['events'])


@pytest.mark.parametrize('importance', [-1, 6, float('nan'), float('inf')])
def test_excluded_bumper_does_not_bypass_importance_bounds(importance):
    value = analysis()
    value['events'][0]['importance'] = importance
    with pytest.raises(ValueError):
        validate_analysis(value)
    with pytest.raises(ValueError):
        build_episode_profile(100., value['transcript'], [], events=value['events'])
