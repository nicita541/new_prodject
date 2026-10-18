"""Clean media reuse requires explicit lineage and a verified decode receipt."""
import copy
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app import clean_parts
from app.checkpoint_lineage import LineageError, link
from app.config import FFMPEG
from app.content_identity import file_sha256
from app.json_store import atomic_json, read_json
from app.media import run_command


@pytest.fixture
def scenario(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original source')
    probe = {'width': 320, 'height': 180, 'audio_stream': 1}
    part = {'index': 1, 'duration': 2.0, 'cuts': [{'start': 1.0, 'end': 3.0}],
            'subtitles': [{'start': 0, 'end': 1, 'text': 'Current caption'}]}
    owner = str(uuid.uuid4())

    def job():
        root = tmp_path / 'jobs' / str(uuid.uuid4())
        atomic_json(root / 'job.json', {'id': root.name, 'episode_id': owner})
        atomic_json(root / 'analysis.meta.json', {'source': file_sha256(source)})
        atomic_json(root / 'source.json', {'path': str(source)})
        return root

    parent, child = job(), job()
    link(parent, child, source_sha256=file_sha256(source), episode_id=owner)
    return source, probe, part, parent, child, job


def cache(source, probe, part, root):
    identity = clean_parts.clean_identity(source, part, probe)
    path = root / 'clean' / f"part_{part['index']:03}" / identity / 'clean.mkv'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'verified clean media' * 100)
    atomic_json(path.with_suffix('.json'), {'version': clean_parts.CLEAN_VERSION,
        'full_decode_version': clean_parts.FULL_DECODE_VERSION, 'identity': identity,
        'size': path.stat().st_size, 'sha256': file_sha256(path)})
    return path


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob('*') if path.is_file()}


def test_ancestor_media_is_returned_readonly_without_copy_even_with_new_part_rank(scenario):
    source, probe, part, parent, child, _ = scenario
    origin = cache(source, probe, part, parent)
    before = snapshot(parent)
    changed = {**copy.deepcopy(part), 'index': 7, 'subtitles': []}
    with patch.object(clean_parts, 'run_render_command', side_effect=AssertionError('unexpected render')):
        result = clean_parts.prepare_clean_part(source, changed, probe, child)
    assert result[0] == origin
    assert result[1]['index'] == 7
    assert result[1]['subtitles'] == []
    assert result[2]['audio_stream'] == 0
    assert result[3] is True
    assert snapshot(parent) == before
    assert not (child / 'clean').exists()


def test_no_equal_source_store_scan_and_multigeneration_lineage(scenario):
    source, probe, part, parent, child, job = scenario
    origin = cache(source, probe, part, parent)
    unrelated = job()
    assert clean_parts.prepare_clean_part(source, part, probe, unrelated, create=False)[0] == source
    third = job()
    link(child, third, source_sha256=file_sha256(source),
         episode_id=read_json(child / 'job.json')['episode_id'])
    assert clean_parts.prepare_clean_part(source, part, probe, third, create=False)[0] == origin


@pytest.mark.parametrize('corruption', ['same_stat_bytes', 'old_version', 'decode_version', 'receipt', 'missing'])
def test_corrupt_ancestor_is_safe_miss_without_receipt_repair(scenario, corruption):
    source, probe, part, parent, child, _ = scenario
    path = cache(source, probe, part, parent)
    receipt = path.with_suffix('.json')
    if corruption == 'same_stat_bytes':
        stamp = path.stat()
        path.write_bytes(b'x' * stamp.st_size)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif corruption == 'receipt':
        receipt.write_bytes(b'{torn')
    elif corruption == 'missing':
        path.unlink()
    else:
        row = read_json(receipt)
        row['version' if corruption == 'old_version' else 'full_decode_version'] = 0
        atomic_json(receipt, row)
    before = snapshot(parent)
    result = clean_parts.prepare_clean_part(source, part, probe, child, create=False)
    assert result == (source, part, probe, False)
    assert snapshot(parent) == before
    assert not (child / 'clean').exists()


def test_foreign_owner_fails_closed_before_ancestor_media_lookup(scenario):
    source, probe, part, parent, child, _ = scenario
    cache(source, probe, part, parent)
    atomic_json(parent / 'job.json', {'id': parent.name, 'episode_id': str(uuid.uuid4())})
    with pytest.raises(LineageError), patch.object(clean_parts, '_cached', return_value=False):
        clean_parts.prepare_clean_part(source, part, probe, child)


def test_same_size_source_mutation_preserving_mtime_changes_clean_identity(scenario):
    source, probe, part, parent, child, _ = scenario
    cache(source, probe, part, parent)
    old = clean_parts.clean_identity(source, part, probe)
    stamp = source.stat()
    source.write_bytes(b'X' * stamp.st_size)
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert clean_parts.clean_identity(source, part, probe) != old
    assert clean_parts.prepare_clean_part(source, part, probe, child, create=False)[0] == source


def test_redirected_ancestor_clean_directory_is_never_used(scenario):
    source, probe, part, parent, child, _ = scenario
    cache(source, probe, part, parent)
    original = Path.is_junction
    with patch.object(Path, 'is_junction', lambda path: path == parent / 'clean' or original(path)):
        assert clean_parts.prepare_clean_part(source, part, probe, child, create=False)[0] == source


