"""Media probing, shot detection, and transcript normalization."""
from __future__ import annotations

from app.json_store import analysis_json as atomic_json, load_json

import bisect
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from app.config import FFMPEG, FFPROBE, ROOT

SHOT_DETECTOR_VERSION = 5
BASE_SCENE_THRESHOLD = 0.14
SCENE_THRESHOLD = 0.20


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


def adaptive_shot_evidence(candidates: list[tuple[float, float]], duration: float,
                           window: float = 4.0) -> list[dict]:
    """Preserve every raw cut and the exact adaptive/cluster suppression reason."""
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(window) or window <= 0:
        raise ValueError('Некорректные параметры монтажных границ')
    ordered = sorted((float(t), float(score)) for t, score in candidates)
    if any(not math.isfinite(t) or not math.isfinite(score) or not 0 <= t <= duration
           or not 0 <= score <= 1 for t, score in ordered):
        raise ValueError('Некорректный кандидат монтажной границы')
    times = [t for t, _ in ordered]
    evidence, filtered = [], []
    for index, (timestamp, score) in enumerate(ordered):
        count = bisect.bisect_right(times, timestamp + window) - bisect.bisect_left(times, timestamp - window)
        density = count / (2 * window)
        threshold = min(.52, max(.18, .20 + .16 * max(0.0, density - .4)))
        reason = ('near_source_boundary' if timestamp <= .3 or timestamp >= duration - .3 else
                  'below_adaptive_threshold' if score < threshold else 'clustered_to_peak')
        item = {'id': f'candidate_{index:05d}', 'time': timestamp, 'scene_score': score, 'score': score,
                'local_density': density, 'adaptive_threshold': threshold, 'accepted': False,
                'decision': 'suppressed', 'suppression_reason': reason, 'preserved_as_candidate': True}
        evidence.append(item)
        if reason == 'clustered_to_peak':
            filtered.append(item)
    clusters = []
    for item in filtered:
        if clusters and item['time'] - clusters[-1][-1]['time'] < .45:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    last = 0.0
    for cluster in clusters:
        peak = max(cluster, key=lambda item: item['score'])
        average_density = sum(item['local_density'] for item in cluster) / len(cluster)
        for item in cluster:
            item['cluster_peak_time'] = peak['time']
        gap = .65 if average_density > 1 else .40
        if peak['time'] - last < gap:
            peak['suppression_reason'] = 'minimum_gap'
        elif peak['time'] >= duration - .35:
            peak['suppression_reason'] = 'source_tail_margin'
        else:
            peak.update(accepted=True, decision='accepted', suppression_reason=None,
                        accepted_time=round(peak['time'], 3))
            last = peak['time']
    return evidence


def raw_shot_evidence(shots: list[dict], job_dir: Path | None = None) -> list[dict]:
    """Read additive raw evidence without changing the legacy list-of-shots API."""
    rows = [item for shot in shots for item in shot.get('raw_shot_candidates', [])]
    if not rows and job_dir is not None:
        path = Path(job_dir) / 'shots.candidates.json'
        rows = load_json(path) if path.is_file() else []
    unique = {item.get('id', f"time:{item['time']}"): item for item in rows}
    return sorted(unique.values(), key=lambda item: (item['time'], item.get('id', '')))


def detect_shots(source: Path, duration: float, job_dir: Path, cancelled) -> list[dict]:
    log = job_dir / 'shots.log'
    run_process([
        FFMPEG, '-hide_banner', '-i', source,
        '-vf', f"scale=320:-2,select='gt(scene,{BASE_SCENE_THRESHOLD})',metadata=print:key=lavfi.scene_score,showinfo",
        '-an', '-f', 'null', '-'
    ], log, cancelled)
    raw_log = log.read_text('utf-8', errors='replace')
    candidates = parse_shot_candidates(raw_log)
    evidence = adaptive_shot_evidence(candidates, duration)
    times = [0.0, *(item['time'] for item in evidence if item['accepted']), duration]
    scores = dict(candidates)
    shots = [{'id': f'shot_{i:04d}', 'start': round(start, 3), 'end': round(end, 3),
             'scene_score': scores.get(start, 0.0), 'accepted': True}
            for i, (start, end) in enumerate(zip(times, times[1:]))]
    for shot in shots:
        shot['raw_shot_candidates'] = []
    for item in evidence:
        timestamp = item.get('accepted_time', item['time'])
        owner = next((shot for shot in shots if shot['start'] <= timestamp < shot['end']), shots[-1])
        owner['raw_shot_candidates'].append(item)
    atomic_json(job_dir / 'shots.candidates.json', evidence)
    return shots


def shot_checkpoint(source: Path, fingerprint: str, duration: float, job_dir: Path, cancelled) -> list[dict]:
    from .semantic_identity import component_identity
    path, meta = job_dir / 'shots.json', job_dir / 'shots.meta.json'
    identity = {'source': fingerprint, 'duration': duration,
                'version': SHOT_DETECTOR_VERSION, 'threshold': 'adaptive',
                'width': 320, 'minimum_gap': .4, 'candidate_policy': 'preserve-all-v1',
                'semantic_component': component_identity('shot_detector')}
    hit = path.exists() and meta.exists() and load_json(meta) == identity
    from .pipeline_diagnostics import Diagnostics
    Diagnostics(job_dir).event('shot_detection', 'cache_hit' if hit else 'cache_miss', detector_version=SHOT_DETECTOR_VERSION)
    shots = (load_json(path) if hit
             else detect_shots(source, duration, job_dir, cancelled))
    atomic_json(path, shots)
    atomic_json(meta, identity)
    evidence = raw_shot_evidence(shots)
    atomic_json(job_dir / 'shots.candidates.json', evidence)
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    diagnostics.write('shots.candidates.json', evidence)
    diagnostics.summary(raw_shot_candidates=len(evidence), accepted_shot_candidates=sum(item['accepted'] for item in evidence),
                        suppressed_shot_candidates=sum(not item['accepted'] for item in evidence))
    for item in evidence:
        diagnostics.event('shot_detection', item['decision'], candidate_id=item['id'], source_time=item['time'],
                          score=item['scene_score'], local_density=item['local_density'],
                          adaptive_threshold=item['adaptive_threshold'], reason=item['suppression_reason'],
                          preserved_as_candidate=True)
    return shots


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
