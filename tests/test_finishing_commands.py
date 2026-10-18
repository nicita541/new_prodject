"""Finishing storage/recovery tests, with authored bytes and no media inference.

Fake media and explicitly authored decode declarations test receipt mechanics;
they are not a claim that any fake file passed a real decoder.
"""
import copy
import hashlib
import builtins
import importlib.util
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from app.config import TEMP
from app.json_store import atomic_json, read_json
from app.file_lock import InstanceLock
from app import finishing_commands as commands
from app.media import EXPORT_VALIDATION_VERSION

class FinishingCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = TEMP/('finishing-command-storage-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.job = str(uuid.uuid4())
        self.operation = str(uuid.uuid4())
        self.source = self.root/'data/imports/source.mp4'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'authored source identity, not real media')
        self.track = self.root/'finishing/assets/music.mp3'
        self.track.parent.mkdir(parents=True)
        self.track.write_bytes(b'authored music identity')
        self.source_sha = self.sha(self.source)
        self.store = commands.FinishingCommands(self.root, lock_factory=InstanceLock)
        self.request = {'part_indices': [1, 2]}
        self.payload = {
            'source': {'path': 'data/imports/source.mp4', 'sha256': self.source_sha},
            'plan': {'parts': [self.part(1), self.part(2)]},
            'source_plan_digest': '1'*64, 'publication_revision': '2'*64,
            'audio_stream': 1, 'profile': {'authored': 'frozen original style'}, 'preview': None,
            'probe': {'width': 1920, 'height': 1080, 'audio_stream': 1},
            'caption_revisions': {'1': {'target_id': '3'*64, 'revision': 4},
                                  '2': {'target_id': '4'*64, 'revision': 0}},
            'assets': [{'role': 'music', 'path': 'finishing/assets/music.mp3', 'sha256': self.sha(self.track)}],
            'resolved_music': {'1': {'asset_sha256': self.sha(self.track), 'volume': .15}, '2': None},
            'render_contract': {'version': 1, 'code_sha256': '5'*64}}
        self.freeze = Mock(side_effect=lambda: copy.deepcopy(self.payload))
        self.preflight = Mock()

    def tearDown(self):
        self.root.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.root)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def part(index):
        return {'index': index, 'duration': 3.0,
                'cuts': [{'start': index*10.0, 'end': index*10.0+3}],
                'subtitles': [{'start': .2, 'end': 1, 'text': 'Exact authored caption'}]}

    def submit(self, **kwargs):
        values = {'job_id': self.job, 'source_sha256': self.source_sha, 'kind': 'export',
            'request': self.request, 'freeze': self.freeze, 'operation_id': self.operation,
            'preflight': self.preflight}
        values.update(kwargs)
        return self.store.submit(**values)

    def directory(self, command):
        return self.store.task_directory(command['job_id'], command['kind'], command['task_id'])

    def receipt(self):
        return self.root/'finishing/operations'/(self.operation+'.json')

    def running(self, command):
        attempt = self.store.begin_attempt(command)['attempt_id']
        self.store.update_attempt(command, attempt, status='running', progress=.01)
        return attempt

    def fake_artifacts(self, command, attempt, index):
        output = self.directory(command)/'attempts'/attempt/'output'
        output.mkdir(parents=True, exist_ok=True)
        video, subtitles = output/f'part_{index:03}.mp4', output/f'part_{index:03}.srt'
        video.write_bytes(b'authored video receipt bytes '+str(index).encode())
        subtitles.write_bytes(b'authored subtitle receipt bytes')
        return {'video': video.relative_to(self.root).as_posix(),
            'subtitles': subtitles.relative_to(self.root).as_posix(),
            'validation': {'full_decode_version': EXPORT_VALIDATION_VERSION,
                'video_sha256': self.sha(video), 'subtitles_sha256': self.sha(subtitles)}}

    def test_exact_retry_survives_new_store_and_precedes_busy_profile_and_asset_preflight(self):
        command = self.submit()
        self.assertEqual(command['request']['profile'], {'mode': 'stored'})
        self.assertEqual(read_json(self.receipt())['state'], 'committed')
        self.assertEqual(read_json(self.directory(command)/'command.json'), command)
        self.store = commands.FinishingCommands(self.root, lock_factory=InstanceLock)
        self.preflight.side_effect = AssertionError('a busy queue must not block replay')
        self.freeze.side_effect = AssertionError('saved profile must not be resolved again')
        self.source.unlink()
        self.track.unlink()
        self.assertEqual(self.submit(), command)
        self.assertEqual(self.freeze.call_count, 1)
        self.assertEqual(self.preflight.call_count, 1)
        self.assertEqual(self.store.load(self.operation), command)
        with self.assertRaises(commands.CommandError):
            self.store.load(self.operation, verify_assets=True)

    def test_optional_operation_id_is_generated_and_task_type_is_owned(self):
        command = self.submit(operation_id=None)
        self.assertEqual(str(uuid.UUID(command['operation_id'])), command['operation_id'])
        self.assertRegex(command['task_id'], r'^ex_[0-9a-f]{32}$')
        self.assertEqual(self.store.load(command['operation_id'], job_id=self.job,
            source_sha256=self.source_sha, kind='export'), command)
        for expected in ({'job_id': str(uuid.uuid4())}, {'source_sha256': 'f'*64}, {'kind': 'preview'}):
            with self.subTest(expected=expected), self.assertRaises(commands.OperationConflict):
                self.store.load(command['operation_id'], **expected)

    def test_reusing_operation_with_different_request_owner_type_or_order_conflicts(self):
        self.submit()
        self.freeze.reset_mock()
        self.preflight.reset_mock()
        changes = [dict(job_id=str(uuid.uuid4())), dict(source_sha256='f'*64),
            dict(request={'part_indices': [2, 1]}), dict(request={'part_indices': [1]}),
            dict(request={'part_indices': [1, 2], 'settings': self.payload['profile']}),
            dict(kind='preview', request={'part_index': 1})]
        for values in changes:
            with self.subTest(values=values), self.assertRaises(commands.OperationConflict):
                self.submit(**values)
        self.freeze.assert_not_called()
        self.preflight.assert_not_called()

    def test_explicit_profile_is_not_a_stored_profile_marker_and_cannot_freeze_other_settings(self):
        explicit = {'part_indices': [1, 2], 'settings': self.payload['profile']}
        command = self.submit(request=explicit)
        self.assertEqual(command['request']['profile'], {'mode': 'explicit', 'value': self.payload['profile']})
        other = str(uuid.uuid4())
        with self.assertRaisesRegex(commands.CommandError, 'explicit profile'):
            self.submit(operation_id=other, request={**explicit, 'settings': {'other': 'settings'}})
        self.assertFalse((self.root/'finishing/operations'/(other+'.json')).exists())

    def test_preview_preserves_requested_span_separately_from_source_bounded_span(self):
        self.payload['plan']['parts'] = [self.part(1)]
        self.payload['caption_revisions'].pop('2')
        self.payload['resolved_music'].pop('2')
        self.payload['preview'] = {'part_index': 1, 'from': 2.0, 'duration': 1.0}
        command = self.submit(kind='preview', request={'part_index': 1, 'from': 2})
        self.assertRegex(command['task_id'], r'^pv_[0-9a-f]{32}$')
        self.assertEqual(command['request']['preview']['duration'], 5.0)
        self.assertEqual(command['frozen']['preview']['duration'], 1.0)
        self.assertEqual(self.submit(kind='preview', request={'part_index': 1, 'from': 2.0, 'duration': 5}), command)

    def test_crash_after_complete_reservation_recovers_without_callbacks_or_current_assets(self):
        def fail_command(path, value):
            if path.name == 'command.json':
                raise OSError('authored disk interruption')
            return atomic_json(path, value)
        with patch.object(commands, 'atomic_json', side_effect=fail_command), self.assertRaises(OSError):
            self.submit()
        reserved = read_json(self.receipt())
        self.assertEqual(reserved['state'], 'reserved')
        self.source.unlink()
        self.track.unlink()
        self.freeze.side_effect = AssertionError('recovery cannot freeze changed parameters')
        self.preflight.side_effect = AssertionError('recovery cannot check busy state')
        recovered = self.store.recover(self.operation)
        self.assertEqual(recovered, reserved['command'])
        self.assertEqual(read_json(self.receipt())['state'], 'committed')
        self.assertEqual(self.submit(), recovered)
        self.assertEqual(self.freeze.call_count, 1)

    def test_crash_after_command_before_commit_repairs_only_receipt(self):
        def fail_commit(path, value):
            if path == self.receipt() and value['state'] == 'committed':
                raise OSError('authored final pointer interruption')
            return atomic_json(path, value)
        with patch.object(commands, 'atomic_json', side_effect=fail_commit), self.assertRaises(OSError):
            self.submit()
        receipt = read_json(self.receipt())
        command_path = self.directory(receipt['command'])/'command.json'
        before = command_path.read_bytes()
        with patch.object(commands, 'atomic_json', wraps=atomic_json) as writes:
            self.assertEqual(self.store.recover(self.operation), receipt['command'])
        self.assertEqual([call.args[0] for call in writes.call_args_list], [self.receipt()])
        self.assertEqual(command_path.read_bytes(), before)

    def test_corrupt_reserved_receipt_is_preserved_and_never_calls_freeze(self):
        self.receipt().parent.mkdir(parents=True)
        self.receipt().write_bytes(b'{incomplete authored receipt')
        before = self.receipt().read_bytes()
        with self.assertRaises(commands.CommandError):
            self.submit()
        self.freeze.assert_not_called()
        self.preflight.assert_not_called()
        self.assertEqual(self.receipt().read_bytes(), before)

    def test_json_null_receipt_is_corruption_not_missing_operation_to_recreate(self):
        self.receipt().parent.mkdir(parents=True)
        self.receipt().write_bytes(b'null')
        for callback in (self.submit, lambda: self.store.recover(self.operation)):
            with self.subTest(callback=callback), self.assertRaises(commands.CommandError):
                callback()
        self.freeze.assert_not_called()
        self.preflight.assert_not_called()
        self.assertEqual(self.receipt().read_bytes(), b'null')

    def test_json_null_reserved_command_cannot_be_silently_overwritten_during_repair(self):
        def fail_command(path, value):
            if path.name == 'command.json':
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'null')
                raise OSError('authored corrupt command write')
            return atomic_json(path, value)
        with patch.object(commands, 'atomic_json', side_effect=fail_command), self.assertRaises(OSError):
            self.submit()
        command_path = self.directory(read_json(self.receipt())['command'])/'command.json'
        with self.assertRaises(commands.CommandError):
            self.store.recover(self.operation)
        self.assertEqual(command_path.read_bytes(), b'null')

    def test_tampered_command_or_receipt_hash_is_not_rewritten(self):
        command = self.submit()
        command_path = self.directory(command)/'command.json'
        changed = copy.deepcopy(command)
        changed['frozen']['profile']['authored'] = 'changed bytes'
        atomic_json(command_path, changed)
        before = command_path.read_bytes()
        with self.assertRaises(commands.CommandError):
            self.submit()
        self.assertEqual(command_path.read_bytes(), before)
        atomic_json(command_path, command)
        receipt = read_json(self.receipt())
        receipt['command']['source_sha256'] = 'f'*64
        atomic_json(self.receipt(), receipt)
        before = self.receipt().read_bytes()
        with self.assertRaises(commands.CommandError):
            self.store.recover(self.operation)
        self.assertEqual(self.receipt().read_bytes(), before)

    def test_missing_committed_command_is_corruption_not_reservation_to_reconstruct(self):
        command = self.submit()
        (self.directory(command)/'command.json').unlink()
        with self.assertRaisesRegex(commands.CommandError, 'missing'):
            self.store.recover(self.operation)
        self.assertFalse((self.directory(command)/'command.json').exists())

    def test_tombstone_prevents_retry_or_recovery_resurrecting_deleted_task(self):
        command = self.submit()
        with self.assertRaises(commands.OperationConflict):
            self.store.tombstone(self.operation, job_id=str(uuid.uuid4()))
        self.store.tombstone(self.operation, job_id=self.job)
        shutil.rmtree(self.directory(command))
        for callback in (self.submit, lambda: self.store.recover(self.operation),
                         lambda: self.store.load(self.operation), lambda: self.store.begin_attempt(command)):
            with self.subTest(callback=callback), self.assertRaises(commands.OperationConflict):
                callback()
        self.assertEqual(read_json(self.receipt())['state'], 'deleted')
        self.assertFalse(self.directory(command).exists())

    def test_source_and_assets_are_content_verified_independent_of_same_size_metadata(self):
        command = self.submit()
        self.store.verify_assets(command)
        self.track.write_bytes(b'X'*self.track.stat().st_size)
        with self.assertRaisesRegex(commands.CommandError, 'bytes changed'):
            self.store.verify_assets(command)
        self.track.write_bytes(b'authored music identity')
        self.source.write_bytes(b'Y'*self.source.stat().st_size)
        with self.assertRaisesRegex(commands.CommandError, 'bytes changed'):
            self.store.verify_assets(command)

    def test_escape_paths_bad_numeric_profiles_and_owner_ids_fail_before_reservation(self):
        for path in ('../outside.mp4', '/outside.mp4', 'C:/outside.mp4', 'data\\outside.mp4',
                     'data/../outside.mp4', 'data//source.mp4', './data/source.mp4'):
            payload = copy.deepcopy(self.payload)
            payload['source']['path'] = path
            with self.subTest(path=path), self.assertRaises(commands.CommandError):
                self.submit(freeze=lambda: payload)
        for values in ({'operation_id': uuid.uuid4().hex}, {'job_id': '../../other'},
            {'source_sha256': 'not a hash'}, {'request': {'part_indices': [True]}},
            {'request': {'part_indices': [1, 1]}}, {'request': {'part_indices': [1], 'unexpected': True}},
            {'request': {'part_indices': [1], 'settings': {'bad': float('nan')}}}):
            with self.subTest(values=values), self.assertRaises(commands.CommandError):
                self.submit(**values)
        self.assertFalse(self.receipt().exists())

    def test_role_mismatch_or_unowned_source_identity_is_rejected(self):
        invalid = []
        payload = copy.deepcopy(self.payload)
        payload['assets'][0]['role'] = 'avatar'
        invalid.append(payload)
        payload = copy.deepcopy(self.payload)
        payload['source']['sha256'] = 'f'*64
        invalid.append(payload)
        payload = copy.deepcopy(self.payload)
        payload['plan']['parts'].reverse()
        invalid.append(payload)
        payload = copy.deepcopy(self.payload)
        payload['caption_revisions']['1']['target_id'] = 'other-source'
        invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(commands.CommandError):
                self.submit(freeze=lambda: payload)
        self.assertFalse(self.receipt().exists())

    def test_path_alias_cannot_redirect_source_ownership_even_inside_same_root(self):
        alias = self.source.parent/'alias.mp4'
        try:
            alias.symlink_to(self.source)
        except OSError:
            self.skipTest('Windows symbolic-link creation unavailable')
        payload = copy.deepcopy(self.payload)
        payload['source']['path'] = alias.relative_to(self.root).as_posix()
        with self.assertRaisesRegex(commands.CommandError, 'redirect'):
            self.submit(freeze=lambda: payload)
        self.assertFalse(self.receipt().exists())

    def test_operation_lock_prevents_another_store_from_freezing_the_same_operation(self):
        from app.jobs import BusyError
        lock = self.store._lock(self.operation)
        try:
            other = commands.FinishingCommands(self.root, lock_factory=InstanceLock)
            with self.assertRaises(BusyError):
                other.submit(self.job, self.source_sha, 'export', self.request, self.freeze,
                    operation_id=self.operation, preflight=self.preflight)
        finally:
            lock.close()
        self.freeze.assert_not_called()
        self.preflight.assert_not_called()
        self.submit()

    def test_attempt_fencing_survives_reopening_and_blocks_old_or_terminal_writers(self):
        command = self.submit()
        first = self.running(command)
        with self.assertRaises(commands.CommandError):
            self.store.begin_attempt(command)
        self.store.update_attempt(command, first, status='interrupted', progress=.4)
        self.store = commands.FinishingCommands(self.root, lock_factory=InstanceLock)
        second = self.running(command)
        for status in ('running', 'completed', 'failed'):
            with self.subTest(status=status), self.assertRaises(commands.StaleAttempt):
                self.store.update_attempt(command, first, status=status, progress=1)
        self.store.update_attempt(command, second, status='cancelled', progress=.2)
        with self.assertRaises(commands.StaleAttempt):
            self.store.update_attempt(command, second, status='running')
        with self.assertRaises(commands.StaleAttempt):
            self.store.begin_attempt(command, attempt_id=first)

    def test_completion_requires_all_valid_parts_and_resume_reuses_first_receipt(self):
        command = self.submit()
        first = self.running(command)
        with self.assertRaisesRegex(commands.CommandError, 'every validated part'):
            self.store.update_attempt(command, first, status='completed', progress=1)
        first_part = self.store.commit_part(command, first, 1, **self.fake_artifacts(command, first, 1))
        self.store.update_attempt(command, first, status='failed', progress=.5)
        second = self.running(command)
        self.assertEqual(self.store.part_receipt(command, 1), first_part)
        with self.assertRaises(commands.StaleAttempt):
            self.store.commit_part(command, first, 2, **self.fake_artifacts(command, first, 2))
        self.store.commit_part(command, second, 2, **self.fake_artifacts(command, second, 2))
        done = self.store.update_attempt(command, second, status='completed', progress=1)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(self.store.part_receipt(command, 1)['attempt_id'], first)
        with self.assertRaisesRegex(commands.CommandError, 'does not need'):
            self.store.begin_attempt(command)

    def test_part_validation_rejects_wrong_version_hash_owner_and_later_tampering(self):
        command = self.submit()
        attempt = self.running(command)
        artifacts = self.fake_artifacts(command, attempt, 1)
        for replacement in (
            {'full_decode_version': EXPORT_VALIDATION_VERSION+1}, {'video_sha256': 'f'*64}):
            arguments = copy.deepcopy(artifacts)
            arguments['validation'].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(commands.CommandError):
                self.store.commit_part(command, attempt, 1, **arguments)
        arguments = copy.deepcopy(artifacts)
        arguments['video'] = self.payload['source']['path']
        with self.assertRaises(commands.CommandError):
            self.store.commit_part(command, attempt, 1, **arguments)
        receipt = self.store.commit_part(command, attempt, 1, **artifacts)
        self.assertEqual(receipt, self.store.part_receipt(command, 1))
        video = self.root/artifacts['video']
        video.write_bytes(b'X'*video.stat().st_size)
        with self.assertRaisesRegex(commands.CommandError, 'bytes changed'):
            self.store.part_receipt(command, 1)

    def test_part_commit_crash_leaves_reusable_immutable_receipt_before_pointer(self):
        command = self.submit()
        attempt = self.running(command)
        artifacts = self.fake_artifacts(command, attempt, 1)
        pointer = self.directory(command)/'parts/part_001.json'
        def fail_pointer(path, value):
            if path == pointer:
                raise OSError('authored part pointer interruption')
            return atomic_json(path, value)
        with patch.object(commands, 'atomic_json', side_effect=fail_pointer), self.assertRaises(OSError):
            self.store.commit_part(command, attempt, 1, **artifacts)
        self.assertIsNone(self.store.part_receipt(command, 1))
        receipts = list((self.directory(command)/'receipts').glob('*.json'))
        self.assertEqual(len(receipts), 1)
        before = receipts[0].read_bytes()
        with patch.object(commands, 'atomic_json', wraps=atomic_json) as writes:
            self.store.commit_part(command, attempt, 1, **artifacts)
        self.assertEqual([call.args[0] for call in writes.call_args_list], [pointer])
        self.assertEqual(receipts[0].read_bytes(), before)

    def other_area(self, *, outside=False):
        path = ((TEMP/('finishing-other-owner-'+uuid.uuid4().hex)) if outside
                else self.root/('other-owner-'+uuid.uuid4().hex))
        path.resolve().relative_to(TEMP.resolve())
        path.mkdir()
        if outside:
            self.addCleanup(shutil.rmtree, path)
        return path

    def alias(self, path, target, *, directory=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError:
            self.skipTest('Windows symbolic-link creation unavailable')

    def test_default_lock_is_the_same_shared_class_without_jobs_lifecycle_import(self):
        store = commands.FinishingCommands(self.root)
        self.assertIs(store._lock_factory, InstanceLock)
        # Execute this module under a fresh name: storage may import its lock,
        # but importing JobManager/worker/model lifecycle is a layering error.
        real_import = builtins.__import__
        forbidden = {'app.jobs', 'app.worker', 'app.pipeline', 'app.vision', 'app.deepseek'}
        def checked_import(name, *args, **kwargs):
            if name in forbidden:
                raise AssertionError('Finishing storage imported lifecycle: '+name)
            return real_import(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location('finishing_store_import_check', commands.__file__)
        isolated = importlib.util.module_from_spec(spec)
        with patch('builtins.__import__', side_effect=checked_import):
            spec.loader.exec_module(isolated)
            self.assertIs(isolated.FinishingCommands(self.root)._lock_factory, InstanceLock)

    def test_attempt_parent_alias_is_rejected_before_any_directory_is_created(self):
        command = self.submit()
        for outside in (False, True):
            with self.subTest(outside=outside):
                other = self.other_area(outside=outside)
                alias = self.directory(command)/'attempts'
                self.alias(alias, other, directory=True)
                try:
                    with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                        self.store.begin_attempt(command)
                    self.assertEqual(list(other.iterdir()), [])
                    self.assertFalse((self.directory(command)/'runtime.json').exists())
                finally:
                    alias.unlink()

    def test_runtime_file_alias_blocks_reads_and_preserves_both_owners(self):
        command = self.submit()
        other = self.other_area(outside=True)/'foreign-runtime.json'
        other.write_text('{"foreign":"untouched"}', encoding='utf-8')
        self.alias(self.directory(command)/'runtime.json', other)
        with patch.object(commands, 'read_json', wraps=read_json) as reads:
            with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                self.store.begin_attempt(command)
        self.assertNotIn(other, [call.args[0] for call in reads.call_args_list])
        self.assertEqual(other.read_text(encoding='utf-8'), '{"foreign":"untouched"}')

    def test_immutable_command_file_alias_blocks_replay_load_and_recovery(self):
        command = self.submit()
        path = self.directory(command)/'command.json'
        other = self.other_area(outside=True)/'foreign-command.json'
        other.write_bytes(path.read_bytes())
        path.unlink()
        self.alias(path, other)
        before = other.read_bytes()
        for callback in (self.submit, lambda: self.store.load(self.operation),
                         lambda: self.store.recover(self.operation)):
            with self.subTest(callback=callback), self.assertRaisesRegex(commands.CommandError, 'redirect'):
                callback()
        self.assertEqual(other.read_bytes(), before)

    def test_receipt_and_part_pointer_parent_aliases_cannot_redirect_commit_writes(self):
        command = self.submit()
        attempt = self.running(command)
        artifacts = self.fake_artifacts(command, attempt, 1)
        for name in ('receipts', 'parts'):
            with self.subTest(name=name):
                other = self.other_area(outside=True)
                alias = self.directory(command)/name
                self.alias(alias, other, directory=True)
                try:
                    with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                        self.store.commit_part(command, attempt, 1, **artifacts)
                    self.assertEqual(list(other.iterdir()), [])
                finally:
                    alias.unlink()

    def test_receipt_file_and_pointer_file_aliases_are_rejected_before_read(self):
        command = self.submit()
        attempt = self.running(command)
        record = self.store.commit_part(command, attempt, 1,
            **self.fake_artifacts(command, attempt, 1))
        directory = self.directory(command)
        pointer = directory/'parts/part_001.json'
        receipt = directory/'receipts'/(commands.digest(record)+'.json')
        for path in (pointer, receipt):
            with self.subTest(path=path.name):
                other = self.other_area(outside=True)/path.name
                data = path.read_bytes()
                other.write_bytes(data)
                path.unlink()
                self.alias(path, other)
                try:
                    with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                        self.store.part_receipt(command, 1)
                    self.assertEqual(other.read_bytes(), data)
                finally:
                    path.unlink()
                    path.write_bytes(data)

    def test_output_file_alias_cannot_supply_other_owner_bytes_as_validated_artifact(self):
        command = self.submit()
        attempt = self.running(command)
        artifacts = self.fake_artifacts(command, attempt, 1)
        video = self.root/artifacts['video']
        other = self.other_area(outside=True)/video.name
        data = video.read_bytes()
        other.write_bytes(data)
        video.unlink()
        self.alias(video, other)
        with self.assertRaisesRegex(commands.CommandError, 'redirect'):
            self.store.commit_part(command, attempt, 1, **artifacts)
        self.assertEqual(other.read_bytes(), data)

    def test_operation_and_lock_parent_aliases_fail_before_callbacks_or_outside_writes(self):
        for relative in ('finishing/operations', 'finishing/operations/.locks'):
            with self.subTest(relative=relative):
                other = self.other_area(outside=True)
                alias = self.root/relative
                self.alias(alias, other, directory=True)
                try:
                    with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                        self.submit()
                    self.assertEqual(list(other.iterdir()), [])
                    self.freeze.assert_not_called()
                    self.preflight.assert_not_called()
                finally:
                    alias.unlink()

    def test_operation_and_lock_file_aliases_fail_without_rewriting_other_records(self):
        command = self.submit()
        for path in (self.receipt(), self.root/'finishing/operations/.locks'/(self.operation+'.lock')):
            with self.subTest(path=path.name):
                other = self.other_area(outside=True)/path.name
                data = path.read_bytes()
                other.write_bytes(data)
                path.unlink()
                self.alias(path, other)
                try:
                    for callback in (self.submit, lambda: self.store.recover(self.operation),
                                     lambda: self.store.tombstone(self.operation, job_id=self.job)):
                        with self.subTest(callback=callback), self.assertRaisesRegex(commands.CommandError, 'redirect'):
                            callback()
                    self.assertEqual(other.read_bytes(), data)
                finally:
                    path.unlink()
                    path.write_bytes(data)
        self.assertEqual(self.store.load(self.operation), command)

    def test_music_and_avatar_assets_cannot_use_aliases_to_another_owner(self):
        for role in ('music', 'avatar'):
            with self.subTest(role=role):
                path = self.track.parent/(role+'-alias.bin')
                self.alias(path, self.track)
                payload = copy.deepcopy(self.payload)
                payload['assets'].append({'role': role, 'path': path.relative_to(self.root).as_posix(),
                    'sha256': self.sha(self.track)})
                try:
                    with self.assertRaisesRegex(commands.CommandError, 'redirect'):
                        self.submit(freeze=lambda: payload)
                    self.assertFalse(self.receipt().exists())
                finally:
                    path.unlink()


if __name__ == '__main__':
    unittest.main()
