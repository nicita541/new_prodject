"""Manager ownership survives incomplete finishing shutdown and damaged legacy state."""
import uuid
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.file_lock import BusyError, InstanceLock
from app.finishing_commands import CommandError, FinishingCommands
from app.jobs import JobManager
from tests.test_jobs import FakeWorker


def test_incomplete_finishing_shutdown_retains_server_lock_and_close_can_retry(tmp_path):
    manager = JobManager(tmp_path, FakeWorker)
    try:
        with patch('app.studio_render.stop_finishing_tasks', side_effect=[False, True]):
            assert manager.close() is False
            with pytest.raises(BusyError):
                InstanceLock(tmp_path/'data/.server.lock')
            assert manager.close() is True
        replacement = InstanceLock(tmp_path/'data/.server.lock')
        replacement.close()
    finally:
        # Mocked successful stop did not actually stop its test scheduler.
        manager.finishing_execution.stop()
        manager.close()


def test_corrupt_legacy_finishing_status_does_not_abort_startup_or_rewrite_it(tmp_path):
    path = tmp_path/'data/jobs'/str(uuid.uuid4())/'finishing/exports'/('ex_'+uuid.uuid4().hex)/'status.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{corrupt original legacy record')
    original = path.read_bytes()
    manager = JobManager(tmp_path, FakeWorker)
    try:
        assert path.read_bytes() == original
    finally:
        manager.close()


@pytest.mark.skipif(os.name != 'nt', reason='Windows realpath namespace normalization')
@pytest.mark.parametrize('outside', [False, True])
def test_windows_extended_resolution_names_same_owner_but_cannot_escape(tmp_path, outside):
    store = FinishingCommands(tmp_path/'owner')
    relative = 'parts/new-pointer.json'
    target = store.root/relative
    original = Path.resolve
    resolved = Path('\\\\?\\'+str(tmp_path/'other-owner/new-pointer.json' if outside else target))

    def racing_resolution(path, *args, **kwargs):
        return resolved if path == target else original(path, *args, **kwargs)

    with patch.object(Path, 'resolve', racing_resolution):
        if outside:
            with pytest.raises(CommandError, match='escape or redirect'):
                store._path(relative)
        else:
            assert store._path(relative) == target
