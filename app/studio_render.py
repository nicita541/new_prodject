"""Safe, isolated finishing preview/export workers. No expensive AI analysis.

Exports are never written to the source job's /output and never modify its
plan, completion status or registered output files.
"""
from __future__ import annotations

import copy
from datetime import datetime
import logging
import re
from pathlib import Path

from app import config
from app.json_store import atomic_json, read_json
from app.media import inspect_media
from app.content_identity import digest
from app.artifact_publication import effective_plan
from app.caption_state import caption_record

from .finishing_execution import MAX_PENDING_FINISHING_TASKS


def stop_finishing_tasks(manager, timeout=12.0):
    execution = getattr(manager, 'finishing_execution', None)
    return execution.stop(timeout) if execution is not None else True


def slice_part(part: dict, start: float, duration: float) -> dict:
    """Convert source-clock cuts to a bounded output-clock preview."""
    requested_end = start + duration
    offset = 0.0
    cuts = []
    for original in part["cuts"]:
        length = float(original["end"]) - float(original["start"])
        a = max(start, offset)
        b = min(requested_end, offset + length)
        if b > a + 0.00001:
            cut = copy.deepcopy(original)
            cut["start"] = round(float(original["start"]) + (a - offset), 6)
            cut["end"] = round(float(original["start"]) + (b - offset), 6)
            # Focus coordinates use source time. Remove outdated anchors, while
            # preserving the last known composition at the new cut entrance.
            focus = original.get("focus", [])
            prior = [f for f in focus if f.get("time", 0) <= cut["start"]]
            inside = [f for f in focus if cut["start"] < f.get("time", 0) < cut["end"]]
            cut["focus"] = ([
                {**prior[-1], "time": cut["start"]}] if prior else []
            ) + inside
            cuts.append(cut)
        offset += length
    if not cuts:
        raise ValueError("Нет исходных кадров в выбранном интервале")
    result = copy.deepcopy(part)
    result["cuts"] = cuts
    result["duration"] = round(sum(c["end"] - c["start"] for c in cuts), 6)
    result["subtitles"] = [
        {"start": round(max(0, c["start"] - start), 6),
         "end": round(min(result["duration"], c["end"] - start), 6),
         "text": c["text"]}
        for c in part.get("subtitles", [])
        if c["start"] < requested_end and c["end"] > start
    ]
    return result


def _source(request_manager, job_id: str) -> Path:
    info = read_json(request_manager.job_dir(job_id) / "source.json", {}) or {}
    path = Path(info.get("path", "")).resolve()
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError("Исходная серия недоступна")
    if not path.is_relative_to(request_manager.root.resolve()):
        raise ValueError("Исходная серия должна находиться внутри рабочего каталога")
    return path


def _probe(source: Path, work: Path) -> dict:
    raw = inspect_media(source, work)
    video = next((v for v in raw.get("streams", []) if v.get("codec_type") == "video"), None)
    audios = [a for a in raw.get("streams", []) if a.get("codec_type") == "audio"]
    if video is None or not audios:
        raise ValueError("У исходной серии нет видео или аудио")
    # The initial ASR/montage selects the Russian-labelled audio stream.
    # Re-export MUST use the same stream; otherwise subtitles and original
    # dialogue can end up in different languages.
    ordinal = 0
    if len(audios) > 1:
        russian = [i for i, audio in enumerate(audios)
                   if str(audio.get("tags", {}).get("language", "")).lower() in ("ru", "rus")
                   or any(marker in str(audio.get("tags", {}).get("title", "")).lower()
                          for marker in ("рус", "russian"))]
        if not russian:
            raise ValueError("Несколько аудиодорожек без обозначения русской")
        ordinal = russian[0]
    return {"width": int(video["width"]), "height": int(video["height"]),
            "audio_stream": ordinal}


def _effective_part(manager, job_id: str, part: dict, profile: dict, *, plan=None) -> dict:
    result = copy.deepcopy(part)
    directory = manager.job_dir(job_id)
    plan = plan if plan is not None else (effective_plan(directory) or {})
    stored = caption_record(directory, plan, part)
    # Speech belongs to this *job*. Episode-wide legacy part_overrides.cues
    # are not attributable to any particular completed montage and must never
    # overwrite the text or timing of a different attempt.
    if stored is not None:
        result["subtitles"] = stored.get("cues", result.get("subtitles", []))
    result["layout"] = profile["video"]["layout"]
    return result


