"""Current bytes, not size/mtime alone, authorize skipping a full decode."""
import hashlib
import os
from unittest.mock import Mock, patch

import pytest

from app.json_store import atomic_json, read_json
from app.media import EXPORT_VALIDATION_VERSION
from app.pipeline import _validated_cached_render


def test_render_fingerprint_tracks_current_music_bytes_with_restored_stat(tmp_path):
    from app.pipeline import _part_render_fingerprint
    track = tmp_path / 'track.mp3'
    track.write_bytes(b'AAAA')
    stamp = track.stat()
    part = {'index': 1, 'duration': 1, 'cuts': [{'start': 0, 'end': 1}]}
    inputs = {'music': {'smart_ducking': False}}
    first = _part_render_fingerprint(part, inputs, track, {})
    track.write_bytes(b'BBBB')
    os.utime(track, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert first != _part_render_fingerprint(part, inputs, track, {})


def cached(path):
    output=path/'part_001.mp4'; output.write_bytes(b'a'*2000)
    srt=output.with_suffix('.srt');srt.write_text('original subtitles','utf-8')
    receipt=path/'part_001.json'
    atomic_json(receipt,{'fingerprint':'same','size':output.stat().st_size,
        'mtime_ns':output.stat().st_mtime_ns,'srt_hash':hashlib.sha256(srt.read_bytes()).hexdigest(),
        'encoder':None})
    return output,receipt


def test_legacy_receipt_requires_one_full_decode_then_current_sha_allows_reuse(tmp_path):
    output,receipt=cached(tmp_path)
    with patch('app.pipeline.validate_export') as validate:
        result=_validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:False)
        assert validate.call_args.kwargs['full_decode'] is True
        assert result['video_sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
        assert result['full_decode_version']==EXPORT_VALIDATION_VERSION
        assert result['encoder'] is None  # unknown legacy encoder stays unknown
        _validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:False)
        assert validate.call_args.kwargs['full_decode'] is False


def test_same_size_same_mtime_tampering_cannot_reuse_export(tmp_path):
    output,receipt=cached(tmp_path)
    with patch('app.pipeline.validate_export') as validate:
        _validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:False)
        stamp=output.stat();output.write_bytes(b'b'*2000)
        os.utime(output,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        validate.reset_mock()
        assert _validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:False) is None
        validate.assert_not_called()


def test_failed_legacy_decode_does_not_publish_receipt_and_cancel_does_not_rerender(tmp_path):
    output,receipt=cached(tmp_path);before=receipt.read_bytes()
    with patch('app.pipeline.validate_export',side_effect=RuntimeError('corrupt packet')):
        assert _validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:False) is None
    assert receipt.read_bytes()==before
    with pytest.raises(InterruptedError):
        _validated_cached_render(output,receipt,'same',{'duration':10},tmp_path,lambda:True)
    assert read_json(receipt).get('video_sha256') is None
