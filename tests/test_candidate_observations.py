"""Source observation scope and enrichment; no model/semantic answers."""
import copy
import math
from unittest.mock import patch

import pytest

from app import candidate_analysis as native
from app.json_store import atomic_json


def case(count=5):
    return {'source_sha256': 'a'*64,
        'units': [{'id': f'u{i}', 'start': float(i), 'end': float(i+1), 'text': ''} for i in range(count)]}


def plan(start=0., end=5.):
    return {'parts': [{'cuts': [{'start': start, 'end': end}]}]}


def test_asr_silent_gaps_share_shot_observations_instead_of_three_images_each():
    original, edit = case(), plan()
    before = copy.deepcopy((original, edit))
    old = native._frame_requests(original, edit)
    wanted = native._frame_requests(original, edit, shots=[{'start': 0., 'end': 5.}])
    assert sum(map(len, old.values())) == 15
    assert sum(map(len, wanted.values())) == 7
    for i in range(5):
        assert i+.5 in wanted[f'u{i}']
    assert 0. in wanted['u0']
    assert math.nextafter(5., 0.) in wanted['u4']
    assert (original, edit) == before


def test_original_shot_edges_and_actual_cut_edges_keep_exact_owners():
    original = case(4)
    wanted = native._frame_requests(original, plan(1., 3.),
        shots=[{'start': 0., 'end': 2.}, {'start': 2., 'end': 4.}])
    assert 1. in wanted['u1']
    assert math.nextafter(3., 1.) in wanted['u2']
    assert math.nextafter(2., 0.) in wanted['u1']
    assert 2. in wanted['u2']
    for unit in original['units']:
        assert all(unit['start'] <= time < unit['end'] for time in wanted[unit['id']])


def test_source_join_observes_gap_inside_a_large_unit_on_actual_audible_clock():
    original = {'source_sha256': 'a'*64, 'source_join_policy': dict(native.SOURCE_JOIN_POLICY),
        'units': [{'id': 'u0', 'start': 0., 'end': 10., 'text': 'Authored complete speech'}]}
    edit = {'semantic_ranges': [{'start': 0., 'end': 3.}, {'start': 7., 'end': 10.}],
        'parts': [{'cuts': [{'start': .1, 'end': 4.}, {'start': 6., 'end': 9.9}]}]}
    wanted = native._frame_requests(original, edit, shots=[{'start': 0., 'end': 10.}])
    assert {4., 5., math.nextafter(6., 4.)} <= wanted['u0']
    assert 3. not in wanted['u0'] and 7. not in wanted['u0']
    assert all(0. <= time < 10. for time in wanted['u0'])


def test_motion_peak_adds_owned_before_after_but_never_crosses_original_shot():
    motion = [{'motion_start': t-.2, 'time': t, 'crosses_cut': False,
               'residual_motion_score': score} for t, score in
              ((.4, .1), (.8, .1), (1.2, .1), (1.6, .9), (2., .1))]
    motion.append({'motion_start': 3.9, 'time': 4.1, 'crosses_cut': True, 'residual_motion_score': 1.})
    wanted = native._frame_requests(case(), plan(), shots=[{'start': 0., 'end': 5.}], motion=motion)
    assert pytest.approx(1.4) in list(wanted['u1']) and 1.6 in wanted['u1']
    assert not any(4.1 in points or 3.9 in points for points in wanted.values())


def test_steady_camera_motion_does_not_manufacture_an_action_or_extra_peaks():
    original, edit, shots = case(), plan(), [{'start': 0., 'end': 5.}]
    motion = [{'motion_start': i*.2, 'time': (i+1)*.2, 'crosses_cut': False,
               'residual_motion_score': .2, 'global_motion_score': 1.} for i in range(20)]
    assert native._frame_requests(original, edit, shots=shots, motion=motion) == native._frame_requests(original, edit, shots=shots)


def test_requested_enrichment_adds_quarter_points_after_all_three_base_positions_exist():
    original = {'source_sha256': 'a'*64, 'units': [{'id': 'u0', 'start': 0., 'end': 4., 'text': ''}]}
    edit, shots = plan(0., 4.), [{'start': 0., 'end': 4.}]
    baseline = native._frame_requests(original, edit, shots=shots)
    enriched = native._frame_requests(original, edit, shots=shots, enriched=['u0'])
    assert enriched['u0']-baseline['u0'] == {1., 3.}


