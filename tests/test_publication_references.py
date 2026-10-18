"""Authored-byte storage tests; these fixtures do not claim decoder validation."""
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app import artifact_publication as publication
from app import checkpoint_lineage
from app.json_store import atomic_json, load_json
from app.media import EXPORT_VALIDATION_VERSION


SOURCE = 'a' * 64
EPISODE = str(uuid.uuid4())


def job(store, *, source=SOURCE, episode=EPISODE):
    directory = store / str(uuid.uuid4())
    directory.mkdir(parents=True)
    atomic_json(directory / 'job.json', {'id': directory.name, 'episode_id': episode})
    atomic_json(directory / 'analysis.meta.json', {'source': source})
    atomic_json(directory / 'source.json', {'path': str(store / 'original.mp4')})
    return directory


def own(directory, *, count=1, plan=None):
    work = directory / 'work'
    work.mkdir(exist_ok=True)
    artifacts = []
    for index in range(1, count + 1):
        video = work / f'part_{index:03}.mp4'
        subtitles = video.with_suffix('.srt')
        video.write_bytes(f'authored video {index}'.encode())
        subtitles.write_bytes(f'authored subtitles {index}'.encode())
        artifacts.append({'video': video, 'subtitles': subtitles,
                          'candidate_id': f'candidate-{index}',
                          'full_decode_version': EXPORT_VALIDATION_VERSION})
    return publication.publish_revision(directory, plan or {'parts': []}, artifacts,
                                        producer_id='authored-test', attempt_id='first')


def reference(origin, record, *, old_rank=1, rank=1, candidate='new-candidate'):
    return {'candidate_id': candidate, 'output_index': rank,
            'full_decode_version': EXPORT_VALIDATION_VERSION,
            'reference': {'job_id': origin.name, 'revision_id': record['revision_id'],
                          'video_filename': f'part_{old_rank:03}.mp4',
                          'subtitles_filename': f'part_{old_rank:03}.srt'}}


def linked(parent):
    child = job(parent.parent)
    checkpoint_lineage.link(parent, child, source_sha256=SOURCE, episode_id=EPISODE)
    return child


def publish(directory, artifacts, *, plan=None):
    return publication.publish_revision(directory, plan or {'parts': [], 'new': True}, artifacts,
                                        producer_id='reference-test', attempt_id='new')


def test_reference_reuses_bytes_without_copy_and_reranks(tmp_path):
    parent = job(tmp_path)
    original = own(parent, count=2)
    child = linked(parent)
    with patch.object(publication, '_copy_verified', side_effect=AssertionError('No copies permitted')):
        record = publish(child, [reference(parent, original, old_rank=2)])
    assert record['version'] == 2
    assert record['artifacts'][0]['candidate_id'] == 'new-candidate'
    assert record['outputs'] == ['part_001.mp4', 'part_001.srt']
    directory = child / 'revisions' / record['revision_id']
    assert {path.name for path in directory.iterdir()} == {'plan.json', 'manifest.json'}
    assert publication.resolve_output(child, 'part_001.mp4') == (
        parent / 'revisions' / original['revision_id'] / 'part_002.mp4')
    assert publication.resolve_output(child, 'part_001.srt').read_bytes() == b'authored subtitles 2'


def test_chain_same_job_revision_and_read_only_resolution(tmp_path):
    parent = job(tmp_path)
    first = own(parent)
    second = publish(parent, [reference(parent, first, rank=2)])
    child = linked(parent)
    third = publish(child, [reference(parent, second, old_rank=2, rank=3)])
    grandchild = linked(child)
    final = publish(grandchild, [reference(child, third, old_rank=3)])
    before = {path: (path.stat().st_mtime_ns, path.read_bytes())
              for path in tmp_path.rglob('*') if path.is_file()}
    with patch.object(publication, 'atomic_json', side_effect=AssertionError('GET must not write')):
        resolved = publication.resolve_revision_output(grandchild, final['revision_id'], 'part_001.mp4')
        assert publication.current_revision(grandchild) == final
        assert publication.resolve_output(grandchild, 'part_001.mp4') == resolved
    assert resolved == parent / 'revisions' / first['revision_id'] / 'part_001.mp4'
    after = {path: (path.stat().st_mtime_ns, path.read_bytes())
             for path in tmp_path.rglob('*') if path.is_file()}
    assert before == after