def replay_render(manager, job_id, kind, operation_id, original_request):
    """Exact POST replay repairs recorded intent, without mutable preflight."""
    if operation_id is None:
        return None
    from .finishing_commands import FinishingCommands, normalize_request, OperationConflict
    with manager.mutex:
        store = FinishingCommands(manager.root)
        receipt = store._receipt(operation_id)
        if receipt is None:
            return None
        command = store._command(receipt['command'], expected={'job_id': job_id, 'kind': kind})
        if command['request'] != normalize_request(kind, original_request):
            raise OperationConflict('operation_id уже используется с другими параметрами')
        # A crash can occur before command materialization, runtime enrollment or
        # index publication. Recover only this already-authorized exact request.
        def no_refreeze():
            raise AssertionError('Replay must not freeze current settings')
        command = store.submit(job_id, command['source_sha256'], kind, original_request,
                               no_refreeze, operation_id=operation_id)
        manager.finishing_execution.submit(command)
        _index_command(manager, command)
        return _managed_status(manager, command)


def submit_render(manager, job_id, part_indices, profile, *, preview=None,
                  operation_id=None, original_request=None):
    from .finishing_commands import FinishingCommands
    from .finishing_render import freeze_command
    kind = 'preview' if preview else 'export'
    request = original_request if original_request is not None else (
        {'part_index': preview[0], 'from': preview[1], 'duration': preview[2], 'settings': profile}
        if preview else {'part_indices': list(part_indices), 'settings': profile})
    with manager.mutex:
        repeated = replay_render(manager, job_id, kind, operation_id, request)
        if repeated is not None:
            return repeated
        if manager.closed or manager.shutdown_requested:
            raise RuntimeError('Приложение завершает работу')
        if manager.busy():
            raise RuntimeError('Нельзя запускать экспорт во время обработки серии')
        runtime = manager.finishing_execution
        runtime._capacity()
        store = FinishingCommands(manager.root)
        frozen = freeze_command(manager, job_id, list(part_indices), profile, preview=preview)
        command = store.submit(job_id, frozen['source']['sha256'], kind, request,
                               lambda: frozen, operation_id=operation_id)
        runtime.submit(command)
        _index_command(manager, command)
        return _managed_status(manager, command)


def _index_command(manager, command):
    from .finishing_commands import FinishingCommands
    store = FinishingCommands(manager.root)
    if command['kind'] == 'export':
        store._write(store._path('finishing/exports-index/'+command['task_id']+'.json'),
            {'source_job_id': command['job_id'], 'operation_id': command['operation_id']})


def _task_command(manager, identifier, job_id=None):
    from .finishing_commands import FinishingCommands, CommandError
    store = FinishingCommands(manager.root)
    if not re.fullmatch(r'(ex|pv)_[0-9a-f]{32}', identifier):
        raise KeyError(identifier)
    if identifier.startswith('ex_'):
        record = store._read(store._path('finishing/exports-index/'+identifier+'.json'))
        if not isinstance(record, dict):
            raise KeyError(identifier)
        owner = record.get('source_job_id')
        if job_id is not None and job_id != owner:
            raise CommandError('Экспорт принадлежит другому заданию')
        job_id = owner
        operation = record.get('operation_id')
    else:
        if job_id is None:
            raise CommandError('Для предпросмотра нужен ID задания')
        operation = None
    kind = 'preview' if identifier.startswith('pv_') else 'export'
    directory = store.task_directory(job_id, kind, identifier)
    saved = store._read(directory/'command.json')
    if saved is None:
        if operation is not None:
            raise CommandError('Неизменяемая команда экспорта отсутствует')
        return None
    saved = store._command(saved, expected={'job_id': job_id, 'task_id': identifier, 'kind': kind})
    if operation is not None and operation != saved['operation_id']:
        raise CommandError('Индекс экспорта не соответствует его команде')
    command = store.load(saved['operation_id'], job_id=job_id, kind=kind)
    if command != saved:
        raise CommandError('Команда не соответствует квитанции операции')
    return command


def _managed_status(manager, command):
    from .finishing_commands import FinishingCommands
    store = FinishingCommands(manager.root)
    state = manager.finishing_execution.status(command)
    state = state or {'status': 'queued', 'progress': 0, 'attempt_id': None}
    identifier, job_id = command['task_id'], command['job_id']
    preview = command['kind'] == 'preview'
    files = []
    for part in command['frozen']['plan']['parts']:
        receipt = store.part_receipt(command, part['index'], verify_bytes=False)
        if receipt is None:
            continue
        name = Path(receipt['video']['path']).name
        files.append({'part_index': part['index'], 'name': name,
            'duration': command['frozen']['preview']['duration'] if preview else part['duration'],
            'url': f'/api/jobs/{job_id}/previews/{identifier}.mp4' if preview else f'/api/exports/{identifier}/files/{name}',
            'subtitle_url': None if preview else f'/api/exports/{identifier}/files/{Path(name).stem}.srt'})
    return {**state, ('preview_id' if preview else 'export_id'): identifier,
        'operation_id': command['operation_id'], 'source_job_id': job_id,
        'source_plan_digest': command['frozen']['source_plan_digest'],
        'caption_revisions': {key: value['revision'] for key,value in command['frozen']['caption_revisions'].items()},
        'profile': copy.deepcopy(command['frozen']['profile']),
        'created_at': command['created_at'], 'files': files,
        'completed_parts': len(files), 'total_parts': len(command['request']['part_indices']),
        'resumable': state['status'] in {'interrupted', 'failed', 'cancelled'},
        'cancellable': state['status'] in {'queued', 'running'},
        'error': state.get('error'), 'url': files[0]['url'] if preview and files else None}


