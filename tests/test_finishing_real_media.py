"""Generated video through real owned finishing processes; no model inference."""
import shutil
import time
import uuid
import wave
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import config
from app.finishing import FinishProfile
from app.finishing_commands import FinishingCommands
from app.jobs import JobManager
from app.json_store import atomic_json
from app.media import run_command, validate_export
from app.server import create_app
from app.studio_render import control_task, resolve_task_file, submit_render, task_status
from tests.test_jobs import FakeWorker


@pytest.mark.skipif(not config.FFMPEG.is_file(), reason='Bundled FFmpeg required')
def test_real_owned_export_restart_http_replay_reference_and_preview():
    root = config.TEMP/('fmr-'+uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    manager = None
    try:
        source = root/'episode.mp4'
        run_command([str(config.FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=14',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=14',
            '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=14',
            '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-c:a', 'aac', str(source)], root/'generate', timeout=60)
        # Only initial analysis is fake. Finishing uses real WorkerProcess,
        # FFmpeg, validation, store, queue, API and artifact streaming.
        manager = JobManager(root, FakeWorker)
        job = manager.create(manager.list_sources()[0]['id'])
        manager.cancel(job['id'])
        directory = manager.job_dir(job['id'])
        atomic_json(directory/'job.json', {**manager.get(job['id']), 'status': 'completed'})
        atomic_json(directory/'probe.json', {'width': 320, 'height': 180, 'audio_stream': 1})
        parts = [{'index': index, 'duration': end-start, 'layout': 'cinema',
                  'cuts': [{'start': start, 'end': end, 'focus': []}],
                  'subtitles': [{'start': .1, 'end': .8, 'text': f'Original caption {index}'}]}
                 for index, start, end in ((1, 0., 1.), (2, 2., 12.))]
        plan = {'source': {'duration': 14}, 'parts': parts}
        atomic_json(directory/'plan.json', plan)
        profile = FinishProfile().model_dump()
        profile['video']['layout'] = 'cinema'
        profile['audio']['enabled'] = False
        operation = str(uuid.uuid4())
        state = submit_render(manager, job['id'], [1, 2], profile, operation_id=operation)
        identifier = state['export_id']
        store = FinishingCommands(root)
        command = store.load(operation)
        deadline = time.monotonic()+90
        first = None
        while time.monotonic() < deadline:
            first = store.part_receipt(command, 1, verify_bytes=False)
            if first is not None:
                break
            current = task_status(manager, identifier)
            assert current['status'] in ('queued', 'running'), current
            time.sleep(.02)
        assert first is not None
        assert manager.finishing_execution.active is not None
        assert manager.close() is True
        assert store._runtime(command)[1]['status'] == 'interrupted'
        # Resume must not resolve these newly changed values.
        plan['parts'][1]['subtitles'][0]['text'] = 'Changed today - never render'
        atomic_json(directory/'plan.json', plan)
        atomic_json(directory/'source.json', {'path': str(root/'unavailable-today.mp4')})
        manager = JobManager(root, FakeWorker)
        assert task_status(manager, identifier)['status'] == 'interrupted'
        control_task(manager, identifier, 'resume')
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            current = task_status(manager, identifier)
            if current['status'] not in ('queued', 'running'):
                break
            time.sleep(.05)
        assert current['status'] == 'completed', current
        assert store.part_receipt(command, 1) == first
        second = store.part_receipt(command, 2)
        assert first['attempt_id'] != second['attempt_id']
        text = resolve_task_file(manager, identifier, 'part_002.srt').read_text(encoding='utf-8')
        assert 'Original caption 2' in text and 'Changed today' not in text
        for index, duration in ((1, 1.), (2, 10.)):
            validate_export(resolve_task_file(manager, identifier, f'part_{index:03}.mp4'), duration,
                            root/f'verify-{index}', full_decode=True)
        # Verify actual selected audio content, beyond merely storing ordinal1.
        import numpy as np
        audio = root/'selected-audio.wav'
        run_command([str(config.FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(resolve_task_file(manager, identifier, 'part_002.mp4')), '-map', '0:a:0',
            '-t', '1', '-ac', '1', '-ar', '48000', '-c:a', 'pcm_s16le', str(audio)], root/'audio-check', timeout=30)
        with wave.open(str(audio), 'rb') as handle:
            samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(float)
            rate = handle.getframerate()
        spectrum = np.abs(np.fft.rfft(samples*np.hanning(len(samples))))
        peak = np.fft.rfftfreq(len(samples), 1/rate)[spectrum.argmax()]
        assert abs(peak-880) < 3, 'Wrong source audio stream; stream0 contains440Hz'
        # Restore only for creating a new intention through the actual API.
        atomic_json(directory/'source.json', {'path': str(source)})
        with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
            project = client.post('/api/projects', json={'title': 'Generated media verification'}).json()
            episode = client.post('/api/projects/'+project['id']+'/episodes', json={'number': 1}).json()
            atomic_json(directory/'job.json', {**manager.get(job['id']), 'episode_id': episode['id']})

            def wait(url):
                deadline = time.monotonic()+90
                while time.monotonic() < deadline:
                    response = client.get(url)
                    assert response.status_code == 200, response.text
                    result = response.json()
                    if result['status'] not in ('queued', 'running'):
                        assert result['status'] == 'completed', result
                        return result
                    time.sleep(.05)
                pytest.fail('Owned finishing worker did not complete')

            body = {'part_indices': [1], 'settings': profile, 'operation_id': str(uuid.uuid4())}
            accepted = client.post('/api/jobs/'+job['id']+'/exports', json=body)
            assert accepted.status_code == 202, accepted.text
            replay = client.post('/api/jobs/'+job['id']+'/exports', json=body)
            assert replay.status_code == 202, replay.text
            assert accepted.json()['export_id'] == replay.json()['export_id']
            completed = wait('/api/exports/'+accepted.json()['export_id'])
            equivalent = store.load(body['operation_id'])
            assert store.part_receipt(equivalent, 1) == first
            assert client.get(completed['files'][0]['url'], headers={'Range': 'bytes=0-63'}).status_code == 206
            assert client.get(completed['files'][0]['subtitle_url']).status_code == 200
            preview = client.post('/api/jobs/'+job['id']+'/previews', json={
                'part_index': 1, 'from': .2, 'duration': .6, 'settings': profile,
                'operation_id': str(uuid.uuid4())})
            assert preview.status_code == 202, preview.text
            result = wait('/api/jobs/'+job['id']+'/previews/'+preview.json()['preview_id'])
            assert client.get(result['url'], headers={'Range': 'bytes=0-63'}).status_code == 206
            before = {path: path.read_bytes() for path in (directory/'finishing').rglob('*.json')}
            assert client.get('/api/jobs/'+job['id']+'/finishing-tasks').status_code == 200
            assert before == {path: path.read_bytes() for path in (directory/'finishing').rglob('*.json')}
    finally:
        if manager is not None:
            manager.close()
        root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(root)