def test_sibling_origin_damage_does_not_invalidate_good_reference(tmp_path):
    parent = job(tmp_path)
    record = own(parent, count=2)
    child = linked(parent)
    damaged = parent / 'revisions' / record['revision_id'] / 'part_002.mp4'
    damaged.write_bytes(b'damaged and different size')
    result = publish(child, [reference(parent, record)])
    assert publication.current_revision(child) == result
    assert publication.resolve_revision_output(parent, record['revision_id'], 'part_001.mp4').read_bytes() == b'authored video 1'
    with pytest.raises(publication.PublicationError):
        publication.load_revision(parent, record['revision_id'])


def test_metadata_only_and_target_resolution_ignore_missing_other_clip(tmp_path):
    parent = job(tmp_path)
    record = own(parent, count=2)
    missing = parent / 'revisions' / record['revision_id'] / 'part_002.mp4'
    missing.unlink()
    assert publication.current_revision(parent, metadata_only=True) == record
    assert publication.resolve_output(parent, 'part_001.mp4').read_bytes() == b'authored video 1'
    with pytest.raises(publication.PublicationError):
        publication.current_revision(parent, verify_artifacts=False)


@pytest.mark.parametrize('change', ['video', 'subtitles', 'plan', 'manifest', 'missing'])
def test_changed_origin_cannot_publish_or_serve(tmp_path, change):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    current = publish(child, [reference(parent, original)])
    directory = parent / 'revisions' / original['revision_id']
    if change in ('video', 'subtitles'):
        path = directory / ('part_001.mp4' if change == 'video' else 'part_001.srt')
        path.write_bytes(b'x' * path.stat().st_size)
    elif change == 'plan':
        atomic_json(directory / 'plan.json', {'parts': ['changed']})
    elif change == 'manifest':
        manifest = load_json(directory / 'manifest.json')
        manifest['attempt_id'] = 'changed-attempt'
        atomic_json(directory / 'manifest.json', manifest)
    else:
        (directory / 'part_001.mp4').unlink()
    with pytest.raises(publication.PublicationError):
        publication.resolve_output(child, 'part_001.mp4')
    with pytest.raises(publication.PublicationError):
        publish(child, [reference(parent, original, rank=2)])
    assert load_json(child / 'publication.json')['revision_id'] == current['revision_id']


@pytest.mark.parametrize('change', ['source', 'owner', 'source_path', 'lineage_removed', 'lineage_cycle'])
def test_chain_identity_change_rejected(tmp_path, change):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    record = publish(child, [reference(parent, original)])
    if change == 'source':
        atomic_json(parent / 'analysis.meta.json', {'source': 'b' * 64})
    elif change == 'owner':
        atomic_json(parent / 'job.json', {'id': parent.name, 'episode_id': str(uuid.uuid4())})
    elif change == 'source_path':
        atomic_json(parent / 'source.json', {'path': 'another-source.mp4'})
    elif change == 'lineage_removed':
        (child / checkpoint_lineage.FILE).unlink()
    else:
        data = load_json(child / checkpoint_lineage.FILE)
        atomic_json(parent / checkpoint_lineage.FILE, {**data, 'parent_job_id': child.name})
    with pytest.raises(publication.PublicationError):
        publication.resolve_revision_output(child, record['revision_id'], 'part_001.mp4')