def list_tasks(manager, job_id):
    # Runtime has already recovered at startup. GET only projects known records.
    with manager.mutex:
        manager.get(job_id)
        results = [_managed_status(manager, command) for command in
            manager.finishing_execution.commands.values() if command['job_id'] == job_id]
        return sorted(results, key=lambda state: (state['created_at'], state['operation_id']), reverse=True)


def control_task(manager, identifier, action, job_id=None):
    with manager.mutex:
        command = _task_command(manager, identifier, job_id)
        if command is None:
            raise ValueError('Старый экспорт не содержит точной команды и не может быть возобновлён')
        runtime = manager.finishing_execution
        if action == 'resume':
            if manager.busy():
                raise RuntimeError('Дождитесь завершения обработки серии')
            runtime.resume(command['operation_id'])
        elif action == 'cancel':
            runtime.cancel(command['operation_id'])
        else:
            raise ValueError('Неизвестное действие экспорта')
        return _managed_status(manager, command)


def resolve_task_file(manager, identifier, filename, job_id=None):
    from .finishing_commands import FinishingCommands
    command = _task_command(manager, identifier, job_id)
    if command is not None:
        store = FinishingCommands(manager.root)
        for index in command['request']['part_indices']:
            if filename not in (f'part_{index:03}.mp4', f'part_{index:03}.srt'):
                continue
            receipt = store.part_receipt(command, index)
            if receipt is not None:
                return store._path(receipt['video' if filename.endswith('.mp4') else 'subtitles']['path'])
        raise KeyError(filename)
    _, directory = _locate_task(manager, identifier, job_id)
    state = read_json(directory/'status.json', {})
    allowed = {item['name'] for item in state.get('files', [])}
    allowed |= {Path(name).with_suffix('.srt').name for name in allowed}
    if state.get('status') != 'completed' or filename not in allowed:
        raise KeyError(filename)
    output = directory/'output'
    path = output/filename
    if path.resolve() != path or not path.is_file() or not path.is_relative_to(manager.root):
        raise KeyError(filename)
    return path


def recover_legacy_finishing(manager):
    # Classification occurs once at startup, never as a side effect of GET.
    from .finishing_commands import FinishingCommands
    store = FinishingCommands(manager.root)
    for command in manager.finishing_execution.commands.values():
        try:
            _index_command(manager, command)
        except (ValueError, OSError):
            logging.getLogger(__name__).exception('Finishing index recovery failed',
                extra={'operation_id': command['operation_id'], 'action': 'finishing_index_recovery_failed'})
    for path in manager.jobs.glob('*/finishing/*/*/status.json'):
        if (path.parent/'command.json').exists():
            continue
        try:
            state = store._read(path)
            if isinstance(state, dict) and state.get('status') in {'queued','running'}:
                store._write(path, {**state, 'status': 'interrupted', 'resumable': False,
                    'error': 'Старый экспорт прерван; точные параметры команды не были сохранены'})
        except (ValueError, OSError):
            logging.getLogger(__name__).warning('Skipping damaged legacy finishing status',
                extra={'job_id': path.parents[3].name, 'action': 'finishing_legacy_recovery_failed'})


def _locate_task(manager, identifier: str, job_id: str | None = None):
    if identifier.startswith("pv_"):
        if not job_id:
            raise ValueError("Для предпросмотра нужен ID задания")
        base = manager.job_dir(job_id) / "finishing" / "previews" / identifier
    else:
        record = read_json(manager.root / "finishing" / "exports-index" / (identifier + ".json"))
        if not record:
            raise KeyError(identifier)
        job_id = record["source_job_id"]
        base = manager.job_dir(job_id) / "finishing" / "exports" / identifier
    return job_id, base


def plan_digest(plan):
    return digest({'source': plan.get('source'), 'parts': [
        {k: part.get(k) for k in ('index', 'duration', 'cuts', 'subtitles')}
        for part in plan.get('parts', [])]})


