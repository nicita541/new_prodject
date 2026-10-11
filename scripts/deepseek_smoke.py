"""Explicit one-to-three framing samples; connection check and normal bounded retries.

The direct adapter may retry each paid request up to twice. --cache-only forbids
network access. Runtime does not perform monetary balance preflight.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import JOBS, ROOT
from app.deepseek import DeepSeekVision, MODEL, check_connection, public_status
from app.framing import _FrameReader, _grid_image, _focus_prompt, temporal_times, FOCUS_SCHEMA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    parser.add_argument('--times', nargs='+', type=float, required=True)
    parser.add_argument('--cache-only', action='store_true', help='Forbid every network request; use existing answers only')
    args = parser.parse_args()
    if not 1 <= len(args.times) <= 3:
        parser.error('Choose one to three actual source timestamps')
    job = JOBS / str(args.job)
    source = Path(json.loads((job/'source.json').read_text('utf-8'))['path']).resolve()
    source.relative_to(ROOT.resolve())
    probe = json.loads((job/'probe.json').read_text('utf-8'))
    transcript = json.loads((job/'transcript.json').read_text('utf-8'))
    shots = json.loads((job/'shots.json').read_text('utf-8'))
    if any(not 0 <= timestamp < probe['duration'] for timestamp in args.times):
        parser.error('Timestamp is outside the actual source')
    before = ({'available': True, 'vision_supported': True, 'model': MODEL, 'note': 'No network, cached replies only'}
              if args.cache_only else check_connection())
    if not before['available'] or not before['vision_supported']:
        parser.error('Account or image model is not available')
    directory = job/'diagnostics'/('deepseek-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    report = {'model': before['model'], 'limit_usd': public_status()['budget_usd'], 'connection_before': before,
              'budget_before': public_status(), 'results': [],
              'note': 'Up to three short diagnostics; no full paid episode processing.'}
    reader = _FrameReader(source, probe, lambda: False)
    try:
        with DeepSeekVision(job, lambda: False, cache_only=args.cache_only) as vision:
            for index, timestamp in enumerate(args.times):
                segment = next((value for value in transcript['segments']
                                if value['start'] <= timestamp < value['end']), None)
                sample = {'time': timestamp, 'sample_time': timestamp,
                          'phrase': segment['text'] if segment else ''}
                event = {'start': 0, 'end': probe['duration']}
                times = temporal_times(sample, event, shots)
                image = directory/f'sample_{index+1:02}.jpg'
                _grid_image([reader.frame(value) for value in times], times, image)
                started = time.monotonic()
                try:
                    answer = vision.query(_focus_prompt(sample), image, max_tokens=120, schema=FOCUS_SCHEMA)
                except Exception as error:
                    report['error'] = str(error)
                    print(type(error).__name__+': '+str(error), flush=True)
                    break  # No automatic paid retry.
                result = {'time': timestamp, 'phrase': sample['phrase'], 'frame_times': times,
                          'image': str(image.relative_to(ROOT)), 'answer': answer,
                          'seconds': round(time.monotonic()-started, 3)}
                report['results'].append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        reader.close()
        report['budget_after'] = public_status()
        try:
            report['connection_after'] = {'note': 'No network, cached replies only'} if args.cache_only else check_connection()
        except Exception:
            report['connection_after'] = {'error': 'Balance could not be rechecked'}
        (directory/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Saved '+str(directory/'results.json'), flush=True)
        print(json.dumps(report['budget_after'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
