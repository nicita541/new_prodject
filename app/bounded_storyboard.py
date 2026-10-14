"""Small source-only storyboards with verified presentation timestamps."""
from __future__ import annotations


import hashlib
import json
import math
import re
import uuid
from bisect import bisect_left
from pathlib import Path

from PIL import Image, ImageDraw

from app.cancellation import check_cancelled as _check
from .source_identity import source_identity as _source_identity, source_stamp as _stamp, check_source as _unchanged

from .config import FFMPEG, FFPROBE, ROOT
from app.json_store import analysis_json as atomic_json
from .media_probe import run_process

BOUNDED_STORYBOARD_VERSION = 3
# One shared capacity for chunk planner and the physical storyboard renderer.
# Keeping separate 18/12 defaults caused real-model tests to abort with a
# ValueError in scene 2 before issuing their next VLM request.
MAX_INFERENCE_FRAMES = 18
MAX_PAGED_INFERENCE_FRAMES = 2 * MAX_INFERENCE_FRAMES
POLICY = {'max_frames': MAX_INFERENCE_FRAMES, 'context_frames': 2, 'sampling_interval': .5,
          'thumbnail_width': 320, 'thumbnail_height': 180, 'columns': 3, 'caption_height': 24}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Storyboard timestamps must be finite numbers')
    return float(value)


def _digest(path, cancelled):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(1024*1024):
            _check(cancelled)
            result.update(block)
    _check(cancelled)
    return result.hexdigest()


def _pts(log):
    text = log.read_text('utf-8', errors='replace')
    base = re.search(r'config in time_base:\s*(\d+)/(\d+)', text)
    frame = re.search(r'\bn:\s*\d+\s+pts:\s*([+-]?\d+)\s+pts_time:', text)
    if base is None or frame is None or int(base[2]) == 0:
        raise ValueError('FFmpeg did not report a source frame timestamp')
    pts = int(frame[1])
    return pts*int(base[1])/int(base[2]), pts, f'{base[1]}/{base[2]}'


def _requested(start, end, times, context, max_frames=MAX_INFERENCE_FRAMES):
    if type(max_frames) is not int or not 1 <= max_frames <= MAX_PAGED_INFERENCE_FRAMES:
        raise ValueError('Invalid storyboard frame limit')
    cap = POLICY['context_frames'] if context else max_frames
    if times is None:
        if context:
            result = sorted(set([start, max(start, end-.05)]))
        else:
            count = math.ceil((end-start)/POLICY['sampling_interval'])
            if count > cap:
                raise ValueError('Storyboard exceeds frame limit; split the source window')
            result = [start+i*POLICY['sampling_interval'] for i in range(count)]
    else:
        result = list(times)
        if len(result) > cap:
            raise ValueError('Storyboard exceeds frame limit; split the source window')
        result = [_number(value) for value in result]
    if not result or len(result) > cap or any(not start <= value < end for value in result):
        raise ValueError('Storyboard requests must lie inside [start, end)')
    if len(set(result)) != len(result):
        raise ValueError('Duplicate storyboard requests')
    return sorted(result)


def _source_times(source, start, end, directory, cancelled, *, timeout=45):
    key = hashlib.sha256(f'{start!r}:{end!r}'.encode()).hexdigest()
    log = directory/(key+'.probe.log')
    run_process([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-read_intervals',
                 f'{start:.9f}%{end+1:.9f}', '-show_entries',
                 'stream=time_base,start_pts:frame=best_effort_timestamp', '-of', 'json', source],
                log, cancelled, timeout=timeout)
    raw = json.loads(log.read_text('utf-8'))
    streams = raw.get('streams', [])
    if not streams:
        raise ValueError('Source contains no video frames')
    numerator, denominator = map(int, streams[0]['time_base'].split('/'))
    if numerator <= 0 or denominator <= 0:
        raise ValueError('Invalid source video time base')
    values = sorted(set(int(frame['best_effort_timestamp'])*numerator/denominator
                        for frame in raw.get('frames', []) if 'best_effort_timestamp' in frame))
    values = [value for value in values if start <= value < end]
    if not values:
        raise ValueError('Source window contains no video frames')
    first = int(streams[0].get('start_pts', 0))*numerator/denominator
    return values, numerator, denominator, first


def _frame_paths(requested, chosen, start, end, directory, identity, width, height):
    key = hashlib.sha256(json.dumps([identity, start, end, requested, chosen, POLICY, width, height],
                                   sort_keys=True).encode()).hexdigest()
    return tuple(directory/(key+suffix) for suffix in ('.jpg', '.json', '.log'))