def ready_outputs(manager, job_id: str, plan: dict | None = None) -> dict:
    """Latest completed owned finishing file per part; base exports stay intact."""
    folder = (manager.job_dir(job_id) / 'finishing' / 'exports').resolve()
    if not folder.is_relative_to(manager.job_dir(job_id).resolve()) or not folder.is_dir():
        return {}
    plan = plan if plan is not None else (effective_plan(manager.job_dir(job_id)) or {})
    signature = plan_digest(plan)
    parts = {p['index']: p for p in plan.get('parts', [])}
    results, ranks = {}, {}
    from .finishing_commands import FinishingCommands
    store = FinishingCommands(manager.root)
    execution = getattr(manager, 'finishing_execution', None)
    for command in execution.commands.values() if execution is not None else ():
        if (command['job_id'] != job_id or command['kind'] != 'export'
                or command['frozen']['source_plan_digest'] != signature):
            continue
        try:
            state = execution.status(command)
            if not state or state['status'] != 'completed':
                continue
            rank = int(datetime.fromisoformat(command['created_at']).timestamp()*1e9)
            for index in command['request']['part_indices']:
                if index not in parts:
                    continue
                receipt = store.part_receipt(command, index, verify_bytes=False)
                if receipt is None:
                    continue
                path = store._path(receipt['video']['path'])
                name, identifier = path.name, command['task_id']
                if rank <= ranks.get(name, -1):
                    continue
                ranks[name] = rank
                results[name] = {'part_index': index, 'name': name, 'duration': parts[index]['duration'],
                    'export_id': identifier, 'url': f'/api/exports/{identifier}/files/{name}',
                    'subtitle_url': f'/api/exports/{identifier}/files/{path.stem}.srt',
                    'video_sha256': receipt['video']['sha256'], 'srt_sha256': receipt['subtitles']['sha256'],
                    '_path': path}
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).warning('Skipping damaged managed finishing export',
                extra={'job_id': job_id, 'action': 'invalid_finishing_record'})
    for status_path in folder.glob('ex_*/status.json'):
        identifier = status_path.parent.name
        if not re.fullmatch(r'ex_[0-9a-f]{32}', identifier):
            continue
        try:
            if not status_path.resolve().is_relative_to(folder):
                continue
            registry_path = manager.root / 'finishing' / 'exports-index' / (identifier + '.json')
            if not registry_path.resolve().is_relative_to(manager.root.resolve()):
                continue
            registry = read_json(registry_path, {})
            state = read_json(status_path, {})
            if not isinstance(registry, dict) or not isinstance(state, dict):
                raise ValueError('Invalid finishing record')
            if (registry.get('source_job_id') != job_id or state.get('status') != 'completed'
                    or state.get('source_job_id') != job_id or state.get('source_plan_digest') != signature):
                continue
            rank = state.get('created_at_ns', status_path.stat().st_mtime_ns)
            if type(rank) is not int or rank < 0 or not isinstance(state.get('files'), list):
                raise ValueError('Invalid finishing file list or rank')
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).warning('Skipping invalid finishing export %s', identifier,
                extra={'job_id': job_id, 'action': 'invalid_finishing_record'})
            continue
        for item in state.get('files', []):
            if not isinstance(item, dict):
                continue
            index = item.get('part_index')
            if type(index) is not int or index not in parts or item.get('name') != f'part_{index:03}.mp4':
                continue
            name = item['name']
            output = (status_path.parent / 'output').resolve()
            path = (output / name).resolve()
            try:
                if (not path.is_relative_to(output) or not output.is_relative_to(folder)
                        or not path.is_file() or path.stat().st_size == 0 or rank <= ranks.get(name, -1)):
                    continue
                subtitle = path.with_suffix('.srt')
                has_subtitle = subtitle.resolve().is_relative_to(output) and subtitle.is_file()
            except OSError:
                continue
            ranks[name] = rank
            results[name] = {**item, 'export_id': identifier,
                'url': f'/api/exports/{identifier}/files/{name}',
                'subtitle_url': f'/api/exports/{identifier}/files/{Path(name).stem}.srt'
                    if has_subtitle else None,
                '_path': path}
    return results


def task_status(manager, identifier: str, job_id: str | None = None) -> dict:
    command = _task_command(manager, identifier, job_id)
    if command is not None:
        return _managed_status(manager, command)
    job_id, base = _locate_task(manager, identifier, job_id)
    status = read_json(base / "status.json")
    if not status:
        raise KeyError(identifier)
    files = [
        {"part_index": item["part_index"], "name": item["name"],
         "duration": item["duration"],
         "url": (f"/api/jobs/{job_id}/previews/{identifier}.mp4" if identifier.startswith("pv_")
                 else f"/api/exports/{identifier}/files/{item['name']}"),
         "subtitle_url": None if identifier.startswith("pv_")
                 else f"/api/exports/{identifier}/files/{Path(item['name']).stem}.srt"}
        for item in status.get("files", [])
    ]
    return {**status, "files": files, "resumable": False, "cancellable": False,
            "url": files[0]["url"] if files and identifier.startswith("pv_") else None}
