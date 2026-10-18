"""Qualify coarse hypotheses with ordinary source-proof producing native passes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path


def resolve_scope(scenes, episode_map):
    """Resolve finite declared dependencies to whole, original source scenes."""
    canonical = copy.deepcopy(scenes)
    previous_end = None
    for scene in canonical:
        start, end = scene.get('start'), scene.get('end')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or start >= end
                or previous_end is not None and start < previous_end):
            raise ValueError('Canonical scenes must be finite and ordered source owners')
        previous_end = end
    by_scene = {s['id']: s for s in canonical}
    if len(by_scene) != len(canonical):
        raise ValueError('Duplicate canonical scene ID')
    windows = episode_map.get('windows', [])
    by_window = {w['id']: w for w in windows}
    if len(by_window) != len(windows):
        raise ValueError('Duplicate survey window ID')
    for window in windows:
        scene = by_scene.get(window.get('scene_id'))
        start, end = window.get('start'), window.get('end')
        if (scene is None or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or not scene['start'] <= start < end <= scene['end']):
            raise ValueError('Survey window has invalid original scene ownership')
    requested, prerequisites = set(), set()
    for hypothesis in episode_map.get('hypotheses', []):
        for key, target in (('window_ids', requested), ('prerequisite_window_ids', prerequisites)):
            refs = hypothesis.get(key, [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in by_window for ref in refs):
                raise ValueError('Hypothesis references an unknown survey window')
            target.update(refs)
    selected = requested | prerequisites
    owners = {by_window[ref]['scene_id'] for ref in selected}
    chosen = [scene for scene in canonical if scene['id'] in owners]
    contexts = {s['id']: {'previous': canonical[i-1] if i else None,
                          'next': canonical[i+1] if i+1 < len(canonical) else None}
                for i, s in enumerate(canonical) if s['id'] in owners}
    event_ids = {s['id']: f'event_{i:04d}' for i, s in enumerate(canonical) if s['id'] in owners}
    ranges = []
    for scene in chosen:
        if ranges and scene['start'] <= ranges[-1]['end']:
            ranges[-1]['end'] = max(ranges[-1]['end'], scene['end'])
        else:
            ranges.append({'start': scene['start'], 'end': scene['end']})
    return {'scenes': chosen, 'event_ids': event_ids, 'context_scenes': contexts,
            'requested_window_ids': sorted(requested), 'prerequisite_window_ids': sorted(prerequisites),
            'analyzed_window_ids': [w['id'] for w in windows if w['scene_id'] in owners],
            'analyzed_ranges': ranges, 'geometry_policy': ('whole_source_regions'
                if any(s.get('technical_region') for s in chosen) else 'whole_original_scenes'),
            'authority': 'native_qualification_required'}


class _ScopedJournal:
    def __init__(self, journal, identity):
        self.journal, self.identity = journal, identity

    def run(self, name, inputs, callback, producer):
        return self.journal.run('selective_native_' + name,
                                {'identity': self.identity, 'inputs': inputs}, callback, producer)


def _technical_failures(events):
    """Failed source/model contracts are distinct from a valid uncertain answer."""
    failures = []
    for event in events:
        audit = event.get('selection_adjudication', {})
        if audit.get('status') == 'accepted':
            continue  # A later source-grounded decision recovered this owner.
        broken = [row for row in audit.get('decisions', []) if row.get('status') == 'failed']
        for row in broken:
            unknown = row.get('error_type') == 'QuestionJournalError'
            truncated = row.get('error_category') == 'response_length'
            failures.append({'stage': 'source_selection', 'event_id': event['id'],
                'reason': ('unknown_dispatch' if unknown else 'model_output_truncated' if truncated else 'model_output_invalid'
                           if row.get('reason') == 'invalid_evidence' else 'model_or_source_failure'),
                'message': ('Результат предыдущего запроса неизвестен; повторная отправка не выполнена' if unknown else
                    'Ответ модели оборван до завершения; повтор с теми же параметрами не выполнен' if truncated else
                    'Модель вернула некорректное доказательство исходника' if row.get('reason') == 'invalid_evidence'
                    else 'Не удалось завершить проверку исходного материала'),
                'error_type': row.get('error_type', 'AnalysisError'), 'export_eligible': False})
        if not broken and 'model_failure' in event.get('uncertainty_reasons', []):
            failures.append({'stage': 'source_understanding', 'event_id': event['id'],
                'reason': 'model_failure', 'message': 'Не удалось получить ответ модели',
                'error_type': 'ModelError', 'export_eligible': False})
    return failures


def qualify_episode_map(source, probe, transcript, shots, scenes, episode_map, job_dir,
                        sessions, provider, report, cancelled, journal, diagnostics):
    """One native qualification per union of declared promising/prerequisite windows.

    Coarse premises never become proof or editorial dependencies. Unknown native
    evidence remains unresolved; this adapter neither enlarges nor retries scope.
    """
    from .analysis_result import analysis_result
    from .analysis_checks import AnalysisChecks
    from .config import STORY_MODEL, STORY_PROJECTOR
    from .scene_analysis import analyze_scenes
    from .selection_gate import adjudicate_selections, source_selection_readiness, source_selection_problems
    from .antigravity_batch import adjudicate_in_batches, review_events_in_batches, closing_in_batches
    from .story import preserve_dialogue_in_credits, clean_credit_continuations
    from .titles import refine_titles
    from .closing import refine_closing_novelty
    from .source_roles import refine_source_roles
    from .story_structure_pass import infer_story_structure
    from .dialogue_relations import infer_dialogue_relations, attach_dialogue_result
    from .semantic_identity import scoped_identity
    from .json_store import analysis_json as atomic_json
    from functools import partial
    from .unit_decisions import CONTRACT

    probe, transcript, shots, scenes, episode_map = copy.deepcopy((probe, transcript, shots, scenes, episode_map))
    job_dir = Path(job_dir)
    scope = resolve_scope(scenes, episode_map)
    source_path = Path(source)
    stat = source_path.stat() if source_path.is_file() else None
    identity = {'version': 1, 'source': {'path': str(source_path.resolve()),
                'size': stat.st_size if stat else None, 'mtime_ns': stat.st_mtime_ns if stat else None},
                'scope': scope, 'transcript': transcript, 'shots': shots, 'probe': probe,
                'provider': provider, 'story_model': str(STORY_MODEL), 'story_projector': str(STORY_PROJECTOR),
                'code': {name: scoped_identity(name)['digest'] for name in ('perception', 'story', 'late_analysis')},
                'native_decision_contract': {'version': CONTRACT, 'code': hashlib.sha256(
                    Path(__file__).with_name('unit_decisions.py').read_bytes()).hexdigest()},
                'adapter_code': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    scoped_journal = _ScopedJournal(journal, identity)
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    events, structure_result, dialogue_result = [], None, None
    if scope['scenes']:
        with sessions.session(job_dir, cancelled, 'local') as vision:
            events = scoped_journal.run('perception', scope, lambda: analyze_scenes(source, scope['scenes'],
                transcript, shots, job_dir, vision, signature, report, cancelled,
                event_ids=scope['event_ids'], context_scenes=scope['context_scenes']), 'local')
        checks = AnalysisChecks(job_dir, scoped_journal, diagnostics, report)
        with sessions.session(job_dir, cancelled, provider, model=STORY_MODEL,
                              projector=STORY_PROJECTOR, thinking=True) as vision:
            events = preserve_dialogue_in_credits(events, transcript)
            events = checks.targeted('credit_continuations', events, lambda current: clean_credit_continuations(
                current, transcript, shots, job_dir, vision, report, cancelled), provider, task='credits')
            events = checks.targeted('titles', events, lambda current: review_events_in_batches(current,
                transcript, shots, job_dir, vision, report, cancelled, refiner=refine_titles, label='Поиск титров'), provider, task='titles')
            events = checks.targeted('closing_novelty', events, lambda current: closing_in_batches(current,
                transcript, shots, job_dir, vision, report, cancelled,
                refiner=partial(refine_closing_novelty, episode_duration=probe['duration'])), provider, task='closing')
            events = checks.targeted('source_roles', events, lambda current: review_events_in_batches(current,
                transcript, shots, job_dir, vision, report, cancelled, refiner=partial(refine_source_roles,
                episode_duration=probe['duration']), label='Проверяем сюжетную речь', full_context=True), provider, task='source_roles')
            events = scoped_journal.run('final_selection_adjudication', events, lambda: adjudicate_in_batches(
                source, events, transcript, shots, job_dir, vision, report, cancelled,
                refiner=partial(adjudicate_selections, decision_contract=CONTRACT), source_only=True), provider)
            qualified = [event for event in events if not source_selection_problems(event)]
            if qualified:
                builder = getattr(type(vision), 'complete_text_context', None)
                text_vision = builder(vision) if callable(builder) else vision
                structure = scoped_journal.run('story_structure', qualified, lambda: infer_story_structure(
                    qualified, transcript, job_dir, text_vision, cancelled), provider)
                qualified = structure['events']
                structure_result = {k: v for k, v in structure.items() if k != 'events'}
                atomic_json(job_dir/'story_structure-result.json', structure_result)
                dialogue = scoped_journal.run('dialogue_relations', {'events': qualified, 'relations': structure},
                    lambda: infer_dialogue_relations(qualified, transcript, job_dir, text_vision, cancelled,
                                                     relations=structure), provider)
                qualified = attach_dialogue_result(qualified, dialogue)
                by_id = {event['id']: event for event in qualified}
                events = [by_id.get(event['id'], event) for event in events]
                dialogue_result = dialogue
                atomic_json(job_dir/'dialogue_relations-result.json', dialogue)
    scope['native_event_ids'] = [event['id'] for event in events]
    scope['actual_native_ranges'] = [{'event_id': event['id'], 'scene_id': event.get('scene_id'),
                                     'start': event['start'], 'end': event['end']} for event in events]
    scope['native_qualified_event_ids'] = [event['id'] for event in events if not source_selection_problems(event)]
    scope['hypotheses_are_source_proof'] = False
    scope['source_gate'] = source_selection_readiness(events)
    result = analysis_result(job_dir, provider, probe, transcript, shots, events, scenes=scenes)
    result.pop('story', None)  # No whole-episode global retention pass ran here.
    # analysis_result also supports legacy jobs; never attach their stale relations.
    for name, current in (('story_structure', structure_result), ('dialogue_relations', dialogue_result)):
        result.pop(name, None)
        if current is not None:
            result[name] = current
    result['episode_map'], result['selective_scope'] = episode_map, scope
    result['analysis_technical_failures'] = _technical_failures(events)
    atomic_json(job_dir/'selective-scope.json', scope)
    return result
