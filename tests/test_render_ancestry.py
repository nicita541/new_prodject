"""Explicit ancestor render reuse, using authored bytes rather than real media.

These tests exercise ownership, immutable publication and orchestration. The
authored full-decode receipts do not represent a decoder or encoder run.
"""
import copy
import uuid
from unittest.mock import patch

import pytest

from app import artifact_publication as publication, checkpoint_lineage
from app.content_identity import file_sha256
from app.json_store import atomic_json, read_json
from app.media import EXPORT_VALIDATION_VERSION
from app.render_ancestry import inherited_render
from tests import test_standalone_pipeline as standalone_fixture


SOURCE = 'a' * 64
EPISODE = str(uuid.uuid4())


def _job(store, *, source=SOURCE, source_path=None, episode=EPISODE):
    directory = store / str(uuid.uuid4())
    directory.mkdir(parents=True)
    atomic_json(directory / 'job.json', {'id': directory.name, 'episode_id': episode})
    atomic_json(directory / 'analysis.meta.json', {'source': source})
    atomic_json(directory / 'source.json', {'path': str(source_path or store / 'original.mp4'),
                                           'name': 'authored.mp4'})
    atomic_json(directory / 'story-objective.json', {'version': 1, 'objective': 'standalone_shorts'})
    return directory


def _child(parent, **kwargs):
    child = _job(parent.parent, **kwargs)
    checkpoint_lineage.link(parent, child, source_sha256=kwargs.get('source', SOURCE),
                            episode_id=kwargs.get('episode', EPISODE))
    return child


def _publish(directory, fingerprints):
    artifacts, parts = [], []
    work = directory / 'authored'
    work.mkdir()
    for index, fingerprint in enumerate(fingerprints, 1):
        video = work / f'part_{index:03}.mp4'
        video.write_bytes(f'authored video {index}'.encode())
        video.with_suffix('.srt').write_bytes(f'authored subtitles {index}'.encode())
        artifacts.append({'video': video, 'subtitles': video.with_suffix('.srt'),
                          'candidate_id': f'candidate-{index}',
                          'full_decode_version': EXPORT_VALIDATION_VERSION})
        parts.append({'index': index, 'candidate_id': f'candidate-{index}',
                      'render_fingerprint': fingerprint, 'music_track': f'track-{index}.mp3'})
    return publication.publish_revision(directory, {'parts': parts}, artifacts,
                                        producer_id='authored-test', attempt_id='first')


def _snapshot(directory):
    return {str(path.relative_to(directory)): (path.stat().st_mtime_ns, path.read_bytes())
            for path in directory.rglob('*') if path.is_file()}


def test_exact_fingerprint_reuses_public_rank_alias_without_origin_writes(tmp_path):
    parent = _job(tmp_path)
    record = _publish(parent, ['wrong', 'exact'])
    child = _child(parent)
    before = _snapshot(parent)
    with patch.object(publication, 'atomic_json', side_effect=AssertionError('Lookup must be read only')):
        assert inherited_render(child, 'missing') is None
        result = inherited_render(child, 'exact')
    assert result == {'reference': {'job_id': parent.name, 'revision_id': record['revision_id'],
                                   'video_filename': 'part_002.mp4',
                                   'subtitles_filename': 'part_002.srt'},
                      'full_decode_version': EXPORT_VALIDATION_VERSION,
                      'music_track': 'track-2.mp3', 'encoder': None}
    assert _snapshot(parent) == before
    assert not (child / 'publication.json').exists()


def test_transitive_reference_resolves_original_bytes_without_copy(tmp_path):
    parent = _job(tmp_path)
    original = _publish(parent, ['exact'])
    child = _child(parent)
    inherited = inherited_render(child, 'exact')
    with patch.object(publication, '_copy_verified', side_effect=AssertionError('No media copy allowed')):
        middle = publication.publish_revision(child,
            {'parts': [{'index': 3, 'render_fingerprint': 'exact'}]},
            [{**inherited, 'candidate_id': 'reranked', 'output_index': 3}],
            producer_id='authored-child', attempt_id='child')
    grandchild = _child(child)
    before = _snapshot(tmp_path)
    result = inherited_render(grandchild, 'exact')
    assert result['reference']['job_id'] == child.name
    assert result['reference']['revision_id'] == middle['revision_id']
    assert result['reference']['video_filename'] == 'part_003.mp4'
    assert publication.resolve_revision_output(child, middle['revision_id'], 'part_003.mp4') == (
        parent / 'revisions' / original['revision_id'] / 'part_001.mp4')
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('damage', ['missing', 'same_size_corruption', 'subtitle_corruption'])
def test_corrupt_selected_media_is_cache_miss_but_other_clip_is_still_reusable(tmp_path, damage):
    parent = _job(tmp_path)
    record = _publish(parent, ['damaged', 'healthy'])
    child = _child(parent)
    path = parent / 'revisions' / record['revision_id'] / (
        'part_001.srt' if damage == 'subtitle_corruption' else 'part_001.mp4')
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'x' * path.stat().st_size)
    before = _snapshot(parent)
    assert inherited_render(child, 'damaged') is None
    assert inherited_render(child, 'healthy')['reference']['video_filename'] == 'part_002.mp4'
    assert _snapshot(parent) == before


def test_equal_source_without_explicit_link_is_not_a_cache_hit(tmp_path):
    parent = _job(tmp_path)
    _publish(parent, ['exact'])
    unrelated = _job(tmp_path)
    assert inherited_render(unrelated, 'exact') is None


