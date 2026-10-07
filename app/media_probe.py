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

SHOT_DETECTOR_VERSION = 4
BASE_SCENE_THRESHOLD = 0.14
SCENE_THRESHOLD = 0.20


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.tmp.{time.time_ns()}')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def load_json(path: Path):
    return json.loads(path.read_text('utf-8'))


def run_process(command: list[str | Path], log: Path, cancelled, timeout: float = 3600) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
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


def parse_shot_candidates(log_text: str) -> list[tuple[float, float]]:
    """Parse (pts_time, scene_score) pairs from ffmpeg showinfo/metadata log."""
    score_by_pts = {}
    current_pts = None
    for line in log_text.splitlines():
        pts_match = re.search(r'pts_time:([0-9.]+)', line)
        if pts_match:
            current_pts = float(pts_match.group(1))
            score_by_pts.setdefault(current_pts, 0.22)
        score_match = re.search(r'lavfi\.scene_score=([0-9.]+)', line)
        if score_match and current_pts is not None:
            score_by_pts[current_pts] = float(score_match.group(1))
    return sorted(score_by_pts.items(), key=lambda x: x[0])


def adaptive_cut_times(candidates: list[tuple[float, float]], duration: float, window: float = 4.0) -> list[float]:
    """Dynamically adjust shot cut threshold based on local visual motion density.
    
    Calm dialogue maintains fine sensitivity (0.18-0.22).
    Action and sakuga elevate threshold (up to 0.52) and resolve bursts to peak frames.
    """
    if not candidates:
        return [0.0, duration]

    candidate_times = [c[0] for c in candidates]
    filtered = []
    for t, score in candidates:
        if t <= 0.3 or t >= duration - 0.3:
            continue
        local_triggers = sum(1 for other_t in candidate_times if abs(other_t - t) <= window)
        density = local_triggers / (2.0 * window)
        adaptive_threshold = min(0.52, max(0.18, 0.20 + 0.16 * max(0.0, density - 0.4)))
        if score >= adaptive_threshold:
            filtered.append((t, score, density))

    if not filtered:
        return [0.0, duration]

    clusters = []
    current_cluster = [filtered[0]]
    for item in filtered[1:]:
        if item[0] - current_cluster[-1][0] < 0.45:
            current_cluster.append(item)
        else:
            clusters.append(current_cluster)
            current_cluster = [item]
    if current_cluster:
        clusters.append(current_cluster)

    peak_times = []
    for cluster in clusters:
        best = max(cluster, key=lambda x: x[1])
        avg_density = sum(x[2] for x in cluster) / len(cluster)
        peak_times.append((best[0], avg_density))

    times = [0.0]
    for t, density in peak_times:
        min_gap = 0.65 if density > 1.0 else 0.40
        if t - times[-1] >= min_gap and t < duration - 0.35:
            times.append(t)

    if duration - times[-1] >= 0.35:
        times.append(duration)
    else:
        times[-1] = duration

    return times


def detect_shots(source: Path, duration: float, job_dir: Path, cancelled) -> list[dict]:
    import app.analysis as _analysis
    log = job_dir / 'shots.log'
    _analysis.run_process([
        FFMPEG, '-hide_banner', '-i', source,
        '-vf', f"scale=320:-2,select='gt(scene,{BASE_SCENE_THRESHOLD})',metadata=print:key=lavfi.scene_score,showinfo",
        '-an', '-f', 'null', '-'
    ], log, cancelled)
    raw_log = log.read_text('utf-8', errors='replace')
    candidates = parse_shot_candidates(raw_log)
    times = adaptive_cut_times(candidates, duration)
    scores = dict(candidates)
    return [{'id': f'shot_{i:04d}', 'start': round(start, 3), 'end': round(end, 3),
             'scene_score': scores.get(start, 0.0), 'accepted': True}
            for i, (start, end) in enumerate(zip(times, times[1:]))]


def shot_checkpoint(source: Path, fingerprint: str, duration: float, job_dir: Path, cancelled) -> list[dict]:
    import app.analysis as _analysis
    path, meta = job_dir / 'shots.json', job_dir / 'shots.meta.json'
    identity = {'source': fingerprint, 'duration': duration,
                'version': SHOT_DETECTOR_VERSION, 'threshold': 'adaptive',
                'width': 320, 'minimum_gap': .4}
    hit = path.exists() and meta.exists() and load_json(meta) == identity
    from .pipeline_diagnostics import Diagnostics
    Diagnostics(job_dir).event('shot_detection', 'cache_hit' if hit else 'cache_miss', detector_version=SHOT_DETECTOR_VERSION)
    shots = (load_json(path) if hit
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