def test_equal_source_unrelated_job_is_not_an_ancestor(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    unrelated = job(tmp_path)
    with pytest.raises(publication.PublicationError, match='explicit ancestor'):
        publish(unrelated, [reference(parent, original)])
    assert not (unrelated / 'publication.json').exists()


@pytest.mark.parametrize('field,value', [
    ('job_id', '../owner'), ('job_id', None), ('revision_id', '../revision'),
    ('revision_id', None), ('video_filename', '../part_001.mp4'),
    ('subtitles_filename', 'part_002.srt'), ('video_filename', 'part_001.srt'),
])
def test_invalid_reference_rejected(tmp_path, field, value):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    item = reference(parent, original)
    item['reference'][field] = value
    with pytest.raises(publication.PublicationError):
        publish(child, [item])


@pytest.mark.parametrize('value', [True, 0, EXPORT_VALIDATION_VERSION + 1])
def test_reference_does_not_upgrade_full_decode_receipt(tmp_path, value):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    item = reference(parent, original)
    item['full_decode_version'] = value
    with pytest.raises(publication.PublicationError, match='full-decode'):
        publish(child, [item])


def test_unrelated_origin_metadata_still_must_be_valid(tmp_path):
    parent = job(tmp_path)
    original = own(parent, count=2)
    # A new identity with malformed sibling metadata is not a valid origin,
    # even though the requested first clip's media remains intact.
    manifest = dict(original)
    manifest['artifacts'][1]['candidate_id'] = '../untrusted'
    manifest['revision_id'] = publication.digest(publication._identity(manifest))
    directory = parent / 'revisions' / manifest['revision_id']
    directory.mkdir()
    original_directory = parent / 'revisions' / original['revision_id']
    (directory / 'plan.json').write_bytes((original_directory / 'plan.json').read_bytes())
    atomic_json(directory / 'manifest.json', manifest)
    child = linked(parent)
    with pytest.raises(publication.PublicationError, match='candidate ID'):
        publish(child, [reference(parent, manifest)])


def test_v2_same_job_source_identity_is_bound(tmp_path):
    directory = job(tmp_path)
    original = own(directory)
    assert original['version'] == 2
    atomic_json(directory / 'analysis.meta.json', {'source': 'f' * 64})
    with pytest.raises(publication.PublicationError, match='source or ownership changed'):
        publication.resolve_revision_output(directory, original['revision_id'], 'part_001.mp4')


def test_library_startup_migration_preserves_unowned_publication_read_only(tmp_path):
    from app.jobs import JobManager
    from app.library import Library
    from tests.test_jobs import FakeWorker

    source = tmp_path / 'episode.mp4'
    source.write_bytes(b'authored source, not real media')
    manager = JobManager(tmp_path, FakeWorker)
    try:
        source_id = manager.list_sources()[0]['id']
        state = manager.create(source_id)
        manager.cancel(state['id'])
        directory = manager.job_dir(state['id'])
        atomic_json(directory / 'analysis.meta.json', {'source': SOURCE})
        original = own(directory)
        assert original['source_identity']['episode_id'] is None
        before = {path: (path.stat().st_mtime_ns, path.read_bytes())
                  for path in directory.rglob('*') if path.is_file()}
        library = Library(manager)
        assert library.data['legacy_jobs'][directory.name]
        assert load_json(directory / 'job.json').get('episode_id') is None
        with patch.object(publication, 'atomic_json', side_effect=AssertionError('GET must be read only')):
            assert publication.current_revision(directory) == original
            assert publication.resolve_output(directory, 'part_001.mp4').read_bytes() == b'authored video 1'
        after = {path: (path.stat().st_mtime_ns, path.read_bytes())
                 for path in directory.rglob('*') if path.is_file()}
        assert before == after
    finally:
        manager.close()


def test_legacy_unscoped_reference_cannot_cross_migrated_owners(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    parent = job(store, episode=None)
    original = own(parent)
    child = job(store, episode=None)
    checkpoint_lineage.link(parent, child, source_sha256=SOURCE, episode_id=None)
    record = publish(child, [reference(parent, original)])
    mapping = {'legacy_jobs': {parent.name: EPISODE, child.name: EPISODE}}
    atomic_json(store.parent / 'library.json', mapping)
    assert publication.current_revision(child) == record
    mapping['legacy_jobs'][parent.name] = str(uuid.uuid4())
    atomic_json(store.parent / 'library.json', mapping)
    with pytest.raises(publication.PublicationError, match='another owner|ancestry is invalid'):
        publication.resolve_output(child, 'part_001.mp4')


def test_unscoped_reference_cannot_skip_foreign_migrated_intermediate_owner(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    original_job = job(store, episode=None)
    original = own(original_job)
    middle = job(store, episode=None)
    checkpoint_lineage.link(original_job, middle, source_sha256=SOURCE, episode_id=None)
    child = job(store, episode=None)
    checkpoint_lineage.link(middle, child, source_sha256=SOURCE, episode_id=None)
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {
        original_job.name: EPISODE, middle.name: str(uuid.uuid4()), child.name: EPISODE}})
    with pytest.raises(publication.PublicationError, match='another owner|ancestry is invalid'):
        publish(child, [reference(original_job, original)])


def test_migrated_parent_unmapped_legacy_child_reference_remains_readable(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    parent = job(store, episode=None)
    original = own(parent)
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {parent.name: EPISODE}})
    child = job(store, episode=None)
    checkpoint_lineage.link(parent, child, source_sha256=SOURCE, episode_id=None)
    record = publish(child, [reference(parent, original)])
    assert publication.current_revision(child) == record
    # Completing the normal additive adapter changes no immutable files.
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {parent.name: EPISODE, child.name: EPISODE}})
    assert publication.current_revision(child) == record
    assert publication.resolve_output(child, 'part_001.mp4').read_bytes() == b'authored video 1'


