"""Opt-in working selection of proved material; original source remains archived."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from .content_identity import digest
from .json_store import atomic_json, read_json
from .selection_gate import source_selection_problems, selection_readiness, _covers
from .source_ranges import merge_ranges

VERSION = 1
MODE = 'confirmed_only'
REQUIRED_RELATIONS = {'cause', 'response', 'setup_payoff', 'state_transition'}
BOUNDARY_FAILURES = {'ambiguous_internal_boundary','semantic_boundary_unresolved','unverified_scene_boundary'}
SOURCE_FILES = ('events.json','story_structure-result.json','dialogue_relations-result.json',
                'episode_profile.json','boundary-recovery/derived-ownership.json')


def restore_source(directory):
    """Recover the original canonical source even after worker termination."""
    directory=Path(directory)
    manifest=directory/'confirmed-selection/active-source.json'
    saved=read_json(manifest,{})
    if not saved.get('active'):
        return
    if saved['source']!=read_json(directory/'analysis.meta.json',{}).get('source'):
        raise ValueError('Исходник изменён: автоматическое восстановление полного анализа остановлено')
    for name,entry in saved['files'].items():
        if name not in SOURCE_FILES:
            raise ValueError('Неизвестный исходный файл в записи восстановления')
        target=directory/name;target.resolve().relative_to(directory.resolve())
        if entry is None:
            target.unlink(missing_ok=True)
            continue
        backup=directory/entry['backup'];backup.resolve().relative_to((directory/'confirmed-selection').resolve())
        raw=backup.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('Изменена копия полного исходного анализа')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(raw);os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_json(manifest,{**saved,'active':False})


@contextmanager
def preserve_source(analysis,directory):
    """Native passes keep their APIs; scoped outputs cannot replace full source."""
    directory=Path(directory)
    if not analysis.get('selection_scope'):
        yield
        return
    restore_source(directory)
    folder=directory/'confirmed-selection'/'canonical'/uuid.uuid4().hex
    folder.resolve().relative_to(directory.resolve())
    entries={}
    for name in SOURCE_FILES:
        source=directory/name;source.resolve().relative_to(directory.resolve())
        if source.exists():
            backup=folder/name;backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,backup)
            entries[name]={'backup':backup.relative_to(directory).as_posix(),
                           'sha256':hashlib.sha256(backup.read_bytes()).hexdigest()}
        else:
            entries[name]=None
    atomic_json(directory/'confirmed-selection/active-source.json',{'active':True,'files':entries,
        'source':read_json(directory/'analysis.meta.json',{}).get('source')})
    try:
        yield
    finally:
        try:
            for name in SOURCE_FILES:
                source=directory/name
                if source.exists():
                    target=directory/'confirmed-selection/working'/name
                    target.resolve().relative_to(directory.resolve())
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        finally:
            restore_source(directory)


def enabled(directory):
    policy=read_json(Path(directory)/'selection-policy.json', {})
    if not policy:
        return False
    if (not isinstance(policy,dict) or set(policy)!={'version','mode'}
            or policy['version']!=VERSION or policy['mode'] not in ('strict',MODE)):
        raise ValueError('Некорректный режим выбора подтверждённых фрагментов')
    return policy['mode']==MODE


def identity(directory):
    """Bind the working projection to plans, without invalidating perception."""
    return {'version':VERSION,'mode':MODE if enabled(directory) else 'strict',
        'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _pairs(analysis):
    return [*analysis.get('dialogue_relations',{}).get('pairs',[]),
        *(p for e in analysis['events'] for p in e.get('dialogue_relations',{}).get('pairs',[]))]


def _close_dependencies(analysis, candidates, omitted):
    known={e['id']:e for e in analysis['events']}
    order={e['id']:i for i,e in enumerate(analysis['events'])}
    relations=[*analysis.get('story_structure',{}).get('relations',[]),
        *(r for e in analysis['events'] for r in e.get('story_relations',[]))]
    selected=set(candidates)
    while True:
        rejected={}
        for ident in selected:
            event=known[ident]
            missing=[r for r in event.get('requires',[]) if r not in selected
                     or order.get(r,len(order))>=order[ident]]
            if missing:
                rejected[ident]={'reason':'required_source_unavailable','requires':missing}
            if event.get('dependency_refresh_unresolved'):
                rejected[ident]={'reason':'required_source_owner_unresolved'}
        for row in relations:
            if not isinstance(row,dict) or row.get('type') not in REQUIRED_RELATIONS:
                continue
            left,right=row.get('from'),row.get('to')
            if not isinstance(left,dict) or not isinstance(right,dict) or right.get('event') not in selected:
                continue
            owner=known.get(left.get('event'))
            unit=next((u for u in (owner or {}).get('units',[]) if u['id']==left.get('unit')),None)
            if left.get('event') not in selected or unit is None or not _covers(owner['selected_ranges'],[unit]):
                rejected[right['event']]={'reason':'required_relation_endpoint_unavailable','endpoint':left}
        retained=merge_ranges([r for i in selected for r in known[i]['selected_ranges']])
        for pair in _pairs(analysis):
            if pair.get('status')!='confirmed' or not pair.get('requires_answer'):
                continue
            ranges=[*pair.get('question_ranges',[]),*pair.get('answer_ranges',[])]
            touched=[i for i in selected if any(a['start']<b['end'] and b['start']<a['end']
                for a in known[i]['selected_ranges'] for b in ranges)]
            if touched and not _covers(retained,ranges):
                rejected.update({i:{'reason':'required_dialogue_endpoint_unavailable'} for i in touched})
        if not rejected:
            break
        selected.difference_update(rejected)
        omitted.update(rejected)
    return selected


def _archive(analysis, directory):
    source=read_json(directory/'analysis.meta.json',{}).get('source')
    if not isinstance(source,str) or len(source)!=64:
        raise ValueError('Нет исходной идентичности для сохранения полного анализа')
    context={'source':source,'transcript':digest(analysis['transcript']),'shots':digest(analysis['shots'])}
    full={k:copy.deepcopy(analysis[k]) for k in ('events','scenes','story_structure','dialogue_relations',
        'scoped_framing_pending_event_ids') if k in analysis}
    key=digest({'context':context,'full':full})
    path=directory/'confirmed-selection'/'source'/f'{key}.json'
    path.resolve().relative_to(directory.resolve())
    row={'version':VERSION,'context':context,'full':full,'digest':key}
    if path.exists():
        if read_json(path)!=row:
            raise ValueError('Изменён архив полного исходного анализа')
    else:
        atomic_json(path,row)
    return {'archive':str(path.relative_to(directory)),'source_context':context,'source_digest':key}


def project(analysis, directory, report=lambda *a:None, *, reject_ids=()):
    """Discard uncertainty/consumers, never rewrite native proof or confidence."""
    directory=Path(directory)
    if not enabled(directory):
        return analysis
    previous=analysis.get('selection_scope')
    scope=copy.deepcopy(previous) if previous else {'version':VERSION,'mode':MODE,**_archive(analysis,directory)}
    omitted={row['event']: {k:v for k,v in row.items() if k!='event'} for row in scope.get('omitted',[])}
    rejected=set(reject_ids)
    ambiguous={s['id'] for s in analysis.get('scenes',[]) if
               BOUNDARY_FAILURES.intersection(s.get('uncertainty_reasons',[]))}
    candidates=set()
    for event in analysis['events']:
        problems=source_selection_problems(event)
        if event['id'] in rejected:
            omitted[event['id']]={'reason':'necessary_check_unresolved'}
        elif problems:
            omitted[event['id']]={'reason':'source_not_confirmed','problems':problems}
        elif event.get('scene_id') in ambiguous:
            omitted[event['id']]={'reason':'source_boundary_not_confirmed'}
        elif not event.get('selected_ranges'):
            omitted[event['id']]={'reason':'no_selected_source'}
        else:
            candidates.add(event['id'])
    selected=_close_dependencies(analysis,candidates,omitted)
    events=[copy.deepcopy(e) for e in analysis['events'] if e['id'] in selected]
    scope.update(kept_event_ids=[e['id'] for e in events],
        omitted=[{'event':i,**reason} for i,reason in sorted(omitted.items())],
        retained_duration=sum(r['end']-r['start'] for e in events for r in e['selected_ranges']))
    scope_path=directory/'confirmed-selection'/'scope.json'
    scope_path.resolve().relative_to(directory.resolve())
    atomic_json(scope_path,scope)
    if not events:
        raise ValueError('Нет подтверждённых самостоятельных фрагментов: сомнительные и зависимые от них исключены. '
                         'Исходный анализ и ответы сохранены; повторная отправка всего видео не выполняется.')
    result={**analysis,'events':events,'selection_scope':scope,'selection_gate':selection_readiness(events)}
    if 'scoped_framing_pending_event_ids' in analysis:
        result['scoped_framing_pending_event_ids']=[i for i in analysis['scoped_framing_pending_event_ids'] if i in selected]
    if 'scenes' in analysis:
        owners={e.get('scene_id') for e in events}
        result['scenes']=[copy.deepcopy(s) for s in analysis['scenes'] if s['id'] in owners]
    if 'episode_profile' in analysis:
        from .episode_profile import build_episode_profile,adaptive_retention_budget
        profile=build_episode_profile(analysis['probe']['duration'],analysis['transcript'],analysis['shots'],
            result.get('scenes'),events,perception=analysis.get('perception'))
        profile['retention_budget']=adaptive_retention_budget(profile)
        result['episode_profile']=profile
    report('quality_gate',.68,f'Подтверждённые фрагменты: {len(events)}; исключено: {len(omitted)}')
    return result


def prune_failed(analysis, gate, plan, directory, report=lambda *a:None):
    """At the bounded stop, remove failed retained owners instead of another call."""
    if not enabled(directory):
        return None
    from .quality_recovery import problem_owners
    failed=problem_owners(gate['problems'],analysis['events'])
    known={e['id'] for e in analysis['events']}
    for row in gate['problems']:
        transition=row.get('transition',{})
        if transition.get('to') in known:
            failed.add(transition['to'])
        pair=row.get('pair',{})
        failed.update(r['event'] for r in [*pair.get('question_refs',[]),*pair.get('answer_refs',[])]
                      if r.get('event') in known)
        if plan and row.get('part'):
            part=next((p for p in plan['parts'] if p['index']==row['part']),None)
            cuts=(part or {}).get('cuts',[])
            if row['code']=='missing_original_semantic_ending':
                cuts=cuts[-1:]
            elif type(row.get('source_time')) in (int,float):
                cuts=[c for c in cuts if c['start']<=row['source_time']<=c['end']]
            failed.update(i for cut in cuts for i in cut.get('event_ids',[]) if i in known)
    if not failed:
        return None
    return project(analysis,directory,report,reject_ids=failed)
