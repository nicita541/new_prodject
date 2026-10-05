"""Media probing, shot detection, windows chunking, and transcript normalization."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from app.config import FFMPEG, FFPROBE, ROOT

SHOT_DETECTOR_VERSION = 2
SCENE_THRESHOLD = 0.20


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_json(path: Path):
    return json.loads(path.read_text('utf-8'))


def run_process(command, log: Path, cancelled, timeout=3600) -> None:
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen([str(x) for x in command], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        start = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError('Обработка отменена')
                if time.monotonic() - start > timeout:
                    raise RuntimeError(f'Истёк срок выполнения {Path(command[0]).name}')
                time.sleep(0.2)
            if process.returncode:
                tail = log.read_text('utf-8', errors='replace')[-1600:]
                raise RuntimeError(f'{Path(command[0]).name}: {tail}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def probe_media(source: Path) -> dict:
    result = subprocess.run([str(FFPROBE), '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm', '-show_format', '-show_streams', '-of', 'json', str(source)],
                            capture_output=True, text=True, encoding='utf-8', timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    if result.returncode:
        raise ValueError('Не удалось прочитать видео. Проверьте, что файл не повреждён.')
    raw = json.loads(result.stdout)
    video = next((s for s in raw.get('streams', []) if s.get('codec_type') == 'video'), None)
    audio_tracks = [s for s in raw.get('streams', []) if s.get('codec_type') == 'audio']
    audio = audio_tracks[0] if audio_tracks else None
    audio_ordinal = 0
    if not video:
        raise ValueError('В файле нет видеодорожки')
    if not audio:
        raise ValueError('В файле нет звука: первая версия рассчитана на русскую озвучку')
    if len(audio_tracks) > 1:
        russian = [i for i, track in enumerate(audio_tracks)
                   if track.get('tags', {}).get('language', '').lower() in ('ru', 'rus')
                   or any(marker in track.get('tags', {}).get('title', '').lower() for marker in ('рус', 'russian'))]
        if not russian:
            raise ValueError('Несколько аудиодорожек без обозначения русской. Нужен файл с одной русской дорожкой или меткой ru/rus.')
        audio_ordinal = russian[0]
    duration = float(raw.get('format', {}).get('duration', video.get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Некорректная длительность видео')
    numerator, denominator = video.get('avg_frame_rate', '30/1').split('/')
    return {'duration': duration, 'width': int(video['width']), 'height': int(video['height']),
            'fps': float(numerator) / max(float(denominator), 1), 'has_audio': True, 'audio_stream': audio_ordinal}


def detect_shots(source: Path, duration: float, job_dir: Path, cancelled) -> list[dict]:
    import app.analysis as _analysis
    log = job_dir / 'shots.log'
    _analysis.run_process([FFMPEG, '-hide_banner', '-i', source, '-vf', f"scale=320:-2,select='gt(scene,{SCENE_THRESHOLD})',showinfo", '-an', '-f', 'null', '-'], log, cancelled)
    times = [0.0]
    for match in re.finditer(r'pts_time:([0-9.]+)', log.read_text('utf-8', errors='replace')):
        timestamp = float(match.group(1))
        if timestamp - times[-1] >= 0.5 and timestamp < duration - 0.5:
            times.append(timestamp)
    times.append(duration)
    return [{'id': f'shot_{i:04d}', 'start': round(start, 3), 'end': round(end, 3)} for i, (start, end) in enumerate(zip(times, times[1:]))]


def shot_checkpoint(source: Path, fingerprint: str, duration: float, job_dir: Path, cancelled) -> list[dict]:
    import app.analysis as _analysis
    path, meta = job_dir / 'shots.json', job_dir / 'shots.meta.json'
    identity = {'source': fingerprint, 'duration': duration,
                'version': SHOT_DETECTOR_VERSION, 'threshold': SCENE_THRESHOLD,
                'width': 320, 'minimum_gap': .5}
    shots = (load_json(path) if path.exists() and meta.exists() and load_json(meta) == identity
             else _analysis.detect_shots(source, duration, job_dir, cancelled))
    atomic_json(path, shots)
    atomic_json(meta, identity)
    return shots


def analysis_windows(duration: float, transcript: dict, target: float = 40) -> list[tuple[float, float]]:
    boundaries = [float(s['end']) for s in transcript['segments'] if s['end'] > s['start']]
    windows = []
    start = 0.0
    while start < duration - 0.01:
        limit = min(start + target, duration)
        near = [b for b in boundaries if start + target - 8 <= b <= min(start + target + 8, duration)]
        end = min(near, key=lambda b: abs(b - limit)) if near and limit < duration else limit
        # Never introduce a visual-analysis boundary within an ASR word.
        for word in transcript['words']:
            if word['start'] < end < word['end']:
                end = word['end']
        end = min(end, duration)
        windows.append((start, end))
        start = end
    return windows


def normalize_transcript(transcript: dict, duration: float) -> dict:
    """VAD may join distant speech chunks into one misleading long segment."""
    result = dict(transcript)
    words = []
    for word in transcript.get('words', []):
        start, end = max(0, float(word['start'])), min(duration, float(word['end']))
        if math.isfinite(start) and math.isfinite(end) and start < end and str(word['text']).strip():
            words.append({**word, 'start': start, 'end': end})
    words.sort(key=lambda w: w['start'])
    segments, group = [], []
    def flush():
        if group:
            segments.append({'start': group[0]['start'], 'end': group[-1]['end'],
                             'text': ' '.join(w['text'].strip() for w in group)})
            group.clear()
    for word in words:
        if group and word['start'] - group[-1]['end'] > 1.0:
            flush()
        group.append(word)
        if re.search(r'[.!?…]$', word['text'].strip()):
            flush()
    flush()
    result['words'] = words
    result['raw_segments'] = transcript.get('raw_segments', transcript.get('segments', []))
    result['segments'] = segments
    return result