def test_explicit_child_can_reference_legacy_parent_migrated_to_same_owner(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    parent = job(store, episode=None)
    original = own(parent)
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {parent.name: EPISODE}})
    child = job(store)
    checkpoint_lineage.link(parent, child, source_sha256=SOURCE, episode_id=EPISODE)
    record = publish(child, [reference(parent, original)])
    assert publication.current_revision(child) == record
    assert publication.resolve_output(child, 'part_001.mp4').read_bytes() == b'authored video 1'


def test_raw_owner_change_is_rejected_even_when_library_owner_agrees(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    directory = job(store, episode=None)
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {directory.name: EPISODE}})
    record = own(directory)
    assert record['source_identity']['episode_id'] is None
    atomic_json(directory / 'job.json', {'id': directory.name, 'episode_id': EPISODE})
    with pytest.raises(publication.PublicationError, match='source or ownership changed'):
        publication.current_revision(directory)


def test_invalid_migrated_owner_is_not_ignored(tmp_path):
    store = tmp_path / 'data' / 'jobs'
    directory = job(store, episode=None)
    record = own(directory)
    atomic_json(store.parent / 'library.json', {'legacy_jobs': {directory.name: 'invalid-owner'}})
    with pytest.raises(publication.PublicationError, match='source or ownership is invalid'):
        publication.resolve_revision_output(directory, record['revision_id'], 'part_001.mp4')


