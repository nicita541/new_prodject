"""ASR PCM receipts validate bytes, format and explicit producer ancestry."""
import os
import uuid
import wave
from unittest.mock import patch

import pytest

from app import asr_audio
from app.checkpoint_lineage import LineageError, link
from app.content_identity import file_sha256
from app.json_store import atomic_json, read_json


def wav(path):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x01\x00' * 400)


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    tool = tmp_path / 'ffmpeg.exe'
    tool.write_bytes(b'tool')
    sha = file_sha256(source)
    owner = str(uuid.uuid4())
    def job():
        root = tmp_path / 'jobs' / str(uuid.uuid4())
        atomic_json(root / 'job.json', {'id': root.name, 'episode_id': owner})
        atomic_json(root / 'analysis.meta.json', {'source': sha})
        atomic_json(root / 'source.json', {'path': str(source)})
        return root
    def prepare(root, **kwargs):
        return asr_audio.prepare_asr_audio(source, sha, {'audio_stream': 1},
            {'source': sha, 'audio_stream': 1, 'extraction': 'mono-pcm16-16000-v1'}, root, **kwargs)
    def extract(command, log, cancelled):
        assert command[command.index('-map') + 1] == '0:a:1'
        assert command[command.index('-protocol_whitelist') + 1] == 'file,pipe'
        wav(command[-1])
    with patch.object(asr_audio, 'FFMPEG', tool), patch.object(asr_audio, 'run_process', side_effect=extract) as runner:
        yield job, prepare, sha, owner, runner, tool


def test_own_and_explicit_multigeneration_reuse(setup):
    job, prepare, sha, owner, runner, _ = setup
    parent, middle, child = job(), job(), job()
    origin = prepare(parent)
    original = {p.name: p.read_bytes() for p in parent.iterdir()}
    assert prepare(parent) == origin
    link(parent, middle, source_sha256=sha, episode_id=owner)
    link(middle, child, source_sha256=sha, episode_id=owner)
    assert prepare(child) == origin
    assert not (child / 'audio.wav').exists()
    assert {p.name: p.read_bytes() for p in parent.iterdir()} == original
    assert runner.call_count == 1
    prepare(job())
    assert runner.call_count == 2


@pytest.mark.parametrize('damage', ['same_stat', 'truncated', 'missing_receipt', 'malformed', 'stream', 'contract', 'tool'])
def test_invalid_ancestor_is_readonly_miss(setup, damage):
    job, prepare, sha, owner, runner, tool = setup
    parent, child = job(), job()
    audio = prepare(parent)
    receipt = parent / 'audio.receipt.json'
    if damage == 'same_stat':
        stat = audio.stat()
        data = bytearray(audio.read_bytes()); data[-1] ^= 1
        audio.write_bytes(data)
        os.utime(audio, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif damage == 'truncated':
        audio.write_bytes(audio.read_bytes()[:-2])
        row = read_json(receipt); row['pcm'].update(size=audio.stat().st_size, sha256=file_sha256(audio))
        atomic_json(receipt, row)
    elif damage == 'missing_receipt':
        receipt.unlink()
    elif damage == 'malformed':
        receipt.write_text('{bad')
    elif damage == 'tool':
        tool.write_bytes(b'TOOL')
    else:
        row = read_json(receipt)
        row['identity']['audio_stream' if damage == 'stream' else 'preparation_audio'] = 99
        atomic_json(receipt, row)
    before = {p.name: p.read_bytes() for p in parent.iterdir()}
    link(parent, child, source_sha256=sha, episode_id=owner)
    assert prepare(child) == child / 'audio.wav'
    assert {p.name: p.read_bytes() for p in parent.iterdir()} == before
    assert runner.call_count == 2


@pytest.mark.parametrize('damage', ['owner', 'source', 'cycle', 'missing'])
def test_complete_lineage_checked_before_own_pcm(setup, damage):
    job, prepare, sha, owner, _, _ = setup
    parent, child = job(), job()
    prepare(child)
    link(parent, child, source_sha256=sha, episode_id=owner)
    if damage == 'owner':
        atomic_json(parent / 'job.json', {'id': parent.name, 'episode_id': str(uuid.uuid4())})
    elif damage == 'source':
        atomic_json(parent / 'analysis.meta.json', {'source': 'f' * 64})
    elif damage == 'missing':
        (parent / 'source.json').unlink()
    else:
        atomic_json(parent / 'checkpoint-lineage.json', {'version': 1, 'parent_job_id': child.name,
                    'source_sha256': sha, 'episode_id': owner})
    with patch.object(asr_audio, '_cached', side_effect=AssertionError('premature PCM access')):
        with pytest.raises(LineageError):
            prepare(child)


def test_cancelled_extraction_removes_only_own_partial(setup):
    job, prepare, sha, owner, runner, _ = setup
    parent, child = job(), job()
    (parent / 'audio.wav').write_bytes(b'legacy')
    link(parent, child, source_sha256=sha, episode_id=owner)
    def cancel(command, log, cancelled):
        wav(command[-1])
        raise InterruptedError('cancelled')
    runner.side_effect = cancel
    with pytest.raises(InterruptedError):
        prepare(child)
    assert not (child / 'audio.partial.wav').exists()
    assert (parent / 'audio.wav').read_bytes() == b'legacy'


def test_legacy_own_pcm_is_reextracted_and_cancellation_propagates(setup):
    job, prepare, _, _, runner, _ = setup
    root = job()
    wav(root / 'audio.wav')
    prepare(root)
    assert runner.call_count == 1
    with patch.object(asr_audio, '_pcm', side_effect=InterruptedError('cancelled')):
        with pytest.raises(InterruptedError):
            prepare(root)
    assert runner.call_count == 1


@pytest.mark.parametrize('kind', ['audio.wav', 'audio.receipt.json'])
def test_redirected_ancestor_media_is_safe_miss(setup, kind):
    job, prepare, sha, owner, runner, _ = setup
    parent, child = job(), job()
    prepare(parent)
    path = parent / kind
    outside = parent.parent / ('outside-' + kind)
    path.replace(outside)
    try:
        path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f'Filesystem does not permit symbolic links: {error}')
    link(parent, child, source_sha256=sha, episode_id=owner)
    before = outside.read_bytes()
    assert prepare(child) == child / 'audio.wav'
    assert outside.read_bytes() == before
    assert path.is_symlink()
    assert runner.call_count == 2


