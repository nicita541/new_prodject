"""Measured PCM boundaries: timing/selection mechanisms, not story acceptance."""
import math
import uuid
import wave
from unittest.mock import patch

import numpy as np
import pytest

from app import audio_boundaries as audio
from app.checkpoint_lineage import link
from app.content_identity import file_sha256
from app.json_store import atomic_json
from app.media import run_command


def evidence(levels, *, duration=8., stream=0):
    return {'policy': dict(audio.POLICY), 'source_sha256': 'a'*64, 'duration': duration,
            'audio_stream': stream, 'windows': [{'start': 0., 'end': duration}],
            'frames': [[round(i*.02, 6), round((i+1)*.02, 6), level, level]
                       for i, level in enumerate(levels)]}


@pytest.mark.parametrize('gain', [0, -20])
def test_local_valley_follows_tail_without_asr_and_is_gain_relative(gain):
    levels = [-70+gain]*100 + [-10+gain]*100 + [-70+gain]*200
    measured = evidence(levels)
    core = [{'start': 2.4, 'end': 3.7}]
    adjusted, observed = audio.adjust_ranges(core, core, {'words': []}, 8., measured)
    assert adjusted == [{'start': 1.97, 'end': 4.03}]
    assert all(row['status'] == 'measured_relative_valley' for row in observed)
    assert all(row['semantic_completion'] == 'not_established_by_waveform' for row in observed)


def test_steady_background_keeps_fallback_without_claiming_a_completed_action():
    measured = evidence([-18.]*400)
    core = [{'start': 2., 'end': 3.}]
    fallback = [{'start': 1.82, 'end': 3.55}]
    adjusted, observed = audio.adjust_ranges(core, fallback, {}, 8., measured)
    assert adjusted == fallback
    assert {row['status'] for row in observed} == {'no_quiet_transition'}


def test_omitted_words_and_exclusions_are_hard_limits():
    measured = evidence([-70.]*100+[-10.]*100+[-70.]*200)
    core = [{'start': 2.4, 'end': 3.7}]
    fallback = [{'start': 2.3, 'end': 3.75}]
    transcript = {'words': [{'start': 1.9, 'end': 2.3}, {'start': 3.8, 'end': 4.2}]}
    adjusted, _ = audio.adjust_ranges(core, fallback, transcript, 8., measured,
                                    [{'start': 0., 'end': 2.35}, {'start': 3.77, 'end': 8.}])
    assert adjusted[0]['start'] >= 2.35
    assert adjusted[0]['end'] <= 3.77


def test_measured_quiet_can_shorten_fixed_padding_but_cannot_trim_selected_core():
    measured = evidence([-70.]*100+[-10.]*50+[-70.]*250)
    core = [{'start': 2., 'end': 3.}]
    adjusted, _ = audio.adjust_ranges(core, [{'start': 1.82, 'end': 3.55}], {}, 8., measured)
    assert adjusted == [{'start': 1.97, 'end': 3.03}]


def test_pts_gaps_are_not_converted_into_silence_or_crossed(tmp_path):
    wav, log = tmp_path/'pcm.wav', tmp_path/'pts.log'
    with wave.open(str(wav), 'wb') as out:
        out.setparams((1, 2, audio.RATE, 0, 'NONE', 'not compressed'))
        out.writeframes(np.zeros(3200, dtype='<i2').tobytes())
    log.write_text('n:0 pts:0 pts_time:0 nb_samples:1600\n'
                   'n:1 pts:4800 pts_time:0.3 nb_samples:1600\n', encoding='utf-8')
    rows = audio._pcm_frames(wav, log, 0., .4)
    assert not any(row[0] < .3 and row[1] > .1 for row in rows)
    measured = evidence([], duration=.4)
    measured['frames'] = rows
    adjusted, observed = audio.adjust_ranges([{'start': .12, 'end': .2}],
        [{'start': .12, 'end': .2}], {}, .4, measured)
    assert adjusted == [{'start': .12, 'end': .2}]
    assert {row['status'] for row in observed} == {'missing_pcm_coverage'}


