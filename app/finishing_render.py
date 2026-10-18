"""Freeze finishing inputs once; execute only their immutable command later."""
from __future__ import annotations

import copy
from pathlib import Path

from . import config
from .artifact_publication import current_revision, effective_plan
from .caption_state import caption_record
from .content_identity import digest, file_sha256
from .finishing_commands import CommandError, FinishingCommands
from .json_store import read_json


def render_contract():
    """Fail closed on changed executable/render dependencies before resuming."""
    from .subtitles import _speech_font
    modules = ('finishing_render', 'studio_render', 'media', 'subtitles',
               'finishing_avatar', 'social_frame', 'audio_analysis', 'config')
    facts = {'code': {name: file_sha256(Path(__file__).parent/(name+'.py')) for name in modules},
             'tools': [file_sha256(path) for path in (config.FFMPEG, config.FFPROBE)],
             'font': file_sha256(Path(_speech_font().path))}
    return {'version': 1, 'code_sha256': digest(facts)}


def freeze_command(manager, job_id, indices, profile, *, preview=None):
    """Caller holds manager.mutex, shared with caption and plan submissions."""
    from .studio_render import _source, _effective_part, _probe, plan_digest, slice_part
    from .finishing_avatar import resolve_avatar
    from .finishing import FinishProfile
    from .music import list_tracks, pick_track_for_part
    store = FinishingCommands(manager.root)
    directory = manager.job_dir(job_id)
    source = _source(manager, job_id)
    source_sha = file_sha256(source)
    plan = effective_plan(directory)
    if not isinstance(plan, dict):
        raise CommandError('Монтажный план недоступен')
    by_index = {part['index']: part for part in plan.get('parts', [])}
    if any(index not in by_index for index in indices):
        raise CommandError('Некорректные номера частей')
    # Probe original bytes once. Preserve the initial montage's selected stream,
    # including explicitly chosen non-Russian streams; do not select anew later.
    saved_probe = read_json(directory/'probe.json', {})
    if isinstance(saved_probe, dict) and 'audio_stream' in saved_probe:
        from .media import inspect_media
        raw = inspect_media(source, directory/'finishing'/'source-probe')
        videos = [row for row in raw.get('streams', []) if row.get('codec_type') == 'video']
        audios = [row for row in raw.get('streams', []) if row.get('codec_type') == 'audio']
        ordinal = saved_probe['audio_stream']
        if not videos or type(ordinal) is not int or not 0 <= ordinal < len(audios):
            raise CommandError('Исходная выбранная аудиодорожка недоступна')
        probe = {'width': int(videos[0]['width']), 'height': int(videos[0]['height']), 'audio_stream': ordinal}
    else:
        probe = _probe(source, directory/'finishing'/'source-probe')
    # Direct and HTTP callers must freeze identical typed defaults (e.g. 50 and
    # 50.0), otherwise unchanged styling needlessly invalidates media reuse.
    profile = FinishProfile.model_validate(profile).model_dump()
    selected = [_effective_part(manager, job_id, by_index[index], profile, plan=plan) for index in indices]
    frozen_plan = copy.deepcopy(plan)
    frozen_plan['parts'] = selected
    revisions = {str(index): {key: caption_record(directory, plan, by_index[index])[key]
                              for key in ('target_id', 'revision')} for index in indices}
    assets, music = [], {}

    def asset(path, role):
        relative = store._relative(path)
        sha = file_sha256(store._path(relative))
        if not any(row['path'] == relative for row in assets):
            assets.append({'role': role, 'path': relative, 'sha256': sha})
        return sha

    avatar = resolve_avatar(manager.root, profile['video'])
    if avatar:
        asset(avatar, 'avatar')
    music_dir = manager.root/'music'
    audio = profile['audio']
    available = {path.name for path in list_tracks(music_dir)}
    special = {'none', '__none__', 'off', 'без музыки', 'random', '__random__', 'случайный', ''}
    for part in selected:
        render_part = slice_part(part, preview[1], preview[2]) if preview else part
        index = part['index']
        chosen = (audio.get('part_tracks', {}).get(str(index)) if audio.get('mode') == 'per_part'
                  else audio.get('track') if audio.get('mode') == 'single' else None)
        if audio['enabled'] and chosen and chosen not in special and chosen not in available:
            raise CommandError('Выбранный музыкальный трек больше недоступен')
        track = pick_track_for_part(music_dir, audio, index, len(selected))
        music[str(index)] = None if track is None else {
            'asset_sha256': asset(track, 'music'), 'volume': audio['volume'],
            'fade_in': audio['fade_in'] > 0, 'fade_out': audio['fade_out'] > 0,
            'fade_in_seconds': audio['fade_in'], 'fade_out_seconds': audio['fade_out'],
            'duck_intervals': [(cue['start'], cue['end']) for cue in render_part['subtitles']]
                if audio.get('ducking') else [], 'volume_music_duck': min(audio['volume'], .02)}
    publication = current_revision(directory, verify_artifacts=False)
    frozen = {'source': {'path': store._relative(source), 'sha256': source_sha},
        'plan': frozen_plan, 'source_plan_digest': plan_digest(plan),
        'publication_revision': publication['revision_id'] if publication else None,
        'probe': probe, 'audio_stream': probe['audio_stream'], 'profile': profile,
        'preview': None if preview is None else {'part_index': preview[0], 'from': preview[1], 'duration': preview[2]},
        'caption_revisions': revisions, 'assets': assets, 'resolved_music': music,
        'render_contract': render_contract()}
    if file_sha256(source) != source_sha:
        raise CommandError('Исходное видео изменилось во время подготовки экспорта')
    return frozen


