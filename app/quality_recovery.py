"""Repair source analysis for explicit quality failures; the pipeline owns retries."""
from __future__ import annotations

import copy

from .final_quality import _planned_source, gate_identity
from app.source_ranges import merge_ranges
from .source_roles import confirmed_exclusions
from .selection_gate import positive_ranges


def recover_final_quality(source, analysis, plan, gate, job_dir, vision, report, cancelled):
    """Return new source analysis; a recovery result never silently enlarges cuts."""
    from .analysis_result import analysis_result
    from .editorial_pipeline import finalize_editorial_selection
    from app.json_store import analysis_json as atomic_json
    from .pipeline_diagnostics import Diagnostics
    from .continuity_verification import verify_omitted_continuity
    events = copy.deepcopy(analysis['events'])
    diagnostics = Diagnostics(job_dir)
    stages = {problem['recovery_stage'] for problem in gate['problems']}
    history = []
    if 'source_roles' in stages:
        from .source_roles import refine_source_roles
        pending={p['event'] for p in gate['problems'] if p['recovery_stage']=='source_roles' and p.get('event')}
        events=refine_source_roles(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled,
                                   retry_unresolved=True,event_ids=pending or None)
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
        # Reinspect the disputed source geometry. A failure remains explicit;
        # source ambiguity cannot be hidden by greater retention.
        from .scene_detection import scene_checkpoint
        from app.json_store import load_json
        fingerprint = load_json(job_dir/'source-fingerprint.json') if (job_dir/'source-fingerprint.json').is_file() else gate_identity(analysis['probe'])
        cache = job_dir/'scenes.meta.json'
        if cache.is_file():
            cached = load_json(cache)
            fingerprint = cached.get('source', {}).get('fingerprint', fingerprint)
        recovered_scenes = scene_checkpoint(source,fingerprint,analysis['probe']['duration'],analysis['shots'],analysis['transcript'],
            job_dir,cancelled,settings=analysis['episode_profile'].get('scene_settings'),vision=vision,
            perception=analysis.get('perception'),audio_stream=analysis['probe'].get('audio_stream',0),force_boundary_review=True)
        geometry = [(row['id'],row['start'],row['end']) for row in recovered_scenes]
        previous_geometry = [(event.get('scene_id'),event['start'],event['end']) for event in events]
        if geometry != previous_geometry:
            # New scene ownership invalidates old unit IDs and their derived
            # relations. Rebuild in the already owned provider session.
            from .scene_analysis import analyze_scenes
            from .scene_refinement import refine_scene_story
            from .story import preserve_dialogue_in_credits, clean_credit_continuations
            from .eyecatch import detect_eyecatches, apply_eyecatch_exclusions
            from .titles import refine_titles
            from .closing import refine_closing_novelty
            from .source_roles import refine_source_roles
            from .global_verification import verify_global_visual
            exclusions = [r for event in events for r in confirmed_exclusions(event)]
            signature = gate_identity({'source':fingerprint,'scenes':recovered_scenes,'transcript':analysis['transcript']})
            events = analyze_scenes(source,recovered_scenes,analysis['transcript'],analysis['shots'],
                                    job_dir,vision,signature,report,cancelled)
            for event in events:
                event['excluded_review_ranges'] = [{'start':max(event['start'],r['start']),
                    'end':min(event['end'],r['end'])} for r in exclusions
                    if r['start'] < event['end'] and r['end'] > event['start']]
            events = refine_scene_story(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            events = preserve_dialogue_in_credits(events,analysis['transcript'])
            events = clean_credit_continuations(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            eyecatches = detect_eyecatches(events,analysis['transcript'],analysis['shots'],analysis['probe']['duration'])
            if eyecatches:
                events = apply_eyecatch_exclusions(events,eyecatches)
            events = refine_titles(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            events = refine_closing_novelty(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            events = refine_source_roles(events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            events = verify_global_visual(source,events,analysis['transcript'],analysis['shots'],job_dir,vision,report,cancelled)
            history.append({'stage':'semantic_boundary','ownership_rebuilt':True,
                            'previous_geometry':previous_geometry,'source_geometry':geometry})
    if 'selection_adjudication' in stages:
        from .selection_adjudication import adjudicate_event
        from .selection_gate import source_selection_readiness
        pending = {r['event'] for r in source_selection_readiness(events)['unresolved']}
        for index,event in enumerate(events):
            if event['id'] not in pending:
                continue
            questions = ['Разреши конкретную проблему финальной проверки: '+p['code']
                         for p in gate['problems'] if p.get('event') in (None,event['id'])][:18]
            if questions:
                events[index] = adjudicate_event(source,event,analysis['transcript'],analysis['shots'],
                    job_dir,vision,cancelled,questions=questions)
    events = finalize_editorial_selection(source,events,analysis['transcript'],analysis['shots'],analysis['probe'],
        job_dir,vision,report,cancelled,diagnostics,analysis.get('provider','local'))
    atomic_json(job_dir/'events.json',events)
    diagnostics.append('final_quality_recovery.jsonl',{'problems':gate['problems'],'continuity_history':history})
    return analysis_result(job_dir,analysis.get('provider','local'),analysis['probe'],analysis['transcript'],analysis['shots'],events)
