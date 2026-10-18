"""Technical discovery partitions have coverage, never semantic authority."""
import copy

import pytest

from app.discovery_regions import source_regions
from app.episode_survey import survey_windows
from app.selective_analysis import resolve_scope


def regions(duration=95, transcript=None, sha='a' * 64):
    return source_regions({'duration': duration}, transcript or {'words': [], 'segments': []},
                          [{'id': 'shot', 'start': 0, 'end': duration}], sha)


def test_silent_source_coverage_and_selective_neighbor_context_without_semantic_claims():
    catalog = regions()
    assert [(r['start'], r['end']) for r in catalog] == [(0, 30), (30, 60), (60, 90), (90, 95)]
    assert all(r['technical_region'] and r['uncertain'] and r['confidence'] == 0
               and r['evidence']['semantic_authority'] is False for r in catalog)
    windows = survey_windows(catalog, {'words': [], 'segments': []}, 'a' * 64)
    scope = resolve_scope(catalog, {'windows': windows, 'hypotheses': [{
        'window_ids': [windows[1]['id']], 'prerequisite_window_ids': []}]})
    assert scope['analyzed_ranges'] == [{'start': 30, 'end': 60}]
    assert scope['context_scenes'][catalog[1]['id']]['previous']['id'] == catalog[0]['id']
    assert scope['context_scenes'][catalog[1]['id']]['next']['id'] == catalog[2]['id']


def test_region_edges_preserve_words_and_source_inputs():
    transcript = {'words': [{'start': 29, 'end': 32, 'text': 'indivisible'}], 'segments': []}
    original = copy.deepcopy(transcript)
    catalog = regions(65, transcript)
    assert catalog[0]['end'] == 29 and catalog[1]['start'] == 29
    assert all(not 29 < r[k] < 32 for r in catalog for k in ('start', 'end'))
    assert transcript == original
    assert catalog == regions(65, transcript)
    assert catalog[0]['id'] != regions(65, transcript, 'b' * 64)[0]['id']


def test_long_indivisible_speech_is_explicit_not_silently_cut():
    catalog = regions(95, {'words': [{'start': 0, 'end': 70, 'text': 'unbreakable'}]})
    assert catalog[0]['end'] == 70
    assert catalog[0]['evidence']['indivisible_speech_over_context_window']


def test_region_edge_cannot_split_a_complete_utterance_between_its_words():
    transcript = {'segments': [{'start': 27.86, 'end': 30.24, 'text': 'I asked for tea.'}],
        'words': [{'start': 27.86, 'end': 28.2, 'text': 'I'},
                  {'start': 28.4, 'end': 29.1, 'text': 'asked'},
                  {'start': 29.2, 'end': 29.78, 'text': 'for'},
                  {'start': 29.78, 'end': 30.24, 'text': 'tea.'}]}
    original = copy.deepcopy(transcript)
    catalog = regions(65, transcript)
    assert catalog[0]['end'] == 27.86
    assert all(not 27.86 < r[k] < 30.24 for r in catalog for k in ('start', 'end'))
    assert catalog[0]['evidence']['speech_boundary_policy'] == 'complete_asr_utterances_and_words'
    assert transcript == original


def test_words_cannot_hide_a_long_utterance_or_invalid_segment_geometry():
    transcript = {'segments': [{'start': 0, 'end': 70, 'text': 'Long complete utterance.'}],
                  'words': [{'start': 1, 'end': 2, 'text': 'word'}]}
    catalog = regions(95, transcript)
    assert catalog[0]['end'] == 70
    assert catalog[0]['evidence']['indivisible_speech_over_context_window']
    transcript['segments'][0]['end'] = float('nan')
    with pytest.raises(ValueError, match='speech geometry'):
        regions(95, transcript)


def test_overlapping_word_and_utterance_envelopes_preserve_full_coverage():
    transcript = {'segments': [{'start': 28, 'end': 31, 'text': 'One'},
                               {'start': 31, 'end': 33, 'text': 'Two'}],
                  'words': [{'start': 30.9, 'end': 31.2, 'text': 'Overlapping'}]}
    catalog = regions(65, transcript)
    assert catalog[0]['end'] == 28
    assert all(not 28 < r[k] < 33 for r in catalog for k in ('start', 'end'))
    assert catalog[0]['start'] == 0 and catalog[-1]['end'] == 65
    assert all(left['end'] == right['start'] for left, right in zip(catalog, catalog[1:]))


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf'), True])
def test_invalid_source_geometry_cannot_become_discovery_evidence(duration):
    with pytest.raises(ValueError):
        regions(duration)
