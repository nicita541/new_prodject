"""Check the current title classifier on specified baseline source events.

Diagnostics only: publishes QA JSON, leaves completed plans/exports untouched.
Remote checks use the selected job's existing allowance and accounting.
"""
import argparse
import copy
import json
import re
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.analysis import vision_session
from app.config import JOBS
from app.deepseek import job_spending
from app.titles import TITLES_VERSION, refine_titles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=uuid.UUID)
    parser.add_argument('events', nargs='+')
    parser.add_argument('--provider', choices=('local', 'deepseek_plan'), default='local')
    args = parser.parse_args()
    if any(not re.fullmatch(r'event_\d{4}', item) for item in args.events):
        parser.error('Use existing event_NNNN IDs')
    job = JOBS / str(args.job)
    state=json.loads((job/'job.json').read_text('utf-8'))
    if state['status'] != 'completed':
        parser.error('Wait until the job is completed; do not compete with its worker')
    qa = job/'qa'/f'title-verification-v{TITLES_VERSION}'
    qa.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job/'source.json',qa/'source.json')
    transcript=json.loads((job/'transcript.json').read_text('utf-8'))
    shots=json.loads((job/'shots.json').read_text('utf-8'))
    events=[]
    for identifier in args.events:
        event=json.loads((job/'visual'/(identifier+'.json')).read_text('utf-8'))['event']
        event=copy.deepcopy(event)
        # Present the whole actual source interval to test mixed material;
        # do not reuse manual exclusions or prior model retention decisions.
        event['selected_ranges']=[{'start':event['start'],'end':event['end']}]
        events.append(event)
    before=job_spending(job) if args.provider=='deepseek_plan' else None
    with vision_session(job,lambda:False,args.provider) as vision:
        result=refine_titles(events,transcript,shots,qa,vision,
                             lambda stage,progress,message:print(message,flush=True),lambda:False)
    report={'mode':'current_classifier_on_complete_actual_source_events',
            'titles_version':TITLES_VERSION,'provider':args.provider,'input':events,'result':result,
            'spending_before':before,'spending_after':job_spending(job) if before else None,
            'note':'No changes to baseline decisions, manual exclusions, exports or job status.'}
    (qa/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    for event in result:
        print(event['id'],event.get('excluded_title_units',[]),event.get('story_warnings',[]),flush=True)


if __name__=='__main__':
    main()
