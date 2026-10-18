"""Producer receipts for full ASR PCM, reused only through explicit lineage."""
from __future__ import annotations

import os
import wave
from pathlib import Path

from .cancellation import check_cancelled
from .checkpoint_lineage import LineageError, ancestors
from .config import FFMPEG
from .content_identity import file_sha256
from .json_store import atomic_json, read_json
from .media_probe import run_process


def _owned(root, name):
    root = Path(root).absolute()
    path = root / name
    for item in (*reversed(root.parents), root, path):
        if item.is_symlink() or item.is_junction():
            raise ValueError('ASR audio path contains a redirect')
    if path.resolve().parent != root.resolve():
        raise ValueError('ASR audio escapes its producer')
    return path


def _pcm(path, cancelled):
    check_cancelled(cancelled)
    with wave.open(str(path), 'rb') as stream:
        frames = stream.getnframes()
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                stream.getcomptype()) != (1, 2, 16000, 'NONE') or frames <= 0:
            raise ValueError('Invalid ASR PCM format')
        remaining = frames
        while remaining:
            check_cancelled(cancelled)
            count = min(remaining, 65536)
            if len(stream.readframes(count)) != count * 2:
                raise ValueError('Truncated ASR PCM')
            remaining -= count
    return {'channels': 1, 'sample_width': 2, 'sample_rate': 16000,
            'compression': 'NONE', 'frames': frames,
            'size': path.stat().st_size, 'sha256': file_sha256(path, cancelled)}


def _cached(root, expected, cancelled):
    try:
        path = _owned(root, 'audio.wav')
        receipt = read_json(_owned(root, 'audio.receipt.json'))
        if not isinstance(receipt, dict) or receipt.get('identity') != expected or receipt.get('producer_job_id') != root.name:
            return None
        return path if receipt.get('pcm') == _pcm(path, cancelled) else None
    except InterruptedError:
        raise
    except (OSError, ValueError, EOFError, wave.Error):
        return None


def _check_inputs(source, identity, cancelled):
    if (file_sha256(source, cancelled) != identity['source_sha256']
            or file_sha256(FFMPEG, cancelled) != identity['ffmpeg_sha256']):
        raise ValueError('ASR source or FFmpeg bytes changed during preparation')


def prepare_asr_audio(source: Path, source_sha256: str, probe: dict,
                      preparation_audio: dict, job_dir: Path,
                      cancelled=lambda: False) -> Path:
    """Validate the whole ancestry before reading any PCM, including our own."""
    stream = probe.get('audio_stream', 0)
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64
            or any(c not in '0123456789abcdef' for c in source_sha256)
            or type(stream) is not int or stream < 0
            or not isinstance(preparation_audio, dict)
            or preparation_audio.get('source') != source_sha256
            or type(preparation_audio.get('audio_stream')) is not int
            or preparation_audio.get('audio_stream') != stream
            or preparation_audio.get('extraction') != 'mono-pcm16-16000-v1'):
        raise ValueError('Invalid ASR preparation contract')
    lineage = ancestors(job_dir)
    # Reject redirected storage components before any PCM or receipt lookup.
    _owned(job_dir, 'audio.wav')
    _owned(job_dir, 'audio.receipt.json')
    if lineage and read_json(Path(job_dir) / 'analysis.meta.json', {}).get('source') != source_sha256:
        raise LineageError('ASR source does not match checkpoint ancestry')
    check_cancelled(cancelled)
    identity = {'version': 1, 'source_sha256': source_sha256,
                'audio_stream': probe.get('audio_stream', 0),
                'preparation_audio': preparation_audio,
                'ffmpeg_sha256': file_sha256(FFMPEG, cancelled)}
    _check_inputs(source, identity, cancelled)
    for root in (Path(job_dir), *lineage):
        cached = _cached(root, identity, cancelled)
        if cached is not None:
            _check_inputs(source, identity, cancelled)
            return cached
    audio = _owned(job_dir, 'audio.wav')
    receipt = _owned(job_dir, 'audio.receipt.json')
    partial = _owned(job_dir, 'audio.partial.wav')
    try:
        partial.unlink(missing_ok=True)
        run_process([FFMPEG, '-y', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', source, '-map',
                     f"0:a:{identity['audio_stream']}", '-vn', '-ar', '16000',
                     '-ac', '1', '-c:a', 'pcm_s16le', partial],
                    _owned(job_dir, 'audio.log'), cancelled)
        pcm = _pcm(partial, cancelled)
        _check_inputs(source, identity, cancelled)
        check_cancelled(cancelled)
        os.replace(partial, audio)
        atomic_json(receipt, {'identity': identity, 'producer_job_id': Path(job_dir).name,
                              'pcm': pcm})
        return audio
    finally:
        partial.unlink(missing_ok=True)
