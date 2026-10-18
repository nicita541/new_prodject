"""Source-bound useful questions; uncertain dispatches never automatically resend."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
from threading import RLock

from .cancellation import check_cancelled
from .content_identity import digest
from .json_store import atomic_json, now, read_json


class QuestionJournalError(ValueError):
    """Persisted question state is unsafe to reuse or dispatch again."""


def _json(value):
    # Round trip also detaches caller-owned objects and rejects non-JSON types.
    return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))


class QuestionLedger:
    def __init__(self, job_dir, source_sha, cancelled=lambda: False):
        if (not isinstance(source_sha, str) or len(source_sha) != 64
                or any(c not in '0123456789abcdef' for c in source_sha)):
            raise ValueError('Invalid source SHA')
        self.directory = Path(job_dir).resolve()
        self.root = self.directory / 'continuation' / 'questions' / source_sha
        self.source, self.cancelled = source_sha, cancelled
        self.lock = RLock()

    def _path(self, name):
        path = self.root / name
        if not path.resolve().is_relative_to(self.directory):
            raise QuestionJournalError('Question path escapes job')
        return path

    def _identity(self, question):
        q = _json(question)
        for field in ('purpose', 'question', 'evidence_digest'):
            if not isinstance(q.get(field), str) or not q[field].strip():
                raise ValueError('Missing question identity field: ' + field)
        for field in ('affected_refs', 'possible_plan_changes'):
            if (not isinstance(q.get(field), list) or not q[field]
                    or any(not isinstance(v, str) or not v.strip() for v in q[field])):
                raise ValueError('Question cannot change a result: ' + field)
        if not isinstance(q.get('request_identity'), dict) or not q['request_identity']:
            raise ValueError('Missing exact request identity')
        cost = q.get('estimated_cost', {})
        if not isinstance(cost, dict) or any(type(v) not in (int, float)
                or not math.isfinite(v) or v < 0 for v in cost.values()):
            raise ValueError('Invalid cost estimate')
        return {'version': 1, 'source': self.source,
                **{k: q[k] for k in ('purpose', 'question', 'evidence_digest', 'request_identity')},
                **{k: sorted(set(q[k])) for k in ('affected_refs', 'possible_plan_changes')}}

    def question_key(self, question):
        return digest(self._identity(question))

    def _load(self, path):
        try:
            return read_json(path)
        except (OSError, ValueError, UnicodeError) as exc:
            raise QuestionJournalError('Unreadable question state') from exc

    def _completed(self, identity, key):
        reservation = self._path(key + '.reserved.json')
        pointer = self._path(key + '.completed.json')
        saved = self._load(reservation)
        if saved is not None:
            if not isinstance(saved, dict) or saved.get('identity') != identity:
                raise QuestionJournalError('Invalid question reservation')
            committed = self._load(pointer)
            if committed is None:
                raise QuestionJournalError('Question outcome is unknown; new evidence or explicit recovery required')
            try:
                if committed['key'] != key:
                    raise ValueError()
                identifier = committed['artifact_id']
                if (not isinstance(identifier, str) or len(identifier) != 64
                        or any(c not in '0123456789abcdef' for c in identifier)):
                    raise ValueError()
                artifact = self._path(key + '.' + identifier + '.result.json')
                raw = artifact.read_bytes()
                if hashlib.sha256(raw).hexdigest() != committed['sha256']:
                    raise ValueError()
                result = json.loads(raw)
                if result['identity'] != identity or result['key'] != key:
                    raise ValueError()
                _json(result['answer'])
                return True, copy.deepcopy(result['answer'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise QuestionJournalError('Invalid completed question') from exc
        if pointer.exists():
            raise QuestionJournalError('Completed question lacks reservation')
        return False, None

    def run(self, question, callback, producer='unknown'):
        check_cancelled(self.cancelled)
        identity = self._identity(question)
        key = digest(identity)
        with self.lock:
            reservation = self._path(key + '.reserved.json')
            pointer = self._path(key + '.completed.json')
            from .checkpoint_lineage import ancestors
            owners = ancestors(self.directory)
            for ledger in (self, *(QuestionLedger(owner, self.source, self.cancelled) for owner in owners)):
                found, answer = ledger._completed(identity, key)
                if found:
                    return answer
            check_cancelled(self.cancelled)
            reservation.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Exclusive creation arbitrates across ledger instances/processes.
                # A partial write is deliberately retained and fails closed.
                with reservation.open('x', encoding='utf-8') as stream:
                    json.dump({'identity': identity, 'key': key, 'reserved_at': now(),
                               'estimated_cost': _json(question.get('estimated_cost', {}))},
                              stream, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise QuestionJournalError('Question is already reserved') from exc
            # Once reserved, every failure is unknown; retain it even on cancellation.
            answer = _json(callback())
            check_cancelled(self.cancelled)
            result = {'identity': identity, 'key': key, 'answer': answer,
                      'producer': producer, 'completed_at': now()}
            sha = hashlib.sha256(json.dumps(result, ensure_ascii=False, indent=2,
                                           allow_nan=False).encode('utf-8')).hexdigest()
            artifact = self._path(key + '.' + sha + '.result.json')
            if artifact.exists():
                raise QuestionJournalError('Result artifact already exists')
            atomic_json(artifact, result)
            check_cancelled(self.cancelled)
            atomic_json(pointer, {'key': key, 'artifact_id': sha,
                                  'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()})
            return copy.deepcopy(answer)
