"""Compare timestamp-matched original and rendered frames for a saved plan."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import JOBS, ROOT
import cv2
from PIL import Image, ImageDraw


def frame(capture, time, size):
    capture.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
    ok, picture = capture.read()
    if not ok:
        raise ValueError(f'Cannot decode frame at {time}')
    return Image.fromarray(cv2.cvtColor(picture, cv2.COLOR_BGR2RGB)).resize(size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    parser.add_argument('--parts', type=int, nargs='+')
    args = parser.parse_args()
    job = JOBS / str(args.job)
    plan = json.loads((job / 'plan.json').read_text('utf-8'))
    source = Path(json.loads((job / 'source.json').read_text('utf-8'))['path']).resolve()
    source.relative_to(ROOT)
    qa = job / 'qa'
    qa.mkdir(exist_ok=True)
    original = cv2.VideoCapture(str(source))
    try:
        for part in plan['parts']:
            if args.parts and part['index'] not in args.parts:
                continue
            output = cv2.VideoCapture(str(job / 'output' / f"part_{part['index']:03}.mp4"))
            samples, elapsed = [], 0.0
            for cut in part['cuts']:
                # Include early action and mid-cut dialogue; retained silent
                # actions and both sides of conversational cuts are visible.
                length = cut['end'] - cut['start']
                for offset in sorted(set([min(.5, length / 2), length / 2])):
                    samples.append((cut['start'] + offset, elapsed + offset))
                elapsed += length
            try:
                for batch in range(0, len(samples), 4):
                    current = samples[batch:batch + 4]
                    sheet = Image.new('RGB', (660, len(current) * 300), '#151515')
                    draw = ImageDraw.Draw(sheet)
                    for row, (source_time, output_time) in enumerate(current):
                        y = row * 300
                        sheet.paste(frame(original, source_time, (480, 270)), (0, y))
                        sheet.paste(frame(output, output_time, (152, 270)), (495, y))
                        draw.text((5, y + 276), f'Source {source_time:.2f}s | Part {part["index"]:03} {output_time:.2f}s', fill='white')
                    sheet.save(qa / f"compare_{part['index']:03}_{batch // 4:02}.jpg", quality=93)
            finally:
                output.release()
            print(f"Compared part {part['index']:03}: {len(samples)} frames", flush=True)
    finally:
        original.release()


if __name__ == '__main__':
    main()
