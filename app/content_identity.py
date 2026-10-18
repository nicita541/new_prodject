"""Finite JSON evidence and digests; preserve compact and spaced cache encodings."""
from __future__ import annotations

import hashlib
import json
import math


def file_sha256(path, cancelled=lambda: False):
    """Hash current artifact bytes without trusting size/mtime or a memo cache."""
    from .cancellation import check_cancelled
    result = hashlib.sha256()
    check_cancelled(cancelled)
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            check_cancelled(cancelled)
            result.update(block)
    check_cancelled(cancelled)
    return result.hexdigest()


def finite_number(value):
    """JSON numeric evidence excludes booleans, infinity and NaN."""
    return type(value) in (int, float) and math.isfinite(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def evidence_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def stable_semantics(value):
    if isinstance(value, dict):
        return {k: stable_semantics(v) for k, v in value.items() if k not in ('cache_hit', 'visual_cache_hit')}
    if isinstance(value, list):
        return [stable_semantics(v) for v in value]
    return value