def validate_command(root, command):
    store = FinishingCommands(root)
    store.verify_assets(command)
    if command['frozen']['render_contract'] != render_contract():
        raise CommandError('Рендерер изменился. Создайте новый экспорт с текущими настройками')


def _reuse_part(store, command, attempt_id, index):
    # References stay inside this job's lifetime: deleting the job retires all
    # its commands together. No per-attempt media cleanup is allowed underneath.
    directory = store.task_directory(command['job_id'], 'export', command['task_id'])
    for path in sorted(directory.parent.glob('*/command.json'), reverse=True):
        try:
            origin = store._read(path)
            origin = store._command(origin)
            if (origin['operation_id'] != command['operation_id'] and origin['kind'] == 'export'
                    and index in origin['request']['part_indices']
                    and store.presentation_identity(command, index) == store.presentation_identity(origin, index)
                    and store.part_receipt(origin, index) is not None):
                store.reference_part(command, attempt_id, index, origin, index)
                return True
        except (CommandError, OSError, ValueError):
            # A corrupt old cache never approves a new file or destroys it.
            continue
    return False


def render_command(root, operation_id, attempt_id, report, cancelled):
    """No current job/profile/caption/music/avatar lookup or model acquisition."""
    from .media import choose_encoder, render_part
    from .studio_render import slice_part
    store = FinishingCommands(root)
    command = store.load(operation_id)
    if command is None:
        raise CommandError('Неизвестная операция экспорта')
    validate_command(root, command)
    frozen = command['frozen']
    directory = store.task_directory(command['job_id'], command['kind'], command['task_id'])
    attempt = store._owned(directory/'attempts'/attempt_id)
    store.update_attempt(command, attempt_id, status='running', progress=0)
    source = store._path(frozen['source']['path'])
    avatars = [asset for asset in frozen['assets'] if asset['role'] == 'avatar']
    music_assets = {asset['sha256']: asset for asset in frozen['assets'] if asset['role'] == 'music'}
    encoder = None
    parts = frozen['plan']['parts']
    for position, original in enumerate(parts):
        if cancelled():
            raise InterruptedError('Экспорт отменён')
        index = original['index']
        if (store.part_receipt(command, index) is not None
                or command['kind'] == 'export' and _reuse_part(store, command, attempt_id, index)):
            report('reusing', (position+1)/len(parts), 'Используем проверенную готовую часть')
            continue
        part = copy.deepcopy(original)
        if frozen['preview']:
            part = slice_part(part, frozen['preview']['from'], frozen['preview']['duration'])
        style = {**frozen['profile']['subtitles'], **(
            frozen['profile'].get('part_overrides', {}).get(str(index), {}).get('style') or {})}
        music = copy.deepcopy(frozen['resolved_music'][str(index)])
        if music:
            music['path'] = store._path(music_assets[music.pop('asset_sha256')]['path'])
        if encoder is None:
            encoder = choose_encoder(store._owned(attempt/'encoder'), cancelled)
        receipt = []

        def progress(fraction):
            if cancelled():
                raise InterruptedError('Экспорт отменён')
            total = min(.999, (position+fraction)/len(parts))
            store.update_attempt(command, attempt_id, status='running', progress=total)
            report('rendering', total, 'Создаём видео из сохранённой команды')

        output = store._owned(attempt/'output')
        video = render_part(source, part, frozen['probe'], output,
            store._owned(attempt/f'work_{index}'), encoder, cancelled,
            background_music=music, finishing={'subtitles': style, 'video': frozen['profile']['video'],
                'avatar_path': store._path(avatars[0]['path']) if avatars else None},
            on_progress=progress, on_validated=receipt.append)
        if len(receipt) != 1:
            raise CommandError('Рендерер не предоставил квитанцию полного декодирования')
        # Inputs are owned paths, not OS-enforced immutable files. Ordinary
        # replacement during FFmpeg execution must not receive the old identity.
        validate_command(root, command)
        store.commit_part(command, attempt_id, index, video=store._relative(video),
            subtitles=store._relative(video.with_suffix('.srt')), validation=receipt[0])
        report('rendering', (position+1)/len(parts), 'Часть проверена и сохранена')
    if cancelled():
        raise InterruptedError('Экспорт отменён')
    validate_command(root, command)
    store.update_attempt(command, attempt_id, status='completed', progress=1)
    report('completed', 1, 'Экспорт готов')
