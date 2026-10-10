"""Offline, checkpointed audio/visual analysis pipeline; models never invent source timestamps.

Decomposed into:
- app.media_probe: Subprocess execution, ffprobe analysis, shot detection, windows, transcript normalization.
- app.vision: LocalVision VLM runner, session management, and storyboard generation.
- app.story_review: Story units, event validation, global omission validation, and LLM review.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import urllib.error

from app.config import (
    FFMPEG, ROOT, VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR, setup_environment
)
from app.model_perf import purpose as inference_purpose

# Re-exports from app.media_probe
from app.media_probe import (
    atomic_json,
    load_json,
    run_process,
    probe_media,
    detect_shots,
    shot_checkpoint,
    analysis_windows,
    normalize_transcript,
    SHOT_DETECTOR_VERSION,
    SCENE_THRESHOLD,
)

# Re-exports from app.vision
from app.vision import (
    LocalVision,
    vision_session,
    storyboard_times,
    storyboard,
)

# Re-exports from app.story_review
from app.story_review import (
    analysis_context_limit,
    validated_event,
    candidate_units,
    apply_unit_selection,
    validate_global_omissions,
    apply_global_selection,
    global_story_review,
)

ANALYSIS_VERSION = 16
GLOBAL_STORY_VERSION = 9
STORYBOARD_VERSION = 3
EDITORIAL_POLICY = 'evidenced-semantic-selection-v2'


def derived_story_identity(analysis_key, provider, editorial_policy=EDITORIAL_POLICY):
    """Every semantic dependency that can bypass a story-stage checkpoint."""
    from .story import STORY_VERSION, EDGE_VERSION
    from .scene_refinement import SCENE_REFINEMENT_VERSION
    from .global_verification import GLOBAL_VERIFICATION_VERSION
    from .scene_understanding import SCENE_UNDERSTANDING_VERSION
    from .episode_profile import EPISODE_PROFILE_VERSION
    from .semantic_identity import semantic_identity
    from .framing import FOCUS_VERSION
    from .closing import CLOSING_VERSION
    from .titles import TITLES_VERSION
    from .production_sequence import VERSION as SEQUENCE_VERSION, CONTEXT_RADIUS
    from .source_roles import VERSION as SOURCE_ROLE_VERSION
    if provider in ('deepseek', 'deepseek_plan'):
        from .deepseek import DeepSeekVision
        paged = bool(getattr(DeepSeekVision, 'supports_image_pages', False))
    elif provider in ('local_flash_story', 'local_flash_story_budgeted'):
        from .flash_story_trial import TrialStoryVision
        paged = bool(getattr(TrialStoryVision, 'supports_image_pages', False))
    elif provider == 'hybrid':
        from .hybrid import HybridVision
        paged = bool(getattr(HybridVision, 'supports_image_pages', False))
    elif provider in ('local', 'local_fast_story'):
        paged = bool(getattr(LocalVision, 'supports_image_pages', False))
    else:
        raise ValueError('Неизвестный способ анализа')
    return {'visual': analysis_key, 'semantic_components': semantic_identity(), 'story': STORY_VERSION, 'edge': EDGE_VERSION,
            'scene_refinement': SCENE_REFINEMENT_VERSION,
            'scene_understanding': SCENE_UNDERSTANDING_VERSION,
            'episode_profile': EPISODE_PROFILE_VERSION,
            'global_visual_verification': GLOBAL_VERIFICATION_VERSION,
            'credit_routing': 'original-evidence-unioned-sequences-v2',
            'production_sequence': SEQUENCE_VERSION, 'credit_context_radius': CONTEXT_RADIUS,
            'source_roles': SOURCE_ROLE_VERSION,
            'credit_capability': 'image-pages' if paged else 'single-image',
            'editorial_policy': editorial_policy, 'global_story': GLOBAL_STORY_VERSION,
            'closing': CLOSING_VERSION, 'titles': TITLES_VERSION, 'speech_context': 4,
            'storyboard': STORYBOARD_VERSION,
            'focus': FOCUS_VERSION, 'focus_model': str(STORY_MODEL),
            'focus_projector': str(STORY_PROJECTOR)}


def analysis_provider(job_dir: Path) -> str:
    settings = job_dir / 'analysis-settings.json'
    provider = load_json(settings).get('provider', 'local') if settings.is_file() else 'local'
    if provider not in ('local', 'deepseek', 'hybrid', 'deepseek_plan', 'local_flash_story', 'local_fast_story', 'local_flash_story_budgeted'):
        raise ValueError('Неизвестный способ анализа')
    return provider


def selection_snapshot(diagnostics, stage, events):
    from .source_roles import merge_ranges
    active = [e for e in events if not e.get('global_excluded') and not e.get('pacing_excluded')]
    ranges = merge_ranges([r for e in active for r in e.get('selected_ranges', [e])])
    retained = sum(r['end']-r['start'] for r in ranges)
    diagnostics.event(stage, 'result', events=len(events), selected_events=len(active),
                      selected_duration=retained, uncertain=sum(bool(e.get('uncertain')) for e in events))
    diagnostics.summary(**{f'duration_after_{stage}': retained})


def analysis_result(job_dir: Path, provider: str, probe: dict, transcript: dict, shots: list[dict], events: list[dict]) -> dict:
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
    scenes_path = job_dir / 'scenes.json'
    if scenes_path.is_file():
        record['scenes'] = load_json(scenes_path)
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


def finalize_editorial_selection(source, events, transcript, shots, probe, job_dir,
                                vision, report, cancelled, diagnostics, provider):
    """Resolve source selection before endings invoke the strict planner.

    Failed perception remains a persisted analysis result for review/recovery;
    the production planner still refuses to render it.
    """
    job_dir = Path(job_dir)
    from .endings import refine_endings
    from .selection_gate import adjudicate_selections, selection_readiness, source_selection_readiness
    with diagnostics.stage('final_selection_adjudication', provider=provider):
        events = adjudicate_selections(source, events, transcript, shots, job_dir,
                                      vision, report, cancelled, source_only=True)
    gate = source_selection_readiness(events)
    if gate['status'] == 'passed' and selection_readiness(events)['status'] == 'passed':
        events = refine_endings(events, transcript, shots, probe, job_dir, vision, report, cancelled)
        if selection_readiness(events)['status'] != 'passed':
            with diagnostics.stage('ending_selection_adjudication', provider=provider):
                events = adjudicate_selections(source, events, transcript, shots, job_dir,
                                              vision, report, cancelled)
        gate = source_selection_readiness(events)
    elif gate['status'] != 'passed':
        diagnostics.warning('endings', 'unresolved_selection',
                            event_ids=[row['event'] for row in gate['unresolved']])
    if gate['status'] == 'passed':
        from .story_structure_pass import infer_story_structure
        from .dialogue_relations import infer_dialogue_relations, attach_dialogue_result
        report('analyze', .62, 'Определяем сюжетные связи и состояния исходных units')
        with diagnostics.stage('story_structure_analysis', provider=provider):
            structure = infer_story_structure(events, transcript, job_dir, vision, cancelled)
        events = structure['events']
        atomic_json(job_dir/'story_structure-result.json', {k:v for k,v in structure.items() if k != 'events'})
        with diagnostics.stage('dialogue_relations', provider=provider):
            dialogue = infer_dialogue_relations(events, transcript, job_dir, vision, cancelled, relations=structure)
        events = attach_dialogue_result(events,dialogue)
        atomic_json(job_dir/'dialogue_relations-result.json', dialogue)
        diagnostics.write('story_structure.json', {k:v for k,v in structure.items() if k != 'events'})
        diagnostics.write('dialogue_relations.json', dialogue)
        gate = selection_readiness(events)
    diagnostics.write('selection_gate.json', gate)
    return events


def framing_provider(provider: str) -> str:
    return 'local' if provider in ('deepseek_plan', 'local_fast_story') else provider


def analyze(job_dir: Path, source: Path, report, cancelled) -> dict:
    setup_environment()
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    from .editorial import load_profile
    editorial_profile = load_profile(job_dir, persist=True)
    from .editing import load_options
    layout = load_options(job_dir)['layout']
    provider = analysis_provider(job_dir)
    from .deepseek import provider_identity
    provider_profile = provider_identity(provider)
    source = source.resolve()
    if not source.is_relative_to(ROOT):
        raise ValueError('Исходное видео должно находиться внутри папки проекта')
    with source.open('rb') as stream:
        fingerprint = hashlib.file_digest(stream, 'sha256').hexdigest()
    diagnostics.write('run.json', {**load_json(diagnostics.path/'run.json'),
        'source_sha256': fingerprint, 'source_name': source.name, 'provider': provider,
        'analysis_version': ANALYSIS_VERSION, 'storyboard_version': STORYBOARD_VERSION})
    identity = {'source': fingerprint, 'version': ANALYSIS_VERSION}
    meta = job_dir / 'analysis.meta.json'
    if meta.exists() and load_json(meta) != identity:
        previous = load_json(meta)
        if previous.get('source') != fingerprint or previous.get('version') not in range(1, ANALYSIS_VERSION):
            raise ValueError('Исходник или версия анализа изменились. Создайте новое задание.')
        # Preserve factual audio/ASR/shot checkpoints, archive the old model's
        # derived decisions so an upgrade cannot silently reuse stale framing.
        import uuid
        archive = job_dir / 'diagnostics' / ('analysis-v' + str(previous['version']) + '-' + uuid.uuid4().hex)
        archive.mkdir(parents=True)
        names = ('visual', 'focus', 'events.json', 'story.json', 'plan.json') if previous.get('version') < 3 else ('events.json', 'story.json', 'plan.json')
        for name in names:
            old, destination = job_dir / name, archive / name
            if not old.resolve().is_relative_to(job_dir.resolve()) or not destination.resolve().is_relative_to(job_dir.resolve()):
                raise ValueError('Некорректный путь контрольной точки')
            if old.exists():
                old.rename(destination)
    atomic_json(meta, identity)
    report('prepare', 0.02, 'Проверка серии и подготовка звука')
    probe_path = job_dir / 'probe.json'
    probe = load_json(probe_path) if probe_path.exists() else probe_media(source)
    atomic_json(probe_path, probe)
    audio = job_dir / 'audio.wav'
    if not audio.exists():
        partial = job_dir / 'audio.partial.wav'
        run_process([FFMPEG, '-y', '-v', 'error', '-i', source, '-map', f"0:a:{probe.get('audio_stream', 0)}", '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', partial], job_dir / 'audio.log', cancelled)
        partial.replace(audio)
    transcript_path = job_dir / 'transcript.json'
    report('transcribe', 0.06, 'Распознавание русских реплик')
    if not transcript_path.exists():
        run_process([sys.executable, '-m', 'app.inference', audio, transcript_path], job_dir / 'asr.log', cancelled, timeout=7200)
    transcript = load_json(transcript_path)
    if not isinstance(transcript.get('words'), list) or not isinstance(transcript.get('segments'), list):
        raise ValueError('Некорректный сохранённый текст серии')
    settings = load_json(job_dir/'analysis-settings.json') if (job_dir/'analysis-settings.json').is_file() else {}
    from .provided_asr import validate_provided_transcript
    provided = settings.get('transcript_mode') == 'provided'
    if provided:
        transcript = validate_provided_transcript(transcript, settings, fingerprint, probe['duration'])
    from app.inference import REPAIR_VERSION
    if not provided and transcript.get('repair_version') != REPAIR_VERSION:
        report('transcribe', 0.16, 'Проверка подозрительных пауз и временных отметок речи')
        run_process([sys.executable, '-m', 'app.inference', audio, transcript_path, '--repair-only'],
                    job_dir / 'asr-repair.log', cancelled, timeout=7200)
        transcript = load_json(transcript_path)
    transcript = normalize_transcript(transcript, probe['duration'])
    atomic_json(transcript_path, transcript)
    report('scenes', 0.19, 'Определение смены планов')
    with diagnostics.stage('shot_detection', source_duration=probe['duration']):
        shots = shot_checkpoint(source, fingerprint, probe['duration'], job_dir, cancelled)
    from .media_probe import raw_shot_evidence
    raw_candidates = raw_shot_evidence(shots, job_dir)
    diagnostics.write('shots.json', {'accepted_shots': shots, 'raw_candidates': raw_candidates,
        'suppressed_candidates': [c for c in raw_candidates if not c.get('accepted')]})
    from .scene_detection import scene_checkpoint, SCENE_DETECTOR_VERSION
    from .episode_profile import build_episode_profile, scene_settings
    from .media_evidence import perception_checkpoint
    with diagnostics.stage('media_perception', source_duration=probe['duration']):
        perception = perception_checkpoint(source, probe['duration'], shots, transcript, job_dir, cancelled,
                                           audio_stream=probe.get('audio_stream', 0))
    diagnostics.write('media_evidence.json', perception)
    initial_profile = build_episode_profile(probe['duration'], transcript, shots,
        raw_candidates=raw_candidates, perception=perception)
    grouping_settings = scene_settings(initial_profile)
    diagnostics.write('episode_profile.json', {'initial': initial_profile, 'scene_settings': grouping_settings})
    report('scenes', .21, 'Объединение планов в смысловые сцены')
    scene_cache = {}
    with diagnostics.stage('scene_detection', shots=len(shots)):
        with inference_purpose("semantic_boundary"), vision_session(job_dir, cancelled, provider) as boundary_vision:
            scenes = scene_checkpoint(source, fingerprint, probe['duration'], shots, transcript, job_dir, cancelled,
                                      settings=grouping_settings, cache_status=scene_cache,
                                      vision=boundary_vision, perception=perception,
                                      audio_stream=probe.get('audio_stream', 0))
    diagnostics.event('scene_detection', 'cache_hit' if scene_cache.get('cache_hit') else 'cache_miss', **scene_cache)
    diagnostics.write('scenes.json', scenes)
    for scene in scenes:
        diagnostics.event('scene_detection', 'scene_created', scene_id=scene['id'],
            source_start=scene['start'], source_end=scene['end'], duration=scene['end']-scene['start'],
            reason=scene['boundary_reason'], confidence=scene['confidence'], uncertain=scene['uncertain'])
    diagnostics.summary(source_duration=probe['duration'], shots=len(shots), semantic_scenes=len(scenes))
    events_path = job_dir / 'events.json'
    model_identity = [{'path': str(path), 'size': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns}
                      for path in (VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR)]
    from .semantic_identity import semantic_identity
    component_signatures = semantic_identity()
    diagnostics.event('analysis', 'semantic_identity', components=component_signatures)
    analysis_key = hashlib.sha256(json.dumps({'identity': identity, 'models': model_identity,
        'semantic_components': component_signatures,
        'provider': provider_profile,
        'transcript': transcript, 'shots': shots, 'scenes': scenes, 'scene_detector': SCENE_DETECTOR_VERSION,
        'episode_profile': initial_profile, 'scene_settings': grouping_settings}, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    derived_key = hashlib.sha256(json.dumps(derived_story_identity(analysis_key, provider, editorial_profile),
        sort_keys=True).encode('utf-8')).hexdigest()
    derived_meta = job_dir / 'events.meta.json'
    # Story decisions retain their established signature. Only final focus
    # depends on the layout, so switching presets cannot repeat paid story work.
    from .pacing import PACING_VERSION
    from .endings import VERSION as ENDINGS_VERSION, RECOVERY_VERSION as ENDING_RECOVERY_VERSION
    pacing_provider = 'local' if provider == 'local_fast_story' else provider
    if provider in ('deepseek', 'deepseek_plan'):
        from .deepseek import recovery_status
        if recovery_status()['halted']:
            pacing_provider = 'local'
    focus_key = derived_key + f':pacing-v{PACING_VERSION}:endings-v{ENDINGS_VERSION}:ending-recovery-v{ENDING_RECOVERY_VERSION}:' + layout + ':' + pacing_provider
    if (events_path.exists() and derived_meta.exists()
            and load_json(derived_meta).get('signature') == focus_key
            and load_json(derived_meta).get('quality_state') != 'degraded'):
        diagnostics.event('analysis', 'cache_hit', signature=focus_key)
        return analysis_result(job_dir, provider, probe, transcript, shots, load_json(events_path))
    diagnostics.event('analysis', 'cache_miss', signature=focus_key)
    from .scene_analysis import analyze_scenes
    report('analyze', .22, 'Анализ смысловых сцен с соседним контекстом')
    with inference_purpose("scene_analysis"), vision_session(job_dir, cancelled, provider) as vision:
        events = analyze_scenes(source, scenes, transcript, shots, job_dir, vision, analysis_key, report, cancelled)
    # Larger model decides story retention; release the visual model before
    # loading it. Framing uses a separate, non-thinking 9B session: short real
    # comparisons reproduced clipped faces with 4B and improved them with 9B.
    story_checkpoint = job_dir / 'story-events.json'
    saved_story = load_json(story_checkpoint) if story_checkpoint.exists() else {}
    if saved_story.get('signature') == derived_key and saved_story.get('quality_state') != 'degraded':
        diagnostics.event('story_refinement', 'cache_hit', signature=derived_key)
        events = saved_story['events']
    else:
        diagnostics.event('story_refinement', 'cache_miss', signature=derived_key)
        with inference_purpose("story_refinement"), vision_session(job_dir, cancelled, provider, model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True) as vision:
            from app.story import preserve_dialogue_in_credits, clean_credit_continuations
            from .scene_refinement import refine_scene_story
            with diagnostics.stage('story_refinement', provider=provider, model=str(STORY_MODEL)):
                events = refine_scene_story(events, transcript, shots, job_dir, vision, report, cancelled)
            selection_snapshot(diagnostics, 'story_refinement', events)
            events = preserve_dialogue_in_credits(events, transcript)
            events = clean_credit_continuations(events, transcript, shots, job_dir, vision, report, cancelled)
            from app.eyecatch import detect_eyecatches, apply_eyecatch_exclusions
            eyecatches = detect_eyecatches(events, transcript, shots, probe.get('duration'))
            if eyecatches:
                events = apply_eyecatch_exclusions(events, eyecatches)
            from app.titles import refine_titles
            from app.closing import refine_closing_novelty
            events = refine_titles(events, transcript, shots, job_dir, vision, report, cancelled)
            events = refine_closing_novelty(events, transcript, shots, job_dir, vision, report, cancelled)
            from .source_roles import refine_source_roles
            events = refine_source_roles(events, transcript, shots, job_dir, vision, report, cancelled)
            selection_snapshot(diagnostics, 'source_roles', events)
            report('analyze', 0.49, 'Проверка связности истории целиком')
            from .global_verification import verify_global_visual
            with diagnostics.stage('global_visual_verification', provider=provider):
                events = verify_global_visual(source,events,transcript,shots,job_dir,vision,report,cancelled)
            selection_snapshot(diagnostics, 'global_visual_verification', events)
            from .selection_gate import adjudicate_selections
            with diagnostics.stage('selection_adjudication', provider=provider):
                events = adjudicate_selections(source, events, transcript, shots, job_dir, vision, report, cancelled)
            selection_snapshot(diagnostics, 'selection_adjudication', events)
            # Global pass references only existing event IDs, never generated time ranges.
            with inference_purpose("global_story"), diagnostics.stage('global_story', provider=provider, model=str(STORY_MODEL)):
                decisions = global_story_review(vision, events, editorial_profile)
            apply_global_selection(events, decisions, editorial_profile)
            global_path = diagnostics.path/'global_story.json'
            global_audit = load_json(global_path) if global_path.exists() else {'events':{}}
            global_audit['text_review'] = decisions
            for event in events:
                entry = global_audit.setdefault('events',{}).setdefault(event['id'],{})
                entry['global_selection'] = {'selected':event['id'] in decisions.get('keep',[]),
                    'omission':event.get('global_omission'), 'dependencies':[d for d in decisions.get('dependencies',[]) if d.get('event')==event['id']]}
                entry['final_decision'] = {'summary':event.get('final_summary',event['summary']),
                    'summary_source':event.get('summary_source','local'), 'uncertain':event.get('uncertain',False),
                    'confidence':event.get('confidence'), 'selected_ranges':event.get('selected_ranges',[])}
            diagnostics.write('global_story.json',global_audit)
            selection_snapshot(diagnostics, 'global_story', events)
            known = {e['id'] for e in events}
            keep = decisions.get('keep')
            if not isinstance(keep, list) or not keep or any(not isinstance(e, str) or e not in known for e in keep):
                raise ValueError('Модель вернула некорректные ссылки на события серии')
            dependency_map = {}
            for item in decisions.get('dependencies', []):
                if isinstance(item, dict) and item.get('event') in known and isinstance(item.get('requires'), list):
                    dependency_map[item['event']] = [e for e in item['requires'] if isinstance(e, str) and e in known and e < item['event']]
            for event in events:
                if event.get('credit_montage'):
                    # Dedicated visual classifier confirms pure non-narrative
                    # credits; the generic global keep-all response cannot undo it.
                    event['importance'] = 1
                    event['requires'] = []
                    continue
                if event['id'] in keep and not event.get('selection_empty_verified'):
                    event['importance'] = max(4, event['importance'])
                # Explicit global omissions have evidence; the planner uses
                # these dependency signals to find bounded earlier context.
                credits = {e['id'] for e in events if e.get('credit_montage')}
                event['requires'] = sorted(set(event['requires'] + dependency_map.get(event['id'], [])) - credits)
            atomic_json(job_dir / 'story.json', {'summary': str(decisions.get('summary', '')), 'keep': keep,
                                                  'omit': decisions.get('omit', []),
                                                  'incomplete_event_ids': decisions.get('incomplete_event_ids', []),
                                                  'cpu_fallback': vision.cpu_fallback, 'analysis_provider': provider})
            from app.speech_context import protect_speech_context
            events = protect_speech_context(events, transcript)
        atomic_json(story_checkpoint, {'signature': derived_key, 'events': events,
            'quality_state': 'degraded' if any(e.get('analysis_unresolved') or e.get('source_role_unresolved') for e in events) else 'complete'})
    from .pacing import refine_pacing, refine_silent_sequences, BudgetPacingVision
    with inference_purpose("pacing"), vision_session(job_dir, cancelled, pacing_provider, model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
        if pacing_provider in ('deepseek', 'deepseek_plan'):
            with BudgetPacingVision(vision, job_dir, cancelled) as paced:
                events = refine_pacing(source, events, transcript, shots, job_dir, paced, report, cancelled)
        else:
            events = refine_pacing(source, events, transcript, shots, job_dir, vision, report, cancelled)
        events = refine_silent_sequences(source, events, transcript, shots, job_dir, vision, report, cancelled)
        selection_snapshot(diagnostics, 'pacing', events)
        events = finalize_editorial_selection(source, events, transcript, shots, probe,
            job_dir, vision, report, cancelled, diagnostics, pacing_provider)
    if pacing_provider != provider:
        for event in events:
            if event.get('pacing_removed'):
                event.setdefault('story_warnings', []).append('Темп дополнительно проверен локально: платные запросы DeepSeek остановлены')
    from app.framing import refine_focus
    focus_provider = framing_provider(provider)
    if layout == 'portrait':
        with inference_purpose("framing"), vision_session(job_dir, cancelled, focus_provider, model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
            events = refine_focus(source, probe, transcript, shots, events, job_dir, vision, report, cancelled)
    else:
        report('framing', 0.65, 'Сохраняем исходный кадр целиком на мягком вертикальном фоне')
    atomic_json(events_path, events)
    atomic_json(derived_meta, {'signature': focus_key,
        'quality_state': 'degraded' if any(e.get('analysis_unresolved') or e.get('source_role_unresolved') or e.get('pacing_degraded') or e.get('endings_degraded') for e in events) else 'complete',
        'requested_provider': provider, 'pacing_providers': sorted({p for e in events for p in e.get('pacing_providers', [])})})
    return analysis_result(job_dir, provider, probe, transcript, shots, events)
