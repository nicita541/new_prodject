"""Explicit, limited DeepSeek Flash pilot for the STORY model only.

The normal 4B frame/boundary analysis is always local. Unlike 'deepseek_plan',
this pilot offloads only the former 9B story calls. At most 8 HTTP dispatches
per job, including rejected JSON/retries/timeouts and process restarts. A
remote failure falls back to the original local 9B model, without inventing a
story decision or silently accepting invalid schema.

This is a CALL cap, NOT a USD billing guarantee: images, long prompts and
DeepSeek token rates affect actual charges. Never enable by default.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

from .config import STORY_MODEL, STORY_PROJECTOR
from .jobs import atomic_json

PROFILE = "local4b-deepseek-flash-story-pilot-v1"
MAX_PAID_ATTEMPTS = 8


def routing_profile():
    from .deepseek import MODEL, PROFILE as REMOTE_PROFILE
    return {
        "provider": "local_flash_story", "profile": PROFILE,
        "early_visual_model": "local4b", "remote_story": MODEL,
        "remote_story_profile": REMOTE_PROFILE,
        "paid_http_attempt_limit": MAX_PAID_ATTEMPTS,
        "after_limit": "local9b_fallback",
        "framing": "local9b",
        "pacing": "local9b",
    }


class TrialStoryVision:
    supports_image_pages = True

    def __init__(self, job_dir, cancelled, *, local_factory=None, remote_factory=None, **local_settings):
        from .deepseek import DeepSeekVision
        from .vision import LocalVision
        self.job_dir = Path(job_dir)
        self.cancelled = cancelled
        self.local_factory = local_factory or LocalVision
        self.remote_factory = remote_factory or DeepSeekVision
        self.local_settings = local_settings
        self.local = None
        self.remote = None
        self.cache_profile = routing_profile()
        self.thinking = bool(local_settings.get('thinking', True))
        self.cpu_fallback = False
        self.model = STORY_MODEL
        self.projector = STORY_PROJECTOR
        self._guard = threading.RLock()
        self.journal = self.job_dir / "deepseek-story-pilot.json"
        self._state = {"profile": PROFILE, "reserved": [], "fallbacks": 0}
        if self.journal.is_file():
            try:
                loaded = json.loads(self.journal.read_text("utf-8"))
                if (isinstance(loaded, dict) and loaded.get("profile") == PROFILE
                        and isinstance(loaded.get("reserved"), list)
                        and len(loaded["reserved"]) <= MAX_PAID_ATTEMPTS
                        and all(isinstance(v, str) and len(v) == 64 for v in loaded["reserved"])):
                    self._state = loaded
                else:
                    raise ValueError("Некорректная история обращений DeepSeek")
            except (OSError, ValueError, TypeError):
                raise ValueError("Нельзя восстановить историю платных запросов DeepSeek") from None

    def __enter__(self):
        self.job_dir.mkdir(parents=True, exist_ok=True)
        return self

    def _local(self):
        if self.local is None:
            self.local = self.local_factory(self.job_dir, self.cancelled, **self.local_settings)
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
        if self.cancelled():
            raise InterruptedError("Обработка отменена")
        from .deepseek import BudgetExceeded
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        with self._guard:
            if digest in self._state["reserved"]:
                raise BudgetExceeded("Повтор платного запроса после неизвестного исхода запрещён")
            if len(self._state["reserved"]) >= MAX_PAID_ATTEMPTS:
                raise BudgetExceeded("Лимит пробных обращений DeepSeek достигнут")
            # Persist before dispatch: an interrupted/failed HTTP call may
            # still have been billed, so it reserves a slot permanently.
            self._state["reserved"].append(digest)
            atomic_json(self.journal, self._state)

    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        if self.cancelled():
            raise InterruptedError("Обработка отменена")
        from .deepseek import BudgetExceeded, RemoteError, ResponseContractError
        # DeepSeek may serve a FREE cached reply even after the trial HTTP
        # allowance is exhausted. Actual paid dispatches remain guarded by
        # the durable _reserve check; a cache miss falls back to local 9B.
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
                    return raw

            def one_dispatch(body):
                nonlocal dispatched
                if dispatched:
                    raise BudgetExceeded("Пробный режим не повторяет платный запрос")
                self._reserve(body)
                dispatched = True
                return context.run(measured_dispatch, body)
            remote._fetch = one_dispatch
            try:
                return remote.query(prompt, image, max_tokens=max_tokens, schema=schema)
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
