"""Read-only counters; never changes job/inference data.

Non-feature JSON/JSONL reads are bounded to 64 MiB and two cached versions.
Feature maps are streamed (512 MiB cap); only their entry counts are cached by
path/mtime/size, up to 32 maps. Image embeddings are not retained by this reader.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

STEPS = ('prepare', 'transcribe', 'scenes', 'analyze', 'condense', 'framing', 'plan', 'render')
ALIASES = {
    'preparing': 'prepare', 'probe': 'prepare', 'audio': 'prepare',
    'transcribing': 'transcribe', 'transcript': 'transcribe', 'speech': 'transcribe',
    'shots': 'scenes', 'analyzing': 'analyze', 'analysis': 'analyze',
    'events': 'analyze', 'global_verify': 'analyze', 'focus': 'framing',
    'planning': 'plan', 'quality_gate': 'plan', 'rendering': 'render',
}
PHASES = {
    'scenes': 'Поиск смысловых сцен', 'shots': 'Поиск смены планов',
    'analyze': 'Анализ смысловых сцен', 'global_verify': 'Проверка изображения и сюжета',
    'condense': 'Сокращение с сохранением контекста', 'framing': 'Кадрирование',
    'plan': 'Составление плана', 'quality_gate': 'Проверка качества монтажа',
    'render': 'Экспорт и проверка частей',
}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FEATURE_BYTES = 512 * 1024 * 1024
ANALYSIS_PASSES = ('visual_analysis', 'story_refinement', 'titles', 'closing_novelty',
    'source_roles', 'global_visual_verification', 'selection_adjudication', 'global_story',
    'pacing', 'silent_sequences', 'final_selection_adjudication', 'endings',
    'ending_selection_adjudication', 'story_structure_analysis', 'dialogue_relations')


def analysis_passes(job, directory):
    """Separate actual passes without changing legacy stage IDs or worker state."""
    directory = Path(directory)
    result = {step: {'status': 'pending', 'fraction': 0.0} for step in ANALYSIS_PASSES}
    if job.get('status') == 'queued':
        return result
    audit = directory / 'diagnostics' / 'pipeline'
    run = _read(audit / 'run.json')
    run_id = run.get('run_id') if isinstance(run, dict) else None
    records = _current_rows(_lines(audit / 'timeline.jsonl'), run_id if isinstance(run_id, str) else None)
    current, seen, failed = None, set(), set()
    for record in records:
        step, action = record.get('stage'), record.get('action')
        if step not in result:
            continue
        seen.add(step)
        if action == 'start':
            current = step
            failed.discard(step)
            result[step] = {'status': 'running', 'fraction': None}
        elif action == 'exception':
            failed.add(step)
            result[step] = {'status': 'waiting_analysis' if record.get('error_type') == 'AnalysisPending' else 'failed', 'fraction': None}
        elif action == 'end' and step not in failed:
            result[step] = {'status': 'completed', 'fraction': 1.0}
            if current == step:
                current = None
        elif action == 'cache_hit' and step == 'story_refinement':
            for cached in ANALYSIS_PASSES[:ANALYSIS_PASSES.index('pacing')]:
                result[cached] = {'status': 'completed', 'fraction': 1.0}
    message = str(job.get('message') or '')[:2000].lower()
    stage = canonical(job.get('stage'))
    if current is None and stage in ('analyze', 'condense'):
        if 'проверка конкретного выбора' in message:
            current = 'selection_adjudication'
        elif 'обработано событий' in message or job.get('stage') == 'global_verify':
            current = 'global_visual_verification'
        elif 'темп и титры' in message:
            current = 'pacing'
        elif 'безречевую последовательность' in message:
            current = 'silent_sequences'
        elif 'сюжетную речь' in message:
            current = 'source_roles'
        elif 'новых событий в финале' in message:
            current = 'closing_novelty'
        elif any(text in message for text in ('поиск титров', 'подтверждение титра', 'подтверждённой заставкой')):
            current = 'titles'
        elif stage == 'condense':
            current = 'story_refinement'
        elif 'анализ смысловых сцен' in message or 'смысловая сцена' in message:
            current = 'visual_analysis'
    if current in result:
        # Earlier mandatory passes completed before this pass could start.
        # Conditional downstream passes need their own diagnostic evidence.
        for step in ANALYSIS_PASSES[:ANALYSIS_PASSES.index(current)]:
            if step not in seen and ANALYSIS_PASSES.index(step) <= ANALYSIS_PASSES.index('silent_sequences'):
                result[step] = {'status': 'completed', 'fraction': 1.0}
            elif step not in seen:
                result[step] = {'status': 'not_required', 'fraction': None}
        state = job.get('status')
        result[current].update(status=state if state in ('failed', 'cancelled', 'interrupted', 'waiting_analysis') else 'running', fraction=None)
        processed = re.search(r'обработано (?:событий|фрагментов):\s*(\d+)\s+из\s+(\d+)', message)
        counter = processed or re.search(r'(?:сцена|событие|фрагмент|проверка)\s+(\d+)\s+из\s+(\d+)', message)
        counter = counter or re.search(r'в финале:\s*(\d+)\s*/\s*(\d+)', message)
        relevant = {
            'visual_analysis': ('сцена',), 'story_refinement': ('сцена', 'фрагмент'),
            'titles': ('титр', 'заставк'), 'closing_novelty': ('в финале',),
            'global_visual_verification': ('независимая проверка', 'проверка изображения'),
            'selection_adjudication': ('проверка конкретного выбора',),
            'final_selection_adjudication': ('проверка конкретного выбора',),
            'ending_selection_adjudication': ('проверка конкретного выбора',),
            'pacing': ('темп',),
            'story_structure_analysis': ('сюжетные связи',),
            'dialogue_relations': ('связи реплик',)}
        if counter and any(text in message for text in relevant.get(current, ())):
            value, total = map(int, counter.groups())
            _counter(result[current], value if processed else value-1, total, '', 'обработано')
    if stage in ('framing', 'plan', 'render') or job.get('status') == 'completed':
        for step in ANALYSIS_PASSES:
            if step not in seen and result[step]['status'] == 'pending':
                result[step] = {'status': 'not_required', 'fraction': None}
    return result


def canonical(stage):
    return ALIASES.get(stage, stage) if isinstance(stage, str) else None


@lru_cache(maxsize=2)
def _json_file(path, mtime_ns, size):
    if size > MAX_FILE_BYTES:
        return None
    return json.loads(Path(path).read_text('utf-8-sig'))


def _read(path):
    try:
        stat = path.stat()
        return _json_file(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


@lru_cache(maxsize=2)
def _json_lines(path, mtime_ns, size):
    if size > MAX_FILE_BYTES:
        return ()
    rows = []
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # An append-only writer may not have finished its last row.
            if isinstance(row, dict):
                rows.append(row)
    return tuple(rows)


def _lines(path):
    try:
        stat = path.stat()
        return _json_lines(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, TypeError, UnicodeError):
        return ()


@lru_cache(maxsize=32)
def _feature_map_size(path, mtime_ns, size):
    """Count source intervals without retaining a whole map of image embeddings."""
    if size > MAX_FEATURE_BYTES:
        return None
    decoder, buffer, position, eof = json.JSONDecoder(), '', 0, False
    with Path(path).open(encoding='utf-8-sig') as stream:
        def refill():
            nonlocal buffer, position, eof
            chunk = stream.read(64 * 1024)
            buffer, position = buffer[position:] + chunk, 0
            eof = not chunk

        def token():
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position] in ' \t\r\n':
                    position += 1
                if position < len(buffer) or eof:
                    return buffer[position:position+1]
                refill()

        def value():
            nonlocal position
            token()
            while True:
                try:
                    parsed, position = decoder.raw_decode(buffer, position)
                    return parsed
                except ValueError:
                    if eof or len(buffer)-position > 8 * 1024 * 1024:
                        raise ValueError('Incomplete feature entry') from None
                    refill()

        if token() != '{':
            return None
        position += 1
        names = set()
        if token() != '}':
            while True:
                name = value()
                if not isinstance(name, str) or name in names or token() != ':':
                    return None
                names.add(name)
                position += 1
                if not isinstance(value(), dict):
                    return None
                separator = token()
                if separator == '}':
                    break
                if separator != ',':
                    return None
                position += 1
        position += 1
        return len(names) if token() == '' else None


def _feature_count(path):
    try:
        stat = path.stat()
        return _feature_map_size(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _counter(row, completed, total, phase, detail):
    if type(total) is not int or total <= 0 or type(completed) is not int:
        return
    completed = max(0, min(total, int(completed)))
    row.update(fraction=completed / total, completed=completed, total=total,
               phase=phase, detail=detail)


def _current_rows(rows, run_id):
    # Missing/corrupt run metadata cannot authorize an earlier named run.
    return [row for row in rows if row.get('run_id') == run_id]


def _render_count(directory, plan):
    parts, fingerprint = plan.get('parts'), plan.get('fingerprint')
    if (not isinstance(parts, list) or not parts or not isinstance(fingerprint, str)
            or not fingerprint or any(not isinstance(p, dict) or type(p.get('index')) is not int
                                      or p['index'] <= 0 for p in parts)
            or len({p['index'] for p in parts}) != len(parts)):
        return None
    completed = 0
    for part in parts:
        name = f"part_{part['index']:03}"
        saved = _read(directory / 'render' / f'{name}.json')
        if not isinstance(saved, dict):
            continue
        media = directory / 'output' / f'{name}.mp4'
        try:
            stat = media.stat()
            subtitle = media.with_suffix('.srt')
            valid = (stat.st_size > 0 and media.is_file() and
                     saved.get('fingerprint') == fingerprint and
                     type(saved.get('size')) is int and saved['size'] == stat.st_size and
                     type(saved.get('mtime_ns')) is int and saved['mtime_ns'] == stat.st_mtime_ns and
                     subtitle.is_file() and subtitle.stat().st_size <= MAX_FILE_BYTES and
                     saved.get('srt_hash') == hashlib.sha256(subtitle.read_bytes()).hexdigest())
        except OSError:
            valid = False
        completed += int(valid)
    return completed, len(parts)


def stage_progress(job, directory):
    """Expose only whitelisted presentation fields from this validated job directory.

    Fractions belong to the named current pass. Overall job.progress is never used.
    Progress does not assert that model decisions passed the quality gate.
    """
    directory = Path(directory)
    job = job if isinstance(job, dict) else {}
    status, stage = job.get('status'), canonical(job.get('stage'))
    result = {step: {'status': 'pending', 'fraction': 0.0} for step in STEPS}
    if status == 'completed':
        return {step: {'status': 'completed', 'fraction': 1.0} for step in STEPS}
    if status == 'queued' or job.get('stage') == 'queued' or stage not in STEPS:
        return result

    audit = directory / 'diagnostics' / 'pipeline'
    rows = _lines(audit / 'timeline.jsonl')
    # Retried jobs retain append-only diagnostics; use the current run only.
    run = _read(audit / 'run.json')
    run_id = run.get('run_id') if isinstance(run, dict) else None
    run_id = run_id if isinstance(run_id, str) and run_id else None
    rows = _current_rows(rows, run_id)
    finished, failed = set(), set()
    for record in rows:
        step = canonical(record.get('stage'))
        if step not in STEPS:
            continue
        if record.get('action') == 'start':
            finished.difference_update(STEPS[STEPS.index(step):])
            failed.discard(step)
        elif record.get('action') == 'exception':
            failed.add(step)
            finished.discard(step)
        elif record.get('action') == 'end' and step not in failed:
            finished.add(step)
    # Older jobs have no diagnostic stage events: the current milestone still
    # establishes the preceding stages, but supplies no fraction for this stage.
    if not rows:
        finished.update(STEPS[:STEPS.index(stage)])
    for step in finished:
        if step in result and step != stage:
            result[step] = {'status': 'completed', 'fraction': 1.0}

    current = result[stage]
    current.update(status=status if status in ('failed', 'cancelled', 'interrupted', 'waiting_analysis') else 'running',
                   fraction=None, phase=PHASES.get(job.get('stage'), PHASES.get(stage, '')))
    if stage == 'transcribe':
        progress = _read(directory / 'asr-progress.json')
        probe = _read(directory / 'probe.json')
        if isinstance(progress, dict) and isinstance(probe, dict):
            fraction, duration, expected = progress.get('fraction'), progress.get('duration'), probe.get('duration')
            # Never display a previous attempt's partial ASR as current work.
            if (run_id is not None and progress.get('run_id') == run_id and
                    type(fraction) in (int, float) and math.isfinite(fraction) and 0 <= fraction <= 1 and
                    type(duration) in (int, float) and type(expected) in (int, float) and
                    math.isfinite(duration) and math.isfinite(expected) and abs(duration - expected) < .1):
                current.update(fraction=fraction, phase='Проверка таймкодов речи' if progress.get('phase') == 'repair'
                    else 'Распознавание по времени исходного аудио')
    elif stage == 'scenes':
        feature_count = _feature_count(directory / 'scene-features.json')
        if type(feature_count) is int and feature_count > 1:
            # Exactly one feature row exists per interval; the detector checks
            # the edge before every interval except the first.
            total = feature_count - 1
            decisions = _lines(audit / 'boundary_decisions.jsonl')
            times = {round(row['source_time'], 6) for row in _current_rows(decisions, run_id)
                     if type(row.get('source_time')) in (int, float)
                     and math.isfinite(row['source_time']) and row['source_time'] >= 0
                     and isinstance(row.get('decision'), dict)}
            _counter(current, len(times), total, 'Проверка границ сцен', 'границ проверено')
    elif stage in ('analyze', 'condense', 'framing'):
        # These coordinator reports are issued BEFORE processing the indexed
        # item. N-1 is the work already completed, never N/total as if accepted.
        message = job.get('message', '')
        message = message if isinstance(message, str) else ''
        processed = re.search(r'обработано событий:\s*(\d+)\s+из\s+(\d+)', message, re.I)
        match = processed or re.search(r'(?:сцена|событие|кадрирование|проверка)\s+(\d+)\s+из\s+(\d+)', message, re.I)
        if match:
            completed, total = map(int, match.groups())
            # Presentation never echoes free text from a provider/log/source.
            phase = PHASES.get(stage, '')
            if stage == 'condense' and 'темп' in message.lower():
                phase = 'Проверка темпа и титров'
            _counter(current, completed if processed else completed - 1, total, phase, 'обработано')
    elif stage == 'render':
        plan = _read(directory / 'plan.json')
        counter = _render_count(directory, plan) if isinstance(plan, dict) else None
        if counter:
            # Render commits publish a validated part checkpoint before the
            # coordinator's progress report. Do not count partial MP4 files.
            _counter(current, *counter, PHASES['render'], 'частей проверено')
    return result
