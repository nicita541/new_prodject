"""Private, append-only local VLM performance measurements.

No prompts, frames, local paths, model filenames, responses or error messages.
A START record persists even if Windows terminates the process at timeout.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time
import uuid

_PURPOSE = ContextVar("kadr_model_purpose", default="general")
_ALLOWED = frozenset(("general", "semantic_boundary", "scene_analysis",
    "story_refinement", "choose_units", "verify_omissions",
    "credit_classifier", "global_story", "global_visual", "source_roles",
    "titles", "framing", "pacing"))
_LOCK = threading.Lock()


def model_alias(model):
    from .config import STORY_MODEL, VLM_MODEL
    candidate = Path(model)
    if str(model) == "deepseek-flash":
        return "deepseek_flash"
    return "story9b" if candidate == STORY_MODEL else (
        "visual4b" if candidate == VLM_MODEL else "other")


def metric(value):
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e9:
        return round(float(value), 4)
    return None


def _append(job_dir, row):
    if job_dir is None:
        return
    try:
        path = Path(job_dir) / "model-performance.jsonl"
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps({
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    **row,
                }, allow_nan=False, sort_keys=True) + "\n")
                stream.flush()
    except (OSError, TypeError, ValueError):
        pass


@contextmanager
def purpose(name):
    if name not in _ALLOWED:
        raise ValueError("Unrecognized model performance stage")
    token = _PURPOSE.set(name)
    try:
        yield
    finally:
        _PURPOSE.reset(token)


def model_started(job_dir, model, seconds, cpu, status):
    _append(job_dir, {
        "event": "startup", "model": model_alias(model),
        "seconds": metric(seconds), "cpu": bool(cpu),
        "status": status if status in ("ok", "fallback", "timeout") else "failed",
    })


class RequestTrace:
    def __init__(self, job_dir, model, *, pages, prompt_chars, max_tokens, thinking, cpu):
        self.job_dir = job_dir
        self.id = uuid.uuid4().hex
        self.model = model_alias(model)
        self.stage = _PURPOSE.get()
        self.started = time.perf_counter()
        self.details = {}
        self.retried = False
        _append(job_dir, {
            "event": "request_start", "id": self.id, "model": self.model,
            "stage": self.stage, "pages": metric(pages),
            "prompt_chars": metric(prompt_chars), "max_tokens": metric(max_tokens),
            "thinking": bool(thinking), "cpu": bool(cpu),
        })

    def response(self, raw):
        if not isinstance(raw, dict):
            return
        usage = raw.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                self.details[key] = metric(usage.get(key))
        if isinstance(usage, dict):
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                self.details["reasoning_tokens"] = metric(details.get("reasoning_tokens"))
        choices = raw.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            reason = choices[0].get("finish_reason")
            if reason in ("stop", "length", "tool_calls", "content_filter"):
                self.details["finish_reason"] = reason
        timings = raw.get("timings")
        if isinstance(timings, dict):
            for key in ("prompt_ms", "predicted_ms", "prompt_n", "predicted_n"):
                self.details[key] = metric(timings.get(key))

    def close(self, status):
        _append(self.job_dir, {
            "event": "request_end", "id": self.id, "model": self.model,
            "stage": self.stage, "seconds": metric(time.perf_counter()-self.started),
            "status": status, **self.details,
        })


@contextmanager
def measure_request(job_dir, model, *, pages, prompt_chars, max_tokens, thinking, cpu):
    trace = RequestTrace(job_dir, model, pages=pages, prompt_chars=prompt_chars,
                         max_tokens=max_tokens, thinking=thinking, cpu=cpu)
    try:
        yield trace
    except BaseException as error:
        trace.close("cancelled" if isinstance(error, (KeyboardInterrupt, InterruptedError)) else "failed")
        raise
    else:
        trace.close("retried" if trace.retried else "ok")