@pytest.mark.parametrize('sha,samples', [('b'*64, []), ('a'*64, 'model text is not a sample array')])
def test_foreign_or_malformed_sampling_hints_are_ignored(tmp_path, sha, samples):
    atomic_json(tmp_path/'media-evidence.json', {'source': {'sha256': sha}, 'samples': samples})
    assert native._source_motion(tmp_path, 'a'*64) == []


def test_sampling_never_sends_semantic_hint_text_as_source_evidence(tmp_path):
    row = {'time': 1., 'motion_start': .8, 'crosses_cut': False, 'residual_motion_score': .2,
           'untrusted_model_label': 'THIS IS A COMPLETE STORY'}
    atomic_json(tmp_path/'media-evidence.json', {'source': {'sha256': 'a'*64}, 'samples': [row]})
    wanted = native._frame_requests(case(), plan(), shots=[{'start': 0., 'end': 5.}],
                                   motion=native._source_motion(tmp_path, 'a'*64))
    assert all(type(time) is float for points in wanted.values() for time in points)
    assert sum(map(len, wanted.values())) == 7


def test_invalid_physical_adapter_owner_fails_before_page_creation_or_model(tmp_path):
    original, edit = case(1), plan(0., 1.)
    def foreign(source, requests, directory, cancelled):
        return {'sha256': 'a'*64}, [([{'time': 2., 'sha256': 'b'*64}], [directory/'frame.jpg'])]
    with patch('app.bounded_storyboard.source_frame_groups', side_effect=foreign):
        with pytest.raises(ValueError, match='physical source owner'):
            native._prepare_frames(tmp_path/'source.mp4', original, edit, tmp_path/'evidence', lambda: False,
                                   shots=[{'start': 0., 'end': 1.}])


def test_proposal_observes_original_shots_and_prominent_motion_before_selecting_cuts():
    motion = [{'motion_start': t-.2, 'time': t, 'crosses_cut': False,
               'residual_motion_score': score} for t, score in
              ((.4, .1), (.8, .1), (1.2, .1), (1.6, .9), (2., .1))]
    original = case()
    wanted = native._proposal_requests(original, [{'start': 0., 'end': 5.}], motion, 36)
    assert wanted['u2'] == {2.5}
    assert pytest.approx(1.4) in list(wanted['u1']) and 1.6 in wanted['u1']
    assert sum(map(len, wanted.values())) == 3


def test_proposal_capacity_preserves_quiet_time_coverage_among_dense_fast_shots():
    shots = [{'start': i/10, 'end': (i+1)/10} for i in range(40)]
    shots.append({'start': 4., 'end': 100.})
    wanted = native._proposal_requests(case(100), shots, [], 4)
    times = sorted(time for points in wanted.values() for time in points)
    assert 52. in times  # Quiet long shot is not displaced by many rapid cuts.
    assert any(time < 4. for time in times)
    assert len(times) <= 4


def test_proposal_fallback_covers_catalog_without_crossing_disconnected_owners():
    original = {'units': [{'id': 'left', 'start': 0., 'end': 2.},
                          {'id': 'right', 'start': 8., 'end': 10.}],
                'source_ranges': [{'start': 0., 'end': 2.}, {'start': 8., 'end': 10.}]}
    assert native._proposal_requests(original, [{'start': 0., 'end': 10.}], [], 36) == {
        'left': {1.}, 'right': {9.}}


@pytest.mark.parametrize('budget', [0, -1, True])
def test_invalid_proposal_capacity_rejected(budget):
    with pytest.raises(ValueError, match='capacity'):
        native._proposal_requests(case(), [], [], budget)


def paired_case(count=5):
    return {**case(count), 'proposal_policy': dict(native.PROPOSAL_POLICY)}


def test_paired_proposal_reserves_whole_endpoint_pairs_before_optional_detail():
    original = paired_case(4)
    shots = [{'start': float(i), 'end': float(i+1)} for i in range(4)]
    wanted = native._proposal_requests(original, shots, [], 4)
    points = {time for values in wanted.values() for time in values}
    assert len(points) == 4
    for shot in shots:
        endpoints = {shot['start'], math.nextafter(shot['end'], shot['start'])}
        assert len(points & endpoints) in (0, 2)
    assert all(time % 1 != .5 for time in points)