@pytest.mark.parametrize('field,value', [
    ('stream', True), ('stream', -1), ('stream', 1.0),
    ('preparation_stream', True), ('extraction', 'future-algorithm'),
    ('sha', 'x' * 64), ('sha', 'a' * 63), ('sha', True),
])
def test_invalid_contract_precedes_media_access(setup, field, value):
    job, _, sha, _, runner, _ = setup
    root = job()
    probe = {'audio_stream': 1}
    preparation = {'source': sha, 'audio_stream': 1, 'extraction': 'mono-pcm16-16000-v1'}
    if field == 'stream':
        probe['audio_stream'] = value
        preparation['audio_stream'] = value
    elif field == 'preparation_stream':
        preparation['audio_stream'] = value
    elif field == 'extraction':
        preparation['extraction'] = value
    else:
        sha = value
        preparation['source'] = value
    with patch.object(asr_audio, '_cached', side_effect=AssertionError('PCM lookup')):
        with pytest.raises(ValueError):
            asr_audio.prepare_asr_audio(root.parent / 'source.mp4', sha, probe, preparation, root)
    runner.assert_not_called()


def test_parent_storage_junction_rejected_before_pcm_access(setup):
    job, prepare, _, _, runner, _ = setup
    root = job()
    path_type = type(root)
    actual = path_type.is_junction
    def junction(path):
        return path == root.parent or actual(path)
    with patch.object(path_type, 'is_junction', junction), \
            patch.object(asr_audio, '_cached', side_effect=AssertionError('PCM lookup')), \
            patch.object(asr_audio, 'file_sha256', side_effect=AssertionError('media read')):
        with pytest.raises(ValueError, match='redirect'):
            prepare(root)
    runner.assert_not_called()


@pytest.mark.parametrize('mutate', ['source', 'tool'])
def test_same_stat_input_mutation_during_extraction_is_not_published(setup, mutate):
    job, prepare, _, _, runner, tool = setup
    root = job()
    source = root.parent.parent / 'source.mp4'
    target = source if mutate == 'source' else tool
    original, stamp = target.read_bytes(), target.stat()
    def changing_extract(command, log, cancelled):
        wav(command[-1])
        target.write_bytes(b'X' * len(original))
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    runner.side_effect = changing_extract
    with pytest.raises(ValueError, match='bytes changed'):
        prepare(root)
    assert not (root / 'audio.wav').exists()
    assert not (root / 'audio.receipt.json').exists()
    assert not (root / 'audio.partial.wav').exists()
    target.write_bytes(original)
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    runner.side_effect = lambda command, log, cancelled: wav(command[-1])
    assert prepare(root) == root / 'audio.wav'
    assert runner.call_count == 2


def test_input_mutation_during_cache_validation_rejects_reuse(setup):
    job, prepare, _, _, runner, _ = setup
    root = job()
    prepare(root)
    source = root.parent.parent / 'source.mp4'
    original_pcm = asr_audio._pcm
    def changing_validation(path, cancelled):
        result = original_pcm(path, cancelled)
        source.write_bytes(b'changed')
        return result
    with patch.object(asr_audio, '_pcm', side_effect=changing_validation):
        with pytest.raises(ValueError, match='bytes changed'):
            prepare(root)
    assert runner.call_count == 1
