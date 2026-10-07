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

ANALYSIS_VERSION = 9
GLOBAL_STORY_VERSION = 6
STORYBOARD_VERSION = 3
EDITORIAL_POLICY = 'balanced-atmosphere-v1'


def derived_story_identity(analysis_key, provider, editorial_policy=EDITORIAL_POLICY):
    """Every semantic dependency that can bypass a story-stage checkpoint."""
    from .story import STORY_VERSION, EDGE_VERSION
    from .scene_refinement import SCENE_REFINEMENT_VERSION
    from .framing import FOCUS_VERSION
    from .closing import CLOSING_VERSION
    from .titles import TITLES_VERSION
    from .production_sequence import VERSION as SEQUENCE_VERSION, CONTEXT_RADIUS
    from .source_roles import VERSION as SOURCE_ROLE_VERSION
    if provider in ('deepseek', 'deepseek_plan'):
        from .deepseek import DeepSeekVision
        paged = bool(getattr(DeepSeekVision, 'supports_image_pages', False))
    elif provider == 'hybrid':
        from .hybrid import HybridVision
        paged = bool(getattr(HybridVision, 'supports_image_pages', False))
    elif provider == 'local':
        paged = bool(getattr(LocalVision, 'supports_image_pages', False))
    else:
        raise ValueError('Неизвестный способ анализа')
    return {'visual': analysis_key, 'story': STORY_VERSION, 'edge': EDGE_VERSION,
            'scene_refinement': SCENE_REFINEMENT_VERSION,
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
    if provider not in ('local', 'deepseek', 'hybrid', 'deepseek_plan'):
        raise ValueError('Неизвестный способ анализа')
    return provider


def analysis_result(job_dir: Path, provider: str, probe: dict, transcript: dict, shots: list[dict], events: list[dict]) -> dict:
    record = {
        'probe': probe,
        'transcript': transcript,
        'shots': shots,
        'events': events,
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
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    diagnostics.summary(story_events=len(events),
        raw_selected_duration=sum(r['end']-r['start'] for e in events
                                  if not e.get('global_excluded') for r in e.get('selected_ranges', [])),
        globally_omitted=sum(bool(e.get('global_excluded')) for e in events),
        narrative_bridges=sum(bool(e.get('narrative_bridge')) for e in events))
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


def framing_provider(provider: str) -> str:
    return 'local' if provider == 'deepseek_plan' else provider


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
        if previous.get('source') != fingerprint or previous.get('version') not in (1, 2, 3, 4, 5, 6, 7, 8):
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
    from app.inference import REPAIR_VERSION
    if transcript.get('repair_version') != REPAIR_VERSION:
        report('transcribe', 0.16, 'Проверка подозрительных пауз и временных отметок речи')
        run_process([sys.executable, '-m', 'app.inference', audio, transcript_path, '--repair-only'],
                    job_dir / 'asr-repair.log', cancelled, timeout=7200)
        transcript = load_json(transcript_path)
    transcript = normalize_transcript(transcript, probe['duration'])
    atomic_json(transcript_path, transcript)
    report('scenes', 0.19, 'Определение смены планов')
    with diagnostics.stage('shot_detection', source_duration=probe['duration']):
        shots = shot_checkpoint(source, fingerprint, probe['duration'], job_dir, cancelled)
    diagnostics.write('shots.json', [{**shot, 'scene_score': shot.get('scene_score'), 'accepted': True} for shot in shots])
    from .scene_detection import scene_checkpoint, SCENE_DETECTOR_VERSION
    report('scenes', .21, 'Объединение планов в смысловые сцены')
    scene_cache = {}
    with diagnostics.stage('scene_detection', shots=len(shots)):
        scenes = scene_checkpoint(source, fingerprint, probe['duration'], shots, transcript, job_dir, cancelled, cache_status=scene_cache)
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
    analysis_key = hashlib.sha256(json.dumps({'identity': identity, 'models': model_identity,
        'provider': provider_profile,
        'transcript': transcript, 'shots': shots, 'scenes': scenes, 'scene_detector': SCENE_DETECTOR_VERSION}, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    derived_key = hashlib.sha256(json.dumps(derived_story_identity(analysis_key, provider, editorial_profile),
        sort_keys=True).encode('utf-8')).hexdigest()
    derived_meta = job_dir / 'events.meta.json'
    # Story decisions retain their established signature. Only final focus
    # depends on the layout, so switching presets cannot repeat paid story work.
    from .pacing import PACING_VERSION
    from .endings import VERSION as ENDINGS_VERSION, RECOVERY_VERSION as ENDING_RECOVERY_VERSION
    pacing_provider = provider
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
    with vision_session(job_dir, cancelled, provider) as vision:
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
        with vision_session(job_dir, cancelled, provider, model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True) as vision:
            from app.story import preserve_dialogue_in_credits, clean_credit_continuations
            from .scene_refinement import refine_scene_story
            events = refine_scene_story(events, transcript, shots, job_dir, vision, report, cancelled)
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
            report('analyze', 0.49, 'Проверка связности истории целиком')
            # Global pass references only existing event IDs, never generated time ranges.
            decisions = global_story_review(vision, events, editorial_profile)
            apply_global_selection(events, decisions, editorial_profile)
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
                if event['id'] in keep:
                    event['importance'] = max(4, event['importance'])
                # Explicit global omissions have evidence; dependency closure
                # in the planner still restores needed earlier context.
                credits = {e['id'] for e in events if e.get('credit_montage')}
                event['requires'] = sorted(set(event['requires'] + dependency_map.get(event['id'], [])) - credits)
            atomic_json(job_dir / 'story.json', {'summary': str(decisions.get('summary', '')), 'keep': keep,
                                                  'omit': decisions.get('omit', []),
                                                  'incomplete_event_ids': decisions.get('incomplete_event_ids', []),
                                                  'cpu_fallback': vision.cpu_fallback, 'analysis_provider': provider})
            from app.speech_context import protect_speech_context
            events = protect_speech_context(events, transcript)
        atomic_json(story_checkpoint, {'signature': derived_key, 'events': events,
            'quality_state': 'degraded' if any(e.get('source_role_unresolved') for e in events) else 'complete'})
    from .pacing import refine_pacing, refine_silent_sequences, BudgetPacingVision
    with vision_session(job_dir, cancelled, pacing_provider, model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
        if pacing_provider in ('deepseek', 'deepseek_plan'):
            with BudgetPacingVision(vision, job_dir, cancelled) as paced:
                events = refine_pacing(source, events, transcript, shots, job_dir, paced, report, cancelled)
        else:
            events = refine_pacing(source, events, transcript, shots, job_dir, vision, report, cancelled)
        events = refine_silent_sequences(source, events, transcript, shots, job_dir, vision, report, cancelled)
        from .endings import refine_endings
        events = refine_endings(events, transcript, shots, probe, job_dir, vision, report, cancelled)
    if pacing_provider != provider:
        for event in events:
            if event.get('pacing_removed'):
                event.setdefault('story_warnings', []).append('Темп дополнительно проверен локально: платные запросы DeepSeek остановлены')
    from app.framing import refine_focus
    focus_provider = framing_provider(provider)
    if layout == 'portrait':
        with vision_session(job_dir, cancelled, focus_provider, model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
            events = refine_focus(source, probe, transcript, shots, events, job_dir, vision, report, cancelled)
    else:
        report('framing', 0.65, 'Сохраняем исходный кадр целиком на мягком вертикальном фоне')
    atomic_json(events_path, events)
    atomic_json(derived_meta, {'signature': focus_key,
        'quality_state': 'degraded' if any(e.get('source_role_unresolved') or e.get('pacing_degraded') or e.get('endings_degraded') for e in events) else 'complete',
        'requested_provider': provider, 'pacing_providers': sorted({p for e in events for p in e.get('pacing_providers', [])})})
    return analysis_result(job_dir, provider, probe, transcript, shots, events)