@pytest.mark.parametrize('change', ['source', 'owner', 'source_path', 'ancestor_owner', 'cycle'])
def test_changed_lineage_identity_fails_closed_before_media_lookup(tmp_path, change):
    parent = _job(tmp_path)
    _publish(parent, ['exact'])
    child = _child(parent)
    if change == 'source':
        atomic_json(child / 'analysis.meta.json', {'source': 'b' * 64})
    elif change in ('owner', 'ancestor_owner'):
        target = child if change == 'owner' else parent
        atomic_json(target / 'job.json', {'id': target.name, 'episode_id': str(uuid.uuid4())})
    elif change == 'source_path':
        atomic_json(parent / 'source.json', {'path': str(tmp_path / 'foreign.mp4')})
    else:
        atomic_json(parent / checkpoint_lineage.FILE,
                    {**read_json(child / checkpoint_lineage.FILE), 'parent_job_id': child.name})
    with patch('app.render_ancestry.current_revision', side_effect=AssertionError('No invalid owner lookup')):
        with pytest.raises(checkpoint_lineage.LineageError):
            inherited_render(child, 'exact')


def test_cancellation_propagates_before_and_during_media_validation(tmp_path):
    parent = _job(tmp_path)
    _publish(parent, ['exact'])
    child = _child(parent)
    with pytest.raises(InterruptedError):
        inherited_render(child, 'exact', cancelled=lambda: True)
    with patch('app.render_ancestry.resolve_revision_output',
               side_effect=InterruptedError('Authored validation cancellation')):
        with pytest.raises(InterruptedError, match='validation cancellation'):
            inherited_render(child, 'exact')


@pytest.fixture
def standalone():
    fixture = standalone_fixture.StandalonePipelineTests(methodName='runTest')
    fixture.setUp()
    store = fixture.job
    fixture.analysis = standalone_fixture.source_fixture(2)
    # The production context records the actual shared source hash; the
    # analyzer/renderer are the existing explicitly authored boundary fakes.
    sha = file_sha256(fixture.source)
    fixture.job = _job(store, source=sha, source_path=fixture.source)
    try:
        yield fixture, store, sha
    finally:
        fixture.job = store
        fixture.doCleanups()


def test_standalone_child_reuses_parent_media_with_new_rank_and_no_encoder(standalone):
    fixture, store, sha = standalone
    parent = fixture.job
    fixture.run_job()
    original = publication.current_revision(parent)
    before = _snapshot(parent)
    child = _child(parent, source=sha, source_path=fixture.source)
    fixture.job = child
    fixture.analysis['events'][1]['importance'] = 5
    fixture.renderer.reset_mock()
    fixture.encoder.reset_mock()
    fixture.renderer.side_effect = AssertionError('Exact ancestor media must not be rendered')
    fixture.encoder.side_effect = AssertionError('Exact ancestor media must not choose encoder')
    outputs = fixture.run_job()
    assert outputs == ['part_001.mp4', 'part_001.srt', 'part_002.mp4', 'part_002.srt']
    inherited = publication.current_revision(child)
    assert inherited['plan']['parts'][0]['cuts'][0]['start'] == 70
    assert all('reference' in item for item in inherited['artifacts'])
    assert inherited['artifacts'][0]['reference']['video_filename'] == 'part_002.mp4'
    assert publication.resolve_output(child, 'part_001.mp4') == (
        parent / 'revisions' / original['revision_id'] / 'part_002.mp4')
    assert not list(child.rglob('*.mp4'))
    assert not list(child.rglob('*.srt'))
    assert _snapshot(parent) == before
    fixture.renderer.assert_not_called()
    fixture.encoder.assert_not_called()
    fixture.query.assert_not_called()


def test_standalone_changed_captions_render_locally_instead_of_reusing_ancestor(standalone):
    fixture, store, sha = standalone
    parent = fixture.job
    fixture.run_job()
    before = _snapshot(parent)
    child = _child(parent, source=sha, source_path=fixture.source)
    fixture.job = child
    atomic_json(child / 'render-settings.json', {'layout': 'portrait', 'caption_style': 'accent'})
    fixture.renderer.reset_mock()
    fixture.encoder.reset_mock()
    fixture.run_job()
    record = publication.current_revision(child)
    assert fixture.renderer.call_count == 2
    fixture.encoder.assert_called_once()
    assert all('reference' not in item for item in record['artifacts'])
    assert all(part['caption_style'] == 'accent' for part in record['plan']['parts'])
    assert _snapshot(parent) == before
    fixture.query.assert_not_called()


def test_standalone_changed_cuts_render_locally_instead_of_reusing_ancestor(standalone):
    fixture, store, sha = standalone
    parent = fixture.job
    fixture.run_job()
    original = publication.current_revision(parent)
    before = _snapshot(parent)
    child = _child(parent, source=sha, source_path=fixture.source)
    fixture.job = child
    source_probe = copy.deepcopy(fixture.analysis['probe'])
    fixture.analysis = standalone_fixture.source_fixture(2, seconds=18)
    fixture.analysis['probe'] = source_probe
    fixture.renderer.reset_mock()
    fixture.encoder.reset_mock()
    fixture.run_job()
    record = publication.current_revision(child)
    assert fixture.renderer.call_count == 2
    fixture.encoder.assert_called_once()
    assert all('reference' not in item for item in record['artifacts'])
    assert record['plan']['parts'][0]['cuts'] != original['plan']['parts'][0]['cuts']
    assert _snapshot(parent) == before
    fixture.query.assert_not_called()
