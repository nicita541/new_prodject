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
from app.bounded_storyboard import build_bounded_storyboard


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

    def test_dense_half_second_sampling_has_exact_twelve_frame_hard_ceiling(self):
        values, board = self.build(end=6)
        self.assertEqual(values, [i/2 for i in range(12)])
        self.assertEqual(len(board['frames']), 12)
        self.assertEqual(len(board['pages']), 1)
        with Image.open(self.destination) as picture:
            self.assertEqual(picture.size, (960, 816))
        with self.assertRaises(ValueError):
            self.build(end=6.01)

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
        invalid = [{'times': [i/10 for i in range(13)]},
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


if __name__ == '__main__':
    unittest.main()
