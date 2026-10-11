"""Operational logs must be searchable, local, and never retain credentials."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient

from app import config
from app.jobs import JobManager
from app.run_logging import configure_logging, scrub
from app.server import create_app


def test_logging_reopens_owned_handlers_after_external_dictconfig_or_close():
    """Use subprocesses: dictConfig also closes pytest's own capture handlers."""
    script = r'''
import json, logging, logging.config, os, sys
from app.run_logging import configure_logging
folder = configure_logging('tests')
logger = logging.getLogger('app.logging_reinit_probe')
logger.info('before reconfiguration', extra={'action': 'before_probe'})
mode = sys.argv[1]
if mode == 'uvicorn':
    import uvicorn
    uvicorn.Config('app.server:app', host='127.0.0.1', port=8765, access_log=False)
elif mode == 'dictconfig':
    logging.config.dictConfig({'version': 1, 'disable_existing_loggers': False,
                              'handlers': {}, 'loggers': {}})
else:
    next(h for h in logging.getLogger('app').handlers if hasattr(h, 'file')).close()
assert configure_logging('tests') == folder
assert configure_logging('tests') == folder
logger.info('after reconfiguration', extra={'action': 'after_probe'})
rows = [json.loads(line) for line in (folder / f'events-{os.getpid()}.jsonl').read_text('utf-8').splitlines()]
assert sum(row.get('action') == 'before_probe' for row in rows) == 1
assert sum(row.get('action') == 'after_probe' for row in rows) == 1
readable = (folder / f'readable-{os.getpid()}.log').read_text('utf-8')
assert readable.count('before reconfiguration') == 1
assert readable.count('after reconfiguration') == 1
assert len(logging.getLogger('app').handlers) == 2
print('PASS logging reinitialization:', mode)
'''
    for mode in ('dictconfig', 'uvicorn', 'one_closed'):
        folder = config.ROOT / 'logs' / 'tests' / ('logging-reinit-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        env = dict(os.environ, KADR_LOG_DIR=str(folder))
        result = subprocess.run([sys.executable, '-c', script, mode], cwd=config.ROOT,
                                env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Logging error' not in result.stderr, result.stderr


def test_credentials_are_redacted_even_in_freeform_error_and_stack():
    sample = ("Authorization=Bearer secretsuperlongvalue "
              "api_key=really-secret-123456 and sk-reallysecretvalue123 "
              "github_pat_abc123verysecretkey")
    filtered = scrub(sample)
    for secret in ("secretsuperlongvalue", "really-secret-123456",
                   "sk-reallysecretvalue123", "github_pat_abc123verysecretkey"):
        assert secret not in filtered
    assert "[REDACTED]" in filtered


def test_credentials_are_redacted_in_json_and_python_dict_errors():
    sample = ('{"api_key": "json-secret-123", "password": "two words", '
              '"Authorization": "Bearer auth-secret-123"} '
              "{'access_token': 'dict-secret-123'}")
    filtered = scrub(sample)
    for secret in ('json-secret-123', 'two words', 'auth-secret-123', 'dict-secret-123'):
        assert secret not in filtered
    assert 'tail-of-secret' not in scrub(r'{"password":"escaped\"tail-of-secret"}')


def test_structured_and_readable_logs_include_timed_correlated_stage():
    root = configure_logging("tests")
    assert root.is_relative_to(config.ROOT / "logs")
    assert (root / "session.json").is_file()
    assert (root / "README.txt").is_file()
    job_id = str(uuid.uuid4())
    logger = logging.getLogger("app.test_logging")
    logger.info("QA event API_KEY=secret-test-789",
                extra={"action": "integration_stage", "job_id": job_id,
                       "stage": "transcribe", "elapsed_ms": 12.5})
    jsonl = root / f"events-{__import__('os').getpid()}.jsonl"
    rows = [json.loads(s) for s in jsonl.read_text("utf-8").splitlines()]
    row = next(item for item in rows if item.get("job_id") == job_id)
    assert row["stage"] == "transcribe"
    assert row["action"] == "integration_stage"
    assert row["elapsed_ms"] == 12.5
    assert "secret-test-789" not in jsonl.read_text("utf-8")
    readable = root / f"readable-{__import__('os').getpid()}.log"
    assert readable.is_file()
    assert "secret-test-789" not in readable.read_text("utf-8")


def test_client_diagnostics_and_http_traces_exclude_user_input():
    root = config.TEMP / ("qa-logging-" + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    manager = JobManager(root)
    try:
        with TestClient(create_app(manager), base_url="http://127.0.0.1:8765") as client:
            response = client.post("/api/diagnostics/client", json={
                "kind": "ui_error", "action": "runtime",
                "message": "Failed, password=never-log-this", "line": 34})
            assert response.status_code == 204, response.text
            response = client.get("/api/health")
            assert response.status_code == 200
            assert client.post("/api/diagnostics/client", json={
                "kind": "ui_action", "action": "nav",
                "message": "", "line": 0, "form_values": {"password": "private"}
            }).status_code == 422
        folder = configure_logging("studio")
        text = (folder / f"events-{__import__('os').getpid()}.jsonl").read_text("utf-8")
        assert "never-log-this" not in text
        assert '"action": "ui_error"' in text
        assert '"http_route": "/api/health"' in text
        assert "form_values" not in text
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
