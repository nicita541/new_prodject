"""Durable finishing command storage; no worker or API lifecycle ownership.

The supplied root is the storage boundary. Operation locks serialize writers;
command.json is immutable, while the operation receipt commits its existence.
Recovery only materializes the exact reserved bytes. It never calls a profile,
source, model, renderer, or queue callback. Integrating callers retain ownership
of API validation, worker scheduling, render-contract compatibility, real media
validation, and stopping obsolete workers before removing task files.

Owned paths reject existing symlink/junction redirects, including descendants.
This detects persisted path aliases; it is not a defense against a hostile
concurrent filesystem writer changing ancestors between validation and I/O.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
import uuid

from app.content_identity import digest, file_sha256, finite_number
from app.json_store import atomic_json, now, read_json
from app.file_lock import BusyError, InstanceLock

VERSION = 1
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_TASK = re.compile(r'(pv|ex)_[0-9a-f]{32}\Z')
_ATTEMPT = re.compile(r'[0-9a-f]{32}\Z')
_TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


def _canonical_resolved(path):
    resolved = path.resolve()
    # Windows may retain the extended namespace prefix when a pointer appears
    # during realpath's existence checks. It names the same drive path, not an
    # alias. Preserve all other resolution/containment checks.
    value = str(resolved)
    if os.name == 'nt' and re.match(r'^\\\\\?\\[A-Za-z]:\\', value):
        return Path(value[4:])
    return resolved


class CommandError(ValueError):
    """A command or owned persisted record is invalid; preserve it untouched."""


class OperationConflict(CommandError):
    """The operation belongs to a different immutable request or was deleted."""


class StaleAttempt(CommandError):
    """An obsolete worker cannot publish progress or artifact receipts."""


def _json(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError) as error:
        raise CommandError('Finishing parameters must be finite JSON') from error


def _uuid(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise CommandError('Finishing operation and job IDs require canonical UUIDs') from None
    return value


def _sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise CommandError('Finishing requires canonical SHA256 identities')
    return value


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise CommandError('Invalid finishing record fields')


def _part_index(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise CommandError('Invalid finishing part index')
    return value


def normalize_request(kind, request):
    """Original intention is distinct from its frozen saved-profile resolution."""
    if kind not in ('preview', 'export') or not isinstance(request, dict):
        raise CommandError('Invalid finishing command type or request')
    allowed = {'part_indices', 'settings'} if kind == 'export' else {'part_index', 'from', 'duration', 'settings'}
    if set(request)-allowed:
        raise CommandError('Unexpected finishing request fields')
    settings = request.get('settings')
    if settings is not None and not isinstance(settings, dict):
        raise CommandError('Explicit finishing profile must be an object')
    profile = {'mode': 'stored'} if settings is None else {'mode': 'explicit', 'value': _json(settings)}
    if kind == 'export':
        indices = request.get('part_indices')
        if not isinstance(indices, list) or not 1 <= len(indices) <= 100:
            raise CommandError('Finishing requires selected parts')
        indices = [_part_index(value) for value in indices]
        if len(set(indices)) != len(indices):
            raise CommandError('Duplicate finishing parts')
        preview = None
    else:
        indices = [_part_index(request.get('part_index'))]
        start, duration = request.get('from', 0), request.get('duration', 5)
        if not finite_number(start) or start < 0 or not finite_number(duration) or not 0 < duration <= 10:
            raise CommandError('Invalid finishing preview interval')
        preview = {'part_index': indices[0], 'from': float(start), 'duration': float(duration)}
    return {'kind': kind, 'part_indices': indices, 'preview': preview, 'profile': profile}


class FinishingCommands:
    def __init__(self, root, *, lock_factory=InstanceLock, lock_timeout=10.):
        self.root = _canonical_resolved(Path(root))
        # Injectable for composition/tests without importing JobManager or
        # acquiring its server lock or triggering its recovery lifecycle.
        self._lock_factory = lock_factory
        if not finite_number(lock_timeout) or lock_timeout < 0:
            raise CommandError('Invalid finishing operation lock timeout')
        self.lock_timeout = float(lock_timeout)

    def _path(self, relative):
        if (type(relative) is not str or not relative or '\\' in relative or ':' in relative
                or PurePosixPath(relative).is_absolute() or relative != str(PurePosixPath(relative))
                or any(part in ('', '.', '..') for part in relative.split('/'))):
            raise CommandError('Invalid owned finishing path')
        path = self.root.joinpath(*relative.split('/'))
        try:
            resolved = _canonical_resolved(path)
        except (OSError, RuntimeError) as error:
            raise CommandError('Unreadable owned finishing path') from error
        if not resolved.is_relative_to(self.root) or resolved != path:
            raise CommandError('Finishing paths cannot escape or redirect their owner')
        return path

    def _owned(self, path):
        """Check a complete descendant, not merely its task-directory prefix."""
        try:
            relative = Path(path).relative_to(self.root).as_posix()
        except (ValueError, TypeError) as error:
            raise CommandError('Finishing path is outside its store') from error
        return self._path(relative)

    def _write(self, path, value):
        atomic_json(self._owned(path), value)

    def _mkdir(self, path):
        self._owned(path).mkdir(parents=True)

    def _operation(self, operation_id):
        return self._path('finishing/operations/'+_uuid(operation_id)+'.json')

    def _lock(self, operation_id):
        started = time.monotonic()
        while True:
            try:
                return self._lock_factory(self._path('finishing/operations/.locks/'+_uuid(operation_id)+'.lock'))
            except BusyError:
                if time.monotonic()-started >= self.lock_timeout:
                    raise BusyError('Квитанция экспорта временно занята; повторите тот же запрос') from None
                time.sleep(.02)

    def task_directory(self, job_id, kind, task_id):
        _uuid(job_id)
        if (kind not in ('preview', 'export') or type(task_id) is not str or not _TASK.fullmatch(task_id)
                or not task_id.startswith('pv_' if kind == 'preview' else 'ex_')):
            raise CommandError('Invalid finishing task owner or type')
        return self._path('data/jobs/'+job_id+'/finishing/'+
            ('previews' if kind == 'preview' else 'exports')+'/'+task_id)

    def _relative(self, path):
        return self._owned(path).relative_to(self.root).as_posix()

    def _read(self, path):
        path = self._owned(path)
        try:
            record = read_json(path)
            if record is None and path.exists():
                raise CommandError('Null finishing record is corrupt, not absent')
            return record
        except (OSError, ValueError, UnicodeError) as error:
            raise CommandError('Unreadable finishing record') from error

    def _frozen(self, frozen, request, source_sha):
        frozen = _json(frozen)
        _fields(frozen, ('source', 'plan', 'source_plan_digest', 'publication_revision', 'audio_stream', 'probe',
            'profile', 'preview', 'caption_revisions', 'assets', 'resolved_music', 'render_contract'))
        _fields(frozen['source'], ('path', 'sha256'))
        self._path(frozen['source']['path'])
        if _sha(frozen['source']['sha256']) != source_sha:
            raise CommandError('Frozen source does not match command owner')
        _sha(frozen['source_plan_digest'])
        if frozen['publication_revision'] is not None:
            _sha(frozen['publication_revision'])
        if type(frozen['audio_stream']) is not int or frozen['audio_stream'] < 0:
            raise CommandError('Invalid frozen audio stream')
        _fields(frozen['probe'], ('width', 'height', 'audio_stream'))
        if (any(type(frozen['probe'][key]) is not int or not 0 < frozen['probe'][key] <= 32768
                for key in ('width', 'height'))
                or type(frozen['probe']['audio_stream']) is not int
                or frozen['probe']['audio_stream'] != frozen['audio_stream']):
            raise CommandError('Invalid frozen source probe or selected audio stream')
        if not isinstance(frozen['profile'], dict) or not isinstance(frozen['plan'], dict):
            raise CommandError('Frozen profile and plan must be objects')
        if request['profile']['mode'] == 'explicit' and frozen['profile'] != request['profile']['value']:
            raise CommandError('Frozen explicit profile differs from original request')
        parts = frozen['plan'].get('parts')
        if not isinstance(parts, list) or not all(isinstance(part, dict) for part in parts):
            raise CommandError('Frozen plan requires selected parts')
        if [part.get('index') for part in parts] != request['part_indices']:
            raise CommandError('Frozen part order differs from original request')
        for part in parts:
            _part_index(part['index'])
            if not finite_number(part.get('duration')) or part['duration'] <= 0:
                raise CommandError('Invalid frozen part duration')
            if not isinstance(part.get('cuts'), list) or not part['cuts'] or not isinstance(part.get('subtitles'), list):
                raise CommandError('Frozen parts require cuts and captions')
            previous = None
            for cut in part['cuts']:
                if (not isinstance(cut, dict) or not finite_number(cut.get('start'))
                        or not finite_number(cut.get('end')) or not 0 <= cut['start'] < cut['end']
                        or previous is not None and cut['start'] < previous):
                    raise CommandError('Invalid frozen source cuts')
                previous = cut['end']
            if abs(sum(cut['end']-cut['start'] for cut in part['cuts'])-part['duration']) > .002:
                raise CommandError('Frozen cuts do not match part duration')
        if request['kind'] == 'export':
            if frozen['preview'] is not None:
                raise CommandError('Export cannot contain a preview interval')
        else:
            _fields(frozen['preview'], ('part_index', 'from', 'duration'))
            wanted, actual = request['preview'], frozen['preview']
            _part_index(actual['part_index'])
            if (actual['part_index'] != wanted['part_index'] or not finite_number(actual['from'])
                    or actual['from'] != wanted['from']
                    or not finite_number(actual['duration']) or not 0 < actual['duration'] <= wanted['duration']
                    or actual['from']+actual['duration'] > parts[0]['duration']+.001):
                raise CommandError('Frozen preview differs from requested bounded interval')
        expected_parts = {str(index) for index in request['part_indices']}
        if not isinstance(frozen['caption_revisions'], dict) or set(frozen['caption_revisions']) != expected_parts:
            raise CommandError('Caption ownership must cover every selected part')
        for caption in frozen['caption_revisions'].values():
            _fields(caption, ('target_id', 'revision'))
            _sha(caption['target_id'])
            if type(caption['revision']) is not int or caption['revision'] < 0:
                raise CommandError('Invalid caption revision')
        if not isinstance(frozen['assets'], list):
            raise CommandError('Frozen assets must be a list')
        music_ids, asset_paths = set(), set()
        for asset in frozen['assets']:
            _fields(asset, ('role', 'path', 'sha256'))
            if asset['role'] not in ('music', 'avatar'):
                raise CommandError('Unknown frozen asset role')
            self._path(asset['path'])
            _sha(asset['sha256'])
            if asset['path'] in asset_paths:
                raise CommandError('Duplicate frozen asset path')
            asset_paths.add(asset['path'])
            if asset['role'] == 'music':
                music_ids.add(asset['sha256'])
        if not isinstance(frozen['resolved_music'], dict) or set(frozen['resolved_music']) != expected_parts:
            raise CommandError('Music decisions must cover every selected part')
        for music in frozen['resolved_music'].values():
            if music is not None and (not isinstance(music, dict) or music.get('asset_sha256') not in music_ids):
                raise CommandError('Resolved music must reference a frozen asset')
        _fields(frozen['render_contract'], ('version', 'code_sha256'))
        if type(frozen['render_contract']['version']) is not int or frozen['render_contract']['version'] < 1:
            raise CommandError('Invalid render contract version')
        _sha(frozen['render_contract']['code_sha256'])
        return frozen

    def _command(self, command, *, expected=None):
        _fields(command, ('version', 'operation_id', 'task_id', 'job_id', 'source_sha256', 'kind',
            'request', 'request_hash', 'frozen', 'frozen_hash', 'created_at', 'command_hash'))
        if type(command['version']) is not int or command['version'] != VERSION:
            raise CommandError('Unsupported finishing command version')
        _uuid(command['operation_id'])
        _uuid(command['job_id'])
        _sha(command['source_sha256'])
        self.task_directory(command['job_id'], command['kind'], command['task_id'])
        _fields(command['request'], ('kind', 'part_indices', 'preview', 'profile'))
        # Reconstruct the original wire intention to validate normalized shape.
        request = command['request']
        profile = request['profile']
        if not isinstance(profile, dict) or profile.get('mode') not in ('stored', 'explicit'):
            raise CommandError('Invalid normalized finishing profile marker')
        _fields(profile, ('mode',) if profile['mode'] == 'stored' else ('mode', 'value'))
        if command['kind'] == 'export':
            raw = {'part_indices': request['part_indices']}
        else:
            raw = copy.deepcopy(request['preview'])
            if not isinstance(raw, dict):
                raise CommandError('Invalid normalized preview request')
        if profile['mode'] == 'explicit':
            raw['settings'] = profile['value']
        if normalize_request(command['kind'], raw) != request:
            raise CommandError('Finishing request is not canonical')
        if digest(request) != command['request_hash']:
            raise CommandError('Finishing request hash mismatch')
        frozen = self._frozen(command['frozen'], request, command['source_sha256'])
        if digest(frozen) != command['frozen_hash']:
            raise CommandError('Frozen finishing payload hash mismatch')
        if (not isinstance(command['created_at'], str) or not command['created_at']
                or digest({key: value for key, value in command.items() if key != 'command_hash'}) != command['command_hash']):
            raise CommandError('Finishing command hash mismatch')
        if expected is not None and any(command[key] != value for key, value in expected.items()):
            raise OperationConflict('Finishing operation belongs to a different request or owner')
        return copy.deepcopy(command)

    def _receipt(self, operation_id):
        record = self._read(self._operation(operation_id))
        if record is None:
            return None
        _fields(record, ('version', 'operation_id', 'state', 'command'))
        if (type(record['version']) is not int or record['version'] != VERSION
                or record['operation_id'] != operation_id or record['state'] not in ('reserved', 'committed', 'deleted')):
            raise CommandError('Invalid finishing operation receipt')
        self._command(record['command'], expected={'operation_id': operation_id})
        return record

    def verify_assets(self, command):
        command = self._command(command)
        for asset in (command['frozen']['source'], *command['frozen']['assets']):
            path = self._path(asset['path'])
            try:
                if not path.is_file() or file_sha256(path) != asset['sha256']:
                    raise CommandError('Finishing source or asset bytes changed')
            except OSError as error:
                raise CommandError('Finishing source or asset is unavailable') from error

    def _materialize(self, receipt):
        if receipt['state'] == 'deleted':
            raise OperationConflict('Finishing task was deleted; operation cannot resurrect it')
        command = self._command(receipt['command'])
        directory = self.task_directory(command['job_id'], command['kind'], command['task_id'])
        path = directory/'command.json'
        existing = self._read(path)
        if existing is not None:
            self._command(existing)
            if existing != command:
                raise CommandError('Immutable finishing command differs from reserved parameters')
        elif receipt['state'] == 'committed':
            # Once committed, missing/tampered state is corruption, not a
            # reservation crash to silently repair or overwrite.
            raise CommandError('Committed finishing command is missing')
        else:
            self._write(path, command)
        if receipt['state'] != 'committed':
            self._write(self._operation(command['operation_id']), {**receipt, 'state': 'committed'})
        return command

    def submit(self, job_id, source_sha256, kind, request, freeze, *, operation_id=None, preflight=None):
        job_id, source_sha256 = _uuid(job_id), _sha(source_sha256)
        operation_id = _uuid(operation_id) if operation_id is not None else str(uuid.uuid4())
        normalized = normalize_request(kind, request)
        expected = {'operation_id': operation_id, 'job_id': job_id, 'source_sha256': source_sha256,
                    'kind': kind, 'request_hash': digest(normalized)}
        lock = self._lock(operation_id)
        try:
            receipt = self._receipt(operation_id)
            if receipt is not None:
                self._command(receipt['command'], expected=expected)
                return self._materialize(receipt)
            if preflight is not None:
                preflight()
            frozen = self._frozen(freeze(), normalized, source_sha256)
            command = {'version': VERSION, **expected,
                'task_id': ('pv_' if kind == 'preview' else 'ex_')+uuid.uuid4().hex,
                'request': normalized, 'frozen': frozen, 'frozen_hash': digest(frozen), 'created_at': now()}
            command['command_hash'] = digest(command)
            self.verify_assets(command)
            receipt = {'version': VERSION, 'operation_id': operation_id, 'state': 'reserved', 'command': command}
            self._write(self._operation(operation_id), receipt)
            return self._materialize(receipt)
        finally:
            lock.close()

    def load(self, operation_id, *, job_id=None, source_sha256=None, kind=None, verify_assets=False):
        receipt = self._receipt(operation_id)
        if receipt is None:
            return None
        if receipt['state'] == 'deleted':
            raise OperationConflict('Finishing task was deleted')
        expected = {key: value for key, value in (
            ('job_id', job_id), ('source_sha256', source_sha256), ('kind', kind)) if value is not None}
        command = self._command(receipt['command'], expected=expected)
        if receipt['state'] != 'committed':
            raise CommandError('Finishing command reservation needs materialization')
        path = self.task_directory(command['job_id'], command['kind'], command['task_id'])/'command.json'
        if self._read(path) != command:
            raise CommandError('Stored finishing command differs from its receipt')
        if verify_assets:
            self.verify_assets(command)
        return command

    def recover(self, operation_id):
        """Repair a reservation only; never validates current assets or starts work."""
        lock = self._lock(operation_id)
        try:
            receipt = self._receipt(operation_id)
            return None if receipt is None else self._materialize(receipt)
        finally:
            lock.close()

    def tombstone(self, operation_id, *, job_id):
        lock = self._lock(operation_id)
        try:
            receipt = self._receipt(operation_id)
            if receipt is None:
                raise CommandError('Unknown finishing operation')
            self._command(receipt['command'], expected={'job_id': _uuid(job_id)})
            self._write(self._operation(operation_id), {**receipt, 'state': 'deleted'})
        finally:
            lock.close()

    def _runtime(self, command):
        directory = self.task_directory(command['job_id'], command['kind'], command['task_id'])
        state = self._read(directory/'runtime.json')
        if state is not None:
            _fields(state, ('version', 'command_hash', 'attempt_id', 'status', 'sequence', 'progress'))
            if (type(state['version']) is not int or state['version'] != VERSION or state['command_hash'] != command['command_hash']
                    or type(state['attempt_id']) is not str or not _ATTEMPT.fullmatch(state['attempt_id'])
                    or type(state['status']) is not str or state['status'] not in _TERMINAL | {'queued', 'running'}
                    or type(state['sequence']) is not int or state['sequence'] < 0
                    or not finite_number(state['progress']) or not 0 <= state['progress'] <= 1):
                raise CommandError('Invalid finishing attempt ownership or state')
        return directory, state

    def begin_attempt(self, command, *, attempt_id=None):
        command = self._command(command)
        attempt_id = uuid.uuid4().hex if attempt_id is None else attempt_id
        if type(attempt_id) is not str or not _ATTEMPT.fullmatch(attempt_id):
            raise CommandError('Invalid finishing attempt ID')
        lock = self._lock(command['operation_id'])
        try:
            command = self.load(command['operation_id'], job_id=command['job_id'],
                source_sha256=command['source_sha256'], kind=command['kind'])
            if command is None:
                raise CommandError('Unknown finishing operation')
            directory, state = self._runtime(command)
            if state and state['status'] not in _TERMINAL:
                raise CommandError('Current finishing attempt must stop before resume')
            if state and state['status'] == 'completed':
                raise CommandError('Completed finishing command does not need a new attempt')
            if self._owned(directory/'attempts'/attempt_id).exists():
                raise StaleAttempt('Finishing attempt ID cannot be reused')
            self._mkdir(directory/'attempts'/attempt_id)
            state = {'version': VERSION, 'command_hash': command['command_hash'], 'attempt_id': attempt_id,
                     'status': 'queued', 'sequence': 0, 'progress': 0.0}
            self._write(directory/'runtime.json', state)
            return state
        finally:
            lock.close()

    def update_attempt(self, command, attempt_id, *, status, progress=0.0):
        command = self._command(command)
        lock = self._lock(command['operation_id'])
        try:
            command = self.load(command['operation_id'], job_id=command['job_id'],
                source_sha256=command['source_sha256'], kind=command['kind'])
            if command is None:
                raise CommandError('Unknown finishing operation')
            directory, state = self._runtime(command)
            if not state or state['attempt_id'] != attempt_id:
                raise StaleAttempt('Finishing attempt no longer owns this task')
            if state['status'] in _TERMINAL:
                raise StaleAttempt('Finished attempt cannot publish new state')
            if (type(status) is not str or status not in _TERMINAL | {'running'} or not finite_number(progress)
                    or not 0 <= progress <= 1 or status == 'completed' and progress != 1):
                raise CommandError('Invalid finishing attempt transition')
            if status == 'completed' and any(self.part_receipt(command, index) is None
                    for index in command['request']['part_indices']):
                raise CommandError('Finishing completion requires every validated part receipt')
            updated = {**state, 'status': status, 'progress': float(progress), 'sequence': state['sequence']+1}
            self._write(directory/'runtime.json', updated)
            return updated
        finally:
            lock.close()

    def part_input_digest(self, command, part_index):
        command = self._command(command)
        _part_index(part_index)
        if part_index not in command['request']['part_indices']:
            raise CommandError('Part is outside finishing command')
        # Deliberately command-bound for this prototype. Cross-command reuse
        # needs a separate render-identity adapter; never guess equivalence.
        return digest({'command_hash': command['command_hash'], 'part_index': part_index})

    def presentation_identity(self, command, part_index):
        """Pixel/audio inputs only; an operation/revision counter is not content."""
        command = self._command(command)
        frozen = command['frozen']
        part = next((part for part in frozen['plan']['parts'] if part['index'] == part_index), None)
        if part is None:
            raise CommandError('Part is outside finishing command')
        profile = frozen['profile']
        style = {**profile.get('subtitles', {}), **(
            profile.get('part_overrides', {}).get(str(part_index), {}).get('style') or {})}
        style.pop('safe_guides', None)
        return digest({'version': 1, 'source': frozen['source']['sha256'], 'probe': frozen['probe'],
            'part': part, 'preview': frozen['preview'], 'video': profile.get('video', {}), 'subtitles': style,
            'music': frozen['resolved_music'][str(part_index)], 'render_contract': frozen['render_contract'],
            'avatar': [asset['sha256'] for asset in frozen['assets'] if asset['role'] == 'avatar']})

    def reference_part(self, command, attempt_id, part_index, origin, origin_index):
        """Adopt verified same-job media by reference, preserving its decode proof."""
        command, origin = self._command(command), self._command(origin)
        if (command['job_id'] != origin['job_id'] or command['operation_id'] == origin['operation_id']
                or self.presentation_identity(command, part_index) != self.presentation_identity(origin, origin_index)):
            raise CommandError('Finishing references require identical presentation inputs in the same job')
        lock = self._lock(command['operation_id'])
        try:
            if self.load(command['operation_id']) != command or self.load(origin['operation_id']) != origin:
                raise CommandError('Finishing reference command changed')
            directory, state = self._runtime(command)
            if not state or state['attempt_id'] != attempt_id or state['status'] != 'running':
                raise StaleAttempt('Only current running attempt can adopt a part')
            existing = self.part_receipt(command, part_index)
            if existing is not None:
                return existing
            record = self.part_receipt(origin, origin_index)
            if record is None:
                raise CommandError('Origin has no validated part')
            self._write(directory/'parts'/f'part_{part_index:03}.json', {
                'version': 2, 'command_hash': command['command_hash'], 'part_index': part_index,
                'origin_operation_id': origin['operation_id'], 'origin_part_index': origin_index,
                'origin_receipt_id': digest(record), 'render_input_digest': self.part_input_digest(command, part_index),
                'presentation_sha256': self.presentation_identity(command, part_index)})
            return record
        finally:
            lock.close()

    def part_receipt(self, command, part_index, *, verify_bytes=True, _seen=None):
        from app.media import EXPORT_VALIDATION_VERSION
        command = self._command(command)
        seen = set() if _seen is None else set(_seen)
        owner = (command['operation_id'], part_index)
        if owner in seen:
            raise CommandError('Finishing artifact reference cycle')
        seen.add(owner)
        input_digest = self.part_input_digest(command, part_index)
        directory = self.task_directory(command['job_id'], command['kind'], command['task_id'])
        pointer = self._read(directory/'parts'/f'part_{part_index:03}.json')
        if pointer is None:
            return None
        if isinstance(pointer, dict) and pointer.get('version') == 2:
            _fields(pointer, ('version', 'command_hash', 'part_index', 'origin_operation_id',
                'origin_part_index', 'origin_receipt_id', 'render_input_digest', 'presentation_sha256'))
            _part_index(pointer['origin_part_index'])
            _sha(pointer['origin_receipt_id'])
            origin = self.load(pointer['origin_operation_id'], job_id=command['job_id'])
            if (type(pointer['version']) is not int
                    or pointer['command_hash'] != command['command_hash'] or type(pointer['part_index']) is not int
                    or pointer['part_index'] != part_index or pointer['render_input_digest'] != input_digest
                    or origin is None or pointer['presentation_sha256'] != self.presentation_identity(command, part_index)
                    or pointer['presentation_sha256'] != self.presentation_identity(origin, pointer['origin_part_index'])):
                raise CommandError('Finishing reference differs from its frozen presentation')
            record = self.part_receipt(origin, pointer['origin_part_index'], verify_bytes=verify_bytes, _seen=seen)
            if record is None or digest(record) != pointer['origin_receipt_id']:
                raise CommandError('Finishing reference origin receipt changed')
            return record
        _fields(pointer, ('version', 'command_hash', 'part_index', 'receipt_id'))
        if (type(pointer['version']) is not int or pointer['version'] != VERSION
                or pointer['command_hash'] != command['command_hash'] or type(pointer['part_index']) is not int
                or pointer['part_index'] != part_index):
            raise CommandError('Part receipt pointer does not match command owner')
        _sha(pointer['receipt_id'])
        record = self._read(directory/'receipts'/(pointer['receipt_id']+'.json'))
        _fields(record, ('version', 'command_hash', 'part_index', 'attempt_id', 'render_input_digest',
            'full_decode_version', 'video', 'subtitles'))
        if (type(record['version']) is not int or record['version'] != VERSION
                or digest(record) != pointer['receipt_id'] or record['command_hash'] != command['command_hash']
                or type(record['part_index']) is not int or record['part_index'] != part_index
                or record['render_input_digest'] != input_digest
                or type(record['attempt_id']) is not str or not _ATTEMPT.fullmatch(record['attempt_id'])
                or type(record['full_decode_version']) is not int
                or record['full_decode_version'] != EXPORT_VALIDATION_VERSION):
            raise CommandError('Invalid validated part receipt')
        output = directory/'attempts'/record['attempt_id']/'output'
        for key, suffix in (('video', '.mp4'), ('subtitles', '.srt')):
            item = record[key]
            _fields(item, ('path', 'sha256', 'size'))
            path = self._path(item['path'])
            _sha(item['sha256'])
            if (path != output/f'part_{part_index:03}{suffix}' or type(item['size']) is not int
                    or item['size'] < 0 or key == 'video' and item['size'] == 0):
                raise CommandError('Part artifact is outside its immutable owner')
            try:
                if (path.stat().st_size != item['size']
                        or verify_bytes and file_sha256(path) != item['sha256']):
                    raise CommandError('Validated finishing artifact bytes changed')
            except OSError as error:
                raise CommandError('Validated finishing artifact is unavailable') from error
        return record

    def commit_part(self, command, attempt_id, part_index, *, video, subtitles, validation):
        """Bind a renderer's existing full-decode receipt to its current bytes.

        This helper never decodes media and does not manufacture provenance.
        The integrating renderer must supply its genuine validation result.
        """
        from app.media import EXPORT_VALIDATION_VERSION
        command = self._command(command)
        input_digest = self.part_input_digest(command, part_index)
        _fields(validation, ('full_decode_version', 'video_sha256', 'subtitles_sha256'))
        if (type(validation['full_decode_version']) is not int
                or validation['full_decode_version'] != EXPORT_VALIDATION_VERSION):
            raise CommandError('Missing current full-decode validation receipt')
        lock = self._lock(command['operation_id'])
        try:
            command = self.load(command['operation_id'], job_id=command['job_id'],
                source_sha256=command['source_sha256'], kind=command['kind'])
            if command is None:
                raise CommandError('Unknown finishing operation')
            directory, state = self._runtime(command)
            if not state or state['attempt_id'] != attempt_id or state['status'] != 'running':
                raise StaleAttempt('Only current running attempt can commit a part')
            old = self.part_receipt(command, part_index)
            if old is not None:
                return old
            output = directory/'attempts'/attempt_id/'output'
            record = {'version': VERSION, 'command_hash': command['command_hash'], 'part_index': part_index,
                'attempt_id': attempt_id, 'render_input_digest': input_digest,
                'full_decode_version': EXPORT_VALIDATION_VERSION}
            for key, relative, suffix in (('video', video, '.mp4'), ('subtitles', subtitles, '.srt')):
                path = self._path(relative)
                _sha(validation[key+'_sha256'])
                if path != output/f'part_{part_index:03}{suffix}':
                    raise CommandError('Renderer artifact is outside this attempt')
                try:
                    actual, size = file_sha256(path), path.stat().st_size
                except OSError as error:
                    raise CommandError('Renderer artifact is unavailable') from error
                if actual != validation[key+'_sha256'] or size < 0 or key == 'video' and size == 0:
                    raise CommandError('Renderer validation does not match artifact bytes')
                record[key] = {'path': relative, 'sha256': actual, 'size': size}
            receipt_id = digest(record)
            path = directory/'receipts'/(receipt_id+'.json')
            existing = self._read(path)
            if existing is not None and existing != record:
                raise CommandError('Immutable part receipt changed')
            if existing is None:
                self._write(path, record)
            self._write(directory/'parts'/f'part_{part_index:03}.json', {
                'version': VERSION, 'command_hash': command['command_hash'], 'part_index': part_index,
                'receipt_id': receipt_id})
            return record
        finally:
            lock.close()