def test_pcm_features_do_not_depend_on_codec_packet_sizes(tmp_path):
    pcm = (20000*np.sin(2*np.pi*880*np.arange(16000)/16000)).astype('<i2')
    wav = tmp_path/'same.wav'
    with wave.open(str(wav), 'wb') as out:
        out.setparams((1, 2, audio.RATE, 0, 'NONE', 'not compressed'))
        out.writeframes(pcm.tobytes())
    observed = []
    for packet_size in (320, 1024):
        cursor, lines = 0, []
        while cursor < len(pcm):
            count = min(packet_size, len(pcm)-cursor)
            lines.append(f'n:{len(lines)} pts:{cursor} pts_time:{.75+cursor/16000:.8f} nb_samples:{count}')
            cursor += count
        log = tmp_path/f'packet-{packet_size}.log'
        log.write_text('\n'.join(lines), encoding='utf-8')
        observed.append(audio._pcm_frames(wav, log, .75, 1.75))
    assert observed[0] == observed[1]
    assert len(observed[0]) == 50
    assert observed[0][0][0] == .75  # A delayed track is not relabeled to zero.


def test_empty_audio_window_is_missing_coverage_and_not_quiet(tmp_path):
    wav, log = tmp_path/'empty.wav', tmp_path/'empty.log'
    with wave.open(str(wav), 'wb') as out:
        out.setparams((1, 2, audio.RATE, 0, 'NONE', 'not compressed'))
    log.write_text('No selected audio packets in this source window.', encoding='utf-8')
    assert audio._pcm_frames(wav, log, 0., .4) == []
    fallback = [{'start': .1, 'end': .3}]
    adjusted, observations = audio.adjust_ranges(fallback, fallback, {}, .4, evidence([], duration=.4))
    assert adjusted == fallback
    assert {row['status'] for row in observations} == {'missing_pcm_coverage'}


@pytest.mark.parametrize('change', ['sha', 'policy', 'stream', 'nan', 'overlap'])
def test_invalid_physical_evidence_rejected(change):
    measured = evidence([-50.]*400)
    if change == 'sha': measured['source_sha256'] = 'b'*64
    elif change == 'policy': measured['policy']['step'] = .5
    elif change == 'stream': measured['audio_stream'] = True
    elif change == 'nan': measured['frames'][0][2] = math.nan
    else: measured['frames'][1][0] = 0.
    with pytest.raises(ValueError):
        audio.validate_evidence(measured, 'a'*64, 8.)


