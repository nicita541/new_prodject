"""Real source-frame/PTS integration; no semantic model or supplied answers."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from PIL import Image

from app.config import FFMPEG, FFPROBE, TEMP
from app.media_probe import run_process
from app.bounded_storyboard import build_bounded_storyboard, source_frame_files, source_frame_groups


@unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), 'Portable FFmpeg/FFprobe absent')
class BoundedStoryboardSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TEMP/('bounded-storyboard-'+uuid.uuid4().hex)
        cls.directory.mkdir(parents=True)
        cls.original = cls.directory/'original.mp4'
        cls.encode(cls.original)

    @classmethod
    def tearDownClass(cls):
        cls.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(cls.directory)

    @staticmethod
    def encode(path, pattern='testsrc2=s=160x90:r=12:d=8', offset=0):
        run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', pattern,
                     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-output_ts_offset', str(offset), path],
                    path.with_suffix('.encode.log'), lambda: False, timeout=45)

    def setUp(self):
        self.job = self.directory/uuid.uuid4().hex
        self.job.mkdir()
        self.source = self.job/'source.mp4'
        shutil.copy2(self.original, self.source)
        self.destination = self.job/'current.jpg'

    def build(self, start=0, end=2, **kwargs):
        values = build_bounded_storyboard(self.source, start, end, self.destination,
                                         kwargs.pop('cancelled', lambda: False), **kwargs)
        return values, json.loads(self.destination.with_suffix('.storyboard.json').read_text('utf-8'))

    def test_two_second_context_is_two_original_frames_on_one_small_page(self):
        values, board = self.build(context=True)
        self.assertEqual(values, [0, 23/12])
        self.assertEqual(len(board['frames']), 2)
        self.assertEqual(board['pages'], [str(self.destination.resolve())])
        with Image.open(self.destination) as picture:
            self.assertEqual(picture.size, (960, 204))
        for frame in board['frames']:
            raw = self.job/frame['frame']
            raw.resolve().relative_to(self.job.resolve())
            with Image.open(raw) as picture:
                self.assertEqual(picture.size, (320, 180))
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), frame['sha256'])
        self.assertTrue(board['context'])
        self.assertEqual(board['source']['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_dense_half_second_sampling_uses_shared_eighteen_frame_ceiling(self):
        values, board = self.build(end=6)
        self.assertEqual(values, [i/2 for i in range(12)])
        self.assertEqual(len(board['frames']), 12)
        self.assertEqual(len(board['pages']), 1)
        with Image.open(self.destination) as picture:
            self.assertEqual(picture.size, (960, 816))
        # Real 18-frame CURRENT inference is permitted and retains source PTS.
        timestamps = [i * 0.4 for i in range(18)]
        values18, board18 = self.build(end=8, times=timestamps)
        self.assertEqual(len(values18), 18)
        self.assertEqual(len(board18['frames']), 18)
        self.assertTrue(all(0 <= t < 8 for t in values18))
        with Image.open(self.destination) as page:
            self.assertEqual(page.size, (960, 1224))
        # 19 requests must still fail before decode, without silent truncation.
        with self.assertRaises(ValueError):
            self.build(times=[i / 10 for i in range(19)])

    def test_off_grid_and_late_requests_disclose_actual_pts_without_borrowing(self):
        requests = [1.013, 1.95]
        values, board = self.build(start=1, end=2, times=requests)
        self.assertEqual(values, [13/12, 23/12])
        self.assertEqual([frame['requested_time'] for frame in board['frames']], requests)
        self.assertTrue(all(1 <= value < 2 for value in values))
        for frame in board['frames']:
            numerator, denominator = map(int, frame['time_base'].split('/'))
            self.assertEqual(frame['time'], frame['pts']*numerator/denominator)
        self.assertNotEqual(values, requests)

    def test_nonzero_source_start_keeps_absolute_pts(self):
        self.encode(self.source, offset=3)
        values, _ = self.build(start=3, end=5, times=[3.13, 4.95])
        self.assertEqual(values, [38/12, 59/12])
        self.assertTrue(all(3 <= value < 5 for value in values))

    def test_no_frame_in_window_and_requests_outside_window_are_errors(self):
        for start, end, times in ((.01, .05, [.02]), (0, 2, [2]), (1, 2, [.9]), (9, 10, [9.5])):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.build(start=start, end=end, times=times)
        values, _ = self.build(start=7, end=8, times=[7.99])
        self.assertEqual(values, [95/12])

    def test_limits_and_invalid_numeric_requests_fail_before_source_processing(self):
        invalid = [{'times': [i/10 for i in range(19)]},
                   {'context': True, 'times': [0, .5, 1]}, {'times': []},
                   {'times': [0, 0]}, {'times': [True]}, {'times': [float('nan')]},
                   {'start': float('inf')}, {'end': False}, {'start': 2, 'end': 1},
                   {'context': 'true'}]
        with patch('app.bounded_storyboard.run_process') as execute:
            for arguments in invalid:
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    self.build(**arguments)
            execute.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_verified_cache_reuses_frames_but_repairs_image_log_and_timestamp_tampering(self):
        values, board = self.build(times=[.13])
        frame = self.job/board['frames'][0]['frame']
        meta, log = frame.with_suffix('.json'), frame.with_suffix('.log')
        with patch('app.bounded_storyboard.run_process', wraps=run_process) as execute:
            self.assertEqual(self.build(times=[.13])[0], values)
            self.assertFalse(any(Path(call.args[0][0]) == FFMPEG for call in execute.call_args_list))
        for damage in ('image', 'time', 'log', 'page'):
            if damage == 'image':
                frame.write_bytes(b'broken cache')
            elif damage == 'time':
                saved = json.loads(meta.read_text('utf-8'))
                saved['time'] = 1.5
                meta.write_text(json.dumps(saved), 'utf-8')
            elif damage == 'log':
                log.write_text('invented source PTS', 'utf-8')
            else:
                self.destination.write_bytes(b'broken page')
            with self.subTest(damage=damage):
                repaired, actual = self.build(times=[.13])
                self.assertEqual(repaired, values)
                self.assertEqual(actual['frames'], board['frames'])
                with Image.open(self.destination) as picture:
                    self.assertEqual(picture.size, (960, 204))

    def test_modified_source_invalidates_cached_original_frames(self):
        _, initial = self.build(times=[.13])
        self.encode(self.source, pattern='color=c=red:s=160x90:r=12:d=8')
        _, modified = self.build(times=[.13])
        self.assertNotEqual(initial['source']['sha256'], modified['source']['sha256'])
        self.assertNotEqual(initial['frames'][0]['sha256'], modified['frames'][0]['sha256'])
        self.assertNotEqual(initial['frames'][0]['frame'], modified['frames'][0]['frame'])

    def test_source_mutation_during_extraction_does_not_publish_a_page(self):
        def mutate(command, *args, **kwargs):
            result = run_process(command, *args, **kwargs)
            if Path(command[0]) == FFMPEG:
                with self.source.open('ab') as handle:
                    handle.write(b'source modified during extraction')
            return result
        with patch('app.bounded_storyboard.run_process', side_effect=mutate), self.assertRaises(ValueError):
            self.build(times=[.13])
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix('.storyboard.json').exists())

    def test_cancellation_before_processing_after_decode_and_on_warm_cache_propagates(self):
        with self.assertRaises(InterruptedError):
            self.build(cancelled=lambda: True)
        cancelled = False
        def cancel_after_decode(command, *args, **kwargs):
            nonlocal cancelled
            result = run_process(command, *args, **kwargs)
            if Path(command[0]) == FFMPEG:
                cancelled = True
            return result
        with patch('app.bounded_storyboard.run_process', side_effect=cancel_after_decode):
            with self.assertRaises(InterruptedError):
                self.build(times=[.13], cancelled=lambda: cancelled)
        self.assertFalse(self.destination.exists())
        self.build(times=[.13])
        with self.assertRaises(InterruptedError):
            self.build(times=[.13], cancelled=lambda: True)

    def test_groups_share_one_probe_and_decoder_without_crossing_half_open_owners(self):
        groups = [
            {'start': 1, 'end': 2, 'times': [1.99, 1.013]},
            {'start': 0, 'end': 1, 'times': [.99, 0]},
            {'start': .01, 'end': .05, 'times': [.02]},
            {'start': 1, 'end': 2, 'times': [1]},
            {'start': .08, 'end': .09, 'times': [.081]},
            {'start': 6, 'end': 7, 'times': [6.1]},
        ]
        with patch('app.bounded_storyboard.run_process', wraps=run_process) as execute:
            identity, result = source_frame_groups(self.source, groups, self.job, lambda: False)
        commands = [Path(call.args[0][0]) for call in execute.call_args_list]
        self.assertEqual(commands.count(FFPROBE), 1)
        self.assertEqual(commands.count(FFMPEG), 1)
        self.assertEqual([[r['time'] for r in records] for records, _ in result],
                         [[23/12, 13/12], [11/12, 0], [], [1], [1/12], [74/12]])
        self.assertEqual(result[2], ([], []))
        self.assertEqual(identity['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        for group, (records, paths) in zip(groups, result, strict=True):
            for record, path in zip(records, paths, strict=True):
                self.assertTrue(group['start'] <= record['time'] < group['end'])
                numerator, denominator = map(int, record['time_base'].split('/'))
                self.assertEqual(record['time'], record['pts']*numerator/denominator)
                self.assertEqual(record['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                with Image.open(path) as picture:
                    self.assertEqual(picture.size, (320, 180))

    def test_group_cache_is_byte_compatible_with_single_owner_helper(self):
        groups = [{'start': 0, 'end': 1, 'times': [.13, .99]},
                  {'start': 1.0, 'end': 2.0, 'times': [1.0, 1.99]}]
        expected, saved_bytes = [], {}
        for group in groups:
            identity, records, paths = source_frame_files(self.source, group['start'], group['end'],
                self.job, lambda: False, group['times'])
            expected.append((records, paths))
            for path in paths:
                for proof in (path, path.with_suffix('.log'), path.with_suffix('.json')):
                    saved_bytes[proof] = proof.read_bytes()
        with patch('app.bounded_storyboard._decode_frames') as decode, \
                patch('app.bounded_storyboard.run_process', wraps=run_process) as execute:
            grouped_identity, actual = source_frame_groups(self.source, groups, self.job, lambda: False)
        self.assertEqual(grouped_identity, identity)
        self.assertEqual(actual, expected)
        decode.assert_not_called()
        self.assertEqual(len(execute.call_args_list), 1)
        self.assertEqual(Path(execute.call_args.args[0][0]), FFPROBE)
        self.assertEqual({path: path.read_bytes() for path in saved_bytes}, saved_bytes)

    def test_group_missing_pts_are_deduplicated_globally_and_decoded_in_bounded_batches(self):
        from app.bounded_storyboard import _decode_frames
        self.encode(self.source, pattern='testsrc2=s=160x90:r=24:d=8')
        groups = [{'start': 0, 'end': 3, 'times': [i/24 for i in range(72)]},
                  {'start': 3, 'end': 6, 'times': [i/24 for i in range(72, 144)]},
                  {'start': 6, 'end': 8, 'times': [i/24 for i in range(144, 192)]},
                  {'start': 0, 'end': 8, 'times': [0, 3, 6]}]
        with patch('app.bounded_storyboard._decode_frames', wraps=_decode_frames) as decode:
            _, result = source_frame_groups(self.source, groups, self.job, lambda: False)
        self.assertEqual([len(call.args[1]) for call in decode.call_args_list], [128, 64])
        self.assertEqual([len(records) for records, _ in result], [72, 72, 48, 3])
        self.assertEqual([record['time'] for records, _ in result[:3] for record in records],
                         [i/24 for i in range(192)])
        self.assertEqual([record['time'] for record in result[3][0]], [0, 3, 6])

    def test_all_groups_without_actual_pts_are_empty_but_legacy_helper_still_raises(self):
        groups = [{'start': .01, 'end': .03, 'times': [.02]},
                  {'start': .04, 'end': .05, 'times': [.045]}]
        with patch('app.bounded_storyboard._decode_frames') as decode:
            _, result = source_frame_groups(self.source, groups, self.job, lambda: False)
        self.assertEqual(result, [([], []), ([], [])])
        decode.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Source window contains no video frames'):
            source_frame_files(self.source, .01, .03, self.job, lambda: False, [.02])

    def test_group_validation_precedes_source_processing(self):
        invalid = [[], None, [{}], [{'start': 0, 'end': 1, 'times': None}],
            [{'start': 0, 'end': 1, 'times': []}], [{'start': 1, 'end': 1, 'times': [1]}],
            [{'start': True, 'end': 1, 'times': [.5]}],
            [{'start': 0, 'end': float('inf'), 'times': [.5]}],
            [{'start': 0, 'end': 1, 'times': [True]}],
            [{'start': 0, 'end': 1, 'times': [float('nan')]}],
            [{'start': 0, 'end': 1, 'times': [1]}],
            [{'start': 0, 'end': 1, 'times': [-.1]}],
            [{'start': 0, 'end': 1, 'times': [.5, .5]}]]
        with patch('app.bounded_storyboard.run_process') as execute:
            for groups in invalid:
                with self.subTest(groups=groups), self.assertRaises(ValueError):
                    source_frame_groups(self.source, groups, self.job, lambda: False)
            for width, height in ((0, 180), (320, False), (320.0, 180)):
                with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                    source_frame_groups(self.source, [{'start': 0, 'end': 1, 'times': [.5]}],
                        self.job, lambda: False, width=width, height=height)
            execute.assert_not_called()

    def test_group_source_change_invalidates_cache_and_mid_decode_mutation_fails_closed(self):
        groups = [{'start': 0, 'end': 1, 'times': [.13]},
                  {'start': 2, 'end': 3, 'times': [2.13]}]
        initial_identity, initial = source_frame_groups(self.source, groups, self.job, lambda: False)
        self.encode(self.source, pattern='color=c=red:s=160x90:r=12:d=8')
        changed_identity, changed = source_frame_groups(self.source, groups, self.job, lambda: False)
        self.assertNotEqual(initial_identity['sha256'], changed_identity['sha256'])
        for (old_records, old_paths), (new_records, new_paths) in zip(initial, changed, strict=True):
            self.assertNotEqual(old_records[0]['sha256'], new_records[0]['sha256'])
            self.assertNotEqual(old_paths, new_paths)
        new_groups = [{'start': 3, 'end': 4, 'times': [3.13]}]
        def mutate(command, *args, **kwargs):
            value = run_process(command, *args, **kwargs)
            if Path(command[0]) == FFMPEG:
                with self.source.open('ab') as handle:
                    handle.write(b'changed during grouped decode')
            return value
        with patch('app.bounded_storyboard.run_process', side_effect=mutate), \
                self.assertRaisesRegex(ValueError, 'Source changed'):
            source_frame_groups(self.source, new_groups, self.job, lambda: False)


if __name__ == '__main__':
    unittest.main()
