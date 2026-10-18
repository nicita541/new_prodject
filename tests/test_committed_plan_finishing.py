"""Finishing must use the plan of the visible published video, no inference."""
import copy
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.artifact_publication import effective_plan, publish_revision
from app.finishing import FinishProfile, _job_plan
from app.jobs import JobManager
from app.json_store import atomic_json
from app.media import EXPORT_VALIDATION_VERSION
from app.studio_render import submit_render
from tests.test_jobs import FakeWorker
from tests.test_finishing import authored_finishing


@pytest.fixture
def published(tmp_path):
    (tmp_path / 'episode.mp4').write_bytes(b'authored placeholder, not media')
    manager = JobManager(tmp_path, FakeWorker)
    try:
        job = manager.create(manager.list_sources()[0]['id'])
        manager.cancel(job['id'])
        directory = manager.job_dir(job['id'])
        job = {**manager.get(job['id']), 'status': 'completed'}
        atomic_json(directory / 'job.json', job)
        plan = {'source': {'duration': 10}, 'parts': [{'index': 1, 'duration': 3,
            'cuts': [{'start': 1, 'end': 4}],
            'subtitles': [{'start': .1, 'end': 1, 'text': 'Published text'}]}]}
        output = directory / 'output'
        output.mkdir()
        video, subtitles = output / 'part_001.mp4', output / 'part_001.srt'
        video.write_bytes(b'authored export placeholder, no decoder claimed')
        subtitles.write_text('Published text', 'utf-8')
        publish_revision(directory, plan, [{'candidate_id': 'candidate', 'video': video,
            'subtitles': subtitles, 'full_decode_version': EXPORT_VALIDATION_VERSION}],
            producer_id=job['id'], attempt_id='authored')
        changed = copy.deepcopy(plan)
        changed['parts'][0]['cuts'] = [{'start': 6, 'end': 9}]
        changed['parts'][0]['subtitles'][0]['text'] = 'Unpublished failed attempt'
        atomic_json(directory / 'plan.json', changed)
        yield manager, job, directory, plan
    finally:
        manager.close()


def test_committed_plan_wins_over_mutable_attempt_and_never_falls_back_after_corruption(published):
    _, _, directory, plan = published
    assert effective_plan(directory) == plan
    (directory / 'publication.json').write_text('{torn', 'utf-8')
    from app.artifact_publication import PublicationError
    with pytest.raises(PublicationError):
        effective_plan(directory)


def test_finishing_can_edit_prior_committed_video_after_failed_new_attempt(published):
    manager, job, directory, plan = published
    atomic_json(directory / 'job.json', {**job, 'status': 'failed'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(manager=manager)))
    assert _job_plan(request, job['id'])[1] == plan
    atomic_json(directory / 'job.json', {**job, 'status': 'running'})
    with patch.object(manager, 'get', return_value={**job, 'status': 'running'}):
        with pytest.raises(HTTPException) as error:
            _job_plan(request, job['id'])
    assert error.value.status_code == 409


def test_queued_finishing_captures_committed_source_geometry(published):
    manager, job, _, plan = published
    captured, entered = [], threading.Event()
    def execute(source, part, probe, output, work, encoder, cancelled, **kwargs):
        captured.append(copy.deepcopy(part))
        entered.set()
        output.mkdir(parents=True, exist_ok=True)
        video = output/f"part_{part['index']:03}.mp4"
        video.write_bytes(b'Authored committed geometry fixture, not media')
        return video
    with authored_finishing(manager, execute):
        submit_render(manager, job['id'], [1], FinishProfile().model_dump())
        assert entered.wait(2)
    assert captured[0]['cuts'] == plan['parts'][0]['cuts']
    assert captured[0]['subtitles'] == plan['parts'][0]['subtitles']


def test_failed_new_attempt_still_uses_finishing_for_the_committed_video(published):
    from app.server import public_job
    manager, job, _, plan = published
    with patch('app.studio_render.ready_outputs', return_value={}) as ready:
        result = public_job({**job, 'status': 'failed'}, manager, include_progress=False)
    assert result['published_revision']
    assert result['files']
    ready.assert_called_once_with(manager, job['id'], plan)
