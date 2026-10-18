"""Explicit source/owner-bound ancestors; never infer lineage from source equality."""
from __future__ import annotations

from pathlib import Path
import uuid

from .json_store import atomic_json, read_json

FILE = 'checkpoint-lineage.json'


class LineageError(ValueError):
    """A referenced checkpoint owner is missing or inconsistent."""


def _id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise LineageError('Invalid ancestor job ID') from exc
    return value


def _read(path):
    try:
        return read_json(path)
    except (OSError, ValueError, UnicodeError) as exc:
        raise LineageError('Unreadable checkpoint lineage') from exc


def _record(directory):
    record = _read(directory / FILE)
    if record is None:
        if (directory / FILE).exists():
            raise LineageError('Invalid null checkpoint lineage')
        return None
    if (not isinstance(record, dict) or set(record) !=
            {'version', 'parent_job_id', 'source_sha256', 'episode_id'}
            or record.get('version') != 1):
        raise LineageError('Invalid checkpoint lineage')
    _id(record['parent_job_id'])
    sha = record['source_sha256']
    if (not isinstance(sha, str) or len(sha) != 64
            or any(c not in '0123456789abcdef' for c in sha)):
        raise LineageError('Invalid ancestor source SHA')
    if record['episode_id'] is not None:
        _id(record['episode_id'])
    return record


def _owner(directory, job, expected):
    # Legacy source-level jobs predate library ownership. Keep their original
    # unscoped adapter; explicit episode lineage uses the migrated owner.
    if expected is None:
        return job.get('episode_id')
    if job.get('episode_id') is not None:
        return job['episode_id']
    library = _read(directory.parent.parent / 'library.json') or {}
    return library.get('legacy_jobs', {}).get(directory.name)


def _validate(directory, record):
    job = _read(directory / 'job.json')
    meta = _read(directory / 'analysis.meta.json')
    source = _read(directory / 'source.json')
    if (not isinstance(job, dict) or job.get('id') != directory.name
            or _owner(directory, job, record['episode_id']) != record['episode_id']
            or not isinstance(meta, dict) or meta.get('source') != record['source_sha256']
            or not isinstance(source, dict) or not isinstance(source.get('path'), str)):
        raise LineageError('Checkpoint ancestor source or ownership changed')
    return source['path']


def _known_owner(directory):
    """Resolve migrated ownership without rewriting a historical job record."""
    try:
        owner = _owner(directory, _read(directory / 'job.json'), True)
        if owner is not None:
            _id(owner)
        return owner
    except (AttributeError, KeyError, TypeError) as error:
        raise LineageError('Invalid ancestor owner adapter') from error


def ancestors(directory):
    """Validate the complete chain before allowing any ancestor cache read."""
    current = Path(directory).resolve()
    root = current.parent
    seen, result = {current.name}, []
    record = _record(current)
    if record is None:
        return result
    source_path = _validate(current, record)
    owners = {_known_owner(current)} - {None}
    identity = {k: record[k] for k in ('source_sha256', 'episode_id')}
    while record is not None:
        if (record['source_sha256'] != identity['source_sha256']
                or record['episode_id'] not in (None, identity['episode_id'])):
            raise LineageError('Ancestor chain changes source or owner')
        identifier = record['parent_job_id']
        if identifier in seen:
            raise LineageError('Cyclic checkpoint lineage')
        seen.add(identifier)
        target = root / identifier
        if target.is_symlink() or target.is_junction() or target.resolve().parent != root:
            raise LineageError('Ancestor path escapes job store')
        if _validate(target, {**record, **identity}) != source_path:
            raise LineageError('Ancestor chain changes source path')
        owners.update({_known_owner(target)} - {None})
        # Legacy source-level submissions can be read before Library migrates
        # the new child. Known owners must still agree across every hop.
        if len(owners) > 1:
            raise LineageError('Ancestor chain changes migrated owner')
        result.append(target)
        record = _record(target)
    return result


def link(previous, destination, *, source_sha256, episode_id):
    previous, destination = Path(previous).resolve(), Path(destination).resolve()
    _id(previous.name)
    _id(destination.name)
    if previous == destination or previous.parent != destination.parent:
        raise LineageError('Ancestors must be distinct jobs in the same store')
    record = {'version': 1, 'parent_job_id': previous.name,
              'source_sha256': source_sha256, 'episode_id': episode_id}
    source_path = _validate(previous, record)
    for ancestor in ancestors(previous):
        if ancestor == destination:
            raise LineageError('Cyclic checkpoint lineage')
        if _validate(ancestor, record) != source_path:
            raise LineageError('Ancestor chain changes source path')
    existing = _record(destination)
    if existing is not None and existing != record:
        raise LineageError('Checkpoint lineage cannot be replaced')
    # The caller holds the manager lock. Commit the reference before copying
    # checkpoints or publishing job.json, including interrupted submissions.
    atomic_json(destination / FILE, record)
    return source_path


def dependents(jobs_root, identifier):
    """Direct references protect the entire chain, including unfinished jobs."""
    _id(identifier)
    root = Path(jobs_root).resolve()
    result = []
    for path in root.glob('*/' + FILE):
        directory = path.parent
        if directory.name == identifier:
            continue  # Removing a corrupt reference owner is itself safe.
        if directory.is_symlink() or directory.is_junction() or directory.resolve().parent != root:
            raise LineageError('Unsafe checkpoint reference')
        _id(directory.name)
        record = _record(directory)
        if record and record['parent_job_id'] == identifier:
            result.append(directory.name)
    return sorted(result)
