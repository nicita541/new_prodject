"""Cancellable, bounded waits for explicit official-provider quota resets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import time
import uuid

from .json_store import atomic_json, read_json, now

MAX_QUOTA_RETRIES = 2
RESET_MARGIN_SECONDS = 30


class QuotaRecoveryBlocked(RuntimeError):
    pass


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Invalid quota timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Quota timestamp requires timezone')
    return result.astimezone(timezone.utc)


def reset_fields(error, finished_at):
    """Parse a complete duration; rereads never move its original deadline."""
    if not isinstance(error, str) or len(error) > 16384:
        return {}
    match = re.search(r'\bresets\s+in\s+((?:\d+\s*[hms]\s*){1,3})(?:[.!]|$)', error, re.I)
    if not match:
        return {}
    parts = re.findall(r'(\d+)\s*([hms])', match[1].lower())
    order = ['hms'.index(unit) for _, unit in parts]
    if len(set(order)) != len(order) or order != sorted(order):
        return {}
    seconds = sum(int(n)*{'h':3600,'m':60,'s':1}[unit] for n,unit in parts)
    if not 0 < seconds <= 86400:
        return {}
    try:
        finished = _timestamp(finished_at)
    except (ValueError, TypeError, OverflowError):
        return {}
    reset = finished + timedelta(seconds=seconds)
    return {'quota_finished_at': finished.isoformat(), 'quota_delay_seconds': seconds,
            'quota_reset_at': reset.isoformat(),
            'quota_retry_at': (reset+timedelta(seconds=RESET_MARGIN_SECONDS)).isoformat()}


def cooldown_state(root):
    path=(Path(root)/'quota-cooldown.json').resolve()
    path.relative_to(Path(root).resolve())
    for attempt in range(25):
        try:
            value = read_json(path, {})
            break
        except PermissionError:
            if attempt == 24:
                raise QuotaRecoveryBlocked('Не удалось прочитать время ожидания лимита Antigravity') from None
            time.sleep(.05)
    if not value:
        return None
    if (not isinstance(value, dict) or value.get('code') != 'quota'
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('packet', '')))):
        raise QuotaRecoveryBlocked('Некорректное состояние ожидания лимита Antigravity')
    try:
        finished, reset, retry = map(_timestamp, (value['quota_finished_at'],
            value['quota_reset_at'], value['quota_retry_at']))
        delay = value['quota_delay_seconds']
        if (type(delay) is not int or not 0 < delay <= 86400
                or abs((reset-finished).total_seconds()-delay) > .00001
                or (retry-reset).total_seconds() != RESET_MARGIN_SECONDS):
            raise ValueError('Invalid quota duration')
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        raise QuotaRecoveryBlocked('Не подтверждено время восстановления лимита Antigravity') from error
    return value


def seed_cooldown(job_dir, failure=None):
    root = Path(job_dir)/'antigravity'
    settings = read_json(root/'automation.json', {})
    if settings.get('enabled') is not True or settings.get('managed') is not True:
        return None
    existing = cooldown_state(root)
    if failure is None and existing:
        return existing
    if failure is None:
        from .antigravity_exchange import packet_failure
        hint = read_json(root/'runner.json', {})
        identifier = hint.get('packet')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{64}', identifier):
            return None
        failure = packet_failure(root/'packets'/identifier, identifier)
    if not isinstance(failure, dict) or failure.get('code') != 'quota' or not failure.get('quota_retry_at'):
        return existing
    if existing and _timestamp(existing['quota_retry_at']) >= _timestamp(failure['quota_retry_at']):
        return existing
    atomic_json(root/'quota-cooldown.json', failure)
    return cooldown_state(root)


def _rearm(root, state):
    packet = (root/'packets'/state['packet']).resolve()
    packet.relative_to(root.resolve())
    for name in ('request.json','failure.json','quota-retry.json','result.json','agy-result.json'):
        (packet/name).resolve().relative_to(packet)
    request = read_json(packet/'request.json', {})
    if request.get('id') != state['packet']:
        raise QuotaRecoveryBlocked('Ожидание лимита относится к другому запросу')
    failure = read_json(packet/'failure.json', {})
    if failure.get('packet') != state['packet'] or failure.get('code') != 'quota':
        return
    # An accepted/published reply is never removed to make room for a retry.
    if (packet/'result.json').exists() or (packet/'agy-result.json').exists():
        return
    ticket_path = packet/'quota-retry.json'
    ticket = read_json(ticket_path, {})
    count = ticket.get('count', 0)
    if type(count) is not int or not 0 <= count < MAX_QUOTA_RETRIES:
        raise QuotaRecoveryBlocked('Лимит Antigravity повторился после двух автоматических ожиданий; ответы сохранены')
    history = (packet/'quota-history').resolve()
    history.relative_to(packet)
    history.mkdir(exist_ok=True)
    # Only the failed control marker moves; CLI attempts and request/evidence stay.
    atomic_json(ticket_path, {'count':count+1,'previous_attempt':failure.get('attempt'),
                            'retry_at':state['quota_retry_at']})
    (packet/'failure.json').rename(history/(uuid.uuid4().hex+'.json'))


def wait_for_quota(job_dir, cancelled):
    """Called by the owner, never by read APIs; retain the actual pipeline stack."""
    job_dir, root = Path(job_dir), Path(job_dir)/'antigravity'
    previous, published = None, 0.0
    try:
        while (state := cooldown_state(root)) is not None:
            if cancelled():
                raise InterruptedError('Обработка отменена')
            from .antigravity_exchange import _runner_state
            runner = _runner_state(root/'runner.json')
            if runner.get('status') == 'error':
                raise QuotaRecoveryBlocked('Автоматический обмен Antigravity остановлен; результаты сохранены')
            packet = root/'packets'/state['packet']
            count = read_json(packet/'quota-retry.json', {}).get('count',0)
            if (not (packet/'result.json').exists() and not (packet/'agy-result.json').exists()
                    and (type(count) is not int or not 0 <= count < MAX_QUOTA_RETRIES)):
                raise QuotaRecoveryBlocked('Лимит Antigravity повторился после двух автоматических ожиданий; ответы сохранены')
            remaining = (_timestamp(state['quota_retry_at'])-datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                _rearm(root, state)
                if cooldown_state(root) == state:
                    (root/'quota-cooldown.json').unlink(missing_ok=True)
                continue
            if previous is None or time.monotonic()-published >= 30:
                job = read_json(job_dir/'job.json', {})
                previous = previous or (job.get('provider_wait') or {}).get('previous_message') or job.get('message','')
                minutes = max(1, int((remaining+59)//60))
                job.update(updated_at=now(),message=f'Лимит Antigravity. Автоматическое продолжение через {minutes} мин; ответы сохранены.',
                    provider_wait={'reason':'quota','resume_at':state['quota_retry_at'],
                        'packet':state['packet'],'previous_message':previous})
                atomic_json(job_dir/'job.json', job)
                published = time.monotonic()
            time.sleep(.5)
    finally:
        job = read_json(job_dir/'job.json', {})
        if job.pop('provider_wait', None) is not None:
            if previous is not None and not cancelled():
                job['message'] = previous
            job['updated_at'] = now()
            atomic_json(job_dir/'job.json', job)
