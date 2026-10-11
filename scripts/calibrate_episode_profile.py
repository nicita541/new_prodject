"""Offline pace calibration from cached source measurements; no model calls.

Reviewed categories are used only for fitting/evaluation, never supplied to the
production profile builder. Held-out labels do not enter threshold selection.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLIPS = ROOT/'scratch/raw_video_quality/calibration/clips'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def profile_module():
    from app import episode_profile
    return episode_profile


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_clip(clip_id, clips=CLIPS):
    folder = Path(clips)/clip_id
    perception = _json(folder/'measurement/media-evidence.json')
    source = folder/'source.mp4'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != perception['source']['sha256']:
        raise ValueError('Source measurement hash differs: '+clip_id)
    duration = perception['source']['duration']
    raw = _json(folder/'measurement/shots.candidates.json')
    starts = sorted({0.0, *(r['accepted_time'] for r in raw
                            if r.get('accepted') is True and 0 < r['accepted_time'] < duration)})
    shots = [{'id': f'shot_{i:05d}', 'start': t,
              'end': starts[i+1] if i+1 < len(starts) else duration}
             for i, t in enumerate(starts)]
    return {'clip': clip_id, 'duration': duration, 'transcript': _json(folder/'transcript.json'),
            'shots': shots, 'raw_candidates': raw, 'perception': perception, 'source_sha256': digest}


def measurements(clips=CLIPS):
    module = profile_module()
    reviewed = _json(Path(clips)/'root_review.json')
    rows = []
    for clip_id in sorted(set(reviewed['training']) | set(reviewed['holdout'])):
        clip = load_clip(clip_id, clips)
        profile = module.build_episode_profile(clip['duration'], clip['transcript'], clip['shots'],
            raw_candidates=clip['raw_candidates'], perception=clip['perception'])
        rows.append({'clip': clip_id, 'source_sha256': clip['source_sha256'], 'duration': clip['duration'],
                     'speech_score': profile['speech_score'], 'motion_score': profile['motion_score'],
                     'editing_score': profile['editing_score'], 'raw_candidates': profile['metrics']['raw_candidates'],
                     'action_score': profile['action_score'], 'motion_reliable': profile['metrics']['motion_reliable'],
                     'actual': profile['profile']})
    return rows, reviewed


def classify(speech, motion, policy):
    if motion >= policy['motion_high']:
        return 'mixed' if speech >= policy['speech_high'] else 'action_dense'
    if motion <= policy['motion_low'] and speech >= policy['speech_high']:
        return 'dialogue_slow'
    return 'balanced'


def fit_thresholds(rows, training):
    """Use the training partition exclusively, with deterministic ties."""
    by_id = {r['clip']: r for r in rows}
    candidates = []
    for speech, high, low in itertools.product((.4, .45, .5, .55, .6, .65),
                                               (.35, .4, .45, .5, .55, .6, .65),
                                               (.1, .15, .2, .25, .3)):
        policy = {'speech_high': speech, 'motion_high': high, 'motion_low': low}
        errors = sum(classify(by_id[key]['speech_score'], by_id[key]['motion_score'], policy) != label
                     for key, label in training.items())
        distance = round(abs(speech-.6)+abs(high-.45)+abs(low-.2), 12)
        candidates.append((errors, distance, speech, high, low, policy))
    best = min(candidates, key=lambda r: r[:5])
    return {'policy': best[-1], 'training_error_count': best[0], 'search_candidates': len(candidates),
            'selection_rule': 'training errors, distance to .6/.45/.2, then numeric thresholds; no holdout fit'}


def calibration_report(clips=CLIPS):
    rows, reviewed = measurements(clips)
    fit = fit_thresholds(rows, reviewed['training'])
    partitions = {}
    for partition in ('training', 'holdout'):
        partitions[partition] = [{**r, 'expected_review_only': reviewed[partition][r['clip']],
            'passed': classify(r['speech_score'], r['motion_score'], fit['policy']) == reviewed[partition][r['clip']]}
            for r in rows if r['clip'] in reviewed[partition]]
    return {**fit, 'measurement_origin': 'cached decoded source optical flow and actual ASR',
            'semantic_labels_supplied_to_profile': False, 'results': partitions,
            'review_method': reviewed['review_method'],
            'limitations': ['12 short manually reviewed source clips, not episode semantic quality',
                'holdout contact sheets previously inspected; labels excluded from threshold selection',
                'editing frequency does not imply physical movement or a semantic action',
                'optical flow includes camera movement; accepted action evidence is a separate measure']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'temp/calibration_report.json')
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT not in output.parents:
        raise ValueError('Output must remain inside workspace')
    report = calibration_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'policy': report['policy'],
        'training_passed': sum(r['passed'] for r in report['results']['training']),
        'holdout_passed': sum(r['passed'] for r in report['results']['holdout'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
