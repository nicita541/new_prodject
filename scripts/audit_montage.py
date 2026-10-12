"""Generic source/output audit: measures and visual evidence, no edit injection."""
import argparse
import json
import math
import statistics
import sys
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
from PIL import Image,ImageDraw,ImageFont
from app.config import JOBS,ROOT
from app.json_store import atomic_json
from app.deepseek import job_spending
from app.planner import MAX_DURATION

def load(folder,name):return json.loads((folder/name).read_text('utf-8'))

def pictures(source,groups,folder,prefix,columns=4):
    video=cv2.VideoCapture(str(source))
    width,height=320,208
    font=ImageFont.load_default(size=15)
    try:
        last=(video.get(cv2.CAP_PROP_FRAME_COUNT)-1)/video.get(cv2.CAP_PROP_FPS)
        for offset in range(0,len(groups),6):
            rows=groups[offset:offset+6]
            sheet=Image.new('RGB',(width*columns,height*len(rows)),'#121212')
            draw=ImageDraw.Draw(sheet)
            for row,(label,times) in enumerate(rows):
                for column,t in enumerate(times):
                    video.set(cv2.CAP_PROP_POS_MSEC,min(max(0,t),last)*1000)
                    ok,pixels=video.read()
                    if not ok:raise ValueError(f'Cannot decode source at {t}')
                    picture=Image.fromarray(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB))
                    picture.thumbnail((width,180))
                    x,y=column*width,row*height
                    sheet.paste(picture,(x+(width-picture.width)//2,y+28+(180-picture.height)//2))
                    draw.text((x+3,y+3),f'{label} | {t:.2f}s',font=font,fill='white')
            sheet.save(folder/f'{prefix}-{offset//6+1:02}.jpg',quality=91)
    finally:video.release()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job',type=uuid.UUID)
    parser.add_argument('--pictures',action='store_true')
    args=parser.parse_args()
    folder=JOBS/str(args.job)
    state=load(folder,'job.json')
    if state['status']!='completed':raise ValueError('Audit requires a completed job')
    plan=load(folder,'plan.json');transcript=load(folder,'transcript.json');probe=load(folder,'probe.json')
    source=Path(load(folder,'source.json')['path']).resolve();source.relative_to(ROOT)
    qa=folder/'qa';qa.mkdir(exist_ok=True)
    parts=plan['parts'];lengths=[p['duration'] for p in parts]
    merged=[]
    for part in parts:
        if part['duration']>MAX_DURATION+.001:raise ValueError('Part exceeds processing duration limit')
        for cut in part['cuts']:
            if merged and cut['start']<merged[-1]['end']-.002:raise ValueError('Source chronology overlaps')
            if merged and cut['start']<=merged[-1]['end']+.002:merged[-1]['end']=cut['end']
            else:merged.append({'start':cut['start'],'end':cut['end']})
    gaps=[];left=0
    for cut in merged+[{'start':probe['duration'],'end':probe['duration']}]:
        if cut['start']-left>.05:gaps.append({'start':left,'end':cut['start']})
        left=cut['end']
    retained=[];partial=[]
    for word in transcript['words']:
        hits=[c for c in merged if c['start']<word['end']-.002 and c['end']>word['start']+.002]
        if any(c['start']<=word['start']+.002 and c['end']>=word['end']-.002 for c in hits):retained.append(word)
        elif hits:partial.append(word)
    events=load(folder,'events.json')
    report={'job':str(args.job),'source':source.name,'source_seconds':probe['duration'],
        'selected_seconds':round(sum(lengths),3),'removed_seconds':round(probe['duration']-sum(lengths),3),
        'parts':len(parts),'durations':[round(v,3) for v in lengths],
        'duration_spread':round(max(lengths)-min(lengths),3),'duration_std':round(statistics.pstdev(lengths),3),
        'source_words':len(transcript['words']),'retained_words':len(retained),'partial_words':partial,
        'warnings':plan.get('warnings',[]),'removed_intervals':gaps,
        'editorial_evidence':[{k:e[k] for k in ('id','start','end','omitted_story_units','excluded_credit_ranges',
             'excluded_title_units','excluded_closing_ranges','pacing_removed','global_omission') if k in e} for e in events],
        'spending':job_spending(folder),
        'note':'Account decrease is not a per-key/job invoice; token ceiling excludes discounts. Visual samples are evidence, not a universal quality guarantee.'}
    atomic_json(qa/'audit.json',report)
    if args.pictures:
        groups=[(f'GAP {i+1}',[max(0,g['start']-.4),g['start']+(g['end']-g['start'])*.25,
                             g['start']+(g['end']-g['start'])*.75,min(probe['duration']-.05,g['end']+.4)])
                for i,g in enumerate(gaps) if g['end']-g['start']>.75]
        pictures(source,groups,qa,'removed')
        times=list(range(0,math.ceil(probe['duration']),10))
        groups=[('SOURCE',times[i:i+4]) for i in range(0,len(times),4)]
        pictures(source,groups,qa,'source')
    print(json.dumps({k:report[k] for k in ('job','parts','selected_seconds','removed_seconds','duration_spread','duration_std','retained_words')},ensure_ascii=False),flush=True)
    print('partial_words',len(partial),'warnings',len(report['warnings']),flush=True)

if __name__=='__main__':main()