def _cached_frame(image, meta, log, requested, chosen, start, end, identity, width, height, cancelled):
    try:
        saved = json.loads(meta.read_text('utf-8'))
        actual, pts, recorded_base = _pts(log)
        if (saved['source'] == identity and saved['version'] == BOUNDED_STORYBOARD_VERSION
                and saved['requested_time'] == requested and saved['time'] == actual == chosen
                and saved['pts'] == pts and saved['time_base'] == recorded_base
                and start <= actual < end and saved['sha256'] == _digest(image, cancelled)
                and saved['log_sha256'] == _digest(log, cancelled)):
            with Image.open(image) as picture:
                if picture.size == (width, height):
                    return saved, image
    except InterruptedError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _decode_frames(source, times, directory, base, width, height, cancelled):
    """One decoder pass for a group of exact original PTS, with actual showinfo evidence."""
    numerator, denominator, first = base
    ticks = sorted({round(value*denominator/numerator) for value in times})
    batch = directory / ('decode-' + uuid.uuid4().hex)
    batch.mkdir()
    log = batch/'decode.log'
    try:
        select = '+'.join(f'eq(pts,{tick})' for tick in ticks)
        seek = max(0, min(times)-first-.25)
        run_process([FFMPEG, '-y', '-hide_banner', '-ss', f'{seek:.9f}',
                     '-copyts', '-i', source, '-map', '0:v:0', '-an', '-vf',
                     f"select='{select}',"
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,showinfo',
                     '-frames:v', str(len(ticks)), '-fps_mode', 'vfr', '-q:v', '2', batch/'%03d.jpg'],
                    log, cancelled, timeout=max(45, (max(times)-min(times))*2+30))
        _check(cancelled)
        text = log.read_text('utf-8', errors='replace')
        config = next((line for line in text.splitlines() if 'config in time_base:' in line), None)
        lines = [line for line in text.splitlines() if re.search(r'\bn:\s*\d+\s+pts:', line)]
        # The decoder may log an extra buffered frame; only emitted JPEGs count.
        outputs = sorted(batch.glob('*.jpg'))
        if config is None or len(outputs) != len(ticks) or len(lines) < len(ticks):
            raise ValueError('FFmpeg did not return all requested source frames')
        result = {}
        for index, (tick, image) in enumerate(zip(ticks, outputs)):
            evidence = config+'\n'+lines[index]+'\n'
            evidence_path = batch/f'{index}.log'
            evidence_path.write_text(evidence, 'utf-8')
            actual, pts, recorded_base = _pts(evidence_path)
            if pts != tick or actual != tick*numerator/denominator:
                raise ValueError('Decoded source frame has a different PTS')
            with Image.open(image) as picture:
                if picture.size != (width, height):
                    raise ValueError('Invalid decoded source frame')
            result[actual] = (image.read_bytes(), evidence, pts, recorded_base)
        return result
    finally:
        for path in batch.iterdir():
            path.unlink()
        batch.rmdir()


def source_frame_files(source, start, end, directory, cancelled, times, *, width=320, height=180):
    """Shared source-only extraction for readable inference and legacy overview pages."""
    source, directory = Path(source).resolve(), Path(directory).resolve()
    directory.relative_to(ROOT.resolve())
    identity = _source_identity(source, cancelled)
    stamp = {key: identity[key] for key in ('size', 'mtime_ns', 'ctime_ns')}
    directory = directory/'.bounded-frames'/identity['sha256']
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory/'source.json', identity)
    available, numerator, denominator, first = _source_times(source, start, end, directory, cancelled,
        timeout=max(45, (end-start)/4+30))
    _unchanged(source, stamp, cancelled)
    entries, missing = [], set()
    for requested in times:
        position = min(bisect_left(available, requested), len(available)-1)
        chosen = available[position]
        image, meta, log = _frame_paths(requested, chosen, start, end, directory, identity, width, height)
        cached = _cached_frame(image, meta, log, requested, chosen, start, end, identity, width, height, cancelled)
        entries.append((requested, chosen, image, meta, log, cached))
        if cached is None:
            missing.add(chosen)
    decoded = {}
    values = sorted(missing)
    for offset in range(0, len(values), 128):
        decoded.update(_decode_frames(source, values[offset:offset+128], directory,
                       (numerator, denominator, first), width, height, cancelled))
        _unchanged(source, stamp, cancelled)
    records, paths = [], []
    for requested, chosen, image, meta, log, cached in entries:
        if cached is None:
            pixels, evidence, pts, time_base = decoded[chosen]
            partial = image.with_suffix('.partial.jpg')
            try:
                partial.write_bytes(pixels)
                log.write_text(evidence, 'utf-8')
                saved = {'version': BOUNDED_STORYBOARD_VERSION, 'source': identity, 'time': chosen,
                         'requested_time': requested, 'pts': pts, 'time_base': time_base,
                         'sha256': _digest(partial, cancelled), 'log_sha256': _digest(log, cancelled)}
                _unchanged(source, stamp, cancelled)
                partial.replace(image)
                atomic_json(meta, saved)
            finally:
                partial.unlink(missing_ok=True)
        else:
            saved = cached[0]
        records.append({key: saved[key] for key in ('time', 'requested_time', 'pts', 'time_base', 'sha256')})
        paths.append(image)
    _unchanged(source, stamp, cancelled)
    return identity, records, paths


