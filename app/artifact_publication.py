"""Immutable rendered revisions; the small publication pointer commits last.

The renderer owns media validation. This module requires its full-decode receipt,
then binds the validated video, subtitles and exact plan to their current bytes.
It never starts a decoder or upgrades a legacy export's validation provenance.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from .cancellation import check_cancelled
from .content_identity import digest, file_sha256
from .json_store import atomic_json, load_json, now, read_json
from .media import EXPORT_VALIDATION_VERSION

VERSION = 1
REFERENCE_VERSION = 2
_WORKSPACE = Path(__file__).resolve().parents[1]
_PUBLIC_NAME = re.compile(r"part_[0-9]{3}\.(?:mp4|srt)\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PublicationError(ValueError):
    """Missing, untrusted or changed publication evidence."""


def _canonical_resolved(path):
    resolved = Path(path).resolve()
    value = str(resolved)
    # Windows can retain the extended drive namespace when an atomic pointer
    # appears during realpath checks. It is the same path, not a store escape.
    if os.name == 'nt' and re.match(r'^\\\\\?\\[A-Za-z]:\\', value):
        return Path(value[4:])
    return resolved


def _inside(path: Path, root: Path) -> Path:
    original = Path(path).absolute()
    boundary = Path(root).absolute()
    for component in (original, *original.parents):
        if component == boundary:
            break
        if component.is_symlink() or component.is_junction():
            raise PublicationError("Artifact path uses an alias")
    resolved = _canonical_resolved(path)
    if not resolved.is_relative_to(_canonical_resolved(root)):
        raise PublicationError("Artifact path escapes its store")
    return resolved


def _job_root(job_dir: Path) -> Path:
    root = _inside(job_dir, _WORKSPACE)
    if root == _WORKSPACE:
        raise PublicationError("A job directory is required")
    return root


def _identifier(value, name):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PublicationError(f"Invalid {name}")
    return value


def _name(value):
    if not isinstance(value, str) or not _PUBLIC_NAME.fullmatch(value):
        raise PublicationError("Invalid public artifact filename")
    return value


def _finite_copy(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise PublicationError("Plan must contain finite JSON values") from error


def _identity(record):
    keys = ("version", "plan_sha256", "producer_id", "parent_revision", "artifacts")
    if record['version'] == REFERENCE_VERSION:
        keys += ('source_identity',)
    return {key: record[key] for key in keys}


def _source_identity(root):
    from .checkpoint_lineage import _id, _owner
    try:
        job = load_json(_inside(root / 'job.json', root))
        meta = load_json(_inside(root / 'analysis.meta.json', root))
        source = load_json(_inside(root / 'source.json', root))
        _id(root.name)
        if job['id'] != root.name or not _SHA256.fullmatch(meta['source']):
            raise ValueError()
        # Library migration adds an external owner adapter without modifying
        # legacy job.json. Bind the durable raw owner, so that legitimate
        # startup migration does not rewrite an immutable revision's identity.
        episode = job.get('episode_id')
        effective_owner = _owner(root, job, True)
        for owner in (episode, effective_owner):
            if owner is not None:
                _id(owner)
        if not isinstance(source['path'], str) or not source['path']:
            raise ValueError()
        return {'job_id': root.name, 'source_sha256': meta['source'],
                'episode_id': episode, 'source_path': source['path']}
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise PublicationError('Publication source or ownership is invalid') from error


def _reference_root(root, identifier):
    from .checkpoint_lineage import ancestors, _id, LineageError
    try:
        _id(identifier)
        if identifier == root.name:
            return root
        # The lineage owner validates every hop, including migrated legacy
        # adapters. Media, source evidence and model caches share this boundary.
        for ancestor in ancestors(root):
            if ancestor.name == identifier:
                return _job_root(ancestor)
    except (LineageError, OSError, KeyError, TypeError, AttributeError) as error:
        raise PublicationError('Publication ancestry is invalid') from error
    raise PublicationError('Publication origin is not an explicit ancestor')


def _reference(value):
    if not isinstance(value, dict) or set(value) != {
            'job_id', 'revision_id', 'video_filename', 'subtitles_filename', 'manifest_sha256'}:
        raise PublicationError('Invalid publication reference')
    from .checkpoint_lineage import _id, LineageError
    try:
        _id(value['job_id'])
    except LineageError as error:
        raise PublicationError('Invalid reference job ID') from error
    for key in ('revision_id', 'manifest_sha256'):
        if not isinstance(value[key], str) or not _SHA256.fullmatch(value[key]):
            raise PublicationError('Invalid reference identity')
    video, subtitles = _name(value['video_filename']), _name(value['subtitles_filename'])
    if not video.endswith('.mp4') or subtitles != Path(video).with_suffix('.srt').name:
        raise PublicationError('Invalid reference filenames')
    return value


def _metadata(root: Path, revision_id: str, cancelled, memo):
    if not isinstance(revision_id, str) or not _SHA256.fullmatch(revision_id):
        raise PublicationError("Invalid revision ID")
    directory = _inside(root / "revisions" / revision_id, root)
    cache_key = ('metadata', root, revision_id)
    if cache_key in memo:
        return memo[cache_key]
    manifest_path = _inside(directory / "manifest.json", directory)
    try:
        record = load_json(manifest_path)
        if (type(record['version']) is not int or record["version"] not in (VERSION, REFERENCE_VERSION)
                or record["revision_id"] != revision_id
                or digest(_identity(record)) != revision_id):
            raise PublicationError("Revision identity does not match its manifest")
        _identifier(record["producer_id"], "producer ID")
        _identifier(record["attempt_id"], "attempt ID")
        if record['version'] == REFERENCE_VERSION and record['source_identity'] != _source_identity(root):
            raise PublicationError('Publication source or ownership changed')
        parent = record["parent_revision"]
        if parent is not None and (not isinstance(parent, str) or not _SHA256.fullmatch(parent)):
            raise PublicationError("Invalid parent revision")
        if not isinstance(record["plan"], dict) or digest(record["plan"]) != record["plan_sha256"]:
            raise PublicationError("Revision plan changed")
        plan_path = _inside(directory / "plan.json", directory)
        if (file_sha256(plan_path, cancelled) != record["plan_file_sha256"]
                or load_json(plan_path) != record["plan"]):
            raise PublicationError("Stored plan changed")
        names = []
        if not isinstance(record["artifacts"], list) or not record["artifacts"]:
            raise PublicationError("A revision requires rendered artifacts")
        for item in record["artifacts"]:
            if 'reference' in item:
                if record['version'] != REFERENCE_VERSION:
                    raise PublicationError('Legacy revision cannot contain references')
                _reference(item['reference'])
            _identifier(item["candidate_id"], "candidate ID")
            if type(item["full_decode_version"]) is not int or item["full_decode_version"] != EXPORT_VALIDATION_VERSION:
                raise PublicationError("Missing full-decode validation receipt")
            video, subtitles = item["video"], item["subtitles"]
            if not video["filename"].endswith(".mp4") or subtitles["filename"] != Path(video["filename"]).with_suffix(".srt").name:
                raise PublicationError("Video and subtitles do not share a basename")
            for artifact in (video, subtitles):
                name = _name(artifact["filename"])
                if name in names:
                    raise PublicationError("Duplicate artifact filename")
                names.append(name)
                if (not isinstance(artifact["sha256"], str) or not _SHA256.fullmatch(artifact["sha256"])
                        or type(artifact["size"]) is not int or artifact["size"] < 0):
                    raise PublicationError('Invalid artifact metadata')
        if names != record["outputs"]:
            raise PublicationError("Output index does not match artifacts")
        check_cancelled(cancelled)
        memo[cache_key] = record
        return record
    except PublicationError:
        raise
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise PublicationError("Revision is incomplete or unreadable") from error


def _resolve(root, revision_id, filename, cancelled, verify_artifacts, memo, seen):
    key = (root, revision_id, filename)
    if key in seen:
        raise PublicationError('Cyclic publication reference')
    if ('resolved', *key, verify_artifacts) in memo:
        return memo[('resolved', *key, verify_artifacts)]
    seen = seen | {key}
    record = _metadata(root, revision_id, cancelled, memo)
    for item in record['artifacts']:
        kind = next((kind for kind in ('video', 'subtitles')
                     if item[kind]['filename'] == filename), None)
        if kind is None:
            continue
        artifact = item[kind]
        if 'reference' in item:
            ref = item['reference']
            origin = _reference_root(root, ref['job_id'])
            origin_record = _metadata(origin, ref['revision_id'], cancelled, memo)
            manifest = _inside(origin / 'revisions' / ref['revision_id'] / 'manifest.json', origin)
            hash_key = ('manifest_hash', manifest)
            if hash_key not in memo:
                try:
                    memo[hash_key] = file_sha256(manifest, cancelled)
                except OSError as error:
                    raise PublicationError('Referenced manifest is unreadable') from error
            if memo[hash_key] != ref['manifest_sha256']:
                raise PublicationError('Referenced manifest changed')
            origin_item = next((other for other in origin_record['artifacts']
                                if other['video']['filename'] == ref['video_filename']
                                and other['subtitles']['filename'] == ref['subtitles_filename']), None)
            if origin_item is None or origin_item['full_decode_version'] != item['full_decode_version']:
                raise PublicationError('Referenced validation provenance changed')
            for media in ('video', 'subtitles'):
                if any(item[media][field] != origin_item[media][field] for field in ('size', 'sha256')):
                    raise PublicationError('Referenced artifact identity changed')
            path = _resolve(origin, ref['revision_id'], ref[kind + '_filename'],
                            cancelled, verify_artifacts, memo, seen)
        else:
            path = _inside(root / 'revisions' / revision_id / filename, root)
            try:
                if path.stat().st_size != artifact['size']:
                    raise PublicationError('Published artifact bytes changed')
                hash_key = ('artifact_hash', path)
                if verify_artifacts:
                    if hash_key not in memo:
                        memo[hash_key] = file_sha256(path, cancelled)
                    if memo[hash_key] != artifact['sha256']:
                        raise PublicationError('Published artifact bytes changed')
            except OSError as error:
                raise PublicationError('Published artifact is unreadable') from error
        check_cancelled(cancelled)
        memo[('resolved', *key, verify_artifacts)] = path
        return path
    raise PublicationError('Output is not in the published revision')


def _load_revision(root: Path, revision_id: str, cancelled, verify_artifacts=True, memo=None):
    memo = {} if memo is None else memo
    record = _metadata(root, revision_id, cancelled, memo)
    for filename in record['outputs']:
        _resolve(root, revision_id, filename, cancelled, verify_artifacts, memo, set())
    return record


def resolve_revision_output(job_dir: Path, revision_id: str, filename: str, *,
                            verify_artifacts=True, cancelled=lambda: False) -> Path:
    """Read one immutable output through explicit ancestry without writing files.

    All visited plans and manifests validate, but unrelated origin media is not
    read: a damaged sibling must not invalidate a separately referenced clip.
    """
    root, filename, memo = _job_root(job_dir), _name(filename), {}
    record = _metadata(root, revision_id, cancelled, memo)
    item = next((item for item in record['artifacts']
                 if filename in (item['video']['filename'], item['subtitles']['filename'])), None)
    if item is None:
        raise PublicationError('Output is not in the published revision')
    paths = {item[kind]['filename']: _resolve(root, revision_id, item[kind]['filename'],
             cancelled, verify_artifacts, memo, set()) for kind in ('video', 'subtitles')}
    return paths[filename]


def load_revision(job_dir: Path, revision_id: str, *, verify_artifacts=True, cancelled=lambda: False):
    """Verify a revision; metadata polling may skip streaming media hashes."""
    return _load_revision(_job_root(job_dir), revision_id, cancelled, verify_artifacts)


def current_revision(job_dir: Path, *, verify_artifacts=True, metadata_only=False,
                     cancelled=lambda: False):
    """Return verified metadata, or None only when unpublished.

    Metadata polling can set verify_artifacts=False to avoid streaming large
    media files. Manifest, exact plan, artifact schemas and sizes still verify;
    serving and publication retain full byte verification by default.
    metadata_only=True reads only the pointer and immutable manifest/plan/schema;
    callers must resolve_revision_output before trusting any media path.
    """
    root = _job_root(job_dir)
    pointer_path = _inside(root / "publication.json", root)
    if not pointer_path.exists():
        return None
    try:
        pointer = load_json(pointer_path)
        if type(pointer['version']) is not int or pointer["version"] not in (VERSION, REFERENCE_VERSION):
            raise PublicationError("Unsupported publication version")
        record = (_metadata(root, pointer['revision_id'], cancelled, {}) if metadata_only else
                  _load_revision(root, pointer["revision_id"], cancelled, verify_artifacts))
        manifest_path = _inside(root / "revisions" / record["revision_id"] / "manifest.json", root)
        if file_sha256(manifest_path, cancelled) != pointer["manifest_sha256"]:
            raise PublicationError("Publication manifest changed")
        return record
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise PublicationError("Publication pointer is unreadable") from error


def _copy_verified(source: Path, destination: Path, expected_hash: str, cancelled):
    result = hashlib.sha256()
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        while block := incoming.read(1024 * 1024):
            check_cancelled(cancelled)
            result.update(block)
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    check_cancelled(cancelled)
    if result.hexdigest() != expected_hash:
        raise PublicationError("Render changed while being published")


def publish_revision(job_dir: Path, plan: dict, artifacts: list[dict], *,
                     producer_id: str, attempt_id: str, parent_revision=None,
                     cancelled=lambda: False):
    """Publish already validated renders as one immutable, coherent revision.

    Each artifact has video/subtitles Paths, candidate_id and full_decode_version,
    or an explicit reference quartet (job_id, revision_id, video_filename,
    subtitles_filename). References preserve existing validation provenance.
    Optional output_index (1..999) aliases native filenames to public rank.
    Identical content preserves its first producer attempt and timestamp. The
    caller may pass a verified parent ID for explicit finishing ancestry.
    """
    root = _job_root(job_dir)
    check_cancelled(cancelled)
    producer_id = _identifier(producer_id, "producer ID")
    attempt_id = _identifier(attempt_id, "attempt ID")
    if not isinstance(plan, dict):
        raise PublicationError("Plan must be an object")
    plan = _finite_copy(plan)
    if not isinstance(artifacts, list) or not artifacts:
        raise PublicationError("A revision requires rendered artifacts")
    # A corrupt current pointer is never silently replaced with a new success.
    current_revision(root, cancelled=cancelled)
    if parent_revision is not None:
        _load_revision(root, parent_revision, cancelled)
    records, sources, names, memo = [], {}, set(), {}
    for item in artifacts:
        try:
            if type(item["full_decode_version"]) is not int or item["full_decode_version"] != EXPORT_VALIDATION_VERSION:
                raise PublicationError("Missing full-decode validation receipt")
            candidate = _identifier(item["candidate_id"], "candidate ID")
            reference = item.get('reference')
            origin_item = None
            if reference is not None:
                if (not isinstance(reference, dict) or set(reference) != {
                        'job_id', 'revision_id', 'video_filename', 'subtitles_filename'}):
                    raise PublicationError('Invalid publication reference')
                origin = _reference_root(root, reference['job_id'])
                origin_record = _metadata(origin, reference['revision_id'], cancelled, memo)
                origin_item = next((other for other in origin_record['artifacts']
                    if other['video']['filename'] == reference['video_filename']
                    and other['subtitles']['filename'] == reference['subtitles_filename']), None)
                if origin_item is None or origin_item['full_decode_version'] != item['full_decode_version']:
                    raise PublicationError('Referenced validation provenance changed')
                reference = {**reference, 'manifest_sha256': file_sha256(
                    _inside(origin / 'revisions' / reference['revision_id'] / 'manifest.json', origin), cancelled)}
                _reference(reference)
                video = _resolve(origin, reference['revision_id'], reference['video_filename'],
                                 cancelled, True, memo, set())
                subtitles = _resolve(origin, reference['revision_id'], reference['subtitles_filename'],
                                     cancelled, True, memo, set())
            else:
                if 'reference' in item:
                    raise PublicationError('Invalid publication reference')
                video = _inside(Path(item["video"]), root)
                subtitles = _inside(Path(item["subtitles"]), root)
            if not video.name.endswith(".mp4") or subtitles.name != video.with_suffix(".srt").name:
                raise PublicationError("Video and subtitles do not share a basename")
            _name(video.name)
            _name(subtitles.name)
            output_index = item.get("output_index")
            if "output_index" in item and (type(output_index) is not int or not 1 <= output_index <= 999):
                raise PublicationError("Invalid public output index")
            entry = {"candidate_id": candidate, "full_decode_version": EXPORT_VALIDATION_VERSION}
            if reference is not None:
                entry['reference'] = reference
            for key, path in (("video", video), ("subtitles", subtitles)):
                original_name = reference[key + '_filename'] if reference else path.name
                name = _name(original_name if output_index is None else f"part_{output_index:03}{path.suffix}")
                if name in names:
                    raise PublicationError("Duplicate artifact filename")
                names.add(name)
                entry[key] = ({**origin_item[key], 'filename': name} if reference else
                              {"filename": name, "sha256": file_sha256(path, cancelled), "size": path.stat().st_size})
                if reference is None:
                    sources[name] = path
            records.append(entry)
        except (KeyError, TypeError, OSError) as error:
            raise PublicationError("Invalid render evidence") from error
    record = {"version": VERSION, "plan": plan, "plan_sha256": digest(plan),
              "producer_id": producer_id, "attempt_id": attempt_id,
              "parent_revision": parent_revision, "artifacts": records,
              "outputs": [artifact[key]["filename"] for artifact in records for key in ("video", "subtitles")],
              "created_at": now()}
    source_files = ('job.json', 'analysis.meta.json', 'source.json')
    try:
        canonical_job_id = str(uuid.UUID(root.name)) == root.name
    except ValueError:
        canonical_job_id = False
    if (canonical_job_id and all((root / name).exists() for name in source_files)
            or any('reference' in item for item in records)):
        record['source_identity'] = _source_identity(root)
        record['version'] = REFERENCE_VERSION
    revision_id = digest(_identity(record))
    record["revision_id"] = revision_id
    revisions = _inside(root / "revisions", root)
    revisions.mkdir(parents=True, exist_ok=True)
    directory = _inside(revisions / revision_id, revisions)
    if not directory.exists():
        staging = _inside(revisions / (".staging-" + uuid.uuid4().hex), revisions)
        staging.mkdir()
        for item in records:
            if 'reference' in item:
                continue
            for key in ("video", "subtitles"):
                artifact = item[key]
                _copy_verified(sources[artifact["filename"]], staging / artifact["filename"], artifact["sha256"], cancelled)
        atomic_json(staging / "plan.json", plan)
        record["plan_file_sha256"] = file_sha256(staging / "plan.json", cancelled)
        atomic_json(staging / "manifest.json", record)
        check_cancelled(cancelled)
        try:
            staging.rename(directory)
        except FileExistsError:
            # A concurrent identical publisher may have committed this directory.
            pass
    record = _load_revision(root, revision_id, cancelled)
    pointer = {"version": record['version'], "revision_id": revision_id,
               "manifest_sha256": file_sha256(directory / "manifest.json", cancelled)}
    check_cancelled(cancelled)
    atomic_json(root / "publication.json", pointer)
    # No cancellation after this commit: the revision is now publicly available.
    return record


def resolve_output(job_dir: Path, filename: str, *, allow_legacy=True) -> Path:
    """Resolve a published file, or read an untouched legacy output directory."""
    root = _job_root(job_dir)
    filename = _name(filename)
    record = current_revision(root, metadata_only=True)
    if record is not None:
        if filename not in record["outputs"]:
            raise PublicationError("Output is not in the published revision")
        return resolve_revision_output(root, record['revision_id'], filename)
    if not allow_legacy:
        raise PublicationError("No revision has been published")
    legacy = _inside(root / "output" / filename, root)
    if not legacy.is_file():
        raise PublicationError("Legacy output does not exist")
    return legacy


def effective_plan(job_dir: Path) -> dict | None:
    """Finishing uses the committed revision when a newer attempt failed."""
    root = _job_root(job_dir)
    published = current_revision(root, verify_artifacts=False)
    return _finite_copy(published['plan']) if published else read_json(root / 'plan.json')
