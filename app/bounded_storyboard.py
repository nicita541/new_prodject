"""Small source-only storyboards with verified presentation timestamps."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .config import FFMPEG, FFPROBE, ROOT
from .media_probe import atomic_json, run_process

BOUNDED_STORYBOARD_VERSION = 1
POLICY = {'max_frames': 12, 'context_frames': 2, 'sampling_interval': .5,
          'thumbnail_width': 320, 'thumbnail_height': 180, 'columns': 3, 'caption_height': 24}


def _check(cancelled):
    if cancelled():
        raise InterruptedError('Обработка отменена')


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


def _stamp(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns}


def _unchanged(source, stamp, cancelled):
    _check(cancelled)
    if _stamp(source) != stamp:
        raise ValueError('Source changed while building storyboard')


def _pts(log):
    text = log.read_text('utf-8', errors='replace')
    base = re.search(r'config in time_base:\s*(\d+)/(\d+)', text)
    frame = re.search(r'\bn:\s*0\s+pts:\s*([+-]?\d+)\s+pts_time:', text)
    if base is None or frame is None or int(base[2]) == 0:
        raise ValueError('FFmpeg did not report a source frame timestamp')
    pts = int(frame[1])
    return pts*int(base[1])/int(base[2]), pts, f'{base[1]}/{base[2]}'


def _requested(start, end, times, context):
    cap = POLICY['context_frames'] if context else POLICY['max_frames']
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


def _frame(source, requested, chosen, start, end, directory, identity, base, cancelled):
    key = hashlib.sha256(json.dumps([identity, start, end, requested, chosen, POLICY],
                                   sort_keys=True).encode()).hexdigest()
    image, meta, log = (directory/(key+suffix) for suffix in ('.jpg', '.json', '.log'))
    try:
        saved = json.loads(meta.read_text('utf-8'))
        actual, pts, recorded_base = _pts(log)
        if (saved['source'] == identity and saved['version'] == BOUNDED_STORYBOARD_VERSION
                and saved['requested_time'] == requested and saved['time'] == actual == chosen
                and saved['pts'] == pts and saved['time_base'] == recorded_base
                and start <= actual < end and saved['sha256'] == _digest(image, cancelled)
                and saved['log_sha256'] == _digest(log, cancelled)):
            with Image.open(image) as picture:
                if picture.size == (POLICY['thumbnail_width'], POLICY['thumbnail_height']):
                    return saved, image
    except InterruptedError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        pass
    _check(cancelled)
    partial = image.with_suffix('.partial.jpg')
    try:
        width, height = POLICY['thumbnail_width'], POLICY['thumbnail_height']
        numerator, denominator, first = base
        tick = round(chosen*denominator/numerator)
        end_tick = math.ceil(end*denominator/numerator)
        # Input seeking is relative to stream start; copyts and trim retain
        # absolute source PTS even when the source begins at a nonzero time.
        seek = max(0, chosen-first-.25)
        run_process([FFMPEG, '-y', '-hide_banner', '-ss', f'{seek:.9f}',
                     '-copyts', '-i', source, '-map', '0:v:0', '-an', '-vf',
                     f'trim=start_pts={tick}:end_pts={end_tick},'
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,showinfo',
                     '-frames:v', '1', '-fps_mode', 'vfr', '-q:v', '2', partial],
                    log, cancelled, timeout=45)
        actual, pts, base = _pts(log)
        if actual != chosen or not start <= actual < end or not partial.is_file():
            raise ValueError('Decoded source frame is outside the requested window or has a different PTS')
        with Image.open(partial) as picture:
            if picture.size != (width, height):
                raise ValueError('Invalid decoded source frame')
        saved = {'version': BOUNDED_STORYBOARD_VERSION, 'source': identity, 'time': actual,
                 'requested_time': requested, 'pts': pts, 'time_base': base,
                 'sha256': _digest(partial, cancelled), 'log_sha256': _digest(log, cancelled)}
        _check(cancelled)
        partial.replace(image)
        atomic_json(meta, saved)
        return saved, image
    finally:
        partial.unlink(missing_ok=True)


def build_bounded_storyboard(source, start, end, destination, cancelled, *, times=None, context=False):
    """Return actual source PTS; metadata and all cached evidence stay beside destination.

    Each request selects the first source frame at/after it within the window. If
    none remains, the last frame *inside this window* is used and both times are
    recorded. No temporal interpolation, semantic sampling, or context borrowing.
    """
    _check(cancelled)
    start, end = _number(start), _number(end)
    if start >= end or type(context) is not bool:
        raise ValueError('Invalid storyboard window or context flag')
    requested = _requested(start, end, times, context)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.relative_to(ROOT.resolve())
    if destination == source or destination.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
        raise ValueError('Storyboard destination must be a separate image')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(source)
    identity = {'sha256': _digest(source, cancelled), **stamp}
    _unchanged(source, stamp, cancelled)
    directory = destination.parent/'.bounded-frames'/identity['sha256']
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory/'source.json', identity)
    available, numerator, denominator, first = _source_times(source, start, end, directory, cancelled)
    _unchanged(source, stamp, cancelled)
    records, paths = [], []
    for value in requested:
        chosen = next((pts for pts in available if pts >= value), available[-1])
        record, path = _frame(source, value, chosen, start, end, directory, identity,
                              (numerator, denominator, first), cancelled)
        _unchanged(source, stamp, cancelled)
        records.append({key: record[key] for key in ('time', 'requested_time', 'pts', 'time_base', 'sha256')})
        records[-1].update({'index': len(records), 'frame': str(path.relative_to(destination.parent))})
        paths.append(path)
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
        atomic_json(destination.with_suffix('.storyboard.json'),
                    {'version': BOUNDED_STORYBOARD_VERSION, 'source': identity,
                     'start': start, 'end': end, 'context': context, 'frames': records,
                     'pages': [str(destination)], 'page_sha256': [page_hash],
                     'sampling_interval': POLICY['sampling_interval']})
    finally:
        canvas.close()
        partial.unlink(missing_ok=True)
    return [record['time'] for record in records]
