"""A launcher must detect changed engine code and every active UI asset."""
from pathlib import Path
import shutil
import uuid
from unittest.mock import patch

from app import studio_identity as identity
from app.config import TEMP


def test_fingerprint_detects_worker_and_analysis_updates_and_new_modules():
    directory = TEMP / ('identity_' + uuid.uuid4().hex)
    try:
        (directory / 'app').mkdir(parents=True)
        for name in (*identity._BACKEND, 'app/worker.py', 'app/analysis.py'):
            (directory / name).write_text('original', encoding='utf-8')
        with patch.object(identity, 'ROOT', directory):
            previous = identity.backend_fingerprint()
            assert previous is not None
            for name in ('app/worker.py', 'app/analysis.py', 'app/new_module.py'):
                (directory / name).write_text('updated', encoding='utf-8')
                current = identity.backend_fingerprint()
                assert current != previous
                previous = current
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_every_canonical_ui_file_changes_browser_cache_identity():
    directory = TEMP / ('identity_' + uuid.uuid4().hex)
    try:
        (directory / 'frontend/dist').mkdir(parents=True)
        for name in identity._UI:
            (directory / name).write_text('original', encoding='utf-8')
        with patch.object(identity, 'ROOT', directory):
            previous = identity.ui_fingerprint()
            for name in identity._UI:
                (directory / name).write_text('updated', encoding='utf-8')
                current = identity.ui_fingerprint()
                assert current != previous
                previous = current
            (directory / identity._UI[-1]).unlink()
            assert identity.ui_fingerprint() is None
    finally:
        shutil.rmtree(directory, ignore_errors=True)
