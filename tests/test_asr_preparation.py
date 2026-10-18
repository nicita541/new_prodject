"""Actual analysis preparation orchestration; inference and later perception stubbed."""
from pathlib import Path
from unittest.mock import Mock, patch
import wave

import pytest

from app import analysis
from app.content_identity import file_sha256
from app.inference import REPAIR_VERSION
from app.json_store import atomic_json, read_json
from app.processing import preparation_identity


class ReachedPerception(Exception):
    pass


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'authored source bytes; no video decoding in this orchestration test')
    job = tmp_path/'job'
    job.mkdir()
    probe = {'duration': 2., 'width': 320, 'height': 180, 'fps': 25.,
             'has_audio': True, 'audio_stream': 1}
    atomic_json(job/'probe.json', probe)
    ancestor = tmp_path/'ancestor'
    ancestor.mkdir()
    audio = ancestor/'audio.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\x00'*160)
    return source, job, probe, audio


def reach_perception(source, job):
    with patch.object(analysis, 'setup_environment'), \
            patch.object(analysis, 'shot_checkpoint', side_effect=ReachedPerception):
        with pytest.raises(ReachedPerception):
            analysis._analyze(job, source, Mock(), lambda: False, Mock())


@pytest.mark.parametrize('provided', [False, True])
def test_completed_asr_needs_neither_pcm_materialization_nor_inference(prepared, provided):
    source, job, probe, _ = prepared
    settings = ({'transcript_mode': 'provided', 'transcript_source_sha256': file_sha256(source)}
                if provided else {})
    atomic_json(job/'analysis-settings.json', settings)
    transcript = {'words': [], 'segments': []}
    if not provided:
        transcript['repair_version'] = REPAIR_VERSION
    atomic_json(job/'transcript.json', transcript)
    atomic_json(job/'preparation.meta.json', preparation_identity(file_sha256(source), probe, settings))
    with patch('app.asr_audio.prepare_asr_audio', side_effect=AssertionError('PCM not needed')) as pcm, \
            patch.object(analysis, 'run_process', side_effect=AssertionError('ASR not needed')) as infer:
        reach_perception(source, job)
    pcm.assert_not_called()
    infer.assert_not_called()
    assert not (job/'audio.wav').exists()
    assert read_json(job/'transcript.json')['words'] == []


def test_fresh_transcription_and_repair_resolve_the_same_readonly_ancestor_once(prepared):
    source, job, probe, origin = prepared
    before = origin.read_bytes()
    calls = []
    def infer(command, log, cancelled, **options):
        assert command[1:3] == ['-m', 'app.inference']
        assert Path(command[3]) == origin
        calls.append(command)
        atomic_json(job/'transcript.json', {'words': [], 'segments': [],
                    **({'repair_version': REPAIR_VERSION} if '--repair-only' in command else {})})
    with patch('app.asr_audio.prepare_asr_audio', return_value=origin) as pcm, \
            patch.object(analysis, 'run_process', side_effect=infer):
        reach_perception(source, job)
    assert len(calls) == 2 and '--repair-only' in calls[1]
    pcm.assert_called_once()
    assert pcm.call_args.args[:4] == (source.resolve(), file_sha256(source), probe,
                                     preparation_identity(file_sha256(source), probe, {})['audio'])
    assert origin.read_bytes() == before
    assert not (job/'audio.wav').exists()
    assert read_json(job/'transcript.json')['repair_version'] == REPAIR_VERSION


def test_existing_unrepaired_asr_only_runs_repair_with_resolved_pcm(prepared):
    source, job, _, origin = prepared
    atomic_json(job/'transcript.json', {'words': [], 'segments': []})
    def repair(command, log, cancelled, **options):
        assert '--repair-only' in command and Path(command[3]) == origin
        atomic_json(job/'transcript.json', {'words': [], 'segments': [], 'repair_version': REPAIR_VERSION})
    with patch('app.asr_audio.prepare_asr_audio', return_value=origin) as pcm, \
            patch.object(analysis, 'run_process', side_effect=repair) as infer:
        reach_perception(source, job)
    pcm.assert_called_once()
    infer.assert_called_once()


def test_missing_provided_asr_never_silently_starts_transcription(prepared):
    source, job, _, _ = prepared
    atomic_json(job/'analysis-settings.json', {'transcript_mode': 'provided',
                                              'transcript_source_sha256': file_sha256(source)})
    with patch.object(analysis, 'setup_environment'), \
            patch('app.asr_audio.prepare_asr_audio', side_effect=AssertionError('no supplied ASR')) as pcm, \
            patch.object(analysis, 'run_process', side_effect=AssertionError('no supplied ASR')) as infer:
        with pytest.raises(ValueError, match='Отсутствует предоставленный ASR'):
            analysis._analyze(job, source, Mock(), lambda: False, Mock())
    pcm.assert_not_called()
    infer.assert_not_called()
