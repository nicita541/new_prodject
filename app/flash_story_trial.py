"""Opt-in DeepSeek Flash story routing with no monetary or HTTP-call caps.

Local Qwen4B handles early video/boundary analysis. DeepSeek handles story,
pacing and framing; genuine API failures fall back to local nonthinking 4B.
Every HTTP dispatch is recorded (including retries), and successful responses
are cached. Legacy provider names and journal file paths remain compatible.
No charge estimate is used to stop production. Enabling this profile sends
selected frames and story text to the external paid API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

from .config import STORY_MODEL, STORY_PROJECTOR, VLM_MODEL, VLM_PROJECTOR
from .jobs import atomic_json

PROFILE = "local4b-deepseek-flash-story-pilot-v1"
# Historical name retained for safe resume of old test jobs, not a cap.
BUDGETED_PROFILE = "local4b-deepseek-flash-story-budgeted-v1"
PEAK_INPUT_USD_PER_MILLION = .30
PEAK_OUTPUT_USD_PER_MILLION = 1.20


def _request_digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _peak_charge(raw):
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if (type(prompt) is not int or type(completion) is not int or
            prompt < 0 or completion < 0):
        return None
    hit, miss = usage.get("prompt_cache_hit_tokens"), usage.get("prompt_cache_miss_tokens")
    if (type(hit) is not int or type(miss) is not int or
            hit < 0 or miss < 0 or hit + miss != prompt):
        hit, miss = 0, prompt
    return round((hit * .006 + miss * PEAK_INPUT_USD_PER_MILLION +
                  completion * PEAK_OUTPUT_USD_PER_MILLION) / 1_000_000, 9)



def routing_profile(budgeted=False):
    from .deepseek import MODEL, PROFILE as REMOTE_PROFILE
    return {
        "provider": "local_flash_story_budgeted" if budgeted else "local_flash_story",
        "profile": BUDGETED_PROFILE if budgeted else PROFILE,
        "early_visual_model": "local4b", "remote_story": MODEL,
        "remote_story_profile": REMOTE_PROFILE,
        "paid_http_attempt_limit": None,
        "estimated_peak_budget_usd": None,
        "on_remote_error": "local4b_conservative_fallback",
        "framing": "flash_or_local4b",
        "pacing": "flash_or_local4b",
    }


class TrialStoryVision:
    supports_image_pages = True

    def __init__(self, job_dir, cancelled, *, local_factory=None, remote_factory=None,
                 budgeted=False, **local_settings):
        from .deepseek import DeepSeekVision
        from .vision import LocalVision
        self.job_dir = Path(job_dir)
        self.cancelled = cancelled
        self.budgeted = bool(budgeted)
        self.profile = BUDGETED_PROFILE if self.budgeted else PROFILE
        self.local_factory = local_factory or LocalVision
        self.remote_factory = remote_factory or DeepSeekVision
        self.local_settings = local_settings
        self.local = None
        self.remote = None
        self.cache_profile = routing_profile(self.budgeted)
        self.thinking = bool(local_settings.get('thinking', True))
        self.cpu_fallback = False
        self.model = STORY_MODEL
        self.projector = STORY_PROJECTOR
        self._guard = threading.RLock()
        self.journal = self.job_dir / ("deepseek-story-budgeted.json" if self.budgeted
                                       else "deepseek-story-pilot.json")
        self._state = {"profile": self.profile, "reserved": [], "fallbacks": 0,
                       "local_cache_hits": 0, "charged_peak_usd": {}}
        if self.journal.is_file():
            try:
                loaded = json.loads(self.journal.read_text("utf-8"))
                if (isinstance(loaded, dict) and loaded.get("profile") == self.profile
                        and isinstance(loaded.get("reserved"), list)
                        and all(isinstance(v, str) and len(v) == 64 for v in loaded["reserved"])):
                    self._state = loaded
                    if (type(self._state.get("local_cache_hits", 0)) is not int
                            or self._state.get("local_cache_hits", 0) < 0):
                        raise ValueError("Некорректный счётчик кэша DeepSeek")
                    self._state.setdefault("local_cache_hits", 0)
                    charges = self._state.setdefault("charged_peak_usd", {})
                    if not isinstance(charges, dict) or any(
                        digest not in self._state["reserved"] or type(value) not in (float, int)
                        or not 0 <= value for digest, value in charges.items()
                    ):
                        raise ValueError("Некорректная история стоимости запросов DeepSeek")
                else:
                    raise ValueError("Некорректная история обращений DeepSeek")
            except (OSError, ValueError, TypeError):
                raise ValueError("Нельзя восстановить историю платных запросов DeepSeek") from None

    def __enter__(self):
        self.job_dir.mkdir(parents=True, exist_ok=True)
        return self

    def _local(self):
        if self.local is None:
            settings = dict(self.local_settings)
            settings.update(model=VLM_MODEL, projector=VLM_PROJECTOR, thinking=False)
            self.local = self.local_factory(self.job_dir, self.cancelled, **settings)
            self.local.__enter__()
        return self.local

    def _remote(self):
        if self.remote is None:
            self.remote = self.remote_factory(self.job_dir, self.cancelled)
            # DeepSeek key is validated when selected at job creation and at
            # first remote use, not on every local 4B boundary invocation.
            self.remote.__enter__()
        return self.remote

    def close(self):
        try:
            if self.remote is not None:
                self.remote.close()
        finally:
            if self.local is not None:
                self.local.close()

    def __exit__(self, *args):
        self.close()

    def token_count(self, text):
        # Same conservative counter used by cloud planning.
        return len(text.encode("utf-8")) + 512

    def _reserve(self, body):
        """Account for every HTTP dispatch. Never gate on dollars or attempts.

        Recording happens BEFORE dispatch, including failed/retried requests.
        Request hashes are intentionally not unique: the provider may retry an
        invalid answer, and the user has not requested a spending ceiling.
        """
        if self.cancelled():
            raise InterruptedError("Обработка отменена")
        digest = _request_digest(body)
        with self._guard:
            self._state["reserved"].append(digest)
            atomic_json(self.journal, self._state)


    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        if self.cancelled():
            raise InterruptedError("Обработка отменена")
        from .deepseek import RemoteError, ResponseContractError, BudgetExceeded
        # KADR's disk cache is free. A real DeepSeek API context-cache hit is
        # cheaper, not free. Cache misses may dispatch without a local cap.
        try:
            remote = self._remote()
            original = remote._fetch
            dispatched = False
            from contextvars import copy_context
            from .model_perf import measure_request
            context = copy_context()

            def measured_dispatch(body):
                messages = body.get("messages") if isinstance(body, dict) else []
                text_size, pages = 0, 0
                for message in messages if isinstance(messages, list) else []:
                    content = message.get("content") if isinstance(message, dict) else None
                    if isinstance(content, str):
                        text_size += len(content)
                    elif isinstance(content, list):
                        for part in content:
                            if not isinstance(part, dict):
                                continue
                            if part.get("type") == "text":
                                text_size += len(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                pages += 1
                with measure_request(self.job_dir, "deepseek-flash", pages=pages,
                                     prompt_chars=text_size, max_tokens=body.get("max_tokens", 0),
                                     thinking=False, cpu=False) as trace:
                    raw = original(body)
                    trace.response(raw)
                    measured = _peak_charge(raw)
                    if measured is not None:
                        with self._guard:
                            digest = _request_digest(body)
                            # A reported response may still fail JSON verification.
                            # This is diagnostics only; never blocks more requests.
                            self._state["charged_peak_usd"][digest] = measured
                            atomic_json(self.journal, self._state)
                    return raw

            def one_dispatch(body):
                nonlocal dispatched
                self._reserve(body)
                dispatched = True
                return context.run(measured_dispatch, body)
            remote._fetch = one_dispatch
            try:
                answer = remote.query(prompt, image, max_tokens=max_tokens, schema=schema)
                if not dispatched:
                    # The full response was served by KADR's local disk cache.
                    # DeepSeek's discounted context-cache is NOT free.
                    with self._guard:
                        self._state["local_cache_hits"] += 1
                        atomic_json(self.journal, self._state)
                return answer
            finally:
                remote._fetch = original
        except InterruptedError:
            raise
        except (BudgetExceeded, RemoteError, ResponseContractError, OSError, ValueError):
            # A failed cloud answer is never accepted as story evidence.
            pass
        with self._guard:
            self._state["fallbacks"] += 1
            atomic_json(self.journal, self._state)
        return self._local().query(prompt, image, max_tokens=max_tokens, schema=schema)
