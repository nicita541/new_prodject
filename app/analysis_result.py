"""Assemble persisted analysis records and diagnostics; never start model sessions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.json_store import analysis_json as atomic_json, load_json


def analysis_result(job_dir: Path, provider: str, probe: dict, transcript: dict, shots: list[dict], events: list[dict], *, scenes=None) -> dict:
    from .selection_gate import selection_readiness
    record = {
        'quality_policy': 'source_proved_v1',
        'probe': probe,
        'transcript': transcript,
        'shots': shots,
        'events': events,
        'selection_gate': selection_readiness(events),
        'provider': provider,
        'duration': probe['duration'],
        'width': probe['width'],
        'height': probe['height'],
        'fps': probe['fps'],
        'audio_stream': probe.get('audio_stream', 0),
        'story_warnings': sorted({w for e in events for w in e.get('story_warnings', [])})
    }
    pending_focus=[e['id'] for e in events if e.get('framing_refresh',{}).get('status')=='pending']
    if pending_focus:
        record['scoped_framing_pending_event_ids']=pending_focus
    scenes_path = job_dir / 'scenes.json'
    handles_path = job_dir/'speech-handle-overrides.json'
    if handles_path.is_file():
        from .speech_handles import validate_overrides
        record['speech_handle_overrides'] = validate_overrides(load_json(handles_path), probe['duration'])
    if scenes is not None:
        record['scenes'] = scenes
    elif scenes_path.is_file():
        record['scenes'] = load_json(scenes_path)
    from .scoped_recovery_state import repaired_scenes
    restored_scenes = repaired_scenes(job_dir,events,transcript,shots,record.get('scenes'))
    if restored_scenes is not None:
        record['scenes'] = restored_scenes
    for name in ('story_structure', 'dialogue_relations'):
        path = job_dir/(name+'-result.json')
        if path.is_file():
            record[name] = load_json(path)
    preferences_path = job_dir/'planning-preferences.json'
    if preferences_path.is_file():
        preferences = load_json(preferences_path)
        if (not isinstance(preferences,dict) or set(preferences) != {'preferred_part_count'}
                or type(preferences['preferred_part_count']) is not int or not 1 <= preferences['preferred_part_count'] <= 64):
            raise ValueError('Некорректное предпочтительное количество частей')
        record['preferred_part_count'] = preferences['preferred_part_count']
    from .episode_profile import build_episode_profile, adaptive_retention_budget, scene_settings
    from .media_probe import raw_shot_evidence
    perception_path = job_dir/'media-evidence.json'
    perception = load_json(perception_path) if perception_path.is_file() else None
    if perception is not None:
        record['perception'] = perception
    profile = build_episode_profile(probe['duration'], transcript, shots, record.get('scenes'), events,
                                    raw_candidates=raw_shot_evidence(shots, job_dir), perception=perception)
    profile['retention_budget'] = adaptive_retention_budget(profile)
    profile['initial_profile'] = build_episode_profile(probe['duration'], transcript, shots,
                                                      raw_candidates=raw_shot_evidence(shots, job_dir), perception=perception)
    profile['scene_settings'] = scene_settings(profile['initial_profile'])
    record['episode_profile'] = profile
    atomic_json(job_dir/'episode_profile.json', profile)
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    diagnostics.write('selection_gate.json', record['selection_gate'])
    events_digest = hashlib.sha256(json.dumps(events, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    summary_cache = diagnostics.path/'analysis-summary.json'
    if summary_cache.is_file():
        try:
            saved_summary = load_json(summary_cache)
            if not isinstance(saved_summary, dict) or not isinstance(saved_summary.get('metrics'), dict):
                raise ValueError('Invalid diagnostic summary cache')
        except (OSError, ValueError, TypeError) as error:
            diagnostics.warning('analysis', 'cached_analysis_summary_invalid', error_type=type(error).__name__)
        else:
            if saved_summary.get('events_digest') == events_digest:
                current_metrics = load_json(diagnostics.path/'summary.json') if (diagnostics.path/'summary.json').exists() else {}
                diagnostics.summary(**{key: value for key,value in saved_summary['metrics'].items()
                                       if key.startswith('duration_after_') and key not in current_metrics})
    diagnostics.write('episode_profile.json', profile)
    diagnostics.summary(source_duration=probe['duration'], shots=len(shots),
        semantic_scenes=len(record.get('scenes', [])), story_events=len(events),
        uncertain_initial=sum(bool(e.get('initial_uncertain')) for e in events),
        uncertain_after_recovery=sum(bool(e.get('uncertain_after_recovery',
            any(bool(c.get('uncertain')) for c in e.get('chunk_analyses', [])))) for e in events),
        raw_selected_duration=sum(r['end']-r['start'] for e in events
                                  if not e.get('global_excluded') for r in e.get('selected_ranges', [])),
        globally_omitted=sum(bool(e.get('global_excluded')) for e in events),
        narrative_bridges=sum(bool(e.get('narrative_bridge')) for e in events),
        uncertain_final=sum(bool(e.get('uncertain')) for e in events),
        global_corrections=sum(e.get('summary_source')=='global_correction' for e in events))
    metric_names = {'source_duration','shots','semantic_scenes','story_events','uncertain_initial',
                    'uncertain_after_recovery','uncertain_final','raw_selected_duration',
                    'globally_omitted','narrative_bridges','global_corrections'}
    summary_metrics = {key: value for key,value in load_json(diagnostics.path/'summary.json').items()
                       if key in metric_names or key.startswith('duration_after_')}
    diagnostics.write('analysis-summary.json', {'events_digest': events_digest, 'metrics': summary_metrics})
    story = job_dir / 'story.json'
    if story.is_file():
        record['story'] = load_json(story)
    if provider == 'hybrid':
        from .hybrid import review_summary
        summary = review_summary(job_dir)
        record['hybrid_review'] = summary
        warnings = []
        if summary.get('unresolved'):
            warnings.append(
                f"Гибридная проверка: {summary['unresolved']} сомнительных ответов остались локальными; "
                f"DeepSeek проверил {summary['reviewed']}. Проверьте сюжет и кадрирование.")
        if summary.get('remote_disabled'):
            warnings.append('DeepSeek недоступен или средств недостаточно: обработка продолжена локально.')
        record['warnings'] = warnings
    return record
