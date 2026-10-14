"""Bounded independent refinement producers; one coordinator owns file exchange."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from queue import Empty, Queue
import threading
import time


def text_batch_limits(vision, stage, units, output_tokens):
    """Only an explicit provider text scope opts in; legacy providers keep policy."""
    profile = getattr(vision, 'text_batch_limits', None)
    selected = profile.get(stage) if isinstance(profile, dict) else None
    if not isinstance(selected, dict):
        return units, output_tokens
    count, budget = selected.get('units'), selected.get('output_tokens')
    if type(count) is not int or not 1 <= count <= 12 or type(budget) is not int or not 1 <= budget <= 9600:
        raise ValueError('Invalid bounded cloud text batch profile')
    return count, budget


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


def refine_in_batches(events, transcript, shots, job_dir, vision, report, cancelled, refiner, *, episode_duration=None):
    if not events:
        return []
    duration = max(event['end'] for event in events) if episode_duration is None else episode_duration
    def work(event, proxy, stop_check):
        # Original per-child logic and episode edge tests remain intact.
        # Worker threads never report through the multiprocessing status pipe.
        return refiner([event], transcript, shots, job_dir, proxy, lambda *args: None,
            stop_check, episode_duration=duration)[0]
    def progress(completed, total):
        report('condense', .47+.019*completed/total,
            f'Сокращение по репликам: сцена {min(total, completed+1)} из {total}')
    return run_independent_batches(events, vision, cancelled, work, progress)


def adjudicate_in_batches(source, events, transcript, shots, job_dir, vision, report, cancelled,
                         *, refiner, source_only=False):
    """Batch independent events through the unchanged native per-event gate.

    Native exclusions and readiness operate only on each event. Keeping the
    gate module untouched preserves early-vision semantic cache identities.
    """
    if not getattr(vision, 'supports_query_batch', False):
        return refiner(source, events, transcript, shots, job_dir, vision, report,
                       cancelled, source_only=source_only)
    import copy
    if len({event['id'] for event in events}) != len(events):
        raise ValueError('Пакетная проверка требует уникальных событий')
    def work(event, proxy, stop_check):
        return refiner(source, [copy.deepcopy(event)], transcript, shots, job_dir,
            proxy, lambda *args: None, stop_check, source_only=source_only)[0]
    def progress(completed, total):
        report('analyze', .5, f'Проверка конкретного выбора · обработано событий: {completed} из {total}')
    return run_independent_batches(events, vision, cancelled, work, progress)


def review_events_in_batches(events, transcript, shots, job_dir, vision, report, cancelled,
                            *, refiner, label, full_context=False):
    """Use unchanged event proofs; retain the complete original neighbor context.

    Full-context refiners explicitly select an event, rather than receiving a
    singleton episode that changes duration, prior story or neighbor evidence.
    """
    if getattr(vision, 'supports_query_batch', False) is not True:
        return refiner(events, transcript, shots, job_dir, vision, report, cancelled)
    if len({event['id'] for event in events}) != len(events):
        raise ValueError('Пакетная проверка требует уникальных событий')
    import copy
    def work(index, proxy, stop_check):
        if full_context:
            return refiner(events, transcript, shots, job_dir, proxy,
                lambda *args: None, stop_check, event_ids={events[index]['id']})[index]
        return refiner([copy.deepcopy(events[index])], transcript, shots, job_dir,
            proxy, lambda *args: None, stop_check)[0]
    def progress(completed, total):
        report('condense', .49, f'{label} · обработано событий: {completed} из {total}')
    spans = sorted((event['start'], event['end']) for event in events)
    if any(right > following for (_, right), (following, _) in zip(spans, spans[1:])):
        # Legacy overlapping events can name the same native image/cache files.
        return refiner(events, transcript, shots, job_dir, vision, report, cancelled)
    return run_independent_batches(list(range(len(events))), vision, cancelled, work, progress)


def closing_in_batches(events, transcript, shots, job_dir, vision, report, cancelled, *, refiner):
    from .closing import _ending_anchor
    duration = max((event['end'] for event in events), default=0)
    if not any(_ending_anchor(event, duration) for event in events):
        # Accepted omissions can establish the anchor used by later events.
        return refiner(events, transcript, shots, job_dir, vision, report, cancelled)
    return review_events_in_batches(events, transcript, shots, job_dir, vision, report,
        cancelled, refiner=refiner, label='Проверка новых событий в финале', full_context=True)


def run_independent_batches(items, vision, cancelled, work, progress):
    """Preserve item logic/order; only the coordinator drives physical queries."""
    if not items:
        return []
    queue, stopped = Queue(), threading.Event()
    proxy = _QueryProducer(vision, queue, stopped, cancelled)
    stop_check = lambda: stopped.is_set() or cancelled()
    results, completed = [None] * len(items), set()
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='kadr-contract')
    futures = [pool.submit(copy_context().run, work, item, proxy, stop_check) for item in items]
    try:
        progress(0, len(items))
        reported = 0
        while len(completed) < len(items):
            if cancelled():
                raise InterruptedError('Обработка отменена')
            for index, future in enumerate(futures):
                if index not in completed and future.done():
                    results[index] = future.result()
                    completed.add(index)
            if len(completed) != reported:
                reported = len(completed)
                progress(reported, len(items))
            if len(completed) == len(items):
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
        return results
    finally:
        stopped.set()
        pool.shutdown(wait=True, cancel_futures=True)
