"""Actual decoded ancestor media through publication, HTTP and job lifetime.

Only analysis uses FakeWorker. FFmpeg generation, full decoding, immutable
publication, ancestor resolution, API streaming and deletion are real.
"""
import shutil
import uuid

from fastapi.testclient import TestClient
import pytest

from app import artifact_publication as publication, checkpoint_lineage, config
from app.jobs import JobManager
from app.json_store import atomic_json
from app.library import Library
from app.media import EXPORT_VALIDATION_VERSION, run_command, validate_export
from app.processing import source_digest
from app.server import create_app
from tests.test_jobs import FakeWorker


def _snapshot(directory):
    return {str(path.relative_to(directory)): (path.stat().st_mtime_ns, path.read_bytes())
            for path in directory.rglob('*') if path.is_file()}


@pytest.mark.skipif(not config.FFMPEG.is_file(), reason='Bundled FFmpeg required')
def test_actual_ancestor_media_streams_without_copy_and_survives_until_child_deleted():
    root = config.TEMP / ('pmr-' + uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    manager = None
    try:
        source = root / 'episode.mp4'
        run_command([str(config.FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=1080x1920:rate=30:duration=1',
            '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=1',
            '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-crf', '30', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart',
            str(source)], root / 'generate', timeout=60)
        manager = JobManager(root, FakeWorker)
        source_id = manager.list_sources()[0]['id']
        # Use a real episode owner before publishing. Legacy library migration
        # is a separate storage transition from this decoded-media boundary.
        library = Library(manager)
        project = library.create_project('Generated ancestor media verification')
        episode_id = library.create_episode(project['id'], 1)['id']
        parent_job = manager.create(source_id, episode_id=episode_id)
        manager.cancel(parent_job['id'])
        parent = manager.job_dir(parent_job['id'])
        atomic_json(parent / 'analysis.meta.json', {'source': source_digest(source)})
        output = parent / 'output'
        output.mkdir()
        video = output / 'part_001.mp4'
        shutil.copy2(source, video)
        subtitle_bytes = '1\n00:00:00,100 --> 00:00:00,800\nПроверка оригинала\n'.encode('utf-8')
        video.with_suffix('.srt').write_bytes(subtitle_bytes)
        validated = validate_export(video, 1., root / 'validate-parent', full_decode=True)
        assert validated['full_decode'] is True
        assert validated['validation_version'] == EXPORT_VALIDATION_VERSION
        original = publication.publish_revision(parent,
            {'source': {'sha256': source_digest(source)},
             'parts': [{'index': 1, 'duration': 1., 'render_fingerprint': 'actual-media-render'}]},
            [{'video': video, 'subtitles': video.with_suffix('.srt'), 'candidate_id': 'parent-candidate',
              'full_decode_version': validated['validation_version']}],
            producer_id=parent.name, attempt_id='actual-decode')
        atomic_json(parent / 'job.json', {**manager.get(parent.name), 'status': 'completed',
                                         'outputs': original['outputs']})
        parent_before = _snapshot(parent)

        child_job = manager.create(source_id, episode_id=episode_id,
                                   processing_mode='incremental', reuse_job_id=parent.name)
        manager.cancel(child_job['id'])
        child = manager.job_dir(child_job['id'])
        assert checkpoint_lineage.ancestors(child) == [parent]
        assert not (child / 'output').exists()
        referenced = publication.publish_revision(child,
            {'source': {'sha256': source_digest(source)},
             'parts': [{'index': 2, 'duration': 1., 'render_fingerprint': 'actual-media-render'}]},
            [{'reference': {'job_id': parent.name, 'revision_id': original['revision_id'],
                            'video_filename': 'part_001.mp4', 'subtitles_filename': 'part_001.srt'},
              'candidate_id': 'child-candidate', 'output_index': 2,
              'full_decode_version': validated['validation_version']}],
            producer_id=child.name, attempt_id='reference-actual-decode')
        atomic_json(child / 'job.json', {**manager.get(child.name), 'status': 'completed',
                                        'outputs': referenced['outputs']})
        assert not list(child.rglob('*.mp4'))
        assert not list(child.rglob('*.srt'))
        resolved = publication.resolve_output(child, 'part_002.mp4')
        assert resolved == parent / 'revisions' / original['revision_id'] / 'part_001.mp4'
        assert validate_export(resolved, 1., root / 'validate-reference', full_decode=True)['full_decode']
        assert _snapshot(parent) == parent_before

        actual_bytes = resolved.read_bytes()
        with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
            before = {parent.name: _snapshot(parent), child.name: _snapshot(child)}
            video_url = f'/api/jobs/{child.name}/files/part_002.mp4'
            subtitle_url = f'/api/jobs/{child.name}/files/part_002.srt'
            full = client.get(video_url)
            assert full.status_code == 200, full.text[:100]
            assert full.content == actual_bytes
            head = client.head(video_url)
            assert head.status_code == 200
            assert head.content == b''
            assert int(head.headers['content-length']) == len(actual_bytes)
            ranged = client.get(video_url, headers={'Range': 'bytes=0-63'})
            assert ranged.status_code == 206
            assert ranged.content == actual_bytes[:64]
            assert ranged.headers['content-range'] == f'bytes 0-63/{len(actual_bytes)}'
            subtitles = client.get(subtitle_url)
            assert subtitles.status_code == 200
            assert subtitles.content == subtitle_bytes
            subtitle_head = client.head(subtitle_url)
            assert subtitle_head.status_code == 200
            assert subtitle_head.content == b''
            assert int(subtitle_head.headers['content-length']) == len(subtitle_bytes)
            assert client.get(f'/api/jobs/{child.name}/files/part_001.mp4').status_code == 404
            assert before == {parent.name: _snapshot(parent), child.name: _snapshot(child)}

            blocked = client.delete(f'/api/jobs/{parent.name}')
            assert blocked.status_code == 409, blocked.text
            assert client.get(video_url).content == actual_bytes
            assert before == {parent.name: _snapshot(parent), child.name: _snapshot(child)}
            deleted_child = client.delete(f'/api/jobs/{child.name}')
            assert deleted_child.status_code == 200, deleted_child.text
            assert deleted_child.json()['deleted'] is True
            assert not child.exists()
            assert resolved.exists()
            deleted_parent = client.delete(f'/api/jobs/{parent.name}')
            assert deleted_parent.status_code == 200, deleted_parent.text
            assert deleted_parent.json()['deleted'] is True
            assert not parent.exists()
    finally:
        if manager is not None:
            manager.close()
        root.resolve().relative_to(config.TEMP.resolve())
        shutil.rmtree(root)
