"""Coordinate selection, ending, story and dialogue passes in an owned session."""
from __future__ import annotations

from pathlib import Path

from app.json_store import analysis_json as atomic_json


def finalize_editorial_selection(source, events, transcript, shots, probe, job_dir,
                                vision, report, cancelled, diagnostics, provider, *, journal=None):
    """Resolve source selection before endings invoke the strict planner.

    Failed perception remains a persisted analysis result for review/recovery;
    the production planner still refuses to render it.
    """
    job_dir = Path(job_dir)
    def saved(name, inputs, callback):
        return journal.run(name, inputs, callback, provider) if journal is not None else callback()
    from .endings import refine_endings
    from .selection_gate import adjudicate_selections, selection_readiness, source_selection_readiness
    from .antigravity_batch import adjudicate_in_batches
    context_builder = getattr(type(vision), 'complete_text_context', None)
    text_vision = context_builder(vision) if callable(context_builder) else vision
    with diagnostics.stage('final_selection_adjudication', provider=provider):
        events = saved('final_selection_adjudication', events, lambda: adjudicate_in_batches(source, events, transcript, shots, job_dir,
                                      vision, report, cancelled, refiner=adjudicate_selections, source_only=True))
    gate = source_selection_readiness(events)
    if gate['status'] == 'passed' and selection_readiness(events)['status'] == 'passed':
        with diagnostics.stage('endings', provider=provider):
            events = saved('endings', {'events': events, 'probe': probe}, lambda: refine_endings(events, transcript, shots, probe, job_dir, text_vision, report, cancelled))
        if selection_readiness(events)['status'] != 'passed':
            with diagnostics.stage('ending_selection_adjudication', provider=provider):
                events = saved('ending_selection_adjudication', events, lambda: adjudicate_in_batches(source, events, transcript, shots, job_dir,
                                              vision, report, cancelled, refiner=adjudicate_selections))
        gate = source_selection_readiness(events)
    elif gate['status'] != 'passed':
        diagnostics.warning('endings', 'unresolved_selection',
                            event_ids=[row['event'] for row in gate['unresolved']])
    if gate['status'] == 'passed':
        from .story_structure_pass import infer_story_structure
        from .dialogue_relations import infer_dialogue_relations, attach_dialogue_result
        report('analyze', .62, 'Определяем сюжетные связи и состояния нужных фрагментов')
        with diagnostics.stage('story_structure_analysis', provider=provider):
            structure = saved('story_structure_analysis', events, lambda: infer_story_structure(events, transcript, job_dir, text_vision, cancelled,
                progress=lambda done,total: report('analyze', .62,
                    f'Сюжетные связи · обработано целевых фрагментов: {done} из {total}')))
        events = structure['events']
        atomic_json(job_dir/'story_structure-result.json', {k:v for k,v in structure.items() if k != 'events'})
        with diagnostics.stage('dialogue_relations', provider=provider):
            dialogue = saved('dialogue_relations', {'events': events, 'relations': structure}, lambda: infer_dialogue_relations(events, transcript, job_dir, text_vision, cancelled, relations=structure,
                progress=lambda done,total: report('analyze', .62,
                    f'Связи реплик · обработано целевых фрагментов: {done} из {total}')))
        events = attach_dialogue_result(events,dialogue)
        atomic_json(job_dir/'dialogue_relations-result.json', dialogue)
        diagnostics.write('story_structure.json', {k:v for k,v in structure.items() if k != 'events'})
        diagnostics.write('dialogue_relations.json', dialogue)
        gate = selection_readiness(events)
    diagnostics.write('selection_gate.json', gate)
    return events
