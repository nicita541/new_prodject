"""Create chronological contact sheets and compare rendered audio with source."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import FFMPEG, JOBS, ROOT
from app.media import validate_export
import cv2
import numpy as np
from PIL import Image, ImageDraw


def pcm(path, start, duration, ordinal=0):
    result = subprocess.run([str(FFMPEG), '-v', 'error', '-protocol_whitelist', 'file,pipe', '-ss', str(start),
                             '-i', str(path), '-t', str(duration), '-map', f'0:a:{ordinal}', '-ac', '1', '-ar', '16000',
                             '-f', 'wav', '-'], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with wave.open(io.BytesIO(result.stdout), 'rb') as audio:
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768


def correlation(source, rendered):
    # Allow 50ms either side to measure delay introduced by AAC/concat clocks.
    length = min(len(source), len(rendered)) - 1600
    if length < 4000:
        raise ValueError('Audio sample too short')
    reference = source[800:800+length]
    scale = float(np.linalg.norm(reference))
    if scale < 0.01:
        return {'silent': True}
    scores = []
    for lag in range(-800, 801, 4):
        candidate = rendered[800+lag:800+lag+length]
        score = float(np.dot(reference, candidate) / max(1e-12, scale * np.linalg.norm(candidate)))
        scores.append((score, lag))
    score, lag = max(scores)
    return {'correlation': round(score, 5), 'lag_ms': round(lag / 16, 2)}


def sample_times(duration, fps, frame_count):
    # MP4's audio/container clock can end after the last video frame. Seek
    # samples only where an actual video frame exists, not into that tail.
    last_frame = (frame_count - 1) / fps if fps > 0 and frame_count > 0 else duration
    return list(np.arange(0.5, min(duration, last_frame), 5))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    args = parser.parse_args()
    job = JOBS / str(args.job)
    plan = json.loads((job / 'plan.json').read_text('utf-8'))
    source = Path(json.loads((job / 'source.json').read_text('utf-8'))['path']).resolve()
    source.relative_to(ROOT)
    probe = json.loads((job / 'probe.json').read_text('utf-8'))
    qa = job / 'qa'
    qa.mkdir(exist_ok=True)
    report = {'parts': [], 'method': 'All parts: chronological frames every 5 seconds; three audio excerpts per part compared with original.'}
    for part in plan['parts']:
        path = job / 'output' / f"part_{part['index']:03}.mp4"
        validate_export(path, part['duration'], qa, lambda: False)
        video = cv2.VideoCapture(str(path))
        samples = sample_times(part['duration'], video.get(cv2.CAP_PROP_FPS),
                               video.get(cv2.CAP_PROP_FRAME_COUNT))
        columns, width, height = 6, 180, 344
        rows = (len(samples) + columns - 1) // columns
        sheet = Image.new('RGB', (width * columns, height * rows), '#151515')
        draw = ImageDraw.Draw(sheet)
        try:
            for index, timestamp in enumerate(samples):
                video.set(cv2.CAP_PROP_POS_MSEC, float(timestamp)*1000)
                ok, frame = video.read()
                if not ok:
                    raise ValueError(f'Cannot decode {path.name} at {timestamp}')
                picture = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((width, 320))
                x, y = index % columns * width, index // columns * height
                sheet.paste(picture, (x, y))
                draw.text((x+4, y+322), f"Part {part['index']:03} | {timestamp:.1f}s", fill='white')
        finally:
            video.release()
        sheet.save(qa / f"part_{part['index']:03}.jpg", quality=92)
        cuts, positions, elapsed = part['cuts'], [], 0
        for cut in cuts:
            positions.append(elapsed)
            elapsed += cut['end']-cut['start']
        candidates = sorted(set([0, len(cuts)//2, len(cuts)-1]))
        checks = []
        for index in candidates:
            cut = cuts[index]
            length = min(2.5, cut['end']-cut['start']-0.5)
            if length < 0.5:
                continue
            offset = 0.25
            check = correlation(pcm(source, cut['start']+offset, length, probe.get('audio_stream',0)),
                                pcm(path, positions[index]+offset, length))
            checks.append({'cut': index, 'source_start': cut['start']+offset, **check})
        report['parts'].append({'index': part['index'], 'duration': part['duration'], 'audio_checks': checks,
                                'contact_sheet': str((qa / f"part_{part['index']:03}.jpg").relative_to(job))})
        print(path.name, checks, flush=True)
    (qa / 'measurements.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
