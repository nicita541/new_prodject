"""Explicit run modes and independently copied, source-owned checkpoints."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from app.json_store import atomic_json, read_json

MODES = {'full', 'incremental', 'plan_only'}
# Never inherit job state, cancellation, diagnostics, credentials, provider
# attempts, manual exchange packets, finishing state or partial output files.
FILES = {
    'analysis.meta.json', 'preparation.meta.json', 'probe.json', 'audio.wav',
    'transcript.json', 'shots.json', 'shots.meta.json', 'shots.candidates.json',
    'scenes.json', 'scenes.meta.json', 'scene-features.json', 'scene-features.meta.json',
    'media-evidence.json', 'media-evidence.meta.json', 'story-events.json',
    'events.json', 'events.meta.json', 'story.json', 'episode_profile.json',
    'story_structure-result.json', 'dialogue_relations-result.json',
    'analysis-final.json', 'analysis-final.meta.json', 'plan.json',
    'editorial-settings.json', 'planning-preferences.json',
    'speech-handle-overrides.json',
}
DIRECTORIES = {
    'visual', 'focus', 'scene-features', 'media-evidence', 'story_refinement',
    'global_verification', 'production_sequences', 'title_units', 'closing_novelty',
    'credit_edges', 'source_roles', 'pacing', 'pacing_sequences', 'endings', 'story-structure',
    'dialogue-relations', 'selection-adjudication', 'continuity-verification',
    'part-context', 'clean', 'boundary-recovery',
}


def validate_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError('Неизвестный режим обработки')
    return mode


def load_mode(directory: Path) -> str:
    # A resumed full job reuses its own checkpoints. Full means a fresh launch.
    return validate_mode(read_json(directory / 'processing-settings.json', {}).get('mode', 'full'))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def source_digest(source: Path, cancelled=lambda: False) -> str:
    from .source_identity import source_identity
    return source_identity(source, cancelled)['sha256']


def _snapshot_provider(provider):
    """These interchangeable transports share accepted plan analysis semantics."""
    return 'cloud_story' if provider in ('deepseek_plan','antigravity_manual') else provider


def snapshot_identity(directory: Path, source: Path, analysis: dict) -> dict:
    from .editorial import load_profile
    from .editing import load_options
    from .analysis_provider import analysis_provider
    settings = read_json(directory/'analysis-settings.json', {})
    check_policy = ({'economy_mode': read_json(directory/'analysis-settings.json', {}).get('economy_mode', True)}
                    if 'check_policy' in analysis else {})
    from .confirmed_selection import enabled,identity as selection_identity
    selection_policy = ({'selection_policy':selection_identity(directory)}
                        if analysis.get('selection_scope') or enabled(directory) else {})
    return {**check_policy, **selection_policy, 'version': 1, 'source_sha256': source_digest(source),
            'analysis_sha256': _digest(analysis), 'provider': _snapshot_provider(analysis_provider(directory)),
            'layout': load_options(directory)['layout'], 'editorial_profile': load_profile(directory),
            'transcript_settings': {key: settings[key] for key in
                                    ('transcript_mode', 'transcript_source_sha256') if key in settings},
            'transcript_checkpoint_sha256': _digest(read_json(directory/'transcript.json'))}


def save_snapshot(directory: Path, source: Path, analysis: dict):
    atomic_json(directory / 'analysis-final.json', analysis)
    atomic_json(directory / 'analysis-final.meta.json', snapshot_identity(directory, source, analysis))


def preparation_identity(source_sha256: str, probe: dict, settings: dict) -> dict:
    from .config import ASR_MODEL, FFMPEG, ROOT
    tool_stat = FFMPEG.stat() if FFMPEG.is_file() else None
    audio = {'source': source_sha256, 'audio_stream': probe.get('audio_stream', 0),
             'extraction': 'mono-pcm16-16000-v1',
             'ffmpeg': [tool_stat.st_size, tool_stat.st_mtime_ns] if tool_stat else None}
    transcript = {'audio': audio, 'mode': settings.get('transcript_mode', 'automatic')}
    if transcript['mode'] != 'provided':
        transcript.update(code=hashlib.sha256((ROOT/'app'/'inference.py').read_bytes()).hexdigest(),
                          model={p.name: [p.stat().st_size, p.stat().st_mtime_ns]
                                 for p in ASR_MODEL.iterdir() if p.is_file()} if ASR_MODEL.is_dir() else {})
    return {'audio': audio, 'transcript': transcript}


def cached_analysis(directory: Path, source: Path) -> dict:
    try:
        analysis = read_json(directory / 'analysis-final.json')
        if not isinstance(analysis, dict) or not all(k in analysis for k in ('probe', 'transcript', 'shots', 'events')):
            raise ValueError()
        expected = snapshot_identity(directory, source, analysis)
        saved = read_json(directory / 'analysis-final.meta.json')
        if saved is None:
            # Old completed jobs predate snapshot manifests. Still bind their
            # actual source bytes and provider/layout to the inherited settings.
            meta = read_json(directory / 'analysis.meta.json', {})
            if (analysis.get('selection_scope') or meta.get('source') != expected['source_sha256']
                    or _snapshot_provider(analysis.get('provider')) != expected['provider']):
                raise ValueError()
        elif (not isinstance(saved,dict)
                or {**saved,'provider':_snapshot_provider(saved.get('provider'))} != expected):
            raise ValueError()
        from .planner import validate_analysis
        validate_analysis(analysis)
        preferences = read_json(directory/'planning-preferences.json')
        if preferences is not None:
            if (not isinstance(preferences, dict) or set(preferences) != {'preferred_part_count'}
                    or type(preferences['preferred_part_count']) is not int
                    or not 1 <= preferences['preferred_part_count'] <= 64):
                raise ValueError()
            analysis['preferred_part_count'] = preferences['preferred_part_count']
        return analysis
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError('Нет подходящего сохранённого анализа. Запустите «Обновить по изменениям» или «Полный монтаж».') from None


def inherit_checkpoints(previous: Path, destination: Path, *, plan_only=False) -> list[str]:
    previous, destination = previous.resolve(), destination.resolve()
    if previous == destination or previous.parent != destination.parent:
        raise ValueError('Контрольные точки должны принадлежать разным заданиям одного хранилища')
    copied = []

    def copy(path: Path):
        relative = path.relative_to(previous)
        path.resolve().relative_to(previous)
        target = destination / relative
        target.resolve().relative_to(destination)
        if path.is_symlink() or path.is_junction():
            raise ValueError('Ссылка в контрольных точках недопустима')
        if '.partial.' in path.name or path.name.endswith('.tmp'):
            return
        if path.is_dir():
            for child in path.iterdir():
                copy(child)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(relative.as_posix())

    # Keep upstream model checkpoints even for a plan-only job: a subsequent
    # incremental run must not lose the caches from its analysis lineage.
    directories = DIRECTORIES - {'clean', 'part-context'} if plan_only else DIRECTORIES
    for name in sorted(FILES | directories):
        path = previous / name
        if path.exists():
            copy(path)
    if not plan_only:
        for folder, pattern in (('output', 'part_*.*'), ('render', 'part_*.json')):
            for path in sorted((previous / folder).glob(pattern)):
                if path.is_file() and path.suffix in {'.mp4', '.srt', '.json'}:
                    copy(path)
        path = previous / 'output' / 'plan.json'
        if path.is_file():
            copy(path)
    return copied
