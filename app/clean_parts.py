"""Disposable lossless cuts, independent of subtitles, music and framing."""
from __future__ import annotations

import copy
import threading
from pathlib import Path

from app.config import FFMPEG
from app.content_identity import digest
from app.json_store import atomic_json, read_json
from app.media import inspect_media, run_render_command, _safe_replace

CLEAN_VERSION = 1
_LOCKS = [threading.Lock() for _ in range(16)]


def clean_identity(source: Path, part: dict, probe: dict):
    stat = source.stat()
    return digest({'version': CLEAN_VERSION, 'source': str(source.resolve()),
        'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
        'width': probe['width'], 'height': probe['height'], 'audio': probe.get('audio_stream', 0),
        'duration': part['duration'], 'cuts': [{'start': c['start'], 'end': c['end']} for c in part['cuts']]})


def clean_clock_part(part: dict):
    """Keep focus movements, resetting at each original montage cut."""
    result = copy.deepcopy(part)
    anchors, offset = [], 0.0
    for cut in part['cuts']:
        focus = sorted(cut.get('focus', []), key=lambda f: f['time'])
        prior = [f for f in focus if f['time'] <= cut['start']]
        entrance = prior[-1] if prior else focus[0] if focus else {'x': .5, 'y': .5}
        anchors.append({**entrance, 'time': offset, 'hard_cut': offset > 0})
        for anchor in focus:
            if cut['start'] < anchor['time'] <= cut['end']:
                # Keep an exit movement before the next cut's abrupt reset.
                # Two different positions at the exact same timestamp would
                # otherwise overwrite each other in crop_expressions.
                local_time = min(anchor['time'] - cut['start'], cut['end'] - cut['start'] - .000001)
                anchors.append({**anchor, 'time': offset + local_time})
        offset += cut['end'] - cut['start']
    result['cuts'] = [{'start': 0, 'end': part['duration'], 'focus': anchors}]
    return result


def _cached(path, identity):
    try:
        record = read_json(path.with_suffix('.json'), {})
        stat = path.stat()
        return (isinstance(record, dict) and record.get('identity') == identity
                and record.get('size') == stat.st_size and stat.st_size > 1000
                and record.get('mtime_ns') == stat.st_mtime_ns)
    except (OSError, ValueError, TypeError):
        return False


def prepare_clean_part(source: Path, part: dict, probe: dict, job_dir: Path,
                       cancelled=lambda: False, *, create=True, on_progress=None):
    """Return (source, part, probe, cache_hit); previews can decline a full build."""
    identity = clean_identity(source, part, probe)
    folder = job_dir / 'clean' / f"part_{part['index']:03}" / identity
    if not folder.resolve().is_relative_to(job_dir.resolve()):
        raise ValueError('Некорректный каталог чистой части')
    path = folder / 'clean.mkv'
    if (not path.resolve().is_relative_to(folder.resolve())
            or not path.with_suffix('.json').resolve().is_relative_to(folder.resolve())):
        raise ValueError('Чистая часть должна находиться в своём каталоге')
    lock = _LOCKS[int(identity[:8], 16) % len(_LOCKS)]
    while not lock.acquire(timeout=.2):
        if cancelled():
            raise InterruptedError('Обработка отменена')
    try:
        if cancelled():
            raise InterruptedError('Обработка отменена')
        hit = _cached(path, identity)
        if not hit:
            if not create:
                return source, part, probe, False
            folder.mkdir(parents=True, exist_ok=True)
            partial = folder / 'clean.partial.mkv'
            args = [str(FFMPEG), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-y']
            filters, videos, audios, offset = [], [], [], 0.0
            for i, cut in enumerate(part['cuts']):
                length = cut['end'] - cut['start']
                args.extend(['-ss', f"{cut['start']:.6f}", '-t', f'{length:.6f}', '-i', str(source.resolve())])
                filters.append(f'[{i}:v:0]trim=duration={length:.6f},setpts=PTS-STARTPTS,'
                    f'format=yuv420p,setsar=1,setpts=PTS+{offset:.6f}/TB[v{i}]')
                filters.append(f"[{i}:a:{probe.get('audio_stream', 0)}]atrim=duration={length:.6f},"
                    f'asetpts=PTS-STARTPTS,aresample=48000,'
                    f'aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo[a{i}]')
                videos.append(f'[v{i}]'); audios.append(f'[a{i}]')
                offset += length
            filters.append(''.join(videos) + f"interleave=nb_inputs={len(videos)}:duration=longest,"
                f"trim=duration={part['duration']:.6f},fps=30[video]")
            filters.append(''.join(audios) + f'concat=n={len(audios)}:v=0:a=1[audio]')
            (folder / 'clean.ffscript').write_text(';\n'.join(filters), encoding='utf-8')
            # Lossless at source resolution; PCM avoids re-encoding original
            # dialogue each time music changes. No ASS, crop or visual effects.
            args.extend(['-filter_complex_script', 'clean.ffscript', '-filter_complex_threads', '2',
                '-map', '[video]', '-map', '[audio]', '-t', f"{part['duration']:.6f}",
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-threads', '4',
                '-c:a', 'pcm_s16le', str(partial.resolve())])
            run_render_command(args, folder, part['duration'], cancelled, on_progress)
            media = inspect_media(partial, folder, cancelled)
            video = next((s for s in media.get('streams', []) if s.get('codec_type') == 'video'), {})
            audio = next((s for s in media.get('streams', []) if s.get('codec_type') == 'audio'), {})
            if (partial.stat().st_size < 1000 or video.get('codec_name') != 'h264'
                    or audio.get('codec_name') != 'pcm_s16le'
                    or video.get('width') != probe['width'] or video.get('height') != probe['height']
                    or abs(float(media['format']['duration']) - part['duration']) > .15):
                raise ValueError('Чистая часть не соответствует монтажу')
            if cancelled():
                raise InterruptedError('Обработка отменена')
            _safe_replace(partial, path)
            stat = path.stat()
            atomic_json(path.with_suffix('.json'), {'identity': identity, 'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns, 'version': CLEAN_VERSION})
        return path, clean_clock_part(part), {**probe, 'audio_stream': 0}, hit
    finally:
        lock.release()
