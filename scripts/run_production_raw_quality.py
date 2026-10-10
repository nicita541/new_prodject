"""Genuine production video+ASR run with a transparent local-model observer.

No evaluator answers enter production. Analysis-only runs are diagnostics,
never proof of rendering or final quality. Models remain owned by production.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import setup_environment
from app.media_probe import atomic_json, load_json
from app.semantic_identity import semantic_identity
from scripts.run_raw_video_quality import RecordedVision, sha256, workspace


def run(fixture, job, *, render=False, dramatic=False, preferred_part_count=None,
        analysis_provider="local"):
    import app.analysis as analysis_module
    from app.vision import LocalVision
    from app.flash_story_trial import TrialStoryVision
    from app.editorial import DEFAULT_PROFILE, DRAMATIC_PROFILE
    if analysis_provider not in ("local", "local_fast_story", "local_flash_story"):
        raise ValueError("Raw quality observer supports genuine local 4B or explicit Flash-story pilot only")
    fixture, job = workspace(fixture), workspace(job)
    manifest = load_json(fixture/'input.json')
    if set(manifest) not in ({'source'}, {'source', 'transcript'}):
        raise ValueError('Quality input permits only raw video and ordinary ASR')
    source = workspace(manifest['source'])
    transcript_path = workspace(manifest['transcript']) if 'transcript' in manifest else None
    if not source.is_file() or transcript_path is not None and not transcript_path.is_file():
        raise ValueError('Missing actual raw quality inputs')
    job.mkdir(parents=True, exist_ok=True)
    if preferred_part_count is not None and (type(preferred_part_count) is not int or not 1 <= preferred_part_count <= 64):
        raise ValueError('Editorial preferred part count must be 1..64')
    requested_settings = {'dramatic':bool(dramatic),'preferred_part_count':preferred_part_count,
                          'analysis_provider':analysis_provider}
    run_settings = job/'observed-run-settings.json'
    if run_settings.is_file() and load_json(run_settings) != requested_settings:
        raise ValueError('Resume editorial settings do not match original run')
    atomic_json(run_settings,requested_settings)
    original_inputs = {'source':str(source), 'source_sha256':sha256(source),
                       'transcript_sha256':sha256(transcript_path) if transcript_path else None,
                       'input_manifest_sha256':sha256(fixture/'input.json')}
    input_path=job/'original-inputs.json'
    if input_path.is_file():
        if load_json(input_path) != original_inputs:
            raise ValueError('Resume source/ASR does not match original inputs')
    else:
        atomic_json(input_path, original_inputs)
        atomic_json(job/'source.json', {'path':str(source), 'name':source.name})
        settings={'provider':analysis_provider}
        if transcript_path:
            atomic_json(job/'transcript.json', load_json(transcript_path))
            settings.update(transcript_mode='provided', transcript_source_sha256=original_inputs['source_sha256'])
        atomic_json(job/'analysis-settings.json', settings)
        atomic_json(job/'render-settings.json', {'layout':'cinema','caption_style':'classic'})
        atomic_json(job/'editorial-settings.json', DRAMATIC_PROFILE if dramatic else DEFAULT_PROFILE)
        if preferred_part_count is not None:
            atomic_json(job/'planning-preferences.json',{'preferred_part_count':preferred_part_count})
    atomic_json(job/'observer-input-locations.json', {'input':str(fixture/'input.json'),
        'transcript':str(transcript_path) if transcript_path else None})
    starting_code_identity = semantic_identity()
    atomic_json(job/'observer-code-identity.json', starting_code_identity)
    real_factory=analysis_module.vision_session
    sessions=[]

    @contextmanager
    def observed_factory(*args, **kwargs):
        with real_factory(*args, **kwargs) as vision:
            if isinstance(vision, LocalVision):
                recorder = RecordedVision(vision, job/'actual-model')
                initial = recorder.initial_calls
                cloud = False
            elif analysis_provider == "local_flash_story" and isinstance(vision, TrialStoryVision):
                # Cloud story requests are metered and journaled by TrialStoryVision.
                # Local visual 4B and final 9B still use the genuine raw recorder.
                # Never copy cloud prompts/images/responses into the public report.
                recorder = vision
                cloud = True
                def dispatched():
                    path = job / "deepseek-story-pilot.json"
                    if not path.is_file():
                        return 0
                    state = load_json(path)
                    return len(state.get("reserved", [])) if isinstance(state, dict) else 0
                initial = dispatched()
            else:
                raise TypeError('Raw quality requires genuine local inference or explicit Flash pilot')
            public={'model':"deepseek-flash-pilot" if cloud else str(vision.model),
                    'projector':"remote" if cloud else str(vision.projector),
                    'thinking':bool(getattr(vision,'thinking',False)),
                    'initial_requests':initial}
            sessions.append(public)
            atomic_json(job/'observed-sessions.json', sessions)
            try:
                yield recorder
            finally:
                current = dispatched() if cloud else recorder.calls
                public['new_requests'] = current - initial
                public['total_requests'] = current
                atomic_json(job/'observed-sessions.json', sessions)

    report_path=job/'observed-progress.jsonl'
    def report(stage, progress, message):
        with report_path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'stage':stage,'progress':progress,'message':message},ensure_ascii=False)+'\n')
        print(json.dumps({'stage':stage,'progress':round(progress,3)},ensure_ascii=True),flush=True)
    started=time.monotonic()
    analysis_module.vision_session=observed_factory
    outcome={'mode':'production_render' if render else 'production_analysis_only', 'complete':False}
    try:
        if render:
            from app.pipeline import run_job
            outcome['outputs']=run_job(job,report,lambda:False)
            outcome['quality_gate']=load_json(job/'final_quality_gate.json')
            outcome['complete']=outcome['quality_gate']['status'] == 'passed'
            if (job/'analysis-final.json').is_file():
                atomic_json(job/'actual-analysis.json',load_json(job/'analysis-final.json'))
            outcome['export_sha256']={name:sha256(job/'output'/name) for name in outcome['outputs']}
        else:
            analysis=analysis_module.analyze(job,source,report,lambda:False)
            atomic_json(job/'actual-analysis.json',analysis)
            outcome['selection_gate']=analysis.get('selection_gate')
            outcome['analysis_returned']=True
            outcome['complete']=analysis.get('selection_gate',{}).get('status')=='passed'
    except BaseException as error:
        outcome.update(error_type=type(error).__name__,error=str(error))
        raise
    finally:
        analysis_module.vision_session=real_factory
        final_code_identity=semantic_identity()
        atomic_json(job/'observer-code-identity-final.json', final_code_identity)
        outcome['pipeline_code_stable']=final_code_identity == starting_code_identity
        if not outcome['pipeline_code_stable']:
            outcome['complete']=False
            outcome['proof_limitation']='Pipeline source changed during this diagnostic run'
        outcome['elapsed_seconds']=time.monotonic()-started
        outcome['actual_model_requests']=len(list((job/'actual-model').glob('request-*.json')))
        atomic_json(job/'observed-outcome.json',outcome)
        print(json.dumps({'complete':outcome['complete'],'actual_model_requests':outcome['actual_model_requests'],
                          'error_type':outcome.get('error_type')},ensure_ascii=True),flush=True)
    return outcome


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-dir',type=Path,required=True)
    parser.add_argument('--job-dir',type=Path)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--dramatic',action='store_true')
    parser.add_argument('--preferred-parts',type=int)
    args=parser.parse_args()
    setup_environment()
    job=args.job_dir or ROOT/'scratch/raw_video_quality/production_runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')/'raw-000'
    result=run(args.fixture_dir,job,render=args.render,dramatic=args.dramatic,preferred_part_count=args.preferred_parts)
    return 0 if result['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