def test_failed_reference_commit_preserves_previous_publication(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    previous = own(child)
    writer = publication.atomic_json
    def fail(path, value):
        if path.name == 'publication.json':
            raise OSError('Injected precommit fault')
        writer(path, value)
    with patch.object(publication, 'atomic_json', side_effect=fail):
        with pytest.raises(OSError, match='precommit'):
            publish(child, [reference(parent, original, rank=2)])
    assert publication.current_revision(child) == previous
    completed = publish(child, [reference(parent, original, rank=2)])
    assert completed['revision_id'] != previous['revision_id']


def test_reference_cancel_before_commit_preserves_pointer(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    previous = own(child)
    writer = publication.atomic_json
    stopped = [False]
    def cancel_after_manifest(path, value):
        writer(path, value)
        if path.name == 'manifest.json':
            stopped[0] = True
    with patch.object(publication, 'atomic_json', side_effect=cancel_after_manifest):
        with pytest.raises(InterruptedError):
            publication.publish_revision(child, {'parts': []}, [reference(parent, original, rank=2)],
                producer_id='cancel-test', attempt_id='cancelled', cancelled=lambda: stopped[0])
    assert publication.current_revision(child) == previous


def test_fault_after_reference_pointer_commit_keeps_new_revision_readable(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    own(child)
    writer = publication.atomic_json
    def fail_after(path, value):
        writer(path, value)
        if path.name == 'publication.json':
            raise OSError('Injected postcommit fault')
    with patch.object(publication, 'atomic_json', side_effect=fail_after):
        with pytest.raises(OSError, match='postcommit'):
            publish(child, [reference(parent, original, rank=2)])
    assert publication.current_revision(child)['outputs'] == ['part_002.mp4', 'part_002.srt']


def test_legacy_v1_origin_remains_readable(tmp_path):
    parent = tmp_path / str(uuid.uuid4())
    parent.mkdir()
    original = own(parent)
    assert original['version'] == 1
    atomic_json(parent / 'job.json', {'id': parent.name, 'episode_id': EPISODE})
    atomic_json(parent / 'analysis.meta.json', {'source': SOURCE})
    atomic_json(parent / 'source.json', {'path': str(tmp_path / 'original.mp4')})
    child = linked(parent)
    result = publish(child, [reference(parent, original)])
    assert publication.current_revision(child) == result
    assert publication.load_revision(parent, original['revision_id']) == original


def test_non_uuid_diagnostic_directory_keeps_legacy_publication(tmp_path):
    directory = tmp_path / 'job-120s'
    directory.mkdir()
    atomic_json(directory / 'job.json', {'id': directory.name})
    atomic_json(directory / 'analysis.meta.json', {'source': SOURCE})
    atomic_json(directory / 'source.json', {'path': str(tmp_path / 'original.mp4')})
    record = own(directory)
    assert record['version'] == 1
    assert publication.current_revision(directory) == record


def test_complete_uuid_context_cannot_silently_downgrade_on_corruption(tmp_path):
    directory = job(tmp_path)
    atomic_json(directory / 'job.json', {'id': str(uuid.uuid4()), 'episode_id': EPISODE})
    with pytest.raises(publication.PublicationError, match='source or ownership is invalid'):
        own(directory)
    assert not (directory / 'publication.json').exists()


def test_origin_hashing_is_memoized_per_operation(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    record = publish(child, [reference(parent, original), reference(parent, original, rank=2, candidate='another')])
    calls = []
    real_hash = publication.file_sha256
    def track(path, cancelled=lambda: False):
        calls.append(Path(path))
        return real_hash(path, cancelled)
    with patch.object(publication, 'file_sha256', side_effect=track):
        publication.load_revision(child, record['revision_id'])
    for name in ('part_001.mp4', 'part_001.srt'):
        leaf = parent / 'revisions' / original['revision_id'] / name
        assert calls.count(leaf) == 1


def test_origin_manifest_disappearing_during_read_is_publication_error(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    result = publish(child, [reference(parent, original)])
    manifest = parent / 'revisions' / original['revision_id'] / 'manifest.json'
    real_hash = publication.file_sha256
    def vanished(path, cancelled=lambda: False):
        if path == manifest:
            raise FileNotFoundError('Authored read race')
        return real_hash(path, cancelled)
    with patch.object(publication, 'file_sha256', side_effect=vanished):
        with pytest.raises(publication.PublicationError, match='manifest is unreadable'):
            publication.resolve_revision_output(child, result['revision_id'], 'part_001.mp4')


def test_metadata_poll_never_hashes_media_through_references(tmp_path):
    parent = job(tmp_path)
    original = own(parent)
    child = linked(parent)
    result = publish(child, [reference(parent, original)])
    real_hash = publication.file_sha256
    def metadata_only(path, cancelled=lambda: False):
        assert Path(path).suffix not in ('.mp4', '.srt')
        return real_hash(path, cancelled)
    with patch.object(publication, 'file_sha256', side_effect=metadata_only):
        assert publication.current_revision(child, verify_artifacts=False) == result


def test_alias_in_origin_path_rejected(tmp_path):
    parent = job(tmp_path)
    record = own(parent)
    path = parent / 'revisions' / record['revision_id'] / 'part_001.mp4'
    target = parent / 'actual.mp4'
    path.rename(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip('Windows symlink privilege is unavailable')
    with pytest.raises(publication.PublicationError, match='alias'):
        publication.resolve_revision_output(parent, record['revision_id'], path.name)


@pytest.mark.parametrize('aliased', ['publication.json', 'plan.json', 'manifest.json'])
def test_read_only_metadata_alias_rejected(tmp_path, aliased):
    directory = job(tmp_path)
    record = own(directory)
    path = (directory / aliased if aliased == 'publication.json' else
            directory / 'revisions' / record['revision_id'] / aliased)
    target = path.with_name('actual-' + path.name)
    path.rename(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip('Windows symlink privilege is unavailable')
    before = target.read_bytes()
    with patch.object(publication, 'atomic_json', side_effect=AssertionError('Read must not repair')):
        with pytest.raises(publication.PublicationError, match='alias'):
            publication.current_revision(directory, metadata_only=True)
    assert target.read_bytes() == before


def test_windows_extended_drive_resolution_is_normalized(tmp_path):
    if publication.os.name != 'nt':
        pytest.skip('Windows namespace normalization')
    with patch.object(Path, 'resolve', return_value=Path('\\\\?\\' + str(tmp_path))):
        assert publication._canonical_resolved(tmp_path) == tmp_path


def test_resolver_cycle_guard_rejects_adversarial_metadata_graph(tmp_path):
    # A real content-addressed cycle would require a SHA preimage. Exercise the
    # recursion guard independently using an authored graph, not forged files.
    directory = job(tmp_path)
    revision_id = 'b' * 64
    media = {'filename': 'part_001.mp4', 'size': 1, 'sha256': 'c' * 64}
    subtitles = {**media, 'filename': 'part_001.srt'}
    ref = {'job_id': directory.name, 'revision_id': revision_id,
           'video_filename': media['filename'], 'subtitles_filename': subtitles['filename'],
           'manifest_sha256': 'd' * 64}
    record = {'artifacts': [{'video': media, 'subtitles': subtitles,
              'full_decode_version': EXPORT_VALIDATION_VERSION, 'reference': ref}]}
    with patch.object(publication, '_metadata', return_value=record), patch.object(
            publication, 'file_sha256', return_value='d' * 64):
        with pytest.raises(publication.PublicationError, match='Cyclic'):
            publication.resolve_revision_output(directory, revision_id, media['filename'])
