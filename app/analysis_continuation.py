"""Source-qualified stage outputs and exact accepted replies across providers."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from threading import RLock

from .cancellation import check_cancelled
from .content_identity import digest, stable_semantics
from .json_store import atomic_json, now, read_json

VERSION = 1
LABELS = {'story_refinement': 'понимание сюжета', 'credit_continuations': 'переходы заставки',
          'titles': 'титры', 'closing_novelty': 'новые события в финале', 'source_roles': 'сюжетная речь',
          'global_visual_verification': 'изображение и сюжет', 'selection_adjudication': 'конкретный выбор',
          'global_story': 'связность истории', 'pacing': 'темп', 'silent_sequences': 'безречевые сцены',
          'final_selection_adjudication': 'итоговый выбор', 'endings': 'концовки',
          'ending_selection_adjudication': 'выбор после проверки концовок',
          'story_structure_analysis': 'сюжетные связи', 'dialogue_relations': 'связи реплик', 'framing': 'кадрирование'}


class ContinuationMiss(InterruptedError):
    """Offline reconstruction stops before any unrecorded model request."""


def enable_continuation(directory, old_provider, new_provider):
    path = Path(directory) / 'continuation' / 'control.json'
    control = read_json(path, {})
    history = control.get('history', [])
    atomic_json(path, {**control, 'enabled': True,
        'history': [*history, {'from': old_provider, 'to': new_provider, 'at': now()}]})


def _optional(path):
    try:
        value = read_json(path, {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _source(directory):
    meta = _optional(Path(directory) / 'analysis.meta.json')
    sha = meta.get('source')
    return meta if isinstance(sha, str) and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha) else None


def _request_key(source, prompt, schema, hashes):
    return digest({'version': VERSION, 'source': source, 'prompt': prompt,
                   'schema': schema, 'image_hashes': hashes})


class AcceptedReplies:
    def __init__(self, directory, provider, cancelled):
        self.directory, self.provider, self.cancelled = Path(directory), provider, cancelled
        self.source = _source(directory)
        self.root = self.directory / 'continuation'
        self.control = _optional(self.root / 'control.json')
        self.cache_only = self.control.get('cache_only') is True
        self.lock = RLock()
        self.legacy = None
        self.reused = self.fresh = 0

    def _key(self, prompt, image, schema):
        pages = list(image) if isinstance(image, (list, tuple)) else ([image] if image is not None else [])
        hashes = []
        for value in pages:
            check_cancelled(self.cancelled)
            path = Path(value).resolve()
            from .checkpoint_lineage import ancestors
            if not any(path.is_relative_to(owner.resolve()) for owner in (self.directory, *ancestors(self.directory))):
                raise ValueError('Reply image is outside its checkpoint owners')
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        return _request_key(self.source, prompt, schema, hashes)

    def _validate(self, answer, schema):
        from .antigravity_exchange import validate_answer
        validate_answer(answer, {'schema': schema,
            'source_duration': _optional(self.directory / 'probe.json').get('duration')})

    def _legacy_index(self):
        if self.legacy is not None:
            return self.legacy
        self.legacy = {}
        if self.control.get('enabled') is not True:
            return self.legacy
        root = self.directory / 'antigravity' / 'packets'
        for result_path in root.glob('*/result.json'):
            check_cancelled(self.cancelled)
            folder = result_path.parent
            if folder.is_symlink() or not folder.resolve().is_relative_to(root.resolve()):
                continue
            request = _optional(folder / 'request.json')
            if request.get('source') != self.source or not isinstance(request.get('prompt'), str):
                continue
            key = _request_key(self.source, request['prompt'], request.get('schema'), request.get('image_hashes'))
            self.legacy.setdefault(key, []).append(folder)
        return self.legacy

    def _legacy_answer(self, key, schema):
        from .antigravity_exchange import validate_answer
        for folder in self._legacy_index().get(key, []):
            check_cancelled(self.cancelled)
            request, result = _optional(folder / 'request.json'), _optional(folder / 'result.json')
            try:
                identity = {name: request[name] for name in ('profile', 'source', 'prompt', 'schema',
                    'max_tokens', 'thinking', 'image_hashes')}
                if digest(identity) != folder.name or result.get('id') != folder.name:
                    continue
                if result.get('answer_hash') != digest(result.get('answer')):
                    continue
                if request.get('source_duration') != _optional(self.directory / 'probe.json').get('duration'):
                    continue
                for name, expected in zip(request['images'], request['image_hashes'], strict=True):
                    page = (folder / name).resolve()
                    page.relative_to(folder.resolve())
                    if hashlib.sha256(page.read_bytes()).hexdigest() != expected:
                        raise ValueError('Changed accepted image')
                validate_answer(result['answer'], request)
                self._validate(result['answer'], schema)
                return {'answer': result['answer'], 'producer': 'antigravity_manual',
                        'original_request': folder.name}
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return None

    def find(self, prompt, image, schema):
        check_cancelled(self.cancelled)
        key = self._key(prompt, image, schema)
        with self.lock:
            from .checkpoint_lineage import ancestors
            saved = {}
            for directory in (self.directory, *ancestors(self.directory)):
                saved = _optional(directory / 'continuation' / 'replies' / (key + '.json'))
                if (saved.get('key') == key and saved.get('source') == self.source
                        and saved.get('answer_hash') == digest(saved.get('answer'))):
                    try:
                        self._validate(saved['answer'], schema)
                    except (ValueError, KeyError, TypeError):
                        saved = {}
                else:
                    saved = {}
                if saved:
                    break
            if not saved:
                saved = self._legacy_answer(key, schema)
            if saved:
                self.reused += 1
                self._event('reply_reused', producer=saved.get('producer'), request=key)
                return key, copy.deepcopy(saved['answer'])
        return key, None

    def store(self, key, answer, schema):
        self._validate(answer, schema)
        with self.lock:
            atomic_json(self.root / 'replies' / (key + '.json'),
                        {'key': key, 'source': self.source, 'answer': answer,
                         'answer_hash': digest(answer), 'producer': self.provider, 'accepted_at': now()})
            self.fresh += 1
            self._event('reply_saved', producer=self.provider, request=key)

    def _event(self, action, **fields):
        from .pipeline_diagnostics import Diagnostics
        Diagnostics(self.directory).event('provider_continuation', action, **fields)


def attach_replies(vision, directory, provider, cancelled):
    """Keep the real adapter type/metadata, wrapping only query dispatch."""
    if getattr(vision, '_continuation_attached', False) or _source(directory) is None:
        return vision
    replies = AcceptedReplies(directory, provider, cancelled)
    original = vision.query
    def query(prompt, image=None, max_tokens=1200, schema=None, **kwargs):
        key, answer = replies.find(prompt, image, schema)
        if answer is not None:
            return answer
        if replies.cache_only:
            raise ContinuationMiss('Нет принятого ответа для следующей проверки')
        replies._event('request_dispatched', producer=provider, request=key)
        answer = original(prompt, image, max_tokens=max_tokens, schema=schema, **kwargs)
        replies.store(key, answer, schema)
        return answer
    vision.query = query
    if callable(getattr(vision, 'query_many', None)):
        original_many = vision.query_many
        def query_many(tasks):
            result, missing, keys = [], [], []
            for task in tasks:
                key, answer = replies.find(task['prompt'], task.get('image'), task.get('schema'))
                result.append(answer)
                keys.append(key)
                if answer is None:
                    missing.append(len(result)-1)
            if missing:
                if replies.cache_only:
                    raise ContinuationMiss('Нет принятого ответа для следующего пакета проверок')
                replies._event('request_dispatched', producer=provider, requests=len(missing))
                answers = original_many([tasks[index] for index in missing])
                if len(answers) != len(missing):
                    raise ValueError('Неполный пакет ответов')
                for index, answer in zip(missing, answers, strict=True):
                    replies.store(keys[index], answer, tasks[index].get('schema'))
                    result[index] = answer
            return result
        vision.query_many = query_many
    vision._continuation_attached = True
    vision._continuation_replies = replies
    return vision


class StageJournal:
    def __init__(self, directory, fingerprint, transcript, shots, profile, diagnostics, report, cancelled):
        from .semantic_identity import scoped_identity
        self.directory, self.root = Path(directory), Path(directory) / 'continuation'
        resolved = self.directory.resolve()
        from .checkpoint_lineage import ancestors
        owners = (resolved, *ancestors(resolved))
        self.prefixes = tuple(prefix for owner in owners for prefix in (str(owner), owner.as_posix()))
        self.diagnostics, self.report, self.cancelled = diagnostics, report, cancelled
        self.context = {'version': VERSION, 'source': fingerprint, 'transcript': digest(transcript),
                        'shots': digest(shots), 'profile': profile,
                        'perception_code': scoped_identity('perception')['digest'],
                        'story_code': scoped_identity('story')['digest'],
                        'late_code': scoped_identity('late_analysis')['digest']}

    def _key(self, name, inputs):
        context = self.context
        if name in ('source_evidence', 'episode_survey', 'episode_map', 'standalone_source',
                    'whole_candidate_qualification'):
            context = {k: v for k, v in context.items() if k in ('version', 'source', 'transcript', 'shots')}
        elif name == 'visual_analysis':
            context = {k: v for k, v in context.items() if k not in ('story_code', 'late_code', 'profile')}
        return digest({'context': context, 'stage': name, 'inputs': self._normalise(stable_semantics(inputs))})

    def _normalise(self, value):
        if isinstance(value, dict):
            return {self._normalise(k): self._normalise(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalise(v) for v in value]
        if isinstance(value, str):
            for prefix in self.prefixes:
                if value.startswith(prefix + '/') or value.startswith(prefix + '\\'):
                    return '@job/' + value[len(prefix)+1:].replace('\\', '/')
        return value

    def _load_record(self, root, name, inputs):
        saved = _optional(root / 'stages' / (name + '.json'))
        if saved.get('key') != self._key(name, inputs):
            return None
        try:
            record = saved
            if 'artifact' in saved:
                # A declared new artifact must be complete; never fall through
                # to a stale embedded legacy output after an interrupted commit.
                artifact = saved['artifact']
                path = root / artifact['path']
                path.resolve().relative_to((root / 'artifacts').resolve())
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != artifact['sha256']:
                    return None
                import json
                record = json.loads(raw)
                if any(record.get(key) != saved.get(key) for key in
                       ('key', 'stage', 'producer', 'output_hash', 'completed_at')):
                    return None
                if 'output' in saved and saved['output'] != record.get('output'):
                    return None
            if saved.get('output_hash') != digest(self._normalise(record.get('output'))):
                return None
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            return None
        return record

    def load(self, name, inputs):
        check_cancelled(self.cancelled)
        from .checkpoint_lineage import ancestors
        for directory in (self.directory, *ancestors(self.directory)):
            record = self._load_record(directory / 'continuation', name, inputs)
            if record is None:
                continue
            self.diagnostics.event(name, 'cache_hit', scope='stage', producer=record.get('producer'),
                                   source_job_id=directory.name)
            return copy.deepcopy(record['output'])
        return None

    def save(self, name, inputs, output, producer):
        check_cancelled(self.cancelled)
        key, output_hash = self._key(name, inputs), digest(self._normalise(output))
        artifact = self.root / 'artifacts' / name / key / (output_hash + '.json')
        artifact.resolve().relative_to((self.root / 'artifacts').resolve())
        record = {'version': 1, 'key': key, 'context': self.context, 'stage': name,
                  'producer': producer, 'output': output, 'output_hash': output_hash, 'completed_at': now()}
        # Content-addressed successful results are never overwritten by later
        # selections, retries or an interchangeable provider's identical answer.
        existing = _optional(artifact)
        if artifact.exists():
            try:
                valid = (existing.get('key') == key and existing.get('stage') == name
                         and existing.get('output_hash') == output_hash
                         and digest(self._normalise(existing.get('output'))) == output_hash)
            except (ValueError, TypeError):
                valid = False
            if valid:
                record = existing
            else:
                import uuid
                artifact = artifact.with_name(output_hash + '.recovered-' + uuid.uuid4().hex + '.json')
                atomic_json(artifact, record)
        else:
            atomic_json(artifact, record)
        check_cancelled(self.cancelled)
        manifest = {k: v for k, v in record.items() if k != 'output'}
        manifest['artifact'] = {'path': artifact.relative_to(self.root).as_posix(),
                                'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
        # Commit pointer last. An orphan artifact is harmless after a crash;
        # the previous committed stage remains readable throughout publication.
        atomic_json(self.root / 'stages' / (name + '.json'), manifest)

    def run(self, name, inputs, callback, producer):
        saved = self.load(name, inputs)
        if saved is not None:
            self.report('analyze', .49, 'Сохранённая проверка: ' + LABELS.get(name, name))
            return saved
        # Compute the signature before callbacks that mutate their event inputs.
        original = copy.deepcopy(inputs)
        from .execution_context import scope
        with scope(stage=name):
            result = callback()
        self.save(name, original, result, producer)
        return result

    def perception(self, inputs, *, allow_legacy=False):
        saved = self.load('visual_analysis', inputs)
        if saved is not None:
            return saved
        control_path = self.root / 'control.json'
        control = _optional(control_path)
        if not allow_legacy or control.get('enabled') is not True or control.get('legacy_context') is not None:
            return None
        from .scene_analysis import _scene_image_hashes
        from .scene_detection import SCENE_DETECTOR_VERSION, SCENE_GROUPING_VERSION
        visual = self.directory / 'visual'
        records = []
        try:
            for path in sorted(visual.glob('event_????.json')):
                check_cancelled(self.cancelled)
                row = read_json(path)
                event, boards = row['event'], row['storyboards']
                if _scene_image_hashes(boards, visual) != row['image_hashes']:
                    return None
                evidence = event['scene_evidence']
                if (evidence.get('detector_version') != SCENE_DETECTOR_VERSION
                        or evidence.get('grouping_version') != SCENE_GROUPING_VERSION):
                    return None
                source_boards = [board for board in boards if board.get('role') != 'legacy_overview']
                # Older canonical overview pages have no source field. Their
                # bytes are verified above; CURRENT/recovery source proofs bind
                # the accepted event itself to the original video and ASR.
                if (not any(board.get('role') == 'current' for board in source_boards)
                        or any(board.get('source', {}).get('sha256') != self.context['source'] for board in source_boards)):
                    return None
                transcript = read_json(self.directory / 'transcript.json')
                words = transcript.get('words') or transcript.get('segments', [])
                for unit in event.get('units', []):
                    text = ' '.join(w['text'] for w in words if w['start'] < unit['end'] and w['end'] > unit['start'])
                    if unit.get('text') != text:
                        return None
                records.append(event)
            duration = _optional(self.directory / 'probe.json').get('duration')
            # Legacy scene endpoints are rounded to milliseconds; source
            # container duration can retain microseconds beyond the last frame.
            if (not records or abs(records[0]['start']) > 1e-6 or abs(records[-1]['end']-duration) > .001
                    or records[-1]['end'] > duration + 1e-6
                    or any(abs(left['end']-right['start']) > 1e-6 for left, right in zip(records, records[1:]))):
                return None
            scenes = [{'id': event['scene_id'], 'start': event['start'], 'end': event['end'],
                       'confidence': event.get('scene_confidence', .5), 'uncertain': event.get('initial_uncertain', True),
                       'boundary_reason': ['accepted_source_perception'], 'evidence': event['scene_evidence']}
                      for event in records]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        output = {'scenes': scenes, 'events': records}
        self.save('visual_analysis', inputs, output, 'local')
        atomic_json(control_path, {**control, 'legacy_context': self.context, 'legacy_visual_events': len(records)})
        self.diagnostics.event('visual_analysis', 'legacy_adopted', events=len(records),
                               source_qualified=True, images_verified=True)
        return output
