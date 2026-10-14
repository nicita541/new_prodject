"""Repair source analysis for explicit quality failures; the pipeline owns retries."""
from __future__ import annotations

import copy
import math

from .final_quality import _planned_source
from app.source_ranges import merge_ranges
from .selection_gate import positive_ranges


def problem_owners(problems, events, stage=None):
    """Resolve only explicit IDs and concrete failed source intervals locally."""
    known = {event['id'] for event in events}
    owners = set()
    for problem in problems:
        if stage is not None and problem.get('recovery_stage') != stage:
            continue
        if problem.get('event') in known:
            owners.add(problem['event'])
        windows = [problem.get('range'),*problem.get('ranges',[])]
        for window in windows:
            if (not isinstance(window,dict) or not all(type(window.get(k)) in (int,float)
                    and math.isfinite(window[k]) for k in ('start','end'))
                    or window['start'] >= window['end']):
                continue
            owners.update(event['id'] for event in events
                if event['start'] < window['end'] and window['start'] < event['end'])
    return owners


def needs_model_recovery(gate):
    """Pure plan rebuilds must not load a model or open a cloud session."""
    return any(p.get('recovery_stage') in ('source_roles','semantic_boundary',
        'selection_adjudication','story_structure','dialogue_relations')
        or p.get('code') == 'missing_original_semantic_ending'
        or p.get('code') == 'unresolved_transition' and 'gap' in p.get('transition',{})
        for p in gate['problems'])


def finish_pending_framing(source,analysis,job_dir,report,cancelled,*,allow_new_session=True):
    """Called outside analysis/recovery sessions, before a gate can pass."""
    pending=set(analysis.get('scoped_framing_pending_event_ids',[]))
    pending.update(e['id'] for e in analysis['events'] if e.get('framing_refresh',{}).get('status')=='pending')
    if not pending:
        return analysis
    from .scoped_owner_refresh import finish_scoped_framing
    from .scoped_recovery_state import persist_repaired_scenes
    from .json_store import analysis_json as atomic_json
    framed=finish_scoped_framing(source,analysis,analysis['events'],sorted(pending),
        job_dir,report,cancelled,allow_new_session=allow_new_session)
    if framed['pending_event_ids'] and not allow_new_session:
        raise ValueError('Сохранённый анализ требует уточнения кадрирования. Запустите «Обновить по изменениям».')
    atomic_json(job_dir/'events.json',framed['events'])
    persist_repaired_scenes(job_dir,framed['events'],analysis.get('scenes',[]),analysis['transcript'],analysis['shots'])
    return {**analysis,'events':framed['events'],'scoped_framing_pending_event_ids':framed['pending_event_ids']}


