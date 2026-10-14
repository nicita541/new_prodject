"""Use existing ending proposal/verification only for failed actual part ends."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .cancellation import check_cancelled
from .content_identity import digest
from .json_store import atomic_json, read_json


def recover_missing_endings(analysis, plan, problems, job_dir, vision, report, cancelled):
    from . import endings
    from .final_quality import _source_part_endings
    from .selection_gate import source_selection_readiness
    from .source_ranges import merge_ranges
    events = copy.deepcopy(analysis['events'])
    wanted = {p.get('part') for p in problems if p.get('code') == 'missing_original_semantic_ending'}
    if not wanted or plan is None:
        return events, []
    if source_selection_readiness(events)['status'] != 'passed':
        return events, [{'stage':'endings','status':'unresolved','reason':'source_selection_not_ready'}]
    retained = merge_ranges(cut for part in plan['parts'] for cut in part['cuts'])
    transcript = analysis['transcript']
    existing = _source_part_endings(events,transcript,plan['parts'],[],
        speech_overrides=analysis.get('speech_handle_overrides',[]))
    directory = Path(job_dir)/'endings'/'quality-targets'
    audit = []
    for part in plan['parts']:
        check_cancelled(cancelled)
        if part['index'] not in wanted:
            continue
        if part['index'] in existing:
            audit.append({'stage':'endings','part':part['index'],'status':'accepted','cache_hit':True})
            continue
        time = part['cuts'][-1]['end']
        owner = next((e for e in events if e['start'] < time <= e['end']),None)
        if (owner is None or not endings._safe(time,transcript.get('words',[])) or
                any(s['start'] < time < s['end'] for s in transcript.get('segments',[]))):
            audit.append({'stage':'endings','part':part['index'],'status':'unresolved','reason':'unsafe_source_boundary'})
            continue
        proposal = {'id':'repair_'+digest({'time':time,'event':owner['id']})[:20],
                    'time':time,'kind':'transition','confidence':0,
                    'evidence':'Unconfirmed actual part boundary; inspect only its retained dialogue.'}
        context = endings._ending_context(proposal,transcript,retained)
        identity = {'version':1,'context':context,
                    'source':read_json(Path(job_dir)/'analysis.meta.json',{}).get('source'),
                    'native_code':hashlib.sha256(Path(endings.__file__).read_bytes()).hexdigest()}
        signature = digest(identity)
        path = directory/(signature+'.json')
        try:
            saved = read_json(path,{})
        except (OSError,ValueError,UnicodeError):
            saved = {}
        approved = None
        if saved.get('identity') == identity and saved.get('output_hash') == digest(saved.get('endings')):
            candidate = saved['endings']
            if isinstance(candidate,list) and not candidate:
                approved = []
            elif isinstance(candidate,list) and len(candidate)==1 and candidate[0].get('id')==proposal['id']:
                trial = copy.deepcopy(events)
                next(e for e in trial if e['id']==owner['id']).setdefault('part_endings',[]).extend(candidate)
                verified = _source_part_endings(trial,transcript,plan['parts'],[],
                    speech_overrides=analysis.get('speech_handle_overrides',[]))
                if part['index'] in verified:
                    approved = candidate
        cached = approved is not None
        if approved is None:
            report('quality_gate',.68,f"Проверяем только концовку части {part['index']}")
            proposed = endings.verify_endings([proposal],transcript,retained,vision,classify=True,min_confidence=.5)
            check_cancelled(cancelled)
            approved = endings.verify_endings(proposed,transcript,retained,vision)
            check_cancelled(cancelled)
            atomic_json(path,{'identity':identity,'endings':approved,'output_hash':digest(approved)})
        if approved:
            owner['part_endings'] = [e for e in owner.get('part_endings',[]) if abs(e.get('time',-1)-time)>.002]+approved
        audit.append({'stage':'endings','part':part['index'],'time':time,'cache_hit':cached,
                      'status':'accepted' if approved else 'unresolved','request':signature})
    return events,audit