def build_bounded_storyboard(source, start, end, destination, cancelled, *, times=None, context=False,
                             max_frames=MAX_INFERENCE_FRAMES):
    """Return actual source PTS; metadata and all cached evidence stay beside destination.

    Each request selects the first source frame at/after it within the window. If
    none remains, the last frame *inside this window* is used and both times are
    recorded. No temporal interpolation, semantic sampling, or context borrowing.
    """
    _check(cancelled)
    start, end = _number(start), _number(end)
    if start >= end or type(context) is not bool:
        raise ValueError('Invalid storyboard window or context flag')
    requested = _requested(start, end, times, context, max_frames)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.relative_to(ROOT.resolve())
    if destination == source or destination.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
        raise ValueError('Storyboard destination must be a separate image')
    destination.parent.mkdir(parents=True, exist_ok=True)
    identity, records, paths = source_frame_files(source,start,end,destination.parent,cancelled,requested)
    stamp = {key: identity[key] for key in ('size', 'mtime_ns', 'ctime_ns')}
    for index, (record, path) in enumerate(zip(records, paths)):
        record.update(index=index+1, frame=str(path.relative_to(destination.parent)))
    width, height, caption, columns = (POLICY[key] for key in
                                      ('thumbnail_width', 'thumbnail_height', 'caption_height', 'columns'))
    canvas = Image.new('RGB', (columns*width, math.ceil(len(paths)/columns)*(height+caption)), '#111111')
    draw = ImageDraw.Draw(canvas)
    for index, (path, record) in enumerate(zip(paths, records)):
        _check(cancelled)
        x, y = (index % columns)*width, (index//columns)*(height+caption)
        with Image.open(path) as picture:
            canvas.paste(picture, (x, y+caption))
        draw.text((x+6, y+5), f'Frame {index+1} | source {record["time"]:.3f}s', fill='white')
    partial = destination.with_name(destination.stem+'.partial'+destination.suffix)
    try:
        canvas.save(partial)
        _unchanged(source, stamp, cancelled)
        page_hash = _digest(partial, cancelled)
        partial.replace(destination)
        page_paths, page_hashes = [str(destination)], [page_hash]
        if len(records) > MAX_INFERENCE_FRAMES:
            page_paths, page_hashes = [], []
            for offset in range(0, len(records), MAX_INFERENCE_FRAMES):
                rows = math.ceil(min(MAX_INFERENCE_FRAMES,len(records)-offset)/columns)
                page = canvas.crop((0, offset//columns*(height+caption), columns*width,
                                    (offset//columns+rows)*(height+caption)))
                path = destination.with_name(destination.stem+f'.page-{offset//MAX_INFERENCE_FRAMES:03d}'+destination.suffix)
                try:
                    page.save(path)
                finally:
                    page.close()
                page_paths.append(str(path))
                page_hashes.append(_digest(path,cancelled))
        _unchanged(source, stamp, cancelled)
        atomic_json(destination.with_suffix('.storyboard.json'),
                    {'version': BOUNDED_STORYBOARD_VERSION, 'source': identity,
                     'start': start, 'end': end, 'context': context, 'frames': records,
                     'pages': page_paths, 'page_sha256': page_hashes,
                     'sampling_interval': POLICY['sampling_interval']})
    finally:
        canvas.close()
        partial.unlink(missing_ok=True)
    return [record['time'] for record in records]
