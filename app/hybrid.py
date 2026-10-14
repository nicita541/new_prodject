"""Local-first evidence review; remote failures never discard valid local work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import ROOT
from .deepseek import BudgetExceeded, DeepSeekVision, MODEL, PROFILE, RemoteError, _validate
from .jobs import BusyError
from app.json_store import atomic_json

HYBRID_VERSION = 1
FOCUS_REVIEW_THRESHOLD = .75
CLASSIFIER_REVIEW_THRESHOLD = .85


def routing_profile():
    return {'provider': 'hybrid', 'version': HYBRID_VERSION, 'remote_model': MODEL,
            'remote_profile': PROFILE, 'focus_review_threshold': FOCUS_REVIEW_THRESHOLD,
            'classifier_review_threshold': CLASSIFIER_REVIEW_THRESHOLD,
            'unconfirmed_visible_speech': True, 'focus_accept_threshold': .55}


def _focus_schema(schema):
    return schema is not None and {'x', 'y', 'visible_speaker'} <= set(schema.get('properties', {}))


def _validate_answer(value, schema):
    if not isinstance(value, dict):
        raise ValueError('Модель вернула неверный формат анализа')
    json.dumps(value, allow_nan=False)
    if schema is not None:
        _validate(value, schema)


def review_reason(value, schema, prompt):
    if value.get('uncertain') is True:
        return 'explicit_uncertainty'
    if 'confidence' in value:
        threshold = FOCUS_REVIEW_THRESHOLD if _focus_schema(schema) else CLASSIFIER_REVIEW_THRESHOLD
        confidence = value['confidence']
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            return 'invalid_confidence'
        if confidence < threshold:
            return 'low_confidence'
    if (_focus_schema(schema) and 'Current phrase (evidence):' in prompt
            and value.get('visible_speaker') is not True):
        return 'unconfirmed_visible_speech'
    return None


def _usable_review(value, schema):
    if value.get('uncertain') is True:
        return False
    if 'confidence' in value:
        threshold = .55 if _focus_schema(schema) else CLASSIFIER_REVIEW_THRESHOLD
        return type(value['confidence']) in (int, float) and threshold <= value['confidence'] <= 1
    return True


def review_summary(job_dir: Path):
    path = job_dir / 'hybrid-reviews.json'
    if not path.is_file():
        return {'reviewed': 0, 'unresolved': 0, 'remote_disabled': False}
    data = json.loads(path.read_text('utf-8'))
    entries = data.get('entries', {}).values()
    return {'reviewed': sum(entry.get('outcome') == 'reviewed' for entry in entries),
            'unresolved': sum(entry.get('outcome') != 'reviewed' for entry in entries),
            'remote_disabled': bool(data.get('remote_disabled'))}


def query_checked(vision, prompt, image=None, *, max_tokens, schema, validator, validation_profile):
    """Validate source-domain constraints before accepting a model decision."""
    if isinstance(vision, HybridVision):
        return vision.query(prompt, image, max_tokens=max_tokens, schema=schema,
                            validator=validator, validation_profile=validation_profile)
    arguments = {'max_tokens': max_tokens, 'schema': schema}
    if image is not None:
        arguments['image'] = image
    value = vision.query(prompt, **arguments)
    try:
        validator(value)
    except (ValueError, TypeError, KeyError):
        if isinstance(vision, DeepSeekVision):
            raise RemoteError('DeepSeek вернул неверные связи исходных фрагментов; платный повтор не выполнен') from None
        raise
    return value


class HybridVision:
    def __init__(self, job_dir: Path, cancelled, local):
        self.job_dir = job_dir.resolve()
        self.job_dir.relative_to(ROOT.resolve())
        self.cancelled = cancelled
        self.local = local
        self.cache_profile = routing_profile()
        self.journal = self.job_dir / 'hybrid-reviews.json'
        self.journal.resolve().relative_to(self.job_dir)
        self.state = {'version': HYBRID_VERSION, 'entries': {}, 'remote_disabled': False}
        if self.journal.is_file():
            saved = json.loads(self.journal.read_text('utf-8'))
            if saved.get('version') != HYBRID_VERSION or not isinstance(saved.get('entries'), dict):
                raise ValueError('Повреждён журнал гибридной проверки')
            self.state = saved

    def __getattr__(self, name):
        return getattr(self.local, name)

    def __enter__(self):
        self.local.__enter__()
        return self

    def __exit__(self, *args):
        return self.local.__exit__(*args)

    def close(self):
        self.local.close()

    def token_count(self, text):
        return self.local.token_count(text)

    def _save(self, digest, entry):
        self.state['entries'][digest] = entry
        atomic_json(self.journal, self.state)

    def query(self, prompt, image=None, max_tokens=1200, schema=None, *, validator=None, validation_profile=None):
        if validator is not None and not isinstance(validation_profile, str):
            raise ValueError('Не указан профиль проверки исходных фрагментов')
        if self.cancelled():
            raise InterruptedError('Обработка отменена')
        local, local_error = None, None
        try:
            local = self.local.query(prompt, image, max_tokens=max_tokens, schema=schema)
            _validate_answer(local, schema)
            if validator is not None:
                validator(local)
            reason = review_reason(local, schema, prompt)
        except InterruptedError:
            raise
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as error:
            local, local_error, reason = None, error, 'invalid_local_answer'
        if reason is None:
            return local
        if self.cancelled():
            raise InterruptedError('Обработка отменена')
        image_hash = None
        image_paths = list(image) if isinstance(image, (list,tuple)) else ([image] if image is not None else [])
        if image is not None:
            hashes = []
            for value in image_paths:
                path = Path(value).resolve()
                path.relative_to(ROOT.resolve())
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
            image_hash = hashes if isinstance(image,(list,tuple)) else hashes[0]
        models = []
        for attr in ('model', 'projector'):
            path = Path(getattr(self.local, attr, 'unknown'))
            models.append({'path': str(path), 'size': path.stat().st_size,
                           'mtime_ns': path.stat().st_mtime_ns} if path.is_file() else {'path': str(path)})
        identity = {'profile': self.cache_profile, 'models': models,
            'thinking': bool(getattr(self.local, 'thinking', False)), 'prompt': prompt,
            'image': image_hash, 'schema': schema, 'max_tokens': max_tokens}
        if validation_profile is not None:
            identity['domain_validation'] = validation_profile
        digest = hashlib.sha256(json.dumps(identity,
            sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        previous = self.state['entries'].get(digest)
        if previous is not None:
            result = previous.get('result')
            if previous.get('outcome') == 'reviewed':
                _validate_answer(result, schema)
                if validator is not None:
                    validator(result)
                return result
            if local_error is not None:
                raise local_error
            return local
        entry = {'reason': reason, 'outcome': 'local_fallback',
                 'input_image': str(Path(image_paths[0]).resolve().relative_to(ROOT.resolve())) if len(image_paths)==1 else None,
                 'stage': 'framing' if _focus_schema(schema) else 'story',
                 'local_uncertain': local.get('uncertain') is True if local is not None else None}
        if local is not None and type(local.get('confidence')) in (int, float):
            entry['local_confidence'] = local['confidence']
        if len(image_paths)>1:
            entry['input_images'] = [str(Path(p).resolve().relative_to(ROOT.resolve())) for p in image_paths]
        # Persist before attempting remote review. Restarting this job must not
        # automatically repeat an interrupted or unconfirmed billable request.
        self._save(digest, entry)
        try:
            remote = DeepSeekVision(self.job_dir, self.cancelled,
                                    cache_only=bool(self.state.get('remote_disabled')))
            # query checks key only when a cache miss actually needs the API.
            result = remote.query(prompt, image, max_tokens=min(max_tokens, 1800), schema=schema)
            _validate_answer(result, schema)
            if validator is not None:
                validator(result)
        except InterruptedError:
            raise
        except (BudgetExceeded, RemoteError, BusyError, ValueError, TypeError, KeyError, OSError):
            self.state['remote_disabled'] = True
            entry['failure'] = 'remote_unavailable'
            self._save(digest, entry)
            if local_error is not None:
                raise local_error
            return local
        if _usable_review(result, schema):
            entry.update(outcome='reviewed', result=result)
            if type(result.get('confidence')) in (int, float):
                entry['remote_confidence'] = result['confidence']
            self._save(digest, entry)
            return result
        entry['outcome'] = 'unresolved'
        self._save(digest, entry)
        if local_error is not None:
            # Existing stage fallbacks preserve material/hold crop rather than
            # pretending an invalid local answer became reliable remotely.
            raise local_error
        return local
