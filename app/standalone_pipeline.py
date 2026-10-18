"""Candidate-scoped execution and atomic publication for independent stories.

The aggregate plan is a ranked collection, never an episode timeline. Each
native one-part plan is validated against its own immutable source projection.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from .cancellation import check_cancelled
from .content_identity import digest, file_sha256
from .execution_context import scope
from .json_store import atomic_json, read_json


def _candidate_summary(candidate):
    return {key: copy.deepcopy(value) for key, value in candidate.items()
            if key not in ('plan', 'scoped_analysis')}


def _appearance(job_dir):
    from .config import ROOT
    from .finishing_profile import load_video_finish
    record = read_json(job_dir/'job.json', {})
    owner = record.get('episode_id')
    video = load_video_finish(ROOT, owner) if owner else {}
    finishing = None
    if video.get('frame_style') == 'social':
        from .finishing_avatar import resolve_avatar
        finishing = {'video': video, 'avatar_path': resolve_avatar(ROOT, video, owner)}
    return video, finishing


def run_standalone(job_dir, source, source_info, analysis, objective, options,
                   music_config, music_sources, processing_mode, report, cancelled, timings,
                   *, render_backend):
    from .analysis_continuation import StageJournal
    from .artifact_publication import current_revision, publish_revision
    from .config import ROOT, MUSIC
    from .editorial import load_profile
    from .final_quality import inspect_final_quality
    from .media import EXPORT_VALIDATION_VERSION
    from .music import pick_track_for_part
    from .pipeline_diagnostics import Diagnostics
    from .planner import validate_plan
    from .processing import save_snapshot, source_digest
    from .render_ancestry import inherited_render
    from .semantic_identity import scoped_identity
    from .standalone_planner import build_standalone_candidates
    from .subtitles import make_cues, remap_words, style_identity

    check_cancelled(cancelled)
    started = time.perf_counter()
    diagnostics = Diagnostics(job_dir)
    source_sha = source_digest(source, cancelled)
    journal = StageJournal(job_dir, source_sha, analysis['transcript'], analysis['shots'],
        load_profile(job_dir), diagnostics, report, cancelled)
    source_analysis = analysis
    if analysis.get('analysis_contract') == 'standalone_source_v2':
        from .analysis_provider import analysis_provider
        from .candidate_analysis import qualify_candidates
        analysis = qualify_candidates(source, analysis, objective['settings'], job_dir,
            analysis_provider(job_dir), report, cancelled, journal,
            allow_new=processing_mode != 'plan_only', measure_audio=True)
    inputs = {'analysis': analysis, 'settings': objective['settings'],
              'compiler': scoped_identity('standalone')}
    report('planning', .67, 'Выбираем самостоятельные истории и проверяем каждую отдельно')
    compiled = journal.run('standalone_candidates', inputs,
        lambda: build_standalone_candidates(analysis, objective['settings']), 'deterministic_compiler')
    # Revalidate materialized results, including cache hits, before any export.
    for candidate in compiled['candidates']:
        check_cancelled(cancelled)
        native, scoped = candidate['plan'], candidate['scoped_analysis']
        if candidate.get('export_eligible') is not True or native.get('export_eligible') is not True:
            raise ValueError('Кандидат не разрешён для экспорта')
        validate_plan(native, scoped)
        if inspect_final_quality(scoped, native)['status'] != 'passed':
            raise ValueError('Сохранённый кандидат не прошёл проверку исходных доказательств')
        part = native['parts'][0]
        part.update(options)
        if options['caption_style'] == 'accent':
            part['subtitles'] = make_cues(remap_words(scoped['transcript']['words'], part['cuts']), 'accent')
        native['editing'] = options
        native['source']['name'] = source_info.get('name', source.name)

    framing_failures = []
    if analysis.get('analysis_contract') in ('standalone_selective_v1', 'standalone_candidate_proved_v1'):
        from .analysis_provider import analysis_provider
        from .candidate_framing import frame_final_candidates
        allow_framing = processing_mode != 'plan_only'
        framed = []
        for candidate in compiled['candidates']:
            check_cancelled(cancelled)
            try:
                result = frame_final_candidates(source, {**compiled, 'candidates': [candidate]}, job_dir,
                    analysis_provider(job_dir), report, cancelled, journal=journal,
                    layout=options['layout'], allow_new_session=allow_framing)
                framed.extend(result['candidates'])
            except InterruptedError:
                raise
            except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                # Focus is optional presentation. The independently approved
                # story remains usable with its original full picture/audio.
                allow_framing = False
                candidate = copy.deepcopy(candidate)
                for part in candidate['plan']['parts']:
                    part.update(layout='cinema', framing_fallback={'reason': 'technical_focus_failure'})
                candidate['plan'].setdefault('warnings', []).append(
                    'Не удалось проверить кадрирование: сохранён исходный кадр целиком (cinema).')
                framing_failures.append({'stage': 'candidate_framing', 'candidate_id': candidate['id'],
                    'reason': 'technical_focus_failure', 'error_type': type(error).__name__,
                    'message': 'Ошибка кадрирования; использован исходный кадр целиком', 'fallback': 'cinema'})
                framed.append(candidate)
        compiled['candidates'] = framed
        for candidate in compiled['candidates']:
            validate_plan(candidate['plan'], candidate['scoped_analysis'])
            if inspect_final_quality(candidate['scoped_analysis'], candidate['plan'])['status'] != 'passed':
                raise ValueError('Кандидат не прошёл проверку после финального кадрирования')

    outcome = {'version': 1, 'objective': objective['objective'], 'accepted': [],
               'drafts': [_candidate_summary(d) for d in compiled['drafts']], 'declined': copy.deepcopy(compiled['declined']),
               'technical_failures': [*copy.deepcopy(analysis.get('analysis_technical_failures', [])), *framing_failures]}
    plan = {'schema_version': 1, 'objective': objective['objective'], 'standalone': True,
            'source': {**{k: analysis['probe'][k] for k in ('duration', 'width', 'height')},
                       'name': source_info.get('name', source.name), 'sha256': source_sha},
            'parts': [], 'events': copy.deepcopy(analysis['events']), 'selected_event_ids': [],
            'candidate_plans': {}, 'editing': options, 'warnings': [], 'outcome': outcome}
    for candidate in compiled['candidates']:
        part = copy.deepcopy(candidate['plan']['parts'][0])
        part.update(index=candidate['rank'], candidate_id=candidate['id'])
        plan['parts'].append(part)
        plan['candidate_plans'][candidate['id']] = copy.deepcopy(candidate['plan'])
        plan['selected_event_ids'].extend(e for e in candidate['plan']['selected_event_ids']
                                          if e not in plan['selected_event_ids'])
    if analysis.get('analysis_contract') == 'standalone_candidate_proved_v1':
        # Source-only discovery deliberately has no semantic events. Publish
        # the actual physical owners used by native candidate plans so timeline
        # readers never receive dangling selected_event_ids.
        from .source_ranges import merge_ranges
        owners = {}
        for candidate in compiled['candidates']:
            for event in candidate['plan']['events']:
                if event['id'] not in owners:
                    owners[event['id']] = copy.deepcopy(event)
                else:
                    owners[event['id']]['selected_ranges'] = merge_ranges([
                        *owners[event['id']].get('selected_ranges', []), *event.get('selected_ranges', [])])
        plan['events'] = sorted(owners.values(), key=lambda event: (event['start'], event['id']))
    plan['fingerprint'] = digest({'source': source_sha, 'objective': objective,
        'compiler': inputs['compiler'], 'candidates': plan['candidate_plans'], 'editing': options})
    plan['warnings'] = [warning for candidate in compiled['candidates']
                        for warning in candidate['plan'].get('warnings', [])]
    # Discovery stays reusable when edit preferences change. The independently
    # qualified edits have their own journal and candidate-analysis artifact.
    save_snapshot(job_dir, source, source_analysis)
    timings['stages_seconds']['planning'] = round(time.perf_counter()-started, 6)
    if processing_mode == 'plan_only':
        plan['processing_mode'] = processing_mode
        plan['analysis_reused_from'] = read_json(job_dir/'processing-settings.json', {}).get('reuse_job_id')
        outcome['status'] = 'planned' if plan['parts'] else 'needs_review'
        outcome['planned'] = [_candidate_summary(c) for c in compiled['candidates']]
        atomic_json(job_dir/'plan.json', plan)
        atomic_json(job_dir/'standalone-outcome.json', outcome)
        report('completed', 1., f"План готов: {len(plan['parts'])} отдельных историй. Видео не экспортировалось.")
        return []

    video_finish, finishing = _appearance(job_dir)
    render_inputs = {'source': {'sha256': source_sha}, 'probe': analysis['probe'],
        'appearance': video_finish if finishing else None, 'renderer_version': 6,
        'avatar_sha256': (file_sha256(finishing['avatar_path'], cancelled)
                          if finishing and finishing.get('avatar_path') else None),
        'code': {name: file_sha256(ROOT/'app'/(name+'.py')) for name in
                 ('media', 'clean_parts', 'social_frame', 'finishing_avatar', 'audio_analysis')},
        'subtitle_style': style_identity(options['caption_style']),
        'music': {key: value for key, value in music_config.items()
                  if key not in ('part_tracks', 'track', 'mode', 'seed')}, 'music_sources': music_sources}
    artifacts, successful = [], []
    encoder = None
    rendering_started = time.perf_counter()
    timings['render_workers'] = 1
    for candidate in compiled['candidates']:
        check_cancelled(cancelled)
        ident, rank = candidate['id'], candidate['rank']
        part = candidate['plan']['parts'][0]  # native index 1; rank never alters its media cache
        scoped = candidate['scoped_analysis']
        track = pick_track_for_part(MUSIC, music_config, rank, len(compiled['candidates']))
        fingerprint = render_backend.fingerprint(part, render_inputs, track, scoped['transcript'])
        # FFmpeg's Windows cwd cannot exceed the legacy process path limit.
        # The complete fingerprint remains in the verified checkpoint; a
        # compact private directory does not weaken cache/artifact validation.
        folder = job_dir/'candidate-renders'/ident/fingerprint[:24]
        output_dir, workdir = folder/'output', folder/'render'
        output_dir.mkdir(parents=True, exist_ok=True)
        path, checkpoint = output_dir/'part_001.mp4', workdir/'part_001.json'
        local_started = time.perf_counter()
        with scope(stage='rendering', candidate_id=ident):
            try:
                saved = render_backend.cached(path, checkpoint, fingerprint, part, workdir, cancelled)
                inherited = None if saved is not None else inherited_render(job_dir, fingerprint, cancelled)
                if inherited is not None:
                    saved = inherited
                cache_hit = saved is not None
                if saved is None:
                    if encoder is None:
                        encoder = render_backend.choose_encoder(job_dir/'render', cancelled)
                    background_music = None
                    if track is not None:
                        from .audio_analysis import detect_transcript_music_intervals, map_cuts_to_part_duck_intervals
                        ducking = (map_cuts_to_part_duck_intervals(part['cuts'], detect_transcript_music_intervals(scoped['transcript']))
                                   if music_config.get('smart_ducking', True) else [])
                        background_music = {'path': track, 'volume': music_config['volume'],
                            'volume_music_duck': music_config.get('volume_music_duck', .015),
                            'duck_intervals': ducking, 'fade_in': music_config.get('fade_in', True),
                            'fade_out': music_config.get('fade_out', True)}
                    clean_source, clean_part, clean_probe, _ = render_backend.prepare_clean_part(
                        source, part, analysis['probe'], job_dir, cancelled)
                    path = render_backend.render_part(clean_source, clean_part, clean_probe, output_dir,
                        workdir/'part_001', encoder, cancelled, background_music=background_music, finishing=finishing)
                    metadata = read_json(workdir/'part_001'/'render-info.json', {})
                    saved = {'fingerprint': fingerprint, 'size': path.stat().st_size,
                        'mtime_ns': path.stat().st_mtime_ns, 'encoder': metadata.get('encoder'),
                        'requested_encoder': encoder, 'run_id': timings['run_id'],
                        'music_track': track.name if track else None, 'video_sha256': file_sha256(path, cancelled),
                        'full_decode_version': EXPORT_VALIDATION_VERSION,
                        'srt_hash': file_sha256(path.with_suffix('.srt'), cancelled)}
                    atomic_json(checkpoint, saved)
                successful.append(rank)
                artifacts.append({**({'reference': inherited['reference']} if inherited is not None else
                                    {'video': path, 'subtitles': path.with_suffix('.srt')}),
                    'candidate_id': ident, 'output_index': rank,
                    'full_decode_version': saved['full_decode_version']})
                outcome['accepted'].append({**_candidate_summary(candidate),
                    'output_index': rank, 'filename': f'part_{rank:03}.mp4'})
                target = next(p for p in plan['parts'] if p['index'] == rank)
                target.update(music_track=saved.get('music_track'), render_fingerprint=fingerprint)
                timings['parts'].append({'index': rank, 'candidate_id': ident, 'cached': cache_hit,
                    'encoder': saved.get('encoder'), 'seconds': round(time.perf_counter()-local_started, 6)})
            except InterruptedError:
                raise
            except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                outcome['technical_failures'].append({'candidate_id': ident, 'output_index': rank,
                    'error_type': type(error).__name__, 'error': str(error), 'export_eligible': False})
                diagnostics.event('rendering', 'candidate_failed', candidate_id=ident, error_type=type(error).__name__)
        report('rendering', .7+.28*rank/max(len(compiled['candidates']), 1),
               f"Проверено историй: {rank}; готово: {len(artifacts)}")
    if not compiled['candidates'] and compiled['drafts']:
        from .standalone_drafts import render_drafts
        outcome['drafts'], draft_failures = render_drafts(compiled['drafts'], analysis, source, source_sha,
            job_dir, report, cancelled, timings, render_backend)
        outcome['technical_failures'].extend(draft_failures)
    timings['stages_seconds']['rendering'] = round(time.perf_counter()-rendering_started, 6)
    plan['parts'] = [p for p in plan['parts'] if p['index'] in successful]
    plan['candidate_plans'] = {p['candidate_id']: plan['candidate_plans'][p['candidate_id']] for p in plan['parts']}
    plan['selected_event_ids'] = list(dict.fromkeys(e for p in plan['candidate_plans'].values() for e in p['selected_event_ids']))
    outcome['status'] = ('partial' if outcome['technical_failures'] else 'ready') if artifacts else (
        'failed' if outcome['technical_failures'] else 'needs_review')
    # A failed attempt cannot replace the current publication. The separate
    # attempt record still exposes its declines/drafts/failures for review.
    atomic_json(job_dir/'standalone-outcome.json', outcome)
    atomic_json(job_dir/'plan.json', plan)
    if artifacts:
        if source_digest(source, cancelled, refresh=True) != source_sha:
            raise ValueError('Исходная серия изменилась во время обработки')
        published = publish_revision(job_dir, plan, artifacts, producer_id=job_dir.name,
            attempt_id=timings['run_id'], cancelled=cancelled)
        diagnostics.summary(parts=len(artifacts), declined_candidates=len(outcome['declined']),
            draft_candidates=len(outcome['drafts']), failed_candidates=len(outcome['technical_failures']))
        report('completed', 1., f"Готово самостоятельных историй: {len(artifacts)}; черновых предложений: {len(outcome['drafts'])}.")
        return published['outputs']
    if outcome['technical_failures']:
        raise RuntimeError('Обработка отдельных историй завершилась технической ошибкой; предыдущая публикация сохранена')
    # Analysis completed but approved media does not exist; an explicit outcome
    # distinguishes this from successful export and keeps drafts non-exportable.
    previous = current_revision(job_dir, verify_artifacts=False, cancelled=cancelled)
    report('completed', 1., 'Нет подтверждённых самостоятельных историй. Предложения требуют проверки монтажа.')
    return previous['outputs'] if previous is not None else []
