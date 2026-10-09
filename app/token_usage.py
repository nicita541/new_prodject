"""Actual completion-token accounting for local llama.cpp and DeepSeek.

No prompts/images, keys, or raw model responses are saved here. Each successful
HTTP completion envelope is recorded once, including rejected JSON and retries:
those calls have already consumed tokens. A cached answer consumes zero new
tokens. Missing provider usage is unknown, never guessed.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def record(job_dir: Path, provider: str, model: str, response: dict):
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return
    numbers = {key: value for key in FIELDS
               if (value := usage.get(key)) is not None
               and type(value) is int and value >= 0}
    if not numbers:
        return
    if "total_tokens" not in numbers:
        numbers["total_tokens"] = numbers.get("prompt_tokens", 0) + numbers.get("completion_tokens", 0)
    entry = {"provider": provider, "model": model,
             "timestamp": datetime.now(timezone.utc).isoformat(), **numbers}
    path = Path(job_dir) / "token-usage.jsonl"
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()


def summary(job_dir: Path):
    path = Path(job_dir) / "token-usage.jsonl"
    totals = {name: {"prompt_tokens": 0, "completion_tokens": 0,
                     "total_tokens": 0, "calls": 0} for name in ("local", "deepseek")}
    totals["unknown_calls"] = 0
    if not path.is_file():
        return {"version": 1, **totals, "all_tokens": 0}
    with _LOCK:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                provider = row.get("provider")
                if provider not in ("local", "deepseek"):
                    continue
                totals[provider]["calls"] += 1
                for key in FIELDS:
                    value = row.get(key)
                    if type(value) is int and value >= 0:
                        totals[provider][key] += value
    return {"version": 1, **totals,
            "all_tokens": totals["local"]["total_tokens"] + totals["deepseek"]["total_tokens"]}