def test_paired_quiet_coverage_and_row_capacity_do_not_yield_to_dense_motion():
    shots = [{'start': i/10, 'end': (i+1)/10} for i in range(40)]
    shots.append({'start': 4., 'end': 100.})
    original = paired_case(100)
    wanted = native._proposal_requests(original, shots, [], 18, shot_budget=6)
    times = {time for points in wanted.values() for time in points}
    assert {4., 52., math.nextafter(100., 4.)} <= times
    covered = [shot for shot in shots if shot['start'] in times]
    assert len(covered) == 6 and any(shot['end'] < 4. for shot in covered)
    assert len(times) <= 18


def test_paired_fallback_and_disconnected_catalog_keep_endpoint_owners():
    original = {'proposal_policy': dict(native.PROPOSAL_POLICY),
        'units': [{'id': 'left', 'start': 0., 'end': 2.},
                  {'id': 'right', 'start': 8., 'end': 10.}]}
    wanted = native._proposal_requests(original, [], [], 6)
    assert wanted == {'left': {0., 1., math.nextafter(2., 0.)},
                      'right': {8., 9., math.nextafter(10., 8.)}}


def test_paired_extraction_clips_actual_decode_windows_to_original_shot(tmp_path):
    original = paired_case(2)
    shots = [{'start': 0., 'end': .95}, {'start': .95, 'end': 2.}]
    physical_times = [i*.04 for i in range(50)]
    observed = []
    def physical(source, requests, directory, cancelled):
        observed.extend(requests)
        groups = []
        for window in requests:
            owned = [time for time in physical_times if window['start'] <= time < window['end']]
            chosen = [next((time for time in owned if time >= request), owned[-1])
                      for request in window['times']]
            groups.append(([{'time': time, 'requested_time': request,
                             'sha256': f'{i+1:064x}'}
                            for i, (time, request) in enumerate(zip(chosen, window['times']))],
                           [directory/f'{time}.jpg' for time in chosen]))
        return {'sha256': 'a'*64}, groups
    with patch('app.bounded_storyboard.source_frame_groups', side_effect=physical):
        preview = native._prepare_proposal_frames(tmp_path/'source.mp4', {'shots': shots},
            original, tmp_path/'evidence', 'local', lambda: False, page_budget=1)
    assert [(row['start'], row['end']) for row in observed] == [(0., .95), (.95, 1.), (1., 2.)]
    first_shot = [frame for frame in preview['frames'] if frame['requested_time'] < .95]
    assert first_shot[-1]['time'] == .92 and first_shot[-1]['time'] < .95
    assert max(frame['time'] for frame in preview['frames']) == 1.96
    assert all(original['units'][int(frame['unit'][1:])]['start'] <= frame['time']
               < original['units'][int(frame['unit'][1:])]['end'] for frame in preview['frames'])


def test_single_actual_frame_is_presented_once_and_cannot_become_a_change_pair(tmp_path):
    from PIL import Image
    original = paired_case(1)
    evidence = tmp_path/'evidence'
    evidence.mkdir()
    picture = evidence/'only.jpg'
    Image.new('RGB', (320, 180), 'green').save(picture)
    from app.content_identity import file_sha256
    def physical(source, requests, directory, cancelled):
        return {'sha256': 'a'*64}, [([{'time': .04, 'requested_time': time,
            'sha256': file_sha256(picture)} for time in requests[0]['times']],
            [picture]*len(requests[0]['times']))]
    with patch('app.bounded_storyboard.source_frame_groups', side_effect=physical):
        preview = native._prepare_proposal_frames(tmp_path/'source.mp4',
            {'shots': [{'start': 0., 'end': 1.}]}, original, evidence, 'local', lambda: False)
    assert len(preview['frames']) == 1
    pages, mapping = native._proposal_pages(preview, [{'start': 0., 'end': 1.}],
        evidence/'proposal-pages', lambda: False)
    assert len(pages) == 1 and mapping[0]['frames'] == [{'index': 1, 'time': .04}]
    assert native._proposal_pages(preview, [{'start': 0., 'end': 1.}],
        evidence/'proposal-pages', lambda: False) == (pages, mapping)
    picture.write_bytes(b'changed source image')
    # A damaged page is regenerated from checked source bytes, never trusted.
    pages[0].write_bytes(b'damaged cached page')
    with pytest.raises(ValueError, match='source image changed'):
        native._proposal_pages(preview, [{'start': 0., 'end': 1.}],
            evidence/'proposal-pages', lambda: False)