def test_real_selected_stream_source_pts_and_readonly_ancestor_reuse(tmp_path):
    source = tmp_path/'source.mp4'
    run_command([str(audio.FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'color=c=blue:s=64x64:r=10:d=8', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=8',
        '-f', 'lavfi', '-i', r'aevalsrc=0.8*sin(2*PI*880*t)*between(t\,2\,4):s=16000:d=8',
        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-c:a', 'aac', str(source)], tmp_path/'generate')
    sha = file_sha256(source)
    parent, child = [tmp_path/'jobs'/str(uuid.uuid4()) for _ in range(2)]
    for owner in (parent, child):
        atomic_json(owner/'job.json', {'id': owner.name, 'episode_id': None})
        atomic_json(owner/'source.json', {'path': str(source)})
        atomic_json(owner/'analysis.meta.json', {'source': sha})
    link(parent, child, source_sha256=sha, episode_id=None)
    probe, core = {'duration': 8., 'audio_stream': 1}, [{'start': 2.4, 'end': 3.7}]
    measured = audio.measure_edges(source, sha, probe, core, parent)
    assert measured['frames'][0][0] >= .89  # Input seek preserved source clock.
    assert measured['frames'][-1][1] <= 5.2
    active = [r[2] for r in measured['frames'] if 2.2 < r[0] < 3.8]
    assert np.median(active) > -8  # Selected second stream, not first low tone.
    adjusted, observed = audio.adjust_ranges(core, core, {}, 8., measured)
    assert 3.99 <= adjusted[0]['end'] <= 4.1
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in parent.rglob('*') if p.is_file()}
    with patch.object(audio, 'run_process', side_effect=AssertionError('No repeated decoder')):
        assert audio.measure_edges(source, sha, probe, core, child) == measured
        assert audio.measure_edges(source, sha, probe, core, parent, create=False) == measured
    assert not (child/'audio-boundaries').exists()
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in parent.rglob('*') if p.is_file()}
    with pytest.raises(InterruptedError):
        audio.measure_edges(source, sha, probe, core, child, lambda: True)


def test_compiler_applies_measurements_before_review_and_framing_rebuild_is_exact():
    from tests.test_story_candidates import edge_utterance_fixture
    from app.story_candidates import prototype_plan, with_cut_context
    from app.standalone_planner import _plan
    from app.planner import validate_plan
    analysis, case, proposal = edge_utterance_fixture()
    old, _ = prototype_plan(analysis, with_cut_context(analysis, case, proposal), proposal)
    analysis['audio_boundary_policy'] = dict(audio.POLICY)
    context = with_cut_context(analysis, case, proposal)
    levels = [-80.]*1000+[-10.]*1000+[-25.]*20+[-80.]*980
    context['audio_boundary_evidence'] = evidence(levels, duration=60.)
    plan, scoped = prototype_plan(analysis, context, proposal)
    cut = plan['parts'][0]['cuts'][0]
    assert (cut['start'], cut['end']) == (19.97, 40.43)
    assert (old['parts'][0]['cuts'][0]['start'], old['parts'][0]['cuts'][0]['end']) == (19.82, 40.55)
    assert plan.get('export_eligible') is not True  # A signal never authorizes story export.
    rebuilt = _plan(scoped, plan['semantic_ranges'])
    assert rebuilt['parts'][0]['cuts'] == plan['parts'][0]['cuts']
    assert rebuilt['audio_boundary_observations'] == plan['audio_boundary_observations']
    validate_plan(rebuilt, scoped)


def test_changed_audio_geometry_cannot_reuse_old_story_approval():
    from tests.test_story_candidates import edge_utterance_fixture
    from app.story_candidates import prototype_plan, with_cut_context, inspect_candidate_quality, timeline_digest
    analysis, case, proposal = edge_utterance_fixture()
    context = with_cut_context(analysis, case, proposal)
    old, _ = prototype_plan(analysis, context, proposal)
    analysis['audio_boundary_policy'] = dict(audio.POLICY)
    context['audio_boundary_evidence'] = evidence([-80.]*1000+[-10.]*1000+[-25.]*20+[-80.]*980, duration=60.)
    _, scoped = prototype_plan(analysis, context, proposal)
    scoped['candidate_evidence'] = {'case': context, 'proposal': proposal,
        'review': {}, 'timeline_digest': timeline_digest(old)}
    quality = inspect_candidate_quality(scoped, old)
    assert quality['status'] == 'unresolved'
    assert 'differs from the reviewed edit' in quality['problems'][0]['detail']


def test_new_policy_cannot_drop_measured_audio_to_fall_back_to_old_approval():
    from tests.test_story_candidates import edge_utterance_fixture
    from app.story_candidates import prototype_plan
    analysis, case, proposal = edge_utterance_fixture()
    analysis['audio_boundary_policy'] = dict(audio.POLICY)
    with pytest.raises(ValueError, match='missing measured audio'):
        prototype_plan(analysis, case, proposal)


def test_native_optional_notes_do_not_reclassify_historical_blockers():
    from tests.test_story_candidates import candidate_fixture
    from app.story_candidates import review_status
    analysis, record, plan = candidate_fixture()
    raw = record['review']
    raw['notes'] = ['Optional establishing detail, not required to understand this local story.']
    assert review_status(analysis, record['case'], record['proposal'], plan, raw) == 'ready'
    raw['issues'] = ['The required cause is omitted.']
    assert review_status(analysis, record['case'], record['proposal'], plan, raw) == 'needs_review'
