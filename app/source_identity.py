"""Bounded, process-local source hashes shared by preparation and analysis."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
from pathlib import Path
from threading import RLock

from .cancellation import check_cancelled

_HASHES = OrderedDict()
_LOCK = RLock()


def source_stamp(source):
    stat = Path(source).stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns}


def check_source(source, stamp, cancelled):
    check_cancelled(cancelled)
    if source_stamp(source) != stamp:
        raise ValueError('Source changed while reading source evidence')


def _hash_source(source, cancelled):
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            check_cancelled(cancelled)
            digest.update(block)
    check_cancelled(cancelled)
    return digest.hexdigest()


def source_identity(source, cancelled=lambda: False, *, refresh=False):
    """Never seed this cache from persisted metadata; verify mutation before reuse."""
    source = Path(source).resolve()
    check_cancelled(cancelled)
    with _LOCK:
        check_cancelled(cancelled)
        stamp = source_stamp(source)
        key = (str(source), *stamp.values())
        # Trust boundaries can request current bytes once, then share that hash
        # within the run. Windows ctime is creation time, so stat equality alone
        # cannot detect a same-size rewrite whose mtime was restored.
        digest = None if refresh else _HASHES.get(key)
        if digest is None:
            digest = _hash_source(source, cancelled)
        check_source(source, stamp, cancelled)
        _HASHES[key] = digest
        _HASHES.move_to_end(key)
        while len(_HASHES) > 32:
            _HASHES.popitem(last=False)
        return {'sha256': digest, **stamp}
