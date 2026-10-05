"""Separate development preview using preserved source facts; never overwrite a job."""
import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.deepseek import DeepSeekVision
from app.endings import refine_endings
from app.pacing import refine_pacing, refine_silent_sequences
from app.planner import build_plan, validate_plan
from app.media import choose_encoder, render_part, validate_export
from app.subtitles import make_cues, remap_words


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--events', nargs='+', required=True)
    parser.add_argument('--parts', nargs='+', type=int, default=[2])
    parser.add_argument('--reuse-reviews', type=Path)
    parser.add_argument('--cache-only', action='store_true')
    args = parser.parse_args()
    job, destination = args.job.resolve(), args.output.resolve()
    job.relative_to(ROOT)
    destination.relative_to(ROOT)
    if job == destination or destination.exists():
        raise ValueError('Preview must use a new separate directory')
    source = Path(json.loads((job / 'source.json').read_text('utf-8'))['path']).resolve()
    source.relative_to(ROOT)
    destination.mkdir(parents=True)
    if args.reuse_reviews:
        previous = args.reuse_reviews.resolve()
        previous.relative_to(ROOT)
        for name in ('pacing', 'pacing_sequences', 'endings'):
            if (previous / name).is_dir():
                shutil.copytree(previous / name, destination / name)
    for name in ('editorial-settings.json', 'render-settings.json'):
        shutil.copy2(job / name, destination / name)
    data = {name: json.loads((job / (file + '.json')).read_text('utf-8'))
            for name, file in (('probe', 'probe'), ('transcript', 'transcript'), ('shots', 'shots'), ('events', 'events'))}
    original = copy.deepcopy(data['events'])
    story = json.loads((job / 'story-events.json').read_text('utf-8'))['events']
    selected = [copy.deepcopy(e) for e in story if e['id'] in args.events]
    if {e['id'] for e in selected} != set(args.events):
        raise ValueError('Unknown source event')
    def report(stage, progress, message):
        print(message, flush=True)
    with DeepSeekVision(destination, lambda: False, cache_only=args.cache_only) as vision:
        selected = refine_pacing(source, selected, data['transcript'], data['shots'], destination,
                                 vision, report, lambda: False)
        by_id = {e['id']: e for e in selected}
        data['events'] = [by_id.get(e['id'], e) for e in data['events']]
        # Only re-review the requested source region in this diagnostic preview.
        sequence = refine_silent_sequences(source, selected, data['transcript'], data['shots'], destination,
                                           vision, report, lambda: False)
        by_id = {e['id']: e for e in sequence}
        data['events'] = [by_id.get(e['id'], e) for e in data['events']]
        data['events'] = refine_endings(data['events'], data['transcript'], data['shots'], data['probe'],
                                        destination, vision, report, lambda: False)
    save(destination / 'events.json', data['events'])
    plan = build_plan(data)
    for part in plan['parts']:
        part.update(layout='cinema', caption_style='accent')
        part['subtitles'] = make_cues(remap_words(data['transcript']['words'], part['cuts']), 'accent')
    validate_plan(plan, data)
    save(destination / 'plan.json', plan)
    def coverage(event):
        return sum(r['end'] - r['start'] for r in event.get('selected_ranges', []))
    save(destination / 'comparison.json', {
        'origin': str(job), 'scope': args.events,
        'retained_seconds': [{'event': e['id'], 'before': coverage(e),
                              'after': coverage(next(x for x in data['events'] if x['id'] == e['id']))}
                             for e in original if e['id'] in args.events],
        'parts': [{'index': p['index'], 'duration': p['duration'], 'source_end': p['cuts'][-1]['end'],
                   'ending': p.get('ending')} for p in plan['parts']], 'warnings': plan['warnings']})
    encoder = choose_encoder(destination / 'render')
    for index in args.parts:
        part = plan['parts'][index - 1]
        report('render', 0, f'Rendering preview {index}, {part["duration"]:.2f}s')
        path = render_part(source, part, data['probe'], destination / 'output',
                           destination / 'render' / f'part_{index:03}', encoder)
        save(destination / f'validation-{index}.json', validate_export(path, part['duration'], destination / 'render'))
        print(path, flush=True)


if __name__ == '__main__':
    main()
