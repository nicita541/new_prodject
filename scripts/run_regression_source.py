"""Run a normal API job, reusing verified identical factual/model checkpoints.

Development utility: old results are preserved. No edit decisions are injected.
"""
import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, JOBS


def api(path, body=None, method=None):
    request=urllib.request.Request('http://127.0.0.1:8765'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(request,timeout=45) as response:
        return json.load(response)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_id')
    parser.add_argument('--episode')
    parser.add_argument('--project')
    parser.add_argument('--reuse',type=Path)
    parser.add_argument('--record',type=Path,required=True)
    args=parser.parse_args()
    if api('/api/health')['busy']:
        raise ValueError('Another worker is active')
    reuse=args.reuse.resolve() if args.reuse else None
    sources=json.loads((ROOT/'data/sources.json').read_text('utf-8'))
    current=Path(sources[args.source_id]['path']).resolve()
    current.relative_to(ROOT)
    if reuse:
        reuse.relative_to(ROOT)
        prior=Path(json.loads((reuse/'source.json').read_text('utf-8'))['path']).resolve()
        prior.relative_to(ROOT)
        if digest(prior)!=digest(current):
            raise ValueError('Cannot reuse preparation from another source')
    episode=args.episode
    if not episode:
        project=api('/api/projects',{'title':args.project})
        episode=api('/api/projects/'+project['id']+'/episodes',{'number':1})['id']
        api('/api/episodes/'+episode+'/settings',{'source_id':args.source_id,
            'analysis_provider':'deepseek_plan','layout':'cinema','caption_style':'accent'},'PUT')
    job=api('/api/episodes/'+episode+'/jobs',{},'POST')
    if reuse:
        # Stop before preprocessing/model calls, then copy only identical inputs
        # or signatures independently checked by the production pipeline.
        api('/api/jobs/'+job['id']+'/cancel',{},'POST')
        while api('/api/health')['busy']:
            time.sleep(.25)
        directory=JOBS/job['id']
        for name in ('audio.wav','probe.json','transcript.json','analysis.meta.json','shots.json','shots.meta.json'):
            source=reuse/name
            if source.is_file():shutil.copy2(source,directory/name)
        for name in ('visual','story_refinement','title_units','closing_novelty','pacing'):
            if (reuse/name).is_dir():shutil.copytree(reuse/name,directory/name,dirs_exist_ok=True)
        # A cancelled preparation pass must have sent no paid calls.
        spending=api('/api/jobs/'+job['id']+'/spending')
        if spending['job_total_usd']!='0':
            raise ValueError('Unexpected paid request during preparation reuse; review before resuming')
        job=api('/api/jobs/'+job['id']+'/retry',{},'POST')
    record={'source_id':args.source_id,'episode_id':episode,'job_id':job['id'],'reuse':str(reuse) if reuse else None}
    args.record.resolve().relative_to(ROOT)
    args.record.parent.mkdir(parents=True,exist_ok=True)
    args.record.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
