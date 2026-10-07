"""Opt-in actual LocalVision quality run. No semantic answers enter the pipeline.

Run from the workspace with its portable Python. Building/calibration never
starts a model. Expected answers are evaluated only after scene inference.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.config import IMPORTS, JOBS, VLM_MODEL, VLM_PROJECTOR, setup_environment
from app.media_probe import atomic_json, detect_shots, load_json, probe_media, raw_shot_evidence
from app.scene_detection import scene_checkpoint
from app.vision import LocalVision
from tests.raw_video_fixtures import FIXTURE_NAMES, build_fixture


def workspace(path):
    path = Path(path).resolve()
    path.relative_to(ROOT)
    return path


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


class RecordedVision:
    """Transparent recorder of real requests/responses; never fabricates output."""
    def __init__(self, vision, directory):
        if not isinstance(vision,LocalVision):
            raise TypeError('Production quality requires a real LocalVision session')
        self.vision = vision
        self.directory = workspace(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.calls = 0
        self.calls = max([0,*[int(p.stem.split('-')[-1]) for p in self.directory.glob('request-*.json')]])
        self.initial_calls = self.calls

    def __getattr__(self,name):
        return getattr(self.vision,name)

    def query(self,prompt,image=None,max_tokens=1200,schema=None):
        self.calls += 1
        images = image if isinstance(image,(list,tuple)) else [image] if image is not None else []
        record = {'request':self.calls,'prompt':prompt,'schema':schema,'max_tokens':max_tokens,
                  'images':[{'path':str(path),'sha256':sha256(path)} for path in images]}
        atomic_json(self.directory/f'request-{self.calls:03d}.json',record)
        started = time.monotonic()
        try:
            result = self.vision.query(prompt,image,max_tokens=max_tokens,schema=schema)
        except BaseException as error:
            atomic_json(self.directory/f'response-{self.calls:03d}.json',{
                'elapsed_seconds':time.monotonic()-started,'error_type':type(error).__name__,'error':str(error)})
            raise
        atomic_json(self.directory/f'response-{self.calls:03d}.json',{
            'elapsed_seconds':time.monotonic()-started,'response':result})
        return result


def run_stage1(source,transcript,directory,vision):
    """Original file -> actual FFmpeg/perception -> actual semantic boundary VLM."""
    from app.media_evidence import perception_checkpoint
    directory = workspace(directory)
    directory.mkdir(parents=True,exist_ok=True)
    source = workspace(source)
    probe = probe_media(source)
    atomic_json(directory/'raw_input.json',{'source':str(source),'source_sha256':sha256(source),'transcript':transcript})
    atomic_json(directory/'probe.json',probe)
    shots = detect_shots(source,probe['duration'],directory,lambda:False)
    atomic_json(directory/'shots.json',shots)
    perception = perception_checkpoint(source,probe['duration'],shots,transcript,directory,lambda:False,
                                       audio_stream=probe.get('audio_stream',0))
    atomic_json(directory/'measured_perception.json',perception)
    recorder = RecordedVision(vision,directory/'actual_model')
    scenes = scene_checkpoint(source,sha256(source),probe['duration'],shots,transcript,directory,
                              lambda:False,vision=recorder,perception=perception)
    atomic_json(directory/'actual_scenes.json',scenes)
    return {'source':str(source),'probe':probe,'shots':shots,'perception':perception,
            'scenes':scenes,'actual_model_requests':recorder.calls,
            'new_model_requests':recorder.calls-recorder.initial_calls}


def evaluate_stage1(name,result):
    """Oracle applies ONLY to finished artifacts, never prompts or input files."""
    scenes = result['scenes']
    cuts = [s['start'] for s in scenes[1:]]
    decisions = [d for s in scenes for d in s.get('evidence',{}).get('boundary_decisions',[])]
    proofs = [(d['time'],d.get('boundary_verification') or {}) for d in decisions]
    raw = raw_shot_evidence(result['shots'])
    raw_times = {round(row['time'],3) for row in raw}
    raw_times.update(round(p['time'],3) for p in result['perception'].get('proposals',[])
                     if 'ffmpeg' in p.get('origins',[]))
    motion = result['perception'].get('motion',{})
    checks = []
    def check(label,passed,actual):
        checks.append({'criterion':label,'passed':bool(passed),'actual':actual})
    def near(start,end):
        return any(start <= t <= end for t in cuts)
    def trustworthy(proof):
        return (proof.get('source')=='semantic_boundary_verification' and proof.get('confidence',0)>=.88
                and not proof.get('uncertain',True) and proof.get('accepted',False))
    def physical(start,end,types=None):
        return any(start <= t <= end and trustworthy(p)
            and (p.get('physical_transition') or p.get('character_state_changed') or p.get('object_state_changed'))
            and (types is None or p.get('transition_type') in types) for t,p in proofs)
    check('Complete positive chronological source coverage',bool(scenes) and abs(scenes[0]['start']) < .001
          and abs(scenes[-1]['end']-result['probe']['duration']) < .001
          and all(s['start'] < s['end'] for s in scenes)
          and all(abs(a['end']-b['start']) < .001 for a,b in zip(scenes,scenes[1:])),cuts)
    if name == 'reverse_shots_same_room':
        check('Alternating dialogue camera views remain one semantic scene',len(scenes)==1,cuts)
        check('Fixture actually exercises raw FFmpeg camera-cut evidence',len(raw_times)>=4,sorted(raw_times))
        check('Camera editing is distinct from low intra-shot physical motion',
              motion.get('adequate_coverage',False) and motion.get('physical_motion_density',1)<.25,motion)
    elif name == 'similar_rooms':
        check('Different similar-colour rooms have a trustworthy visual location proof near 6s',
              near(4.8,7.2) and any(4.8<=t<=7.2 and trustworthy(p) and p.get('location_changed') for t,p in proofs),
              [{'time':t,'proof':p} for t,p in proofs if 4.8<=t<=7.2])
    elif name == 'binding_same_background':
        check('Binding wrists is supported from pixels with unchanged background',physical(4,8,{'binding','capture','other'}),
              [{'time':t,'proof':p} for t,p in proofs if 4 <= t <= 8])
    elif name == 'kidnapping_vehicle':
        check('Capture/binding transition independently detected',physical(4.5,8.2,{'binding','capture','other'}),cuts)
        check('Transport into vehicle independently supported by visual evidence',near(7.5,11.8) and
              any(7.5<=t<=11.8 and trustworthy(p) and (p.get('transition_type')=='enter_vehicle' or p.get('location_changed')) for t,p in proofs),
              [{'time':t,'proof':p} for t,p in proofs if 7.5<=t<=11.8])
        check('Source retains the intervening short transition as separate evidence',
              any(4.5 <= s['start'] <= 8.5 and s['end'] <= 11.8 for s in scenes),
              [(s['start'],s['end']) for s in scenes])
    elif name == 'slow_fade':
        check('Slow fade proposes/detects the following scene without a hard cut',near(4.5,8.5),cuts)
    elif name == 'short_action_during_asr':
        check('Brief folder handover inside a continuous spoken line is detected',physical(4.5,7.5,{'handover','other'}),cuts)
    elif name == 'long_tracking_action':
        density,coverage = motion.get('physical_motion_density'),motion.get('measurement_coverage')
        check('Continuous tracking has high aggregate physical motion with usable coverage',
              motion.get('available',False) and motion.get('adequate_coverage',False)
              and type(density) in (int,float) and math.isfinite(density) and density>=.45
              and type(coverage) in (int,float) and math.isfinite(coverage) and coverage>=.35,motion)
        check('Tracking action has few actual raw camera cuts',len(raw_times)<=2,sorted(raw_times))
    return {'fixture':name,'passed':all(c['passed'] for c in checks),'checks':checks,
            'actual_model_requests':result['actual_model_requests']}


def calibration_manifest(directory):
    """Read existing sources/ASR only; propose factual windows for human review."""
    directory = workspace(directory)
    directory.mkdir(parents=True,exist_ok=True)
    imports = IMPORTS.resolve()
    sources = {}
    for job in sorted(JOBS.iterdir()):
        source_json,asr_json = job/'source.json',job/'transcript.json'
        if not source_json.is_file() or not asr_json.is_file():
            continue
        try:
            source = Path(load_json(source_json)['path']).resolve()
            source.relative_to(imports)
            if not source.is_file() or str(source) in sources:
                continue
            transcript = load_json(asr_json)
            if not transcript.get('words'):
                continue
            probe = load_json(job/'probe.json') if (job/'probe.json').is_file() else probe_media(source)
            shots = load_json(job/'shots.json') if (job/'shots.json').is_file() else []
        except (OSError,ValueError,KeyError):
            continue
        duration = probe['duration']
        words = transcript['words']
        candidates = []
        for start in range(0,max(1,int(duration)-24),12):
            end = min(duration,start+24)
            intervals = sorted((max(start,w['start']),min(end,w['end'])) for w in words if w['start']<end and w['end']>start)
            union = []
            for a,b in intervals:
                if union and a <= union[-1][1]:
                    union[-1] = (union[-1][0],max(b,union[-1][1]))
                else:
                    union.append((a,b))
            speech = sum(b-a for a,b in union)/(end-start)
            cuts = sum(start < s['start'] < end for s in shots)
            candidates.append({'start':start,'end':end,'measured_speech_ratio':round(speech,4),'measured_camera_cuts':cuts})
        categories = {
            'speech_and_slow_dialogue':sorted(candidates,key=lambda c:(-c['measured_speech_ratio'],c['measured_camera_cuts'])),
            'reverse_shot_candidate':sorted(candidates,key=lambda c:(-(c['measured_speech_ratio']*c['measured_camera_cuts']))),
            'action_candidate':sorted(candidates,key=lambda c:(c['measured_speech_ratio'],-c['measured_camera_cuts'])),
            'long_tracking_candidate':sorted(candidates,key=lambda c:(c['measured_camera_cuts'],c['measured_speech_ratio']))}
        proposals = []
        for category,ordered in categories.items():
            for candidate in ordered[:2]:
                proposals.append({**candidate,'review_use':category,'review_status':'unreviewed',
                    'meaning':'Factual speech/cut screening only; visual action and scene class require manual inspection.'})
        sources[str(source)] = {'source':str(source),'transcript':str(asr_json),'duration':duration,
                               'candidate_clips':proposals}
    manifest = {'status':'review_candidates_only','semantic_labels_supplied_to_pipeline':False,
                'sources':list(sources.values()),'unpaired_imports':[
                    str(path) for path in sorted(IMPORTS.glob('*/*')) if path.suffix.lower() in ('.mp4','.mkv','.webm')
                    and str(path.resolve()) not in sources],
                'limitation':'Only available ASR sources are paired. Action/tracking proposals are unconfirmed until visual review; thresholds are not calibrated by this manifest.'}
    atomic_json(directory/'calibration_manifest.json',manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--run-stage1',action='store_true')
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--resume-run',type=Path,help='Reuse identity-validated checkpoints and append real requests')
    parser.add_argument('--fixture',action='append',choices=FIXTURE_NAMES)
    parser.add_argument('--directory',type=Path,default=ROOT/'scratch/raw_video_quality')
    parser.add_argument('--model',type=Path,default=VLM_MODEL)
    parser.add_argument('--projector',type=Path,default=VLM_PROJECTOR)
    args = parser.parse_args()
    if not (args.build or args.run_stage1 or args.calibrate):
        parser.error('Choose --build, --calibrate or explicit --run-stage1')
    setup_environment()
    directory = workspace(args.directory)
    names = args.fixture or list(FIXTURE_NAMES)
    if args.build:
        for name in names:
            source,_ = build_fixture(name,directory/'fixtures'/name)
            print(json.dumps({'built':name,'source':str(source)},ensure_ascii=False),flush=True)
    if args.calibrate:
        manifest = calibration_manifest(directory/'calibration')
        print(json.dumps({'calibration_sources':len(manifest['sources']),'manifest':str(directory/'calibration/calibration_manifest.json')}),flush=True)
    if not args.run_stage1:
        return 0
    # One real session owns VRAM for all selected fixtures. No fake-model option.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run = workspace(args.resume_run) if args.resume_run else directory/'runs'/stamp
    run.mkdir(parents=True,exist_ok=True)
    results = []
    with LocalVision(run,lambda:False,model=workspace(args.model),projector=workspace(args.projector)) as vision:
        for name in names:
            job = run/name
            source = directory/'fixtures'/name/'source.mp4'
            try:
                transcript = load_json(directory/'fixtures'/name/'transcript.json')
                actual = run_stage1(source,transcript,job,vision)
                result = evaluate_stage1(name,actual)
            except Exception as error:
                from app.scene_understanding import _control_failure
                if _control_failure(error):
                    raise
                result = {'fixture':name,'passed':False,'error_type':type(error).__name__,'error':str(error)}
            atomic_json(job/'assertions.json',result)
            results.append(result)
            print(json.dumps({'fixture':name,'passed':result['passed'],
                'failed':[c['criterion'] for c in result.get('checks',[]) if not c['passed']],
                'actual_model_requests':result.get('actual_model_requests'),
                **({'error':result['error']} if 'error' in result else {})},ensure_ascii=True),flush=True)
    atomic_json(run/'quality_summary.json',{'stage':1,'real_local_model':True,'fixtures':results,
                                         'passed':all(r['passed'] for r in results)})
    print('Quality artifacts: '+str(run),flush=True)
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
