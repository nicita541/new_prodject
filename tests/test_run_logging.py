"""Operational logs must be searchable, local, and never retain credentials."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import uuid

from fastapi.testclient import TestClient

from app import config
from app.jobs import JobManager
from app.run_logging import configure_logging, scrub
from app.server import create_app


def test_credentials_are_redacted_even_in_freeform_error_and_stack():
    sample = ("Authorization=Bearer secretsuperlongvalue "
              "api_key=really-secret-123456 and sk-reallysecretvalue123 "
              "github_pat_abc123verysecretkey")
    filtered = scrub(sample)
    for secret in ("secretsuperlongvalue", "really-secret-123456",
                   "sk-reallysecretvalue123", "github_pat_abc123verysecretkey"):
        assert secret not in filtered
    assert "[REDACTED]" in filtered


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
