"""Bounded independent refinement producers; one coordinator owns file exchange."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
import threading
import time


class _QueryProducer:
    def __init__(self, vision, queue, stopped, cancelled):
        self.vision, self.queue, self.stopped, self.cancelled = vision, queue, stopped, cancelled

    def __getattr__(self, name):
        return getattr(self.vision, name)

    def query(self, prompt, image=None, max_tokens=1200, schema=None, *, thinking_override=None):
        from .model_perf import _PURPOSE
        reply = Future()
        self.queue.put(({'prompt': prompt, 'image': image, 'max_tokens': max_tokens,
            'schema': schema, 'thinking_override': thinking_override, 'purpose': _PURPOSE.get()}, reply))
        while not reply.done():
            if self.stopped.is_set() or self.cancelled():
                raise InterruptedError('Обработка отменена')
            self.stopped.wait(.05)
        return reply.result()


def refine_in_batches(events, transcript, shots, job_dir, vision, report, cancelled, refiner):
    if not events:
        return []
    queue, stopped = Queue(), threading.Event()
    proxy = _QueryProducer(vision, queue, stopped, cancelled)
    duration = max(event['end'] for event in events)
    results, completed = [None] * len(events), set()
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='kadr-contract')
    def work(event):
        # Original per-child logic and episode edge tests remain intact.
        # Worker threads never report through the multiprocessing status pipe.
        return refiner([event], transcript, shots, job_dir, proxy, lambda *args: None,
            lambda: stopped.is_set() or cancelled(), episode_duration=duration)[0]
    futures = [pool.submit(work, event) for event in events]
    try:
        report('condense', .47, f'Сокращение по репликам: сцена 1 из {len(events)}')
        while len(completed) < len(events):
            if cancelled():
                raise InterruptedError('Обработка отменена')
            for index, future in enumerate(futures):
                if index not in completed and future.done():
                    results[index] = future.result()
                    completed.add(index)
            if len(completed) == len(events):
                break
            try:
                first = queue.get(timeout=.05)
            except Empty:
                continue
            pending = [first]
            deadline = time.monotonic() + .15
            while len(pending) < 4 and time.monotonic() < deadline:
                try:
                    pending.append(queue.get(timeout=max(.001, deadline-time.monotonic())))
                except Empty:
                    break
            # Only this thread waits for the separately launched CLI.
            answers = vision.query_many([request for request, _ in pending])
            if len(answers) != len(pending):
                raise ValueError('Пакет не покрыл все независимые запросы')
            for (_, reply), answer in zip(pending, answers, strict=True):
                reply.set_result(answer)
            report('condense', .47+.019*len(completed)/len(events),
                f'Сокращение по репликам: сцена {min(len(events), len(completed)+1)} из {len(events)}')
        return results
    finally:
        stopped.set()
        pool.shutdown(wait=True, cancel_futures=True)
