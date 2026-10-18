"""Publication tests use authored bytes; decoder validation belongs to rendering."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import artifact_publication as publication
from app.media import EXPORT_VALIDATION_VERSION


class PublicationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / '.test-temp'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'work'
        self.source.mkdir()
        self.video = self.source / 'part_001.mp4'
        self.subtitle = self.source / 'part_001.srt'
        self.video.write_bytes(b'authored video bytes')
        self.subtitle.write_bytes(b'authored subtitle bytes')
        self.artifacts = [{'video': self.video, 'subtitles': self.subtitle,
                           'candidate_id': 'candidate-1',
                           'full_decode_version': EXPORT_VALIDATION_VERSION}]
        self.plan = {'segments': [{'start': 0, 'end': 1}], 'title': 'exact plan'}

    def publish(self, **kwargs):
        return publication.publish_revision(self.root, self.plan, self.artifacts,
            producer_id='renderer-1', attempt_id=kwargs.pop('attempt_id', 'attempt-1'), **kwargs)

    def test_publish_resolve_and_idempotent_retry(self):
        first = self.publish()
        second = self.publish(attempt_id='attempt-2')
        self.assertEqual(first, second)
        self.assertEqual(first, publication.current_revision(self.root))
        self.assertEqual(first, publication.load_revision(self.root, first['revision_id']))
        self.assertEqual(self.video.read_bytes(), publication.resolve_output(self.root, 'part_001.mp4').read_bytes())
        self.assertEqual(self.plan, first['plan'])
        self.assertEqual('attempt-1', second['attempt_id'])

    def test_second_revision_keeps_previous_and_ancestry(self):
        first = self.publish()
        self.plan['title'] = 'new plan'
        second = self.publish(parent_revision=first['revision_id'])
        self.assertNotEqual(first['revision_id'], second['revision_id'])
        self.assertEqual(first['revision_id'], second['parent_revision'])
        self.assertEqual(first, publication.load_revision(self.root, first['revision_id']))

    def test_failure_before_commit_preserves_previous(self):
        first = self.publish()
        self.plan['title'] = 'new plan'
        original = publication.atomic_json
        def fail_pointer(path, data):
            if path.name == 'publication.json':
                raise OSError('injected before commit')
            original(path, data)
        with patch.object(publication, 'atomic_json', side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(first, publication.current_revision(self.root))
        self.assertNotEqual(first['revision_id'], self.publish()['revision_id'])

    def test_failure_after_commit_leaves_new_revision_readable(self):
        self.publish()
        self.plan['title'] = 'new plan'
        original = publication.atomic_json
        def fail_after(path, data):
            original(path, data)
            if path.name == 'publication.json':
                raise OSError('injected after commit')
        with patch.object(publication, 'atomic_json', side_effect=fail_after):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.plan, publication.current_revision(self.root)['plan'])

    def test_cancel_before_commit_preserves_previous(self):
        first = self.publish()
        self.plan['title'] = 'new plan'
        original = publication._copy_verified
        stopped = [False]
        def copy_then_cancel(*args):
            original(*args)
            stopped[0] = True
        with patch.object(publication, '_copy_verified', side_effect=copy_then_cancel):
            with self.assertRaises(InterruptedError):
                self.publish(cancelled=lambda: stopped[0])
        self.assertEqual(first, publication.current_revision(self.root))

    def test_no_cancel_after_commit(self):
        original = publication.atomic_json
        stopped = [False]
        def commit_then_cancel(path, data):
            original(path, data)
            if path.name == 'publication.json':
                stopped[0] = True
        with patch.object(publication, 'atomic_json', side_effect=commit_then_cancel):
            record = self.publish(cancelled=lambda: stopped[0])
        self.assertEqual(record, publication.current_revision(self.root))

    def test_same_size_byte_tamper_rejected_and_preserved(self):
        record = self.publish()
        path = publication.resolve_output(self.root, 'part_001.mp4')
        damaged = b'x' * path.stat().st_size
        path.write_bytes(damaged)
        for action in (lambda: publication.current_revision(self.root), self.publish,
                       lambda: publication.load_revision(self.root, record['revision_id']),
                       lambda: publication.resolve_output(self.root, 'part_001.mp4')):
            with self.assertRaises(publication.PublicationError):
                action()
        self.assertEqual(damaged, path.read_bytes())

    def test_manifest_and_plan_tamper_rejected(self):
        record = self.publish()
        directory = self.root / 'revisions' / record['revision_id']
        path = directory / 'plan.json'
        path.write_text('{"changed": true}', encoding='utf-8')
        with self.assertRaises(publication.PublicationError):
            publication.current_revision(self.root)

    def test_manifest_metadata_tamper_rejected(self):
        record = self.publish()
        path = self.root / 'revisions' / record['revision_id'] / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['attempt_id'] = 'another-attempt'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(publication.PublicationError):
            publication.current_revision(self.root)

    def test_nonfinite_plan_missing_receipt_and_escape_rejected(self):
        self.plan['invalid'] = float('nan')
        with self.assertRaises(publication.PublicationError):
            self.publish()
        self.plan.pop('invalid')
        self.artifacts[0]['full_decode_version'] = True
        with self.assertRaises(publication.PublicationError):
            self.publish()
        self.artifacts[0]['full_decode_version'] = EXPORT_VALIDATION_VERSION
        self.artifacts[0]['video'] = self.root.parent / 'part_001.mp4'
        with self.assertRaises(publication.PublicationError):
            self.publish()
        self.assertFalse((self.root / 'publication.json').exists())

    def test_legacy_only_when_pointer_absent(self):
        output = self.root / 'output'
        output.mkdir()
        legacy = output / 'part_001.mp4'
        legacy.write_bytes(b'legacy')
        self.assertEqual(legacy, publication.resolve_output(self.root, legacy.name))
        with self.assertRaises(publication.PublicationError):
            publication.resolve_output(self.root, legacy.name, allow_legacy=False)
        (self.root / 'publication.json').write_text('broken', encoding='utf-8')
        with self.assertRaises(publication.PublicationError):
            publication.resolve_output(self.root, legacy.name)

    def test_unpublished_outputs_and_public_path_escape_rejected(self):
        self.publish()
        for filename in ('part_002.mp4', '../part_001.mp4', 'part_001.mp4/other'):
            with self.assertRaises(publication.PublicationError):
                publication.resolve_output(self.root, filename)

    def test_metadata_poll_skips_media_streaming_but_full_read_detects_tamper(self):
        record = self.publish()
        video = publication.resolve_output(self.root, 'part_001.mp4')
        video.write_bytes(b'x' * video.stat().st_size)
        original = publication.file_sha256
        def metadata_hash(path, cancelled=lambda: False):
            self.assertNotIn(path.suffix, ('.mp4', '.srt'))
            return original(path, cancelled)
        with patch.object(publication, 'file_sha256', side_effect=metadata_hash):
            self.assertEqual(record, publication.current_revision(self.root, verify_artifacts=False))
            self.assertEqual(record, publication.load_revision(self.root, record['revision_id'], verify_artifacts=False))
        with self.assertRaises(publication.PublicationError):
            publication.current_revision(self.root)

    def test_source_changed_during_copy_cannot_publish(self):
        first = self.publish()
        self.plan['title'] = 'new plan'
        original = publication._copy_verified
        def change_then_copy(source, *args):
            source.write_bytes(b'changed during copy')
            original(source, *args)
        with patch.object(publication, '_copy_verified', side_effect=change_then_copy):
            with self.assertRaises(publication.PublicationError):
                self.publish()
        self.assertEqual(first, publication.current_revision(self.root))

    def test_failure_before_revision_rename_cannot_publish(self):
        first = self.publish()
        self.plan['title'] = 'new plan'
        with patch.object(Path, 'rename', side_effect=OSError('injected rename failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(first, publication.current_revision(self.root))

    def test_nonfinite_manifest_rejected_as_publication_error(self):
        record = self.publish()
        path = self.root / 'revisions' / record['revision_id'] / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['artifacts'][0]['video']['size'] = float('nan')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(publication.PublicationError):
            publication.current_revision(self.root, verify_artifacts=False)

    def test_native_candidate_names_aliased_to_rank(self):
        other = self.root / 'second-candidate'
        other.mkdir()
        (other / self.video.name).write_bytes(b'second candidate video')
        (other / self.subtitle.name).write_bytes(b'second candidate subtitles')
        self.artifacts[0]['output_index'] = 1
        self.artifacts.append({'video': other / self.video.name,
            'subtitles': other / self.subtitle.name, 'candidate_id': 'candidate-2',
            'full_decode_version': EXPORT_VALIDATION_VERSION, 'output_index': 2})
        record = self.publish()
        self.assertEqual(['part_001.mp4', 'part_001.srt', 'part_002.mp4', 'part_002.srt'], record['outputs'])
        self.assertEqual(b'second candidate video', publication.resolve_output(self.root, 'part_002.mp4').read_bytes())
        self.assertEqual(b'second candidate subtitles', publication.resolve_output(self.root, 'part_002.srt').read_bytes())
        self.assertEqual(self.video.read_bytes(), publication.resolve_output(self.root, 'part_001.mp4').read_bytes())

    def test_public_rank_requires_valid_integer(self):
        for value in (None, True, 0, 1000, 1.0, '1'):
            with self.subTest(value=value):
                self.artifacts[0]['output_index'] = value
                with self.assertRaises(publication.PublicationError):
                    self.publish()


if __name__ == '__main__':
    unittest.main()
