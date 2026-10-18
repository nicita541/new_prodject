"""Small, content-free correlation context shared by execution diagnostics."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import re

_CURRENT = ContextVar('kadr_execution_context', default={})
_IDS = frozenset({'job_id', 'attempt_id', 'stage', 'candidate_id',
                  'logical_request_id', 'request_id', 'request_sha256'})
_LABEL = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


def snapshot():
    return dict(_CURRENT.get())


@contextmanager
def scope(**fields):
    """Allow identifiers only: prompts, media, paths and secrets cannot enter."""
    clean = {}
    for name, value in fields.items():
        if name == 'transport_attempt':
            if type(value) is not int or value < 1:
                raise ValueError('Invalid transport attempt')
        elif name not in _IDS or not isinstance(value, str) or not _LABEL.fullmatch(value):
            raise ValueError('Invalid execution correlation field')
        clean[name] = value
    token = _CURRENT.set({**_CURRENT.get(), **clean})
    try:
        yield snapshot()
    finally:
        _CURRENT.reset(token)