def recover_final_quality(source, analysis, plan, gate, job_dir, vision, report, cancelled):
    """Return new source analysis; a recovery result never silently enlarges cuts."""
    from .analysis_result import analysis_result
    from app.json_store import analysis_json as atomic_json
    from .pipeline_diagnostics import Diagnostics
    from .continuity_verification import verify_omitted_continuity
    events = copy.deepcopy(analysis['events'])
    scenes = copy.deepcopy(analysis.get('scenes',[]))
    original_events = {e['id']:copy.deepcopy(e) for e in events}
    diagnostics = Diagnostics(job_dir)
    stages = {problem['recovery_stage'] for problem in gate['problems']}
    history = []
    relation_targets = set()
    boundary_mode = 'semantic_boundary' in stages
    boundary_result = None
    framing_pending = set(analysis.get('scoped_framing_pending_event_ids',[]))
    framing_pending.update(e['id'] for e in events if e.get('framing_refresh',{}).get('status')=='pending')
    if boundary_mode:
        from .scoped_boundary_recovery import recover_scoped_boundaries
        boundary_result = recover_scoped_boundaries(source,analysis,gate['problems'],job_dir,vision,report,cancelled)
        events,scenes = boundary_result['events'],boundary_result['scenes']
        from .scoped_owner_refresh import refresh_scoped_owners
        refreshed_owners = refresh_scoped_owners(source,analysis,boundary_result,job_dir,vision,report,cancelled)
        events = refreshed_owners['events']
        relation_targets.update(refreshed_owners['relation_refresh_event_ids'])
        framing_pending.intersection_update(e['id'] for e in events)
        framing_pending.difference_update(boundary_result.get('framing_required_event_ids',[]))
        framing_pending.update(refreshed_owners['framing_pending_event_ids'])
        history.extend(refreshed_owners['history'])
        relation_targets.update(boundary_result['changed_event_ids'])
        relation_targets.update(boundary_result.get('reassociated_event_ids',[]))
        history.append({key:copy.deepcopy(boundary_result[key]) for key in
            ('status','changed_ranges','changed_event_ids','removed_event_ids','ownership','unresolved')} |
            {'stage':'semantic_boundary'})
    targets = problem_owners(gate['problems'],events)
    if not boundary_mode and 'source_roles' in stages:
        from .source_roles import refine_source_roles
        pending=problem_owners(gate['problems'],events,'source_roles')
        if pending:
            events=refine_source_roles(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled,
                                       retry_unresolved=True,event_ids=pending,episode_duration=analysis['probe']['duration'])
        else:
            history.append({'stage':'source_roles','status':'unresolved','reason':'problem_owner_missing'})
        history.append({'stage':'source_roles','reviewed_event_ids':sorted(pending)})
    if not boundary_mode and 'continuity' in stages and plan is not None:
        runtime,selected = _planned_source(events,[cut for part in plan['parts'] for cut in part['cuts']])
        transitions = [problem['transition'] for problem in gate['problems']
                       if problem['code'] == 'unresolved_transition']
        for transition in transitions:
            if 'gap' not in transition:
                continue
            report('quality_gate', .68, 'Проверяем исходные пропущенные units между выбранными событиями')
            runtime,audit = verify_omitted_continuity(source,runtime,selected,analysis['transcript'],analysis['shots'],
                                                     transition,job_dir,vision,cancelled)
            history.append(audit)
            if audit['status'] != 'accepted':
                continue
            targets.update(ref['event'] for ref in audit['restored_refs'])
            by_id = {e['id']:e for e in events}
            for verified in runtime:
                original = by_id[verified['id']]
                original['continuity_verifications'] = copy.deepcopy(verified.get('continuity_verifications', []))
                for ref in audit['restored_refs']:
                    if ref['event'] != original['id']:
                        continue
                    unit = next(u for u in verified['units'] if u['id'] == ref['unit'])
                    original_unit = next(u for u in original['units'] if u['id'] == ref['unit'])
                    original_unit.update({k:copy.deepcopy(unit[k]) for k in ('state_before','state_after') if k in unit})
                    proofs = [p for p in verified.get('unit_evidence', []) if p.get('unit') == ref['unit']]
                    original['unit_evidence'] = [p for p in original.get('unit_evidence', []) if p.get('unit') != ref['unit']]+copy.deepcopy(proofs)
                    original['selected_ranges'] = merge_ranges([*original.get('selected_ranges', []),
                        *positive_ranges({**verified,'unit_evidence':proofs})])
                    original['mandatory_continuity_units'] = copy.deepcopy(verified.get('mandatory_continuity_units', []))
                    original['action_units'] = list(dict.fromkeys([*original.get('action_units', []),
                        *[i for i in verified.get('action_units', []) if i == ref['unit']]]))
                    original.update(kind='story',importance=max(3,original.get('importance',1)),
                        selection_empty_verified=False,unit_selection_version=1)
                    if verified.get('narrative_bridge'):
                        original['narrative_bridge'] = True
                    for key in ('global_excluded','pacing_excluded','source_role_excluded'):
                        original.pop(key,None)
                    selected.add(original['id'])
    if not boundary_mode and 'selection_adjudication' in stages:
        from .selection_adjudication import adjudicate_event
        from .selection_gate import source_selection_readiness
        pending = {r['event'] for r in source_selection_readiness(events)['unresolved']} & targets
        for index,event in enumerate(events):
            if event['id'] not in pending:
                continue
            questions = ['Разреши конкретную проблему финальной проверки: '+p['code']
                         for p in gate['problems'] if event['id'] in problem_owners([p],events,'selection_adjudication')]
            if questions:
                events[index] = adjudicate_event(source,event,analysis['transcript'],analysis['shots'],
                    job_dir,vision,cancelled,questions=questions)
    # Source changes invalidate only their real relation owners/dependencies.
    # The native passes reconstruct the complete aggregate locally while the
    # scoped adapter permits only missing dependent requests to dispatch.
    from .source_roles import confirmed_exclusions
    from .content_identity import stable_semantics
    def inherited_source(event):
        return stable_semantics({key:event.get(key) for key in ('units','selected_ranges','unit_evidence',
            'source_identity','source_evidence','state_before','state_after','causal_links')} |
            {'confirmed_exclusions':confirmed_exclusions(event)})
    for event in events:
        if event['id'] in original_events and inherited_source(event) == inherited_source(original_events[event['id']]):
            continue
        relation_targets.add(event['id'])
    if not boundary_mode:
        relation_targets.update(problem_owners(gate['problems'],events,'story_structure'))
        relation_targets.update(problem_owners(gate['problems'],events,'dialogue_relations'))
    relation_targets.intersection_update(event['id'] for event in events)
    for event in events:
        if event['id'] not in relation_targets:
            continue
        active_reasons = event.get('analysis_unresolved_reasons',[]) if event.get('analysis_unresolved') else []
        if event.get('analysis_unresolved') and not active_reasons:
            active_reasons = ['source_analysis_unresolved']
        for name in ('story_structure','dialogue_relations'):
            previous = copy.deepcopy(event.get(name,{}))
            event[name] = {**previous,'status':'unresolved','reason':'source_changed_requires_scoped_relation_recovery'}
        event['analysis_unresolved'] = True
        event['analysis_unresolved_reasons'] = list(dict.fromkeys([*active_reasons,
            'story_structure_unresolved','dialogue_relations_unresolved']))
    if relation_targets:
        # Old aggregates remain dependency hypotheses, never accepted geometry
        # after a changed owner. Keep their history for exact native reuse.
        retired = sorted(set(original_events)-{e['id'] for e in events})
        for name in ('story_structure','dialogue_relations'):
            atomic_json(job_dir/(name+'-result.json'),{**copy.deepcopy(analysis.get(name,{})),
                'status':'unresolved','reason':'source_changed_requires_scoped_relation_recovery',
                'changed_event_ids':sorted(relation_targets),'retired_event_ids':retired})
        from .selection_gate import source_selection_readiness
        if source_selection_readiness(events).get('status') == 'passed':
            from .scoped_relations import recover_relations
            try:
                recovered = recover_relations(events,analysis['transcript'],analysis,relation_targets,
                    job_dir,vision,cancelled,report=report)
                from .scoped_owner_refresh import reconcile_scoped_dependencies
                dependencies = reconcile_scoped_dependencies(recovered['events'],recovered['story_structure'],analysis['transcript'])
                events = dependencies['events']
                if dependencies['status']=='unresolved':
                    recovered['story_structure']={**recovered['story_structure'],'status':'unresolved',
                        'reason':'source_dependency_owner_unresolved','dependency_refresh_unresolved':dependencies['unresolved']}
                history.append({'stage':'dependency_ownership','status':dependencies['status'],
                    'unresolved':dependencies['unresolved']})
                atomic_json(job_dir/'story_structure-result.json',{k:v for k,v in recovered['story_structure'].items() if k!='events'})
                atomic_json(job_dir/'dialogue_relations-result.json',recovered['dialogue_relations'])
                history.append({'stage':'relations','owners':sorted(relation_targets),
                    'scope':recovered['recovery_scope'],
                    'story_status':recovered['story_structure']['status'],
                    'dialogue_status':recovered['dialogue_relations']['status'],
                    'status':'accepted' if all(recovered[n]['status']=='accepted' for n in
                        ('story_structure','dialogue_relations')) else 'unresolved'})
            except (ValueError,RuntimeError,OSError,TimeoutError) as error:
                from .scene_understanding import _control_failure
                if _control_failure(error):raise
                history.append({'stage':'relations','owners':sorted(relation_targets),
                    'status':'unresolved','error_type':type(error).__name__})
        else:
            history.append({'stage':'relations','status':'unresolved','reason':'source_selection_not_ready'})
    if not boundary_mode and plan is not None:
        from .scoped_ending_recovery import recover_missing_endings
        events,ending_history = recover_missing_endings({**analysis,'events':events},plan,gate['problems'],
            job_dir,vision,report,cancelled)
        history.extend(ending_history)
    atomic_json(job_dir/'events.json',events)
    from .scoped_recovery_state import persist_repaired_scenes
    if boundary_mode or (job_dir/'boundary-recovery'/'derived-ownership.json').is_file():
        persist_repaired_scenes(job_dir,events,scenes,analysis['transcript'],analysis['shots'])
    diagnostics.append('final_quality_recovery.jsonl',{'problems':gate['problems'],'continuity_history':history})
    refreshed = analysis_result(job_dir,analysis.get('provider','local'),analysis['probe'],analysis['transcript'],analysis['shots'],events,scenes=scenes)
    return {**analysis,**refreshed,'scoped_framing_pending_event_ids':sorted(framing_pending)}
