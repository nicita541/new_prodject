"""Provider balance observations, independent of conservative billing guards."""
from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path

from .config import ROOT
from .jobs import BusyError, InstanceLock, atomic_json

REFRESH_SECONDS = 30


def _path():
    from .deepseek import LEDGER
    path = LEDGER.with_name('deepseek-balances.json').resolve()
    path.relative_to(ROOT.resolve())
    return path


def _read():
    from .deepseek import RemoteError
    path = _path()
    if not path.exists():
        return {'version': 1, 'windows': {}}
    try:
        value = json.loads(path.read_text('utf-8'))
        if value.get('version') != 1 or not isinstance(value.get('windows'), dict):
            raise ValueError()
        return value
    except (OSError, ValueError, AttributeError):
        raise RemoteError('История проверок баланса недоступна') from None


def _snapshot(raw, measured_at):
    from .deepseek import _decimal, RemoteError
    try:
        usd = next(item for item in raw['balance_infos'] if item['currency'] == 'USD')
        if type(raw['is_available']) is not bool:
            raise ValueError()
        return {'balance_usd': str(_decimal(usd['total_balance'])),
                'granted_usd': str(_decimal(usd['granted_balance'])) if 'granted_balance' in usd else None,
                'topped_up_usd': str(_decimal(usd['topped_up_balance'])) if 'topped_up_balance' in usd else None,
                'available': raw['is_available'], 'measured_at': measured_at}
    except (KeyError, TypeError, StopIteration, ValueError):
        raise RemoteError('DeepSeek не подтвердил долларовый баланс') from None


def _changed_funds(previous, current):
    return any(previous.get(k) is not None and current.get(k) is not None
               and Decimal(current[k]) > Decimal(previous[k])
               for k in ('balance_usd', 'granted_usd', 'topped_up_usd'))


def _window_key(job_dir, attempt):
    from .deepseek import job_key
    return f'{job_key(job_dir)}:{attempt}'


def _store(value, snapshot, job_dir=None, attempt=None, first_request=False):
    previous = value.get('latest')
    # A slow older response must not overwrite a newer observation.
    if previous and previous['measured_at'] > snapshot['measured_at']:
        return
    value.setdefault('start', snapshot)
    value['adjusted'] = value.get('adjusted', False) or bool(previous and _changed_funds(previous, snapshot))
    value['latest'] = snapshot
    value.pop('error', None)
    if job_dir is not None:
        key = _window_key(job_dir, attempt)
        window = value['windows'].get(key)
        if window is None or (first_request and window.get('coverage') != 'full_attempt'):
            window = {'start': snapshot, 'coverage': 'full_attempt' if first_request else 'since_observation'}
        window['adjusted'] = window.get('adjusted', False) or bool(window.get('latest') and _changed_funds(window['latest'], snapshot))
        window['latest'] = snapshot
        value['windows'][key] = window
    atomic_json(_path(), value)


def record(raw, job_dir=None, attempt=None, first_request=False, measured_at=None):
    """Record existing provider responses; never fetch or touch the paid ledger."""
    lock = InstanceLock(_path().with_suffix('.lock'))
    try:
        _store(_read(), _snapshot(raw, time.time() if measured_at is None else measured_at),
               job_dir, attempt, first_request)
    finally:
        lock.close()


def _decrease(window):
    if not window or window.get('adjusted'):
        return None
    value = Decimal(window['start']['balance_usd']) - Decimal(window['latest']['balance_usd'])
    return str(value) if value >= 0 else None


def status(job_dir=None, attempt=None):
    value = _read()
    latest = value.get('latest', {})
    window = value['windows'].get(_window_key(job_dir, attempt)) if job_dir is not None else None
    return {'source': 'deepseek_user_balance', 'scope': 'account',
            'attempt': attempt,
            'balance_usd': latest.get('balance_usd'), 'available': latest.get('available'),
            'measured_at': latest.get('measured_at'),
            'stale': not latest or time.time() - latest['measured_at'] > 90,
            'error': value.get('error'), 'adjusted': value.get('adjusted', False),
            'observed_decrease_usd': _decrease({'start':value['start'], 'latest':latest,
                'adjusted':value.get('adjusted', False)}) if latest else None,
            'observation_started_at': value.get('start', {}).get('measured_at'),
            'window': {'decrease_usd':_decrease(window), 'coverage':window['coverage'],
                       'started_at':window['start']['measured_at'],
                       'measured_at':window['latest']['measured_at'],
                       'adjusted':window.get('adjusted', False)} if window else None}


def refresh(job_dir=None, attempt=None, force=False):
    """Free, throttled provider request under a separate lock, never ledger lock."""
    from .deepseek import _http, RemoteError
    try:
        lock = InstanceLock(_path().with_suffix('.lock'))
    except BusyError:
        return status(job_dir, attempt)
    try:
        value = _read()
        now = time.time()
        if now - value.get('last_refresh_attempt', 0) < (5 if force else REFRESH_SECONDS):
            return status(job_dir, attempt)
        value['last_refresh_attempt'] = now
        atomic_json(_path(), value)
        try:
            snapshot = _snapshot(_http('/user/balance', timeout=8), now)
            _store(value, snapshot, job_dir, attempt)
        except (RemoteError, OSError):
            value['error'] = 'Не удалось обновить баланс DeepSeek; показана последняя проверка'
            atomic_json(_path(), value)
        return status(job_dir, attempt)
    finally:
        lock.close()


def safe_record(raw, **kwargs):
    from .deepseek import RemoteError
    try:
        record(raw, **kwargs)
    except (RemoteError, BusyError, OSError, ValueError):
        pass  # Observation failure must not change paid-response accounting.


def safe_refresh(job_dir, attempt):
    from .deepseek import RemoteError
    try:
        refresh(job_dir, attempt, force=True)
    except (RemoteError, BusyError, OSError, ValueError):
        pass