def test_redirected_local_media_is_rejected_before_write(scenario):
    source, probe, part, _, child, _ = scenario
    with patch.object(Path, 'is_junction', lambda path: path == child / 'clean'):
        with pytest.raises(ValueError, match='перенаправление'):
            clean_parts.prepare_clean_part(source, part, probe, child)


def fake_media(probe, part):
    return {'streams': [{'codec_type': 'video', 'codec_name': 'h264',
                         'width': probe['width'], 'height': probe['height']},
                        {'codec_type': 'audio', 'codec_name': 'pcm_s16le'}],
            'format': {'duration': part['duration']}}


@pytest.mark.parametrize('failure', [None, 'decode', 'cancel', 'source_mutation'])
def test_build_requires_complete_cancellable_decode_before_publication(scenario, failure):
    source, probe, part, _, child, _ = scenario
    calls = []
    cancelled = [False]

    def render(args, workdir, duration, check, on_progress=None):
        calls.append(args)
        if args[-1] != '-':
            Path(args[-1]).write_bytes(b'new clean media' * 100)
            return
        assert '-xerror' in args and args[args.index('-err_detect') + 1] == 'explode'
        assert args[args.index('-f') + 1] == 'null'
        assert args.count('-map') == 2
        if failure == 'decode':
            raise RuntimeError('damaged packet at end')
        if failure == 'cancel':
            cancelled[0] = True
            raise InterruptedError('cancelled decoder')
        if failure == 'source_mutation':
            source.write_bytes(b'changed during render')

    with patch.object(clean_parts, 'run_render_command', side_effect=render), \
            patch.object(clean_parts, 'inspect_media', return_value=fake_media(probe, part)):
        if failure:
            expected = {'decode': RuntimeError, 'cancel': InterruptedError, 'source_mutation': ValueError}[failure]
            with pytest.raises(expected):
                clean_parts.prepare_clean_part(source, part, probe, child, lambda: cancelled[0])
            assert not list((child / 'clean').glob('**/clean.json'))
            assert not list((child / 'clean').glob('**/clean.mkv'))
        else:
            path, _, _, hit = clean_parts.prepare_clean_part(source, part, probe, child)
            assert hit is False
            record = read_json(path.with_suffix('.json'))
            assert record['sha256'] == file_sha256(path)
            assert record['full_decode_version'] == clean_parts.FULL_DECODE_VERSION
    assert len(calls) == 2


def test_cancellation_while_hashing_ancestor_propagates_without_local_build(scenario):
    source, probe, part, parent, child, _ = scenario
    cache(source, probe, part, parent)
    def hash_or_cancel(path, cancelled=lambda: False):
        if path.name == 'clean.mkv':
            raise InterruptedError('stop hash')
        return file_sha256(path, cancelled)
    with patch.object(clean_parts, 'file_sha256', side_effect=hash_or_cancel), \
            patch.object(clean_parts, 'run_render_command', side_effect=AssertionError('unexpected render')):
        with pytest.raises(InterruptedError, match='stop hash'):
            clean_parts.prepare_clean_part(source, part, probe, child)
    assert not (child / 'clean').exists()


def test_corrupt_ancestor_regenerates_only_the_current_job(scenario):
    source, probe, part, parent, child, _ = scenario
    origin = cache(source, probe, part, parent)
    origin.write_bytes(b'x' * origin.stat().st_size)
    before = snapshot(parent)
    calls = []

    def render(args, workdir, duration, cancelled, on_progress=None):
        calls.append(workdir)
        assert workdir.is_relative_to(child)
        if args[-1] != '-':
            Path(args[-1]).write_bytes(b'replacement clean media' * 100)

    with patch.object(clean_parts, 'run_render_command', side_effect=render), \
            patch.object(clean_parts, 'inspect_media', return_value=fake_media(probe, part)):
        result = clean_parts.prepare_clean_part(source, part, probe, child)
    assert result[0].is_relative_to(child)
    assert result[3] is False
    assert len(calls) == 2
    assert snapshot(parent) == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended drive namespace')
def test_equivalent_windows_extended_namespace_does_not_fake_an_escape(tmp_path):
    target = tmp_path / 'clean.json'
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return Path('\\\\?\\' + str(result)) if path == target else result

    with patch.object(Path, 'resolve', resolve):
        assert clean_parts._owned_path(tmp_path, target) == target


def test_real_decoded_ancestor_reuses_media_without_ffmpeg_or_copy(scenario):
    source, probe, part, parent, child, _ = scenario
    run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'testsrc2=size=320x180:rate=30', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=48000', '-t', '3.2',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], source.parent)
    sha = file_sha256(source)
    for root in (parent, child):
        atomic_json(root / 'analysis.meta.json', {'source': sha})
    lineage = read_json(child / 'checkpoint-lineage.json')
    atomic_json(child / 'checkpoint-lineage.json', {**lineage, 'source_sha256': sha})
    probe = {**probe, 'audio_stream': 0}
    origin = clean_parts.prepare_clean_part(source, part, probe, parent)[0]
    before = snapshot(parent)
    with patch.object(clean_parts, 'run_render_command', side_effect=AssertionError('ancestor rerender')):
        result = clean_parts.prepare_clean_part(source, {**part, 'index': 3}, probe, child)
    assert result[0] == origin
    assert result[3] is True
    assert not (child / 'clean').exists()
    assert snapshot(parent) == before
