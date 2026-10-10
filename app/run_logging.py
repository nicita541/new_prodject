"""Privacy-conscious local operational logs, shared by Studio and worker processes.

logs/studio/<session> or logs/tests/<session>:
  README.txt         file map
  session.json       startup metadata
  events-<pid>.jsonl structured timestamped events
  readable-<pid>.log human-readable errors and progress

Never capture HTTP bodies, user-typed text, headers, source video or AI prompts.
Existing per-job diagnostics and FFmpeg logs remain in the job directory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import traceback
import uuid

from .config import ROOT

_LOCK = threading.RLock()
_CURRENT = None
_PID = None
_SECRET = re.compile(
    r"(?i)(?:authorization\s*[:=]\s*(?:bearer|basic)\s+[^\s,;&]+|"
    r"bearer\s+[^\s,;&]+|"
    r"(?:sk-|github_pat_|gh[pousr]_)[A-Za-z0-9_.-]{8,})|"
    r"((?:api[_-]?key|access[_-]?token|password|secret|authorization)\s*[:=]\s*)"
    r"([^\s,;&]+)"
)
_MAX_MESSAGE = 1200


def scrub(value, limit: int = _MAX_MESSAGE) -> str:
    value = str(value)
    def replace(match):
        return (match.group(1) + "[REDACTED]") if match.group(1) else "[REDACTED]"
    return _SECRET.sub(replace, value)[:limit]


def _session_dir(kind: str) -> Path:
    kind = kind if kind in {"studio", "tests"} else "studio"
    base = (ROOT / "logs").resolve()
    base.mkdir(parents=True, exist_ok=True)
    inherited = os.environ.get("KADR_LOG_DIR", "")
    if inherited:
        try:
            path = Path(inherited).resolve()
            if path.is_relative_to(base) and path.is_dir():
                return path
        except (ValueError, OSError):
            pass
    token = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = base / kind / (token + "_" + str(os.getpid()) + "_" + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path


class _SafeFormatter(logging.Formatter):
    def format(self, record):
        message = scrub(record.getMessage())
        if record.exc_info:
            details = "".join(traceback.format_exception(*record.exc_info))
            message += "\n" + scrub(details, 12000)
        return message


class _JsonlHandler(logging.Handler):
    def __init__(self, path: Path):
        super().__init__(logging.DEBUG)
        self.file = path.open("a", encoding="utf-8", buffering=1)

    def emit(self, record):
        try:
            event = {
                "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname, "component": record.name,
                "pid": os.getpid(), "message": scrub(record.getMessage()),
            }
            for key in ("job_id", "stage", "action", "elapsed_ms", "status", "run_id",
                        "http_method", "http_route", "http_status", "trace_id",
                        "detail_log", "progress", "tool_name", "code"):
                if hasattr(record, key):
                    value = getattr(record, key)
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        event[key] = scrub(value) if isinstance(value, str) else value
            if record.exc_info:
                event["exception_type"] = record.exc_info[0].__name__
                event["traceback"] = scrub("".join(traceback.format_exception(*record.exc_info)), 12000)
            self.file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            self.file.close()
        finally:
            super().close()


def configure_logging(kind: str = "studio") -> Path:
    """Idempotent per process; subprocesses share the folder, not file handles."""
    global _CURRENT, _PID
    with _LOCK:
        if _CURRENT is not None and _PID == os.getpid():
            return _CURRENT
        folder = _session_dir(kind)
        os.environ["KADR_LOG_DIR"] = str(folder)
        try:
            (ROOT / "logs" / "LATEST.txt").write_text(
                str(folder.relative_to(ROOT)).replace("\\", "/") + "\n",
                encoding="utf-8")
        except OSError:
            # A read-only index must not prevent collecting actual session logs.
            pass
        folder.joinpath("README.txt").write_text(
            "KADR Studio diagnostic session (local only)\n"
            "events-*.jsonl : ordered structured events, search by job_id, stage, level\n"
            "readable-*.log : readable messages and error tracebacks\n"
            "session.json   : runtime info without credentials\n"
            "Job details: data/jobs/<job_id>/diagnostics/pipeline/timeline.jsonl\n"
            "FFmpeg logs: data/jobs/<job_id>/render/**/process_*.log\n"
            "No HTTP bodies, UI form values, prompts or credentials are intentionally recorded.\n",
            encoding="utf-8")
        if not folder.joinpath("session.json").exists():
            folder.joinpath("session.json").write_text(json.dumps({
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "kind": kind, "created_by_pid": os.getpid(),
                "logs_relative": str(folder.relative_to(ROOT)).replace("\\", "/")
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger = logging.getLogger("app")
        logger.setLevel(logging.INFO)
        json_handler = _JsonlHandler(folder / f"events-{os.getpid()}.jsonl")
        logger.addHandler(json_handler)
        readable = logging.FileHandler(folder / f"readable-{os.getpid()}.log",
                                       encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)sZ [%(levelname)s] %(name)s: %(message)s")
        import time
        formatter.converter = time.gmtime
        readable.setFormatter(formatter)
        # Scrub final output too, including exceptions logged by other modules.
        readable.addFilter(_ScrubFilter())
        logger.addHandler(readable)
        _CURRENT, _PID = folder, os.getpid()
        logger.info("Session initialized", extra={"action": "session_start", "run_id": folder.name})
        return folder


class _ScrubFilter(logging.Filter):
    def filter(self, record):
        cloned = scrub(record.getMessage())
        record.msg = cloned
        record.args = ()
        if record.exc_info:
            # The JSON handler retains the redacted formatted traceback;
            # prevent FileHandler from appending raw exception arguments.
            record.exc_text = scrub("".join(traceback.format_exception(*record.exc_info)), 12000)
            record.exc_info = None
        return True


def event(level: int, message: str, **fields):
    """Use a structured event without retaining arbitrary dictionaries."""
    configure_logging()
    logging.getLogger("app.telemetry").log(level, message, extra=fields)
