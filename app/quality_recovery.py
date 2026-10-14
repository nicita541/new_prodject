"""Repair source analysis for explicit quality failures; the pipeline owns retries."""
from __future__ import annotations

import copy

from .final_quality import _planned_source
from app.source_ranges import merge_ranges
from .selection_gate import positive_ranges


def recover_final_quality(source, analysis, plan, gate, job_dir, vision, report, cancelled):
    """Return new source analysis; a recovery result never silently enlarges cuts."""
    from .analysis_result import analysis_result
    from app.json_store import analysis_json as atomic_json
    from .pipeline_diagnostics import Diagnostics
    from .continuity_verification import verify_omitted_continuity
    events = copy.deepcopy(analysis['events'])
    original_events = {e['id']:copy.deepcopy(e) for e in events}
    diagnostics = Diagnostics(job_dir)
    stages = {problem['recovery_stage'] for problem in gate['problems']}
    history = []
    targets = {p['event'] for p in gate['problems'] if p.get('event')}
    for problem in gate['problems']:
        window = problem.get('range')
        if isinstance(window,dict) and 'start' in window and 'end' in window:
            targets.update(e['id'] for e in events if e['start'] < window['end'] and e['end'] > window['start'])
    if 'source_roles' in stages:
        from .source_roles import refine_source_roles
        pending={p['event'] for p in gate['problems'] if p['recovery_stage']=='source_roles' and p.get('event')}
        if pending:
            events=refine_source_roles(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled,
                                       retry_unresolved=True,event_ids=pending,episode_duration=analysis['probe']['duration'])
        else:
            history.append({'stage':'source_roles','status':'unresolved','reason':'problem_owner_missing'})
        history.append({'stage':'source_roles','reviewed_event_ids':sorted(pending)})
    if 'continuity' in stages and plan is not None:
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
    if 'semantic_boundary' in stages:
        # The native boundary API cannot rebuild one disputed boundary yet. A
        # local repair must not silently become a paid whole-episode rebuild.
        history.append({'stage':'semantic_boundary','status':'unresolved',
                        'reason':'scoped_boundary_recovery_unavailable',
                        'scenes':[p.get('scene') for p in gate['problems'] if p['recovery_stage']=='semantic_boundary']})
    if 'selection_adjudication' in stages:
        from .selection_adjudication import adjudicate_event
        from .selection_gate import source_selection_readiness
        pending = {r['event'] for r in source_selection_readiness(events)['unresolved']} & targets
        for index,event in enumerate(events):
            if event['id'] not in pending:
                continue
            questions = ['Разреши конкретную проблему финальной проверки: '+p['code']
                         for p in gate['problems'] if p.get('event') == event['id']
                         or isinstance(p.get('range'),dict) and p['range']['start'] < event['end']
                         and p['range']['end'] > event['start']]
            if questions:
                events[index] = adjudicate_event(source,event,analysis['transcript'],analysis['shots'],
                    job_dir,vision,cancelled,questions=questions)
    # Native relation APIs own complete coverage and cross-owner dependencies.
    # They do not yet support merging a partial repair with exact accepted
    # endpoint ownership. Keep unaffected owners intact and require explicit
    # downstream resolution rather than presenting a partial episode as complete.
    from .source_roles import confirmed_exclusions
    from .content_identity import stable_semantics
    def inherited_source(event):
        return stable_semantics({key:event.get(key) for key in ('units','selected_ranges','unit_evidence',
            'source_identity','source_evidence','state_before','state_after','causal_links')} |
            {'confirmed_exclusions':confirmed_exclusions(event)})
    for event in events:
        if inherited_source(event) == inherited_source(original_events[event['id']]):
            continue
        for name in ('story_structure','dialogue_relations'):
            previous = copy.deepcopy(event.get(name,{}))
            event[name] = {**previous,'status':'unresolved','reason':'source_changed_requires_scoped_relation_recovery'}
        event['analysis_unresolved'] = True
        event['analysis_unresolved_reasons'] = list(dict.fromkeys([*event.get('analysis_unresolved_reasons',[]),
            'story_structure_unresolved','dialogue_relations_unresolved']))
        history.append({'stage':'relations','event':event['id'],'status':'unresolved',
                        'reason':'scoped_cross_owner_relation_recovery_unavailable'})
    atomic_json(job_dir/'events.json',events)
    diagnostics.append('final_quality_recovery.jsonl',{'problems':gate['problems'],'continuity_history':history})
    refreshed = analysis_result(job_dir,analysis.get('provider','local'),analysis['probe'],analysis['transcript'],analysis['shots'],events,scenes=analysis.get('scenes'))
    return {**analysis,**refreshed}
