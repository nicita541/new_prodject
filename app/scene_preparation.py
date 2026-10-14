"""One bounded CURRENT-image lookahead; model calls stay on the coordinator."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

from .cancellation import check_cancelled


class CurrentPreparation:
    def __init__(self, chunks, prepare, cancelled):
        self.chunks = iter(chunks)
        self.prepare, self.cancelled = prepare, cancelled
        self.stop = Event()
        self.executor = None
        self.future = None

    def __enter__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='storyboard')
        self._submit()
        return self

    def _cancelled(self):
        return self.stop.is_set() or self.cancelled()

    def _run(self, chunk):
        check_cancelled(self._cancelled)
        started = time.monotonic()
        result = self.prepare(chunk, self._cancelled)
        check_cancelled(self._cancelled)
        return chunk, result, time.monotonic() - started

    def _submit(self):
        chunk = next(self.chunks, None)
        self.future = self.executor.submit(self._run, chunk) if chunk is not None else None

    def take(self, key):
        if self.future is None:
            raise RuntimeError('Missing CURRENT preparation')
        while not self.future.done():
            check_cancelled(self.cancelled)
            self.stop.wait(.05)
        check_cancelled(self.cancelled)
        chunk, result, elapsed = self.future.result()
        if chunk['key'] != key:
            raise RuntimeError('CURRENT preparation ownership mismatch')
        self.future = None
        return result, elapsed

    def advance(self):
        """Start lookahead after foreground context preparation, just before inference."""
        if self.future is not None:
            raise RuntimeError('CURRENT preparation is already pending')
        self._submit()

    def __exit__(self, *args):
        self.stop.set()
        if self.future is not None:
            self.future.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)
