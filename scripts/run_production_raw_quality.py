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
from app.json_store import analysis_json as atomic_json, load_json
from app.semantic_identity import semantic_identity
from scripts.run_raw_video_quality import RecordedVision, sha256, workspace


def _transport_records(job, remote_model):
    from app.model_perf import model_alias
    path = Path(job)/'model-performance.jsonl'
    counts = {'local': 0, 'remote': 0, 'complete': True}
    if not path.is_file():
        return counts
    for line in path.read_text('utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            counts['complete'] = False
            continue
        if not isinstance(row, dict):
            counts['complete'] = False
            continue
        if row.get('event') == 'request_start':
            counts['remote' if row.get('model') == model_alias(remote_model) else 'local'] += 1
    return counts



def _standalone_accepted(published, current, outputs):
    """A preserved older publication is not success of the current attempt."""
    if (not isinstance(published, dict) or not isinstance(current, dict)
            or current.get('status') not in ('ready', 'partial')
            or current.get('technical_failures') != [] or not current.get('accepted')):
        return False
    plan = published.get('plan', {})
    if plan.get('outcome') != current or set(published.get('outputs', [])) != set(outputs):
        return False
    try:
        accepted = {item['id']: item['filename'] for item in current['accepted']
                    if item['status'] == 'ready' and item['export_eligible'] is True}
        parts = {part['candidate_id'] for part in plan['parts']}
        artifacts = {item['candidate_id']: item['video']['filename'] for item in published['artifacts']}
        return (len(accepted) == len(current['accepted']) and set(accepted) == parts
                and accepted == artifacts and set(accepted.values()).issubset(outputs))
    except (KeyError, TypeError):
        return False


def run(fixture, job, *, render=False, dramatic=False, preferred_part_count=None,
        analysis_provider="local", story_objective=None):
    import app.analysis as analysis_module
    from app.vision import LocalVision
    from app.flash_story_trial import TrialStoryVision
    from app.deepseek import DeepSeekVision, MODEL as REMOTE_MODEL
    from app.editorial import DEFAULT_PROFILE, DRAMATIC_PROFILE
    if analysis_provider not in ("local", "local_fast_story", "local_flash_story", "local_flash_story_budgeted", "deepseek_plan"):
        raise ValueError("Raw quality observer requires an explicit supported provider")
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
    if story_objective is not None:
        from app.story_objective import validate_objective
        story_objective = validate_objective(story_objective)
        requested_settings['story_objective'] = story_objective
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
    objective_path = job/'story-objective.json'
    if story_objective is not None:
        if objective_path.is_file() and load_json(objective_path) != story_objective:
            raise ValueError('Resume story objective differs from the recorded request')
        atomic_json(objective_path, story_objective)
    elif objective_path.is_file():
        raise ValueError('Resume must explicitly retain the original story objective')
    atomic_json(job/'observer-input-locations.json', {'input':str(fixture/'input.json'),
        'transcript':str(transcript_path) if transcript_path else None})
    starting_code_identity = semantic_identity()
    atomic_json(job/'observer-code-identity.json', starting_code_identity)
    real_factory=analysis_module.vision_session
    import app.vision as vision_module
    real_shared_factory = vision_module.vision_session
    import app.candidate_framing as candidate_framing
    real_framing_factory = candidate_framing.vision_session
    sessions=[]
    initial_transports = _transport_records(job, REMOTE_MODEL)

    def remote_dispatches():
        return _transport_records(job, REMOTE_MODEL)['remote']

    @contextmanager
    def observed_factory(*args, **kwargs):
        with real_factory(*args, **kwargs) as vision:
            if isinstance(vision, LocalVision):
                recorder = RecordedVision(vision, job/'actual-model')
                initial = recorder.initial_calls
                cloud = False
            elif analysis_provider in ("local_flash_story", "local_flash_story_budgeted") and isinstance(vision, TrialStoryVision):
                # Cloud story requests are metered and journaled by TrialStoryVision.
                # Local visual 4B and final 9B still use the genuine raw recorder.
                # Never copy cloud prompts/images/responses into the public report.
                recorder = vision
                cloud = True
                def dispatched():
                    path = job / ("deepseek-story-budgeted.json" if analysis_provider == "local_flash_story_budgeted"
                                  else "deepseek-story-pilot.json")
                    if not path.is_file():
                        return 0
                    state = load_json(path)
                    return len(state.get("reserved", [])) if isinstance(state, dict) else 0
                initial = dispatched()
            elif analysis_provider == 'deepseek_plan' and isinstance(vision, DeepSeekVision):
                recorder, cloud, dispatched = vision, True, remote_dispatches
                initial = dispatched()
            else:
                raise TypeError('Raw quality requires genuine local inference or explicit Flash pilot')
            public={'model':(REMOTE_MODEL if analysis_provider == 'deepseek_plan' else "deepseek-flash-pilot") if cloud else str(vision.model),
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
    # Candidate qualification imports the factory at its downstream boundary.
    # Observe that genuine route too, including local lazy acquisition.
    vision_module.vision_session=observed_factory
    candidate_framing.vision_session=observed_factory
    outcome={'mode':'production_render' if render else 'production_analysis_only', 'complete':False}
    try:
        if render:
            from app.pipeline import run_job
            outcome['outputs']=run_job(job,report,lambda:False)
            from app.story_objective import STANDALONE
            standalone = story_objective is not None and story_objective['objective'] == STANDALONE
            if standalone:
                from app.artifact_publication import current_revision, resolve_output
                published = current_revision(job)
                outcome['standalone_outcome'] = load_json(job/'standalone-outcome.json')
                outcome['complete'] = _standalone_accepted(published, outcome['standalone_outcome'], outcome['outputs'])
                outcome['quality_gate'] = {'status': 'passed' if outcome['complete'] else 'not_accepted',
                    'scope': 'each_published_candidate', 'actual_editorial_review': 'pending'}
            else:
                outcome['quality_gate']=load_json(job/'final_quality_gate.json')
                outcome['complete']=outcome['quality_gate']['status'] == 'passed'
            if (job/'analysis-final.json').is_file():
                atomic_json(job/'actual-analysis.json',load_json(job/'analysis-final.json'))
            outcome['export_sha256']={name:sha256(resolve_output(job,name,allow_legacy=False) if standalone else job/'output'/name)
                                     for name in outcome['outputs']}
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
        vision_module.vision_session=real_shared_factory
        candidate_framing.vision_session=real_framing_factory
        final_code_identity=semantic_identity()
        atomic_json(job/'observer-code-identity-final.json', final_code_identity)
        outcome['pipeline_code_stable']=final_code_identity == starting_code_identity
        if not outcome['pipeline_code_stable']:
            outcome['complete']=False
            outcome['proof_limitation']='Pipeline source changed during this diagnostic run'
        outcome['elapsed_seconds']=time.monotonic()-started
        transports = _transport_records(job, REMOTE_MODEL)
        outcome['recorded_local_calls']=len(list((job/'actual-model').glob('request-*.json')))
        outcome['local_model_requests']=transports['local']
        outcome['remote_transport_attempts']=transports['remote']
        outcome['transport_count_complete']=transports['complete'] and initial_transports['complete']
        outcome['actual_model_requests']=outcome['local_model_requests']+outcome['remote_transport_attempts']
        outcome['new_transport_attempts']=sum(transports[k]-initial_transports[k] for k in ('local','remote'))
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
    parser.add_argument('--standalone',action='store_true')
    parser.add_argument('--analysis-provider', default='local',
        choices=('local','local_fast_story','local_flash_story','local_flash_story_budgeted','deepseek_plan'))
    args=parser.parse_args()
    setup_environment()
    job=args.job_dir or ROOT/'scratch/raw_video_quality/production_runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')/'raw-000'
    result=run(args.fixture_dir,job,render=args.render,dramatic=args.dramatic,preferred_part_count=args.preferred_parts,
               analysis_provider=args.analysis_provider,
               story_objective={'objective':'standalone_shorts'} if args.standalone else None)
    return 0 if result['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
