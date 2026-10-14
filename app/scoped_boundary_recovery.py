"""Repair actual disputed source boundaries without rediscovering an episode."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from .content_identity import evidence_digest
from .source_ranges import merge_ranges

BOUNDARY_REASONS={'ambiguous_internal_boundary','semantic_boundary_unresolved','unverified_scene_boundary'}


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _catalog(analysis):
    scenes=copy.deepcopy(analysis.get('scenes',[]))
    if not scenes or len({s['id'] for s in scenes})!=len(scenes):
        raise ValueError('Source scene ownership catalog is missing')
    for index,scene in enumerate(scenes):
        if (not all(_finite(scene.get(k)) for k in ('start','end')) or not 0<=scene['start']<scene['end']
                or index and abs(scenes[index-1]['end']-scene['start'])>.002):
            raise ValueError('Source scene catalog has incomplete/overlapping ownership')
        evidence=scene.get('evidence')
        if not isinstance(evidence,dict):
            evidence=next((copy.deepcopy(e['scene_evidence']) for e in analysis['events']
                           if e.get('scene_id')==scene['id'] and isinstance(e.get('scene_evidence'),dict)),{})
            scene['evidence']=evidence
    return scenes


def _rows(analysis, scenes, problems):
    """Resolve problem IDs/ranges to persisted actual candidate boundaries."""
    requested=set()
    for problem in problems:
        if problem.get('recovery_stage')!='semantic_boundary':continue
        if problem.get('scene'):
            requested.add(problem['scene'])
        owner=next((e for e in analysis['events'] if e['id']==problem.get('event')),None)
        if owner is not None:
            requested.update(s['id'] for s in scenes if s['start']<owner['end'] and owner['start']<s['end'])
        window=problem.get('range')
        if isinstance(window,dict) and all(_finite(window.get(k)) for k in ('start','end')):
            requested.update(s['id'] for s in scenes if s['start']<window['end'] and window['start']<s['end'])
    segments={}
    for scene in scenes:
        for segment in scene['evidence'].get('source_segments',[]):
            if all(_finite(segment.get(k)) for k in ('start','end')) and segment['start']<segment['end']:
                key=(segment['start'],segment['end'])
                segments[key]=copy.deepcopy(segment)
    # Raw montage shots are legitimate source geometry, but do not invent
    # semantic candidates from them. A persisted disputed decision is required.
    for shot in analysis.get('shots',[]):
        if all(_finite(shot.get(k)) for k in ('start','end')):
            segments.setdefault((shot['start'],shot['end']),copy.deepcopy(shot))
    rows={}
    missing=[]
    for scene in scenes:
        if scene['id'] not in requested:continue
        decisions=scene['evidence'].get('boundary_decisions',[])
        disputed=[d for d in decisions if isinstance(d,dict) and (d.get('uncertain')
                   or (d.get('boundary_verification') or {}).get('uncertain'))]
        if not disputed:
            # Already-qualified accepted proof requires no new request. A bare
            # scene-level label cannot identify which source edge to inspect.
            if BOUNDARY_REASONS & set(scene.get('uncertainty_reasons',[])+scene['evidence'].get('uncertainty_reasons',[])):
                missing.append({'scene':scene['id'],'reason':'disputed_source_boundary_missing'})
            continue
        for decision in disputed:
            time=decision.get('time')
            if not _finite(time):
                missing.append({'scene':scene['id'],'reason':'source_boundary_time_missing'})
                continue
            left=[s for s in segments.values() if abs(s['end']-time)<=.002]
            right=[s for s in segments.values() if abs(s['start']-time)<=.002]
            if not left or not right:
                missing.append({'scene':scene['id'],'time':time,'reason':'immediate_source_neighbors_missing'})
                continue
            before=max(left,key=lambda s:s['start'])['start']
            after=min(right,key=lambda s:s['end'])['end']
            rows[round(time,6)]={'time':time,'before':before,'after':after,
                'measured':{'classification':'ambiguous_boundary','scoped_recovery':True,
                            'source_signals':copy.deepcopy(decision.get('signals',{}))}}
    for unknown in requested-{s['id'] for s in scenes}:
        missing.append({'scene':unknown,'reason':'source_scene_owner_missing'})
    return list(sorted(rows.values(),key=lambda r:r['time'])),missing


def _word_safe(time, transcript, first, last):
    crossing=[w for w in transcript.get('words',[]) if w['start']<time<w['end']]
    if not crossing:return time
    edges={w[k] for w in crossing for k in ('start','end')}
    safe=[edge for edge in edges if first<edge<last and abs(edge-time)<=.75
          and not any(w['start']<edge<w['end'] for w in transcript.get('words',[]))]
    if not safe:raise ValueError('No bounded whole-word edge for source boundary')
    return min(safe,key=lambda edge:(abs(edge-time),edge))


def _updated_scenes(scenes, proofs, transcript, source_key):
    first,last=scenes[0]['start'],scenes[-1]['end']
    cuts={s['start'] for s in scenes[1:]}
    for time,proof in proofs.items():
        existing=[s['start'] for s in scenes[1:] if abs(s['start']-time)<=.002
            or abs(s.get('evidence',{}).get('raw_boundary_time',s['start'])-time)<=.002]
        if proof['accepted']:
            cut=_word_safe(time,transcript,first,last)
            if not first<cut<last:raise ValueError('Boundary is outside source scene ownership')
            cuts.difference_update(existing)
            cuts.add(cut)
        else:
            cuts.difference_update(existing)
    edges=[first,*sorted(cuts),last]
    result=[]
    changed=[]
    for start,end in zip(edges,edges[1:]):
        owners=[s for s in scenes if s['start']<end and start<s['end']]
        exact=next((s for s in owners if (s['start'],s['end'])==(start,end)),None)
        relevant={time:p for time,p in proofs.items() if any(
            d.get('time')==time for owner in owners for d in owner['evidence'].get('boundary_decisions',[]))}
        if exact is not None and not relevant:
            result.append(copy.deepcopy(exact));continue
        record=copy.deepcopy(exact or owners[0])
        if exact is None:
            record['id']='scene_boundary_'+evidence_digest({'source':source_key['sha256'],'start':start,'end':end})[:20]
            changed.extend({'start':s['start'],'end':s['end']} for s in owners)
        record.update(start=start,end=end)
        evidence=record.setdefault('evidence',{})
        decisions={}
        for owner in owners:
            for old in owner['evidence'].get('boundary_decisions',[]):
                time=old.get('time')
                if not _finite(time) or not start-.002<=time<end:continue
                decision=copy.deepcopy(old)
                if time in proofs:
                    p=proofs[time]
                    decision.update(accepted=p['accepted'],confidence=p['confidence'],uncertain=p['uncertain'],
                                    reasons=p['reasons'],boundary_verification=copy.deepcopy(p))
                decisions[time]=decision
        evidence['boundary_decisions']=list(sorted(decisions.values(),key=lambda d:d['time']))
        evidence['source_segments']=[{**segment,'start':max(start,segment['start']),'end':min(end,segment['end'])}
            for owner in owners for segment in owner['evidence'].get('source_segments',[])
            if segment['start']<end and start<segment['end']]
        record['shot_ids']=list(dict.fromkeys(segment.get('shot_id',segment.get('id')) for segment in evidence['source_segments']))
        record['candidate_ids']=list(dict.fromkeys(segment['candidate_id'] for segment in evidence['source_segments']
                                                  if segment.get('candidate_id')))
        remaining=[d for d in decisions.values() if d.get('uncertain')]
        reasons=set(r for owner in owners for r in owner.get('uncertainty_reasons',[])+owner['evidence'].get('uncertainty_reasons',[]))
        reasons-=BOUNDARY_REASONS
        if remaining:reasons.add('ambiguous_internal_boundary')
        record['uncertainty_reasons']=sorted(reasons)
        evidence['uncertainty_reasons']=sorted(reasons)
        record['uncertain']=bool(reasons)
        evidence['scoped_boundary_recovery']={'version':1,'previous_owners':[s['id'] for s in owners],
            'source':copy.deepcopy(source_key),'proofs':copy.deepcopy(relevant)}
        if not reasons and relevant:
            visual=min(owner['evidence'].get('visual_coverage',0) for owner in owners)
            record['confidence']=min(min(p['confidence'] for p in relevant.values()),.94 if visual>=.75
                                     else record.get('confidence',.5))
        edge_proof=next(((time,p) for time,p in proofs.items() if p['accepted'] and abs(start-time)<=.75),None)
        if exact is None and edge_proof is not None:
            time,proof=edge_proof
            record['boundary_reason']=list(proof['reasons'])
            evidence['raw_boundary_time']=time
            if start!=time:evidence['word_safe_boundary']={'raw_time':time,'time':start,'reason':'asr_word_edge','uncertain':False}
        result.append(record)
    return result,merge_ranges(changed)


def recover_scoped_boundaries(source, analysis, problems, job_dir, vision, report, cancelled):
    """Return source-owned scenes/events, geometry deltas and explicit misses.

    Existing unit/selection proofs survive a semantic parent reassociation when
    their CURRENT interval is identical. Only intervals split by a newly proven
    edge need fresh native scene analysis and source-selection adjudication.
    """
    from .semantic_boundary import verify_scoped_boundary
    from .source_identity import source_identity
    from .scene_analysis import rebuild_scoped_event
    from .scene_understanding import _control_failure
    source,job_dir=Path(source).resolve(),Path(job_dir).resolve()
    original_events=copy.deepcopy(analysis['events'])
    result={'status':'not_required','events':original_events,'scenes':copy.deepcopy(analysis.get('scenes',[])),
            'changed_ranges':[],'changed_event_ids':[],'reassociated_event_ids':[],
            'removed_event_ids':[],'ownership':{},'scene_ownership':{},'reviewed_boundaries':[],'unresolved':[]}
    if not any(p.get('recovery_stage')=='semantic_boundary' for p in problems):return result
    try:
        scenes=_catalog(analysis)
        rows,missing=_rows(analysis,scenes,problems)
    except ValueError as error:
        return {**result,'status':'unresolved','unresolved':[{'reason':str(error)}]}
    result['unresolved'].extend(missing)
    if not rows:
        return {**result,'status':'unresolved' if missing else 'not_required'}
    source_key=source_identity(source,cancelled)
    proofs={}
    for row in rows:
        if cancelled():raise InterruptedError('Обработка отменена')
        try:
            proof=verify_scoped_boundary(source,row['time'],row['before'],row['after'],analysis['transcript'],
                                         row['measured'],job_dir,vision,cancelled)
            result['reviewed_boundaries'].append({'time':row['time'],'proof':proof})
            if proof['uncertain']:
                result['unresolved'].append({'time':row['time'],'reason':'native_boundary_evidence_uncertain'})
            else:proofs[row['time']]=proof
        except (ValueError,RuntimeError,OSError,TimeoutError) as error:
            if _control_failure(error):raise
            result['unresolved'].append({'time':row['time'],'reason':str(error)})
    if not proofs:return {**result,'status':'unresolved'}
    try:
        updated,changed=_updated_scenes(scenes,proofs,analysis['transcript'],source_key)
        touched={s['id'] for s in scenes if any(d.get('time') in proofs
                 for d in s['evidence'].get('boundary_decisions',[]))}
        touched.update(s['id'] for s in updated if s['id'] not in {old['id'] for old in scenes})
        events=[]
        for event in original_events:
            owners=[s for s in updated if s['start']<event['end'] and event['start']<s['end']]
            if not owners:raise ValueError('Recovered source window has no scene owner')
            if len(owners)==1:
                owner=owners[0]
                if owner['id']!=event.get('scene_id') or (owner['id'] in touched
                        and owner['evidence']!=event.get('scene_evidence')):
                    old_scene=event.get('scene_id')
                    event.update(scene_id=owner['id'],parent_scene_id=owner['id'],scene_evidence=copy.deepcopy(owner['evidence']))
                    for chunk in event.get('analysis_chunks',[]):chunk['parent_scene_id']=owner['id']
                    event['source_boundary_reassociation']={'previous_scene':old_scene,'source':copy.deepcopy(source_key)}
                    result['reassociated_event_ids'].append(event['id'])
                events.append(event)
                result['ownership'][event['id']]=[event['id']]
                continue
            children=[]
            result['removed_event_ids'].append(event['id'])
            for owner in owners:
                window=copy.deepcopy(owner)
                window.update(start=max(owner['start'],event['start']),end=min(owner['end'],event['end']))
                identifier='event_boundary_'+evidence_digest({'source':source_key['sha256'],'owner':event['id'],
                                                              'start':window['start'],'end':window['end']})[:24]
                report('quality_gate',.68,'Уточняем только изменённое исходное окно смысловой границы')
                child=rebuild_scoped_event(source,window,event,analysis['transcript'],analysis['shots'],job_dir,
                                          vision,report,cancelled,source_key=source_key,event_id=identifier)
                children.append(child)
                result['changed_event_ids'].append(identifier)
            events.extend(children)
            result['ownership'][event['id']]=[e['id'] for e in children]
        if source_identity(source,cancelled)!=source_key:raise ValueError('Source changed during boundary recovery')
        for old in scenes:
            result['scene_ownership'][old['id']]=[s['id'] for s in updated if s['start']<old['end'] and old['start']<s['end']]
        result.update(events=events,scenes=updated,changed_ranges=changed)
    except (ValueError,RuntimeError,OSError,TimeoutError) as error:
        if _control_failure(error):raise
        # Native caches remain available for a bounded retry. Do not publish a
        # partial owner replacement when CURRENT coverage cannot be assembled.
        result.update(events=copy.deepcopy(analysis['events']),scenes=copy.deepcopy(analysis.get('scenes',[])),
                      changed_ranges=[],changed_event_ids=[],reassociated_event_ids=[],ownership={},scene_ownership={})
        result['removed_event_ids']=[]
        result['unresolved'].append({'reason':str(error)})
    result['status']='unresolved' if result['unresolved'] else 'accepted'
    return result
