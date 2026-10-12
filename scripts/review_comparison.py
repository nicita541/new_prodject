"""Measure completed plans and show actual source/old/new crop and caption pixels."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import JOBS, ROOT
from app.json_store import atomic_json
import cv2
from PIL import Image, ImageDraw, ImageFont


def load(folder, name):
    return json.loads((folder / name).read_text('utf-8'))


def map_source(plan, timestamp):
    for part in plan['parts']:
        elapsed = 0.
        for cut in part['cuts']:
            if cut['start'] <= timestamp < cut['end']:
                return part['index'], elapsed + timestamp - cut['start']
            elapsed += cut['end'] - cut['start']
    return None


def metrics(folder, plan):
    transcript = load(folder, 'transcript.json')
    cuts = [cut for part in plan['parts'] for cut in part['cuts']]
    retained = [word for word in transcript['words'] if any(
        cut['start'] - .002 <= word['start'] and word['end'] <= cut['end'] + .002 for cut in cuts)]
    cues = [cue for part in plan['parts'] for cue in part['subtitles']]
    return {'parts': len(plan['parts']), 'cuts': len(cuts),
            'selected_seconds': round(sum(part['duration'] for part in plan['parts']), 3),
            'source_seconds': load(folder, 'probe.json')['duration'],
            'durations': [round(part['duration'], 3) for part in plan['parts']],
            'source_words': len(transcript['words']), 'retained_words': len(retained),
            'subtitle_cues': len(cues), 'maximum_subtitle_lines': max(len(cue['text'].splitlines()) for cue in cues),
            'warnings': len(plan.get('warnings', []))}


def frame(path, timestamp, size):
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, pixels = capture.read()
        if not ok:
            raise ValueError(f'Cannot decode {path.name} at {timestamp}')
        return Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)).resize(size)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    parser.add_argument('--baseline', type=uuid.UUID, required=True)
    args = parser.parse_args()
    job, old = JOBS / str(args.job), JOBS / str(args.baseline)
    for folder in (job, old):
        if load(folder, 'job.json')['status'] != 'completed':
            parser.error('Both jobs must have completed')
    plan, prior = load(job, 'plan.json'), load(old, 'plan.json')
    source = Path(load(job, 'source.json')['path']).resolve()
    source.relative_to(ROOT.resolve())
    qa = job / 'qa'
    qa.mkdir(exist_ok=True)
    report = {'current': metrics(job, plan), 'baseline': metrics(old, prior),
              'method': 'Actual exported pixels mapped to the same source time; comparison includes multiple fixes, not an isolated model A/B test.',
              'critical_frames': []}
    times = [42.2, 197.78, 352.1, 652.0, 777.0, 785.2, 1335.5]
    sheet = Image.new('RGB', (830, len(times) * 310), '#171717')
    draw = ImageDraw.Draw(sheet)
    for row, timestamp in enumerate(times):
        top = row * 310
        draw.text((8, top + 4), f'Source {timestamp:.2f}s                 Original                       Previous          Current', fill='white')
        sheet.paste(frame(source, timestamp, (480, 270)), (0, top + 24))
        entry = {'source_time': timestamp}
        for label, folder, selected, left in [('baseline', old, prior, 490), ('current', job, plan, 655)]:
            mapping = map_source(selected, timestamp)
            entry[label] = {'part': mapping[0], 'output_time': round(mapping[1], 3)} if mapping else {'omitted': True}
            if mapping:
                path = folder / 'output' / f'part_{mapping[0]:03}.mp4'
                sheet.paste(frame(path, mapping[1], (152, 270)), (left, top + 24))
            else:
                draw.text((left + 12, top + 130), 'OMITTED', fill='#bbbbbb')
        report['critical_frames'].append(entry)
    sheet.save(qa / 'before-after.jpg', quality=94)
    # Render real exported caption pixels at three retained phrases. No mockups.
    candidates = [map_source(plan, time) for time in (42.2, 352.1, 652.)]
    candidates = [item for item in candidates if item is not None]
    preview = Image.new('RGB', (360 * len(candidates), 685), '#171717')
    preview_draw = ImageDraw.Draw(preview)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 18)
    for column, (index, output_time) in enumerate(candidates):
        part = next(item for item in plan['parts'] if item['index'] == index)
        cue = min(part['subtitles'], key=lambda cue: abs((cue['start'] + cue['end']) / 2 - output_time))
        moment = (cue['start'] + cue['end']) / 2
        preview.paste(frame(job / 'output' / f'part_{index:03}.mp4', moment, (360, 640)), (column * 360, 0))
        preview_draw.text((column * 360 + 12, 650), f'Часть {index} · {moment:.1f} с', font=font, fill='white')
    preview.save(qa / 'preview.jpg', quality=95)
    report['before_after'] = str(qa / 'before-after.jpg')
    report['preview'] = str(qa / 'preview.jpg')
    atomic_json(qa / 'comparison.json', report)
    print(json.dumps({'current': report['current'], 'baseline': report['baseline'],
                      'preview': report['preview']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
