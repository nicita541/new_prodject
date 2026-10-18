"""Draft publication mechanisms use authored placeholder bytes, no encoding."""
import copy
from unittest.mock import Mock, patch
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.artifact_publication import current_revision
from app.jobs import JobManager
from app.standalone_drafts import render_drafts, draft_output
from app.standalone_planner import build_standalone_candidates
from app.server import create_app
from tests.test_jobs import FakeWorker
from tests.test_standalone_planner import source_fixture


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path/'episode.mp4'
    source.write_bytes(b'authored source, no encoded video')
    manager = JobManager(tmp_path, FakeWorker)
    job = manager.create(manager.list_sources()[0]['id'])
    manager.cancel(job['id'])
    analysis = source_fixture(1)
    analysis['events'][0].update(analysis_unresolved=True, understanding_confidence=.4)
    drafts = build_standalone_candidates(analysis)['drafts']
    assert drafts
    def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
        assert part['layout'] == 'cinema' and len(part['cuts']) == 1
        assert kwargs['finishing'] is None and kwargs['background_music'] is None
        path = output/'part_001.mp4'
        path.write_bytes(b'authored draft output, no decoder exercised')
        path.with_suffix('.srt').write_text('authored subtitle', 'utf-8')
        return path
    backend = SimpleNamespace(render_part=Mock(side_effect=render), choose_encoder=Mock(return_value='authored'))
    directory = manager.job_dir(job['id'])
    with patch('app.subtitles.style_identity', return_value={'authored': 'style metadata'}):
        try:
            yield manager, directory, source, analysis, drafts, backend
        finally:
            manager.close()


def run(prepared, cancelled=lambda: False, drafts=None):
    manager, directory, source, analysis, original, backend = prepared
    return render_drafts(drafts or original, analysis, source, 'a'*64, directory,
                         Mock(), cancelled, {'run_id': 'authored'}, backend)


def test_rendered_drafts_are_lightweight_non_ready_and_reuse_immutable_media(prepared):
    _, directory, source, _, _, backend = prepared
    result, failures = run(prepared)
    assert failures == [] and result[0]['status'] == 'rendered_needs_review'
    assert result[0]['export_eligible'] is False and 'plan' not in result[0]
    assert current_revision(directory) is None
    assert source.read_bytes() == b'authored source, no encoded video'
    backend.render_part.reset_mock(); backend.choose_encoder.reset_mock()
    assert run(prepared) == (result, failures)
    backend.render_part.assert_not_called(); backend.choose_encoder.assert_not_called()


def test_draft_api_is_separate_from_ready_files_and_fails_closed_on_tamper(prepared):
    manager, directory, _, _, _, _ = prepared
    result, _ = run(prepared)
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        url = result[0]['video_url']
        assert client.get(url).content == b'authored draft output, no decoder exercised'
        assert client.get(url, headers={'Range': 'bytes=0-2'}).status_code == 206
        assert client.head(url).status_code == 200
        assert client.get(f'/api/jobs/{directory.name}/files/part_001.mp4').status_code == 404
        assert client.get(url.replace(result[0]['id'], 'untrusted')).status_code == 404
        path = draft_output(directory, result[0]['id'], 'part_001.mp4')
        path.write_bytes(b'X'*path.stat().st_size)
        assert client.get(url).status_code == 404


def test_draft_cannot_silently_introduce_disjoint_edits_or_hide_cancellation(prepared):
    drafts = copy.deepcopy(prepared[4])
    part = drafts[0]['plan']['parts'][0]
    part['cuts'].append(copy.deepcopy(part['cuts'][0]))
    result, failures = run(prepared, drafts=drafts)
    assert result[0]['status'] == 'technical_failed' and failures[0]['stage'] == 'draft_rendering'
    prepared[5].render_part.assert_not_called()
    with pytest.raises(InterruptedError):
        run(prepared, cancelled=lambda: True)
