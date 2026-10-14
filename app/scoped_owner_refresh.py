"""Refresh only downstream owners affected by a proven source-boundary repair."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from .source_ranges import intersect_ranges, merge_ranges


def _pending_structure(event):
    active=event.get('analysis_unresolved_reasons',[]) if event.get('analysis_unresolved') else []
    if event.get('analysis_unresolved') and not active:active=['source_analysis_unresolved']
    event['analysis_unresolved']=True
    event['analysis_unresolved_reasons']=list(dict.fromkeys([*active,'story_structure_unresolved']))
    event['story_structure']={**event.get('story_structure',{}),'status':'unresolved',
                             'reason':'source_dependency_owner_changed'}


def _mark_dependency(event, previous, candidates, reason):
    row={'previous_event':previous,'candidate_event_ids':sorted(candidates),'reason':reason}
    event.setdefault('dependency_refresh_unresolved',[]).append(row)
    _pending_structure(event)
    return row


def _remap_requires(events, previous_analysis, boundary):
    from .selection_gate import positive_ranges, _covers
    current={e['id']:e for e in events}
    previous={e['id']:e for e in previous_analysis['events']}
    removed=set(boundary.get('removed_event_ids',[]))
    mapping=boundary.get('ownership',{})
    relations=[*previous_analysis.get('story_structure',{}).get('relations',[]),
               *(r for e in previous_analysis['events'] for r in e.get('story_relations',[]))]
    changed=set()
    unresolved=[]
    for event in events:
        requires=[]
        for required in event.get('requires',[]):
            if required not in removed:
                requires.append(required)
                continue
            candidates=[current[i] for i in mapping.get(required,[]) if i in current and i!=event['id']
                        and current[i]['end']<=event['start']+.002]
            source=previous.get(required)
            refs={r['from'].get('unit') for r in relations if isinstance(r,dict) and isinstance(r.get('from'),dict)
                  and isinstance(r.get('to'),dict) and r['from'].get('event')==required
                  and r['to'].get('event')==event['id'] and r.get('type') in
                  ('cause','response','setup_payoff','state_transition')
                  and r['to'].get('unit') in {u['id'] for u in event.get('units',[])}
                  and type(r.get('confidence')) in (int,float) and math.isfinite(r['confidence'])
                  and .9<=r['confidence']<=1
                  and isinstance(r.get('evidence'),str) and len(r['evidence'].strip())>=12}
            units=[u for u in (source or {}).get('units',[]) if u['id'] in refs]
            changed.add(event['id'])
            changed.update(e['id'] for e in candidates)
            if not units or len(units)!=len(refs):
                unresolved.append({'event':event['id'],**_mark_dependency(event,required,
                    [e['id'] for e in candidates],'source_dependency_unit_missing')})
                continue
            if not _covers(positive_ranges(source),units):
                unresolved.append({'event':event['id'],**_mark_dependency(event,required,
                    [e['id'] for e in candidates],'previous_dependency_source_proof_missing')})
                continue
            matches=[e for e in candidates if intersect_ranges(e.get('selected_ranges',[]),units)]
            coverage=merge_ranges([r for e in matches for r in positive_ranges(e)])
            if not _covers(coverage,units):
                unresolved.append({'event':event['id'],**_mark_dependency(event,required,
                    [e['id'] for e in candidates],'source_dependency_not_positively_covered')})
                continue
            # This is planner ownership bookkeeping only. The previous source
            # relation itself remains old provenance until native reconstruction.
            requires.extend(e['id'] for e in matches)
            _pending_structure(event)
        if event['id'] in changed:
            event['requires']=list(dict.fromkeys(requires))
    return changed,unresolved


def reconcile_scoped_dependencies(events, story_result, transcript):
    """Restore planner IDs only from fresh native relations and exact support.

    Absence of an inferred edge is not a negative dependency proof. An opaque
    previous requirement therefore stays unresolved unless actual new source
    references establish its replacement.
    """
    result=copy.deepcopy(events)
    pending=[e for e in result if e.get('dependency_refresh_unresolved')]
    if not pending:return {'events':result,'status':'not_required','unresolved':[],
                           'relation_refresh_event_ids':[]}
    from .story_structure_pass import source_units, _key, _quote_in
    try:
        nodes,_,_=source_units(result,transcript)
    except ValueError:
        nodes=[]
    known={_key(n['ref']):n for n in nodes}
    proofs={p['id']:p for n in nodes for p in n['proofs']}
    accepted={_key(u['ref']) for u in story_result.get('units',[]) if u.get('status')=='accepted'}
    valid=[]
    for row in story_result.get('relations',[]):
        if not isinstance(row,dict) or not isinstance(row.get('from'),dict) or not isinstance(row.get('to'),dict):continue
        left,right=_key(row['from']),_key(row['to'])
        if (left not in known or right not in known or not {left,right}<=accepted
                or row.get('type') not in ('cause','response','setup_payoff','state_transition')
                or type(row.get('confidence')) not in (int,float) or not math.isfinite(row['confidence'])
                or not .9<=row['confidence']<=1 or known[left]['start']>known[right]['start']
                or not isinstance(row.get('evidence'),str) or len(row['evidence'].strip())<12):continue
        cited=set()
        for support in row.get('support',[]):
            if not isinstance(support,dict) or not isinstance(support.get('ref'),dict):continue
            ref=_key(support['ref'])
            proof=proofs.get(support.get('proof'))
            quote=support.get('quote')
            if (proof is None or _key(proof['ref'])!=ref or not isinstance(quote,str)
                    or quote.strip() and not any(_quote_in(quote,r['text']) for r in proof['ASR_ranges'])):continue
            cited.add(ref)
        if {left,right}<=cited:valid.append(row)
    unresolved=[]
    targets=set()
    current={e['id']:e for e in result}
    for event in pending:
        remaining=[]
        for old in event['dependency_refresh_unresolved']:
            candidates=set(old['candidate_event_ids']) & set(current)
            relations=[r for r in valid if r['from']['event'] in candidates and r['to']['event']==event['id']]
            dependencies=sorted({r['from']['event'] for r in relations if current[r['from']['event']]['end']<=event['start']+.002})
            if dependencies:
                event['requires']=list(dict.fromkeys([*event.get('requires',[]),*dependencies]))
                event.setdefault('dependency_refresh_history',[]).append({'previous_event':old['previous_event'],
                    'refreshed_event_ids':dependencies,'relation_support':[copy.deepcopy(r['support']) for r in relations]})
            else:
                remaining.append(old)
                unresolved.append({'event':event['id'],**copy.deepcopy(old)})
                targets.add(event['id']);targets.update(candidates)
        if remaining:
            event['dependency_refresh_unresolved']=remaining
            _pending_structure(event)
        else:event.pop('dependency_refresh_unresolved',None)
    return {'events':result,'status':'unresolved' if unresolved else 'complete','unresolved':unresolved,
            'relation_refresh_event_ids':sorted(targets)}


def _tasks(parent):
    from .review_scope import check_regions
    result={task for region in check_regions([parent]) for task in region['checks']}
    if any(parent.get(key) for key in ('preview_candidate','promotion_candidate','source_role_candidate')):
        result.add('source_roles')
    return result


def _replace_targets(events, targets, checked):
    expected=[e for e in events if e['id'] in targets]
    rows={e['id']:e for e in checked if e['id'] in targets}
    if set(rows)!=set(targets) or any((rows[e['id']]['start'],rows[e['id']]['end'])!=(e['start'],e['end'])
                                    for e in expected):
        raise ValueError('Specialist refresh changed CURRENT ownership')
    for e in rows.values():
        if any(not e['start']<=r['start']<r['end']<=e['end'] for r in e.get('selected_ranges',[])):
            raise ValueError('Specialist refresh escaped CURRENT source window')
    return [rows.get(e['id'],e) for e in events]


def _provider(analysis, job_dir):
    from .analysis_provider import analysis_provider
    return analysis_provider(job_dir) if (Path(job_dir)/'analysis-settings.json').is_file() else analysis.get('provider','local')


def finish_scoped_framing(source, analysis, events, event_ids, job_dir, report, cancelled, *,
                          vision=None, active_provider=None, allow_new_session=False):
    """Frame new CURRENT windows; open a session only after its caller drained VLMs.

    ``allow_new_session=True`` is an explicit lifecycle contract: the caller has
    already left the prior source/recovery session. Default behavior cannot
    create a nested local4B/local9B allocation.
    """
    from .editing import load_options
    from .analysis_provider import framing_provider
    from .selection_gate import source_selection_readiness
    from .config import STORY_MODEL, STORY_PROJECTOR
    result=copy.deepcopy(events)
    if load_options(Path(job_dir))['layout']!='portrait':
        return {'events':result,'status':'not_required','pending_event_ids':[],'reviewed_event_ids':[]}
    requested=set(event_ids)
    owned=[e for e in result if e['id'] in requested]
    candidates=[e for e in owned if e.get('selected_ranges')]
    targets=[e for e in candidates if source_selection_readiness([e])['status']=='passed']
    blocked={e['id'] for e in owned if source_selection_readiness([e])['status']!='passed'}
    if not candidates and not blocked:
        return {'events':result,'status':'not_required','pending_event_ids':[],'reviewed_event_ids':[]}
    provider=_provider(analysis,job_dir)
    route=framing_provider(provider)
    active_provider=active_provider or provider
    usable=vision is not None and active_provider==route
    if usable and route=='local':
        usable=Path(str(getattr(vision,'model',''))) == STORY_MODEL
    if not targets or (not usable and not allow_new_session):
        pending=sorted({e['id'] for e in candidates}|blocked)
        for e in result:
            if e['id'] in pending:e['framing_refresh']={'status':'pending','provider':route,
                'reason':'source_selection_not_ready' if e['id'] in blocked else 'owned_framing_session_required'}
        return {'events':result,'status':'pending','pending_event_ids':pending,'reviewed_event_ids':[],
                'provider':route}
    from .framing import refine_focus
    from .model_perf import purpose
    def apply(current):
        # Requires govern planning, not local pixel geometry. No unrelated
        # dependency owner is sent through the framing selector just to satisfy
        # its catalog traversal. Restore all original source fields afterward.
        inputs=copy.deepcopy(targets)
        for event in inputs:event['requires']=[]
        previous=getattr(current,'thinking',False)
        try:
            if hasattr(current,'thinking'):current.thinking=False
            with purpose('framing'):
                return refine_focus(source,analysis['probe'],analysis['transcript'],analysis['shots'],
                                    inputs,Path(job_dir),current,report,cancelled)
        finally:
            if hasattr(current,'thinking'):current.thinking=previous
    if usable:
        checked=apply(vision)
    else:
        if vision is not None:
            raise ValueError('Close the active source session before opening scoped framing')
        from .vision import vision_session
        with vision_session(Path(job_dir),cancelled,route,model=STORY_MODEL,projector=STORY_PROJECTOR,
                            thinking=False) as current:
            checked=apply(current)
    expected={(e['id'],e['start'],e['end']) for e in targets}
    if {(e['id'],e['start'],e['end']) for e in checked}!=expected:
        raise ValueError('Framing refresh changed CURRENT ownership')
    by_id={e['id']:e for e in checked}
    for event in result:
        if event['id'] in by_id:
            for name in ('focus','focus_warnings'):
                if name in by_id[event['id']]:event[name]=copy.deepcopy(by_id[event['id']][name])
            event['framing_refresh']={'status':'complete','provider':route}
        elif event['id'] in blocked:
            event['framing_refresh']={'status':'pending','provider':route,'reason':'source_selection_not_ready'}
    return {'events':result,'status':'pending' if blocked else 'complete','provider':route,
            'pending_event_ids':sorted(blocked),'reviewed_event_ids':sorted(by_id)}


def refresh_scoped_owners(source, previous_analysis, boundary_result, job_dir, vision, report, cancelled):
    """Refresh concrete specialist needs and dependency/focus owners only."""
    events=copy.deepcopy(boundary_result['events'])
    changed=set(boundary_result.get('changed_event_ids',[]))
    removed=set(boundary_result.get('removed_event_ids',[]))
    result={'events':events,'history':[],'relation_refresh_event_ids':[],
            'dependency_unresolved':[],'framing_pending_event_ids':[],'status':'not_required'}
    if not changed and not removed:return result
    relation_targets,unresolved=_remap_requires(events,previous_analysis,boundary_result)
    previous={e['id']:e for e in previous_analysis['events']}
    tasks={}
    for old,children in boundary_result.get('ownership',{}).items():
        if old not in previous:continue
        for identifier in set(children)&changed:
            tasks.setdefault(identifier,set()).update(_tasks(previous[old]))
    prior_targets={e['id']:copy.deepcopy(e.get('review_targets')) for e in events}
    prior_credit={e['id']:{k:copy.deepcopy(e[k]) for k in ('source_credit_candidate','source_credit_kind') if k in e}
                  for e in events}
    for event in events:
        if event['id'] in tasks:
            event['review_targets']=sorted(tasks[event['id']])
            if 'credits' in tasks[event['id']]:
                event['source_credit_candidate']=True
                parent=next((previous[old] for old,children in boundary_result.get('ownership',{}).items()
                             if old in previous and event['id'] in children),{})
                kind=parent.get('credits_kind',parent.get('kind'))
                if kind in ('opening','ending'):event['source_credit_kind']=kind
    stages=[('credits','production_sequence'),('titles','titles'),('closing','closing_novelty'),('source_roles','source_roles')]
    for task,name in stages:
        targets={identifier for identifier,needed in tasks.items() if task in needed}
        if not targets:continue
        if cancelled():raise InterruptedError('Обработка отменена')
        selected=[copy.deepcopy(e) for e in events if e['id'] in targets]
        if task=='credits':
            from .story import clean_credit_continuations
            checked=clean_credit_continuations(selected,previous_analysis['transcript'],previous_analysis['shots'],
                                               Path(job_dir),vision,report,cancelled)
        elif task=='titles':
            from .titles import refine_titles
            checked=refine_titles(selected,previous_analysis['transcript'],previous_analysis['shots'],
                                  Path(job_dir),vision,report,cancelled)
        elif task=='closing':
            from .closing import refine_closing_novelty
            checked=refine_closing_novelty(events,previous_analysis['transcript'],previous_analysis['shots'],
                Path(job_dir),vision,report,cancelled,event_ids=targets,episode_duration=previous_analysis['probe']['duration'])
        else:
            from .source_roles import refine_source_roles
            checked=refine_source_roles(events,previous_analysis['transcript'],previous_analysis['shots'],
                Path(job_dir),vision,report,cancelled,event_ids=targets,retry_unresolved=True,
                episode_duration=previous_analysis['probe']['duration'])
        events=_replace_targets(events,targets,checked)
        result['history'].append({'stage':name,'reviewed_event_ids':sorted(targets)})
    for event in events:
        if event['id'] not in tasks:continue
        if prior_targets[event['id']] is None:event.pop('review_targets',None)
        else:event['review_targets']=prior_targets[event['id']]
        for key in ('source_credit_candidate','source_credit_kind'):
            if key in prior_credit[event['id']]:event[key]=prior_credit[event['id']][key]
            else:event.pop(key,None)
    focused=finish_scoped_framing(source,previous_analysis,events,
        boundary_result.get('framing_required_event_ids',list(changed)),job_dir,report,cancelled,vision=vision)
    events=focused['events']
    result.update(events=events,relation_refresh_event_ids=sorted(relation_targets|changed),
                  dependency_unresolved=unresolved,framing_pending_event_ids=focused['pending_event_ids'],
                  status='unresolved' if unresolved else 'pending' if focused['pending_event_ids'] else 'complete')
    result['history'].append({'stage':'framing',**{k:v for k,v in focused.items() if k!='events'}})
    return result
