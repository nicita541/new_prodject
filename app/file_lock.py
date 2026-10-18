"""Small OS-backed exclusive lock shared by lifecycle and command storage.

Importing this module does not construct a manager, perform recovery, or launch
workers. ``app.jobs`` retains compatibility re-exports of these same classes.
"""
from __future__ import annotations

import os
from pathlib import Path


class BusyError(RuntimeError):
    pass


class InstanceLock:
    """OS-backed lock; a crashed server automatically releases ownership."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            self.stream.close()
            raise BusyError("Приложение уже запущено в другом окне") from None

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


