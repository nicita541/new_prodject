"""Audit instrumentation must preserve local isolation and production callbacks."""
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.benchmark_local_pipeline import Measurements, benchmark, instrument, prepare


def test_instrumentation_preserves_progress_and_adds_cooperative_cancellation():
    import app.pipeline as pipeline
    import app.deepseek as deepseek
    original_pipeline = pipeline.run_job
    original_http = deepseek._http
    class Monitor:
        stopped = False
        progress_rows = []
        def progress(self, stage, fraction): self.progress_rows.append((stage, fraction))
        def cancelled(self): return self.stopped
    monitor = Monitor()
    received = []
    def production(job, report, cancelled):
        report('transcribe', .1, 'message unchanged')
        assert not cancelled()
        monitor.stopped = True
        assert cancelled()
        return ['real-output.mp4']
    with patch.object(pipeline, 'run_job', production):
        with instrument(monitor):
            assert pipeline.run_job(Path('job'), lambda *row: received.append(row), lambda: False) == ['real-output.mp4']
            with pytest.raises(RuntimeError, match='forbids all remote'):
                deepseek._http('/chat/completions')
        assert pipeline.run_job is production
        assert deepseek._http is original_http
    assert pipeline.run_job is original_pipeline
    assert received == [('transcribe', .1, 'message unchanged')]
    assert monitor.progress_rows == [('transcribe', .1)]


def test_preparation_refuses_invalid_source_interval_before_ffmpeg():
    source = Path(__file__).resolve()
    directory = source.parents[1] / 'temp' / 'benchmark-unit-no-output'
    with patch('scripts.benchmark_local_pipeline.probe_media', return_value={'duration': 1000, 'has_audio': True}), \
         patch('scripts.benchmark_local_pipeline.run_command') as render:
        for start in (float('nan'), float('inf'), -1, 900):
            with pytest.raises(ValueError): prepare(source, directory, 120, start)
        render.assert_not_called()
    assert not directory.exists()


def test_preparation_refuses_paths_outside_workspace():
    with pytest.raises(ValueError): prepare(Path('C:/outside.mp4'), Path('F:/new_prodject/temp/test'), 120, 0)


def test_resume_refuses_missing_production_job():
    from app.config import TEMP
    import shutil
    import uuid
    directory = TEMP / ('benchmark_guard_' + uuid.uuid4().hex)
    try:
        with pytest.raises(ValueError, match='existing genuine production job'):
            benchmark(directory / 'input', directory / 'job', resume=True, timeout=60)
        assert not (directory / 'job/benchmark').exists()
    finally:
        shutil.rmtree(directory, ignore_errors=True)
