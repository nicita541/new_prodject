"""Measure genuine local production on isolated excerpts, without paid providers.

Uses the existing production observer and preserves semantic quality gates.
Audit output deliberately excludes prompts, transcripts, frames and API keys.
The job directory still holds private production evidence for local debugging.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import config
from app.jobs import atomic_json
from app.media_probe import load_json, probe_media
from app.media import run_command


def workspace(path):
    path = Path(path).resolve()
    path.relative_to(ROOT)
    return path


def utc():
    return datetime.now(timezone.utc).isoformat()


def prepare(source, directory, duration, start):
    source, directory = workspace(source), workspace(directory)
    info = probe_media(source)
    if not math.isfinite(start) or not info['has_audio'] or start < 0 or start + duration > info['duration'] + .2:
        raise ValueError('Source must contain audio and the whole requested interval')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'source-{duration}s.mp4'
    settings = {'source': str(source), 'size': source.stat().st_size,
                'mtime_ns': source.stat().st_mtime_ns, 'start': start, 'duration': duration}
    meta = directory / 'preparation.json'
    if target.is_file():
        if not meta.is_file() or load_json(meta)['settings'] != settings:
            raise ValueError('Existing excerpt does not match the requested source settings')
    else:
        begun = time.perf_counter()
        run_command([config.FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
            '-ss', str(start), '-i', str(source), '-t', str(duration),
            '-map', '0:v:0', '-map', f"0:a:{info.get('audio_stream', 0)}",
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
            '-movflags', '+faststart', str(target)], directory, timeout=1800)
        atomic_json(meta, {'settings': settings, 'seconds': time.perf_counter() - begun})
    checked = probe_media(target)
    if abs(checked['duration'] - duration) > .2 or not checked['has_audio']:
        raise ValueError('Excerpt did not pass real video/audio duration validation')
    atomic_json(directory / 'input.json', {'source': str(target)})
    return target


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                *[(name, ctypes.c_ulonglong) for name in (
                    'total_phys', 'avail_phys', 'total_page', 'avail_page',
                    'total_virtual', 'avail_virtual', 'avail_extended')]]


def system_memory():
    if os.name != 'nt':
        return {}
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {}
    return {'system_ram_used_mib': (status.total_phys - status.avail_phys) / 1024**2,
            'system_ram_total_mib': status.total_phys / 1024**2,
            'system_ram_load_percent': status.load}


def system_cpu_times():
    if os.name != 'nt':
        return None
    from ctypes.wintypes import FILETIME
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    value = lambda x: (x.dwHighDateTime << 32) | x.dwLowDateTime
    return value(idle), value(kernel) + value(user)


class Measurements:
    def __init__(self, directory, timeout):
        self.path = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.deadline = self.started + timeout
        self.stage = 'initialization'
        self.stage_started = self.started
        self.spans = []
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.timeout = False
        self.gpu = shutil.which('nvidia-smi')
        self.thread = threading.Thread(target=self.resources, daemon=True)

    def emit(self, name, **fields):
        row = {'time_utc': utc(), 'elapsed_seconds': time.perf_counter() - self.started,
               'event': name, 'stage': self.stage, **fields}
        with self.lock, (self.path / 'measurements.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps(row, allow_nan=False) + '\n')

    def cancelled(self):
        self.timeout = time.perf_counter() >= self.deadline
        return self.timeout or (self.path.parent.parent / '.cancel').exists()

    def progress(self, stage, progress):
        now = time.perf_counter()
        if stage != self.stage:
            self.spans.append({'stage': self.stage, 'seconds': now - self.stage_started})
            self.stage, self.stage_started = stage, now
        self.emit('progress', progress=progress)

    def resources(self):
        previous = system_cpu_times()
        while not self.stop.is_set():
            fields = system_memory()
            current = system_cpu_times()
            if previous and current and current[1] > previous[1]:
                fields['system_cpu_percent'] = 100 * (1 - (current[0]-previous[0]) / (current[1]-previous[1]))
            previous = current
            if self.gpu:
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    result = subprocess.run([self.gpu,
                        '--query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu',
                        '--format=csv,noheader,nounits'], capture_output=True, text=True,
                        timeout=5, creationflags=flags, cwd=ROOT)
                    parts = result.stdout.strip().splitlines()[0].split(',') if result.returncode == 0 else []
                    if len(parts) == 6:
                        fields['gpu_name'] = parts[0].strip()
                        for name, value in zip(('gpu_utilization_percent', 'gpu_memory_used_mib',
                                'gpu_memory_total_mib', 'gpu_power_w', 'gpu_temperature_c'), parts[1:]):
                            try: fields[name] = float(value.strip())
                            except ValueError: pass
                except (OSError, subprocess.TimeoutExpired, IndexError):
                    fields['gpu_sample_unavailable'] = True
            self.emit('resources', **fields)
            self.stop.wait(2)

    def finish(self):
        now = time.perf_counter()
        self.spans.append({'stage': self.stage, 'seconds': now - self.stage_started})
        self.stop.set()
        self.thread.join(timeout=6)
        atomic_json(self.path / 'stage-occupancy.json', self.spans)


@contextmanager
def instrument(measurements):
    import app.pipeline as pipeline
    import app.analysis as analysis
    import app.deepseek as deepseek
    from app.vision import LocalVision
    from app.model_perf import model_alias
    original_pipeline = pipeline.run_job
    original_process = analysis.run_process
    original_start, original_close = LocalVision.start, LocalVision.close

    def observed_pipeline(job, report, cancelled):
        def progress(stage, fraction, message):
            measurements.progress(stage, fraction)
            report(stage, fraction, message)
        return original_pipeline(job, progress, lambda: cancelled() or measurements.cancelled())

    def observed_process(command, logfile, cancelled, *args, **kwargs):
        tokens = [str(c) for c in command]
        category = ('asr_process' if 'app.inference' in tokens else
                    'audio_prepare' if '-vn' in tokens and '-ar' in tokens else 'media_process')
        begun = time.perf_counter()
        measurements.emit(category + '_start')
        try:
            return original_process(command, logfile, lambda: cancelled() or measurements.cancelled(), *args, **kwargs)
        finally:
            measurements.emit(category + '_end', seconds=time.perf_counter()-begun)

    def observed_start(vision, *args, **kwargs):
        alias = model_alias(vision.model)
        begun = time.perf_counter()
        measurements.emit('model_startup_start', model=alias)
        try:
            return original_start(vision, *args, **kwargs)
        finally:
            measurements.emit('model_startup_end', model=alias,
                              seconds=time.perf_counter()-begun, cpu=vision.cpu_fallback)

    def observed_close(vision):
        begun = time.perf_counter()
        active = vision.process is not None
        try:
            return original_close(vision)
        finally:
            if active: measurements.emit('model_teardown', model=model_alias(vision.model),
                                        seconds=time.perf_counter()-begun)

    def remote_forbidden(*args, **kwargs):
        raise RuntimeError('Benchmark forbids all remote-provider HTTP calls')

    with patch.object(pipeline, 'run_job', observed_pipeline), \
         patch.object(analysis, 'run_process', observed_process), \
         patch.object(LocalVision, 'start', observed_start), \
         patch.object(LocalVision, 'close', observed_close), \
         patch.object(deepseek, '_http', remote_forbidden):
        yield


def benchmark(fixture, job, *, resume, timeout):
    from scripts.run_production_raw_quality import run
    job.mkdir(parents=True, exist_ok=True)
    label = 'resume' if resume else 'fresh'
    if not resume and (job / 'observed-outcome.json').exists():
        raise ValueError('Fresh benchmark refuses an existing run; choose a new directory or --resume')
    if resume and not (job / 'original-inputs.json').is_file():
        raise ValueError('Resume requires an existing genuine production job')
    record = job / 'benchmark' / label
    if record.exists():
        raise ValueError('This benchmark phase has already been recorded')
    metrics = Measurements(record, timeout)
    atomic_json(record / 'started.json', {'time_utc': utc(), 'mode': label,
        'provider': 'local', 'source': str(fixture / 'input.json'),
        'timeout_seconds': timeout, 'resource_scope': 'whole system; may include other apps',
        'fresh_definition': 'new job and checkpoints; OS disk caches are not flushed',
        'cpu_identifier': os.environ.get('PROCESSOR_IDENTIFIER'), 'logical_cpus': os.cpu_count()})
    metrics.thread.start()
    error = None
    try:
        with instrument(metrics):
            outcome = run(fixture, job, render=True, analysis_provider='local')
    except Exception as caught:
        error = type(caught).__name__
        outcome = load_json(job / 'observed-outcome.json') if (job / 'observed-outcome.json').exists() else {}
    finally:
        metrics.finish()
    for name in ('observed-outcome.json', 'observed-sessions.json', 'timings.json',
                 'final_quality_gate.json'):
        if (job / name).is_file(): shutil.copyfile(job / name, record / name)
    for source, destination in ((job / 'model-performance.jsonl', 'model-performance.jsonl'),
            (job / 'diagnostics/pipeline/timeline.jsonl', 'timeline.jsonl'),
            (job / 'diagnostics/pipeline/run.json', 'diagnostic-run.json')):
        if source.is_file(): shutil.copyfile(source, record / destination)
    summary = {'phase': label, 'complete': outcome.get('complete', False),
               'status': 'timeout' if metrics.timeout else 'failed' if error or not outcome.get('complete') else 'completed',
               'elapsed_seconds': time.perf_counter()-metrics.started,
               'error_type': error, 'actual_model_requests_total': outcome.get('actual_model_requests'),
               'stage_at_end': metrics.stage, 'timeout_seconds': timeout}
    atomic_json(record / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--start-seconds', type=float, default=300)
    parser.add_argument('--durations', type=int, nargs='+', choices=(120, 180), default=[120, 180])
    parser.add_argument('--timeout-seconds', type=float, default=1800)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if not 0 < args.timeout_seconds < 86400: parser.error('Timeout must be positive and below one day')
    config.setup_environment()
    directory = workspace(args.directory)
    directory.relative_to(config.TEMP.resolve())
    results = []
    for duration in args.durations:
        fixture = directory / f'input-{duration}s'
        prepare(args.source, fixture, duration, args.start_seconds)
        if not args.prepare_only:
            results.append(benchmark(fixture, directory / f'job-{duration}s',
                                     resume=args.resume, timeout=args.timeout_seconds))
    if results: atomic_json(directory / ('resume-results.json' if args.resume else 'fresh-results.json'), results)
    return 0 if all(r['complete'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
