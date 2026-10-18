"""Shared lock compatibility and OS release; no manager or model execution."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

from app import config
from app.file_lock import BusyError, InstanceLock


class FileLockTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP/('file-lock-test-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.path = self.root/'nested/owner.lock'

    def tearDown(self):
        self.root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(self.root)

    def test_jobs_compatibility_exports_keep_identical_class_identity(self):
        from app import jobs
        self.assertIs(jobs.BusyError, BusyError)
        self.assertIs(jobs.InstanceLock, InstanceLock)
        self.assertTrue(issubclass(jobs.SubmissionConflict, BusyError))

    def test_second_owner_is_blocked_until_close_and_close_is_idempotent(self):
        first = InstanceLock(self.path)
        try:
            with self.assertRaises(BusyError):
                InstanceLock(self.path)
        finally:
            first.close()
        first.close()
        second = InstanceLock(self.path)
        second.close()

    def test_operating_system_releases_child_lock_after_abrupt_exit(self):
        code = ('from pathlib import Path; import os, sys; '
                'from app.file_lock import InstanceLock; '
                'lock = InstanceLock(Path(sys.argv[1])); os._exit(0)')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.path)],
            cwd=config.ROOT, capture_output=True, timeout=10, **options)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        owner = InstanceLock(self.path)
        owner.close()


if __name__ == '__main__':
    unittest.main()
