"""Measured, source-clock PCM near proposed cuts; no semantic sound labels."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import uuid
import wave

import numpy as np

from .cancellation import check_cancelled
from .checkpoint_lineage import ancestors
from .config import FFMPEG, ROOT
from .content_identity import digest, file_sha256
from .json_store import atomic_json, read_json
from .media_probe import run_process
from .source_identity import check_source, source_identity
from .source_ranges import merge_ranges

VERSION = 1
RATE = 16000
STEP = .02  # 320 samples; timing resolution, not a semantic shot length.
REACH = 1.5  # Existing maximum speech-tail repair scope; no unlimited extension.
POLICY = {'version': VERSION, 'rate': RATE, 'step': STEP, 'reach': REACH,
          'stable_frames': 3, 'relative_contrast_db': 6.0}


def _inside(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    relative = path.relative_to(root)
    current = root
    for name in (None, *relative.parts):
        if name is not None:
            current = current / name
        if current.is_symlink() or current.is_junction():
            raise ValueError('Перенаправление в аудиоданных недопустимо')
    def canonical(value):
        value = str(value.resolve())
        return Path(value[4:] if os.name == 'nt' and re.match(r'^\\\\\?\\[A-Za-z]:\\', value) else value)
    if canonical(path) != canonical(root) / relative:
        raise ValueError('Аудиоданные выходят за каталог задания')
    return path


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Invalid measured audio number')
    return value


def validate_evidence(evidence, source_sha, duration):
    if (not isinstance(evidence, dict) or evidence.get('policy') != POLICY
            or evidence.get('source_sha256') != source_sha
            or evidence.get('duration') != duration
            or type(evidence.get('audio_stream')) is not int or evidence['audio_stream'] < 0
            or not isinstance(evidence.get('frames'), list)):
        raise ValueError('Audio boundary evidence changed')
    previous = 0.
    for row in evidence['frames']:
        if (not isinstance(row, list) or len(row) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                or not 0 <= row[0] < row[1] <= duration+.000002
                or row[0] < previous-.000002 or row[1]-row[0] > STEP+.000002
                or not -120 <= row[2] <= 0 or not -120 <= row[3] <= 0):
            raise ValueError('Invalid source-clock audio frame')
        previous = row[1]
    return evidence


def _pcm_frames(path, log, start, end, cancelled=lambda: False):
    packets = re.findall(r'\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([0-9.eE+-]+).*?\bnb_samples:(\d+)',
                         log.read_text('utf-8', errors='replace'))
    if not packets:
        with wave.open(str(path), 'rb') as audio:
            if not audio.getnframes():
                return []  # A delayed/shorter stream has no PCM here; not silence proof.
        raise ValueError('Нет исходных PTS измеренного звука')
    frames = []
    with wave.open(str(path), 'rb') as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (RATE, 1, 2):
            raise ValueError('Invalid boundary PCM format')
        prior = None
        group_start, chunks = None, []
        def flush():
            if not chunks:
                return
            pcm = np.concatenate(chunks)
            for offset in range(0, len(pcm), round(RATE*STEP)):
                block = pcm[offset:offset+round(RATE*STEP)]
                a, b = group_start+offset/RATE, group_start+(offset+len(block))/RATE
                left, right = max(start, a), min(end, b)
                if right <= left:
                    continue
                block = block[round((left-a)*RATE):round((right-a)*RATE)]
                if not len(block):
                    continue
                rms = float(np.sqrt(np.mean(block**2)))
                peak = float(np.max(np.abs(block)))
                db = lambda level: round(max(-120., 20*math.log10(max(level, 1e-6))), 5)
                frames.append([round(left, 6), round(right, 6), db(rms), db(peak)])
        for value, count in packets:
            check_cancelled(cancelled)
            timestamp, count = float(value), int(count)
            if not math.isfinite(timestamp) or count <= 0:
                raise ValueError('Invalid measured audio PTS')
            if prior is not None and timestamp < prior-2/RATE:
                raise ValueError('Overlapping source audio PTS')
            pcm = np.frombuffer(audio.readframes(count), dtype='<i2').astype(np.float64) / 32768
            if len(pcm) != count:
                raise ValueError('Audio packet/WAV sample count mismatch')
            # Do not join across missing PTS. A gap is missing evidence, not silence.
            if prior is not None and abs(timestamp-prior) > 2/RATE:
                flush()
                chunks = []
            if not chunks:
                group_start = timestamp
            chunks.append(pcm)
            prior = timestamp+count/RATE
        flush()
        if audio.readframes(1):
            raise ValueError('Unmapped PCM samples')
    return frames


def measure_edges(source, source_sha, probe, core, job_dir, cancelled=lambda: False, *, create=True):
    """Decode selected edge neighborhoods once; unchanged ancestry is read-only."""
    source, job_dir = Path(source), Path(job_dir)
    _inside(source, ROOT)
    duration = _number(probe['duration'])
    if duration <= 0 or type(probe.get('audio_stream', 0)) is not int or probe.get('audio_stream', 0) < 0:
        raise ValueError('Invalid measured audio source')
    _inside(job_dir, ROOT)
    key = source_identity(source, cancelled)
    if key['sha256'] != source_sha:
        raise ValueError('Measured audio source changed')
    core = merge_ranges(core)
    if not core:
        raise ValueError('Measured audio needs proposed cuts')
    windows = merge_ranges([{'start': max(0., edge-REACH), 'end': min(duration, edge+REACH)}
        for span in core for edge in (span['start'], span['end'])])
    if any(span['start'] < 0 or span['end'] > duration for span in core):
        raise ValueError('Audio edges leave source')
    tool = FFMPEG.stat()
    identity = {'source': source_sha, 'duration': duration, 'audio_stream': probe.get('audio_stream', 0),
        'windows': windows, 'policy': POLICY, 'implementation': file_sha256(Path(__file__)),
        'tool': [tool.st_size, tool.st_mtime_ns]}
    signature = digest(identity)
    for owner in (job_dir, *ancestors(job_dir)):
        check_cancelled(cancelled)
        path = _inside(owner/'audio-boundaries'/(signature+'.json'), owner)
        try:
            saved = read_json(path)
            if (isinstance(saved, dict) and saved.get('identity') == identity
                    and digest(saved['evidence']) == saved['evidence_sha256']):
                evidence = validate_evidence(saved['evidence'], source_sha, duration)
                check_source(source, {k: key[k] for k in ('size', 'mtime_ns', 'ctime_ns')}, cancelled)
                return evidence
        except InterruptedError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            pass
    if not create:
        raise ValueError('Нет измерений звука для этих границ; требуется обновление монтажа')
    folder = _inside(job_dir/'audio-boundaries'/('work-'+uuid.uuid4().hex[:12]), job_dir)
    folder.mkdir(parents=True)
    rows = []
    for index, window in enumerate(windows):
        check_cancelled(cancelled)
        path, log = folder/f'{index:03}.wav', folder/f'{index:03}.log'
        run_process([FFMPEG, '-y', '-hide_banner', '-nostdin', '-copyts',
            '-ss', f"{window['start']:.6f}", '-t', f"{window['end']-window['start']:.6f}",
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm', '-i', source,
            '-map', f"0:a:{identity['audio_stream']}", '-vn', '-ac', '1', '-ar', str(RATE),
            '-af', 'aresample=16000,ashowinfo', '-c:a', 'pcm_s16le', path], log, cancelled, timeout=90)
        rows.extend(_pcm_frames(path, log, window['start'], window['end'], cancelled))
    evidence = {'policy': dict(POLICY), 'source_sha256': source_sha, 'duration': duration,
                'audio_stream': identity['audio_stream'], 'windows': windows, 'frames': rows}
    validate_evidence(evidence, source_sha, duration)
    check_source(source, {k: key[k] for k in ('size', 'mtime_ns', 'ctime_ns')}, cancelled)
    check_cancelled(cancelled)
    atomic_json(_inside(job_dir/'audio-boundaries'/(signature+'.json'), job_dir),
                {'identity': identity, 'evidence': evidence, 'evidence_sha256': digest(evidence)})
    return evidence


def _valleys(rows):
    levels = np.asarray([row[2] for row in rows])
    if not len(levels):
        return []
    low, high = np.quantile(levels, [.2, .8])
    if high-low < POLICY['relative_contrast_db'] and high > -119:
        return []  # Steady background cannot establish a quiet transition.
    threshold = low+(high-low)*.2
    groups = []
    for row in rows:
        if row[2] > threshold:
            continue
        if groups and abs(groups[-1][-1][1]-row[0]) <= 2/RATE:
            groups[-1].append(row)
        else:
            groups.append([row])
    # Use elapsed PCM time: codec packet boundaries need not equal STEP.
    return [(group[0][0], group[-1][1]) for group in groups
            if group[-1][1]-group[0][0] >= POLICY['stable_frames']*STEP-2/RATE]


def adjust_ranges(core, fallback, transcript, duration, evidence, blocked=()):
    """Prefer nearby measured valleys, retaining core and omitted-word barriers.

    This is a technical proposal before native review. A valley proves neither
    a complete scream nor an action; absence is reported, never called silence.
    """
    core = merge_ranges(core)
    words = transcript.get('words', [])
    adjusted, observations = [], []
    for span in core:
        old = next(row for row in fallback if row['start'] <= span['start'] and row['end'] >= span['end'])
        result = dict(old)
        for side in ('start', 'end'):
            edge = span[side]
            low, high = max(0., edge-REACH), min(duration, edge+REACH)
            if side == 'start':
                low = max(low, max((w['end']+2*STEP for w in words if w['end'] <= edge), default=0.))
                low = min(edge, max([low, *[r['end'] for r in blocked if r['start'] < edge and r['end'] <= edge]]))
                high = edge
            else:
                high = min(high, min((w['start']-2*STEP for w in words if w['start'] >= edge), default=duration))
                high = max(edge, min([high, *[r['start'] for r in blocked if edge <= r['start'] < high]]))
                low = edge
            result[side] = min(edge, max(low, old[side])) if side == 'start' else max(edge, min(high, old[side]))
            rows = [r for r in evidence['frames'] if edge-REACH <= r[0] and r[1] <= edge+REACH]
            candidates = [max(low, min(high, max(a+1.5*STEP, min(b-1.5*STEP, edge)))) for a, b in _valleys(rows)
                          if max(a, low) < min(b, high)]
            chosen = min(candidates, key=lambda t: abs(t-edge)) if candidates else None
            status = 'no_quiet_transition'
            if not any(r[0]-2/RATE <= edge <= r[1]+2/RATE for r in rows):
                status = 'missing_pcm_coverage'
            if chosen is not None:
                # Continuous measured coverage between edge and valley is mandatory.
                a, b = min(chosen, edge), max(chosen, edge)
                cover = a
                for row in rows:
                    if row[1] <= cover or row[0] >= b:
                        continue
                    if row[0] > cover+2/RATE:
                        break
                    cover = max(cover, row[1])
                if cover >= b-2/RATE:
                    result[side] = round(chosen, 6)
                    status = 'measured_relative_valley'
                else:
                    status = 'missing_pcm_coverage'
            observations.append({'side': side, 'core_time': edge, 'before': old[side],
                'after': result[side], 'status': status,
                'semantic_completion': 'not_established_by_waveform'})
        adjusted.append(result)
    return merge_ranges(adjusted), observations
