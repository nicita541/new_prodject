import json
import copy
from contextlib import contextmanager
import uuid
import time
import threading
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import FFMPEG, FFPROBE, TEMP
from app.media import choose_encoder, crop_expressions, crop_position, crop_size, inspect_media, render_part, run_command, run_render_command, validate_export
from app.pipeline import _run_render_tasks, run_job


@contextmanager
def workspace_directory(prefix="media_test_"):
    # Keep diagnostic media inside the project and avoid mkdtemp's restricted ACL.
    path = TEMP / (prefix + uuid.uuid4().hex)
    path.mkdir()
    yield str(path)


class CropTests(unittest.TestCase):
    def test_shot_boundary_jumps_at_boundary_while_reply_focus_remains_smooth(self):
        cut = {"start": 10, "end": 15, "focus": [
            {"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
            {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.9, "hard_cut": True},
            {"time": 14, "x": 0.1, "y": 0.5, "confidence": 0.9, "hard_cut": False}]}
        expression, _ = crop_expressions(cut, 64, 36)
        def position(time):
            return eval(expression.replace("if(", "choose("), {"__builtins__": {}},
                        {"t": time, "choose": lambda condition, a, b: a if condition else b,
                         "lt": lambda a, b: a < b, "clip": lambda a, low, high: min(max(a, low), high)})
        self.assertEqual(position(1.9999), 0)
        self.assertEqual(position(2), 44)
        self.assertEqual(position(2.0001), 44)
        self.assertEqual(position(3.75), 44)
        self.assertAlmostEqual(position(3.875), 22)
        self.assertEqual(position(4), 0)

    def test_wide_and_tall_images_clamp(self):
        for width, height in [(1920, 1080), (600, 1600)]:
            cw, ch = crop_size(width, height)
            self.assertLess(abs(cw / ch - 9 / 16), 0.004)
            self.assertEqual(crop_position(-1, -1, width, height), (0, 0))
            self.assertEqual(crop_position(2, 2, width, height), (width - cw, height - ch))


class EncoderProbeTests(unittest.TestCase):
    def test_nvenc_probe_uses_dimensions_supported_by_current_gpu(self):
        with workspace_directory() as directory, patch("app.media.run_command") as run:
            self.assertEqual(choose_encoder(Path(directory)), "h264_nvenc")
            command = run.call_args.args[0]
            self.assertIn("color=size=256x256:rate=30", command)

    def test_nvenc_probe_failure_falls_back_to_cpu(self):
        for error in (RuntimeError("unsupported"), TimeoutError("probe timed out")):
            with self.subTest(error=type(error).__name__), workspace_directory() as directory, \
                    patch("app.media.run_command", side_effect=error):
                self.assertEqual(choose_encoder(Path(directory)), "libx264")


class RenderProgressTests(unittest.TestCase):
    def _simulate(self, directory, observations, on_progress=None, duration=10, inputs=0):
        clock = [0.0]
        def run(args, workdir, cancelled, *, timeout, on_tick):
            self.assertGreater(timeout, 180)
            progress = Path(args[args.index('-progress') + 1])
            self.assertIn('-nostats', args)
            for now, contents in observations:
                clock[0] = now
                if contents is not None:
                    progress.write_text(contents, encoding='ascii')
                on_tick()
            return 'done'
        with patch('app.media.time.monotonic', side_effect=lambda: clock[0]), \
                patch('app.media.run_command', side_effect=run):
            return run_render_command(['ffmpeg', *['-i', 'source'] * inputs, 'output.mp4'],
                                      Path(directory), duration, lambda: False, on_progress)

    def test_no_callback_still_times_out_without_first_frame(self):
        with workspace_directory() as directory:
            with self.assertRaisesRegex(TimeoutError, 'нет первых кадров'):
                self._simulate(directory, [(181, None)])

    def test_repeated_progress_records_do_not_keep_stalled_render_alive(self):
        with workspace_directory() as directory:
            with self.assertRaisesRegex(TimeoutError, 'остановился вывод кадров'):
                self._simulate(directory, [(1, 'frame=1\nout_time_us=1000000\n'),
                                           (90, 'frame=1\nout_time_us=1000000\nprogress=continue\n'),
                                           (122, 'frame=1\nout_time_us=1000000\nprogress=continue\n')])

    def test_advancing_frames_with_static_output_clock_do_not_false_stall(self):
        with workspace_directory() as directory:
            self.assertEqual(self._simulate(directory, [(1, 'frame=1\nout_time_us=0\n'),
                                                       (120, 'frame=2\nout_time_us=0\n'),
                                                       (239, 'frame=3\nout_time_us=0\n')]), 'done')

    def test_reports_monotonic_clock_and_tolerates_incomplete_lines(self):
        values = []
        with workspace_directory() as directory:
            self.assertEqual(self._simulate(directory, [(1, 'out_time_us=1000000\nframe=1\n'),
                                                       (2, 'out_time_us=not_finished\nframe=2\n'),
                                                       (3, 'out_time_us=500000\nframe=2\n'),
                                                       (4, 'out_time_us=20000000\nframe=3\n')], values.append), 'done')
        self.assertEqual(values, [.1, .999])

    def test_first_frame_bootstrap_allows_time_to_open_multiple_inputs(self):
        with workspace_directory() as directory:
            self.assertEqual(self._simulate(directory, [(190, None), (199, 'frame=1\n')],
                                            inputs=10), 'done')

    def test_deadline_scales_with_output_and_input_work(self):
        deadlines = []
        with workspace_directory() as directory, patch('app.media.run_command') as run:
            for duration, count in [(1, 1), (120, 1), (120, 10)]:
                run_render_command(['ffmpeg', *['-i', 'source'] * count, 'output.mp4'],
                                   Path(directory), duration, lambda: False)
                deadlines.append(run.call_args.kwargs['timeout'])
        self.assertLess(deadlines[0], deadlines[1])
        self.assertLess(deadlines[1], deadlines[2])

    def test_stalled_owned_process_is_reaped_without_callback(self):
        processes = []
        start_process = subprocess.Popen
        def capture(*args, **kwargs):
            process = start_process(*args, **kwargs)
            processes.append(process)
            return process
        with workspace_directory() as directory, patch('app.media.subprocess.Popen', side_effect=capture), \
                patch('app.media._RENDER_BOOTSTRAP_SECONDS', .1):
            with self.assertRaisesRegex(TimeoutError, 'нет первых кадров'):
                run_render_command([sys.executable, '-c', 'import time; time.sleep(30)', '-'],
                                   Path(directory), 1, lambda: False)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())


class RenderTaskTests(unittest.TestCase):
    def test_finishing_zoom_below_100_percent_uses_padding_not_impossible_crop(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "source.mp4"
            source.write_bytes(b"placeholder")
            part = {"index": 1, "duration": 1.0, "layout": "portrait",
                    "subtitles": [], "cuts": [{"start": 0, "end": 1, "focus": []}]}
            with patch("app.media.run_command", side_effect=InterruptedError("filter captured")):
                with self.assertRaises(InterruptedError):
                    render_part(source, part, {"width": 320, "height": 180},
                                base / "output", base / "work", "libx264",
                                finishing={"video": {"zoom": 90}})
            filters = (base / "work" / "render.ffscript").read_text("utf-8")
            self.assertIn("scale=iw*0.9000:ih*0.9000:flags=lanczos,pad=1080:1920", filters)
            self.assertNotIn("crop=1080:1920:(in_w-out_w)/2:(in_h-out_h)/2", filters)

    def test_worker_count_cannot_exceed_safety_cap(self):
        with self.assertRaises(ValueError):
            _run_render_tasks([],lambda item,cancelled:item,lambda item,result:None,
                              lambda:False,workers=3)

    def test_render_batch_caps_workers_and_commits_on_caller_in_source_order(self):
        guard=threading.Lock()
        active=0
        maximum=0
        completion=[]
        commits=[]
        caller=threading.current_thread()
        def render(item,cancelled):
            nonlocal active,maximum
            with guard:
                active+=1
                maximum=max(maximum,active)
            try:
                time.sleep(.02 if item%2==0 else .005)
                completion.append(item)
                return f"part-{item}"
            finally:
                with guard:
                    active-=1
        def commit(item,result):
            self.assertIs(threading.current_thread(),caller)
            commits.append((item,result))
        results=_run_render_tasks(list(range(6)),render,commit,lambda:False,workers=2)
        self.assertLessEqual(maximum,2)
        self.assertNotEqual(completion,sorted(completion))
        self.assertEqual(commits,[(i,f"part-{i}") for i in range(6)])
        self.assertEqual(results,[f"part-{i}" for i in range(6)])

    def test_failed_batch_commits_finished_success_and_never_dispatches_later_batch(self):
        first_done=threading.Event()
        dispatched=[]
        committed=[]
        def render(item,cancelled):
            dispatched.append(item)
            if item==0:
                first_done.set()
                return "valid-part-0"
            if item==1:
                self.assertTrue(first_done.wait(1))
                raise RuntimeError("render failed")
            return "unexpected"
        with self.assertRaisesRegex(RuntimeError,"render failed"):
            _run_render_tasks([0,1,2],render,lambda item,result:committed.append((item,result)),
                              lambda:False,workers=2)
        self.assertEqual(sorted(dispatched),[0,1])
        self.assertEqual(committed,[(0,"valid-part-0")])

    def test_cancellation_drains_owned_workers_before_return(self):
        cancelled=threading.Event()
        started=threading.Event()
        start_lock=threading.Lock()
        start_count=0
        drained=[]
        lock=threading.Lock()
        commits=[]
        def render(item,check_cancelled):
            nonlocal start_count
            with start_lock:
                start_count+=1
                if start_count==2:
                    started.set()
            try:
                while not check_cancelled():
                    time.sleep(.002)
                raise InterruptedError("cancelled")
            finally:
                with lock:
                    drained.append(item)
        def request_cancel():
            self.assertTrue(started.wait(timeout=2))
            time.sleep(.01)
            cancelled.set()
        requester=threading.Thread(target=request_cancel)
        requester.start()
        with self.assertRaises(InterruptedError):
            _run_render_tasks([0,1,2],render,lambda item,result:commits.append(item),
                              cancelled.is_set,workers=2)
        requester.join(timeout=1)
        self.assertFalse(requester.is_alive())
        self.assertEqual(sorted(drained),[0,1])
        self.assertEqual(commits,[])

    def test_motion_preserves_finalized_low_confidence_anchors(self):
        cut = {"start": 10, "end": 20, "focus": [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.8},
                                                      {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.1},
                                                      {"time": 14, "x": 0.7, "y": 0.5, "confidence": 0.8}]}
        x, _ = crop_expressions(cut, 1920, 1080)
        self.assertIn("4.000000", x)
        self.assertIn("2.000000", x)
        self.assertIn("3-2*", x)

    def test_missing_focus_uses_center(self):
        self.assertEqual(crop_expressions({"start": 10, "end": 20, "focus": []}, 1920, 1080),
                         ("657.0000", "0.0000"))

    def test_speaker_focus_holds_then_moves_in_quarter_second(self):
        cut = {"start": 0, "end": 12, "focus": [{"time": 0, "x": 0.1, "y": 0.5, "confidence": 0.9},
                                                     {"time": 10, "x": 0.9, "y": 0.5, "confidence": 0.9}]}
        x, _ = crop_expressions(cut, 1920, 1080)
        self.assertIn("t-9.750000", x)
        self.assertIn("/0.250000", x)

    def test_validation_rejects_overlength_and_wrong_geometry(self):
        info = {"format": {"duration": "91"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080,
                    "height": 1920, "avg_frame_rate": "30/1"}, {"codec_type": "audio", "codec_name": "aac"}]}
        with workspace_directory() as directory:
            path = Path(directory) / "output.mp4"
            path.write_bytes(b"x" * 2000)
            with patch("app.media.inspect_media", return_value=info):
                with self.assertRaises(ValueError):
                    validate_export(path, 90, Path(directory))

    def test_validation_accepts_110_second_part_and_enforces_new_ceiling(self):
        info = {"format": {"duration": "110"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080,
                    "height": 1920, "avg_frame_rate": "30/1"}, {"codec_type": "audio", "codec_name": "aac"}]}
        with workspace_directory() as directory:
            path = Path(directory) / "output.mp4"
            path.write_bytes(b"x" * 2000)
            with patch("app.media.inspect_media", return_value=info):
                self.assertEqual(validate_export(path, 110, Path(directory))['duration'], 110)
                info['format']['duration'] = '121'
                with self.assertRaises(ValueError):
                    validate_export(path, 121, Path(directory))

    def test_full_decode_is_explicit_and_propagates_packet_errors(self):
        info = {"format": {"duration": "1"}, "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080,
             "height": 1920, "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"}]}
        with workspace_directory() as directory:
            path = Path(directory) / 'output.mp4'
            path.write_bytes(b'x' * 2000)
            with patch('app.media.inspect_media', return_value=info), \
                    patch('app.media.run_render_command', side_effect=RuntimeError('invalid packet')) as decode:
                validate_export(path, 1, Path(directory))
                decode.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, 'invalid packet'):
                    validate_export(path, 1, Path(directory), full_decode=True)
                command = decode.call_args.args[0]
                self.assertIn('-xerror', command)
                self.assertIn('-err_detect', command)
                self.assertEqual(command[-3:], ['-f', 'null', '-'])

    def test_fresh_render_requires_full_decode_before_publishing(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / 'source.mp4'
            source.write_bytes(b'placeholder')
            part = {'index': 1, 'duration': 1, 'cuts': [{'start': 0, 'end': 1, 'focus': []}],
                    'subtitles': []}
            with patch('app.media.run_render_command'), \
                    patch('app.media.validate_export', side_effect=RuntimeError('decode failed')) as validate:
                with self.assertRaisesRegex(RuntimeError, 'decode failed'):
                    render_part(source, part, {'width': 320, 'height': 180},
                                base / 'output', base / 'work', 'libx264')
            self.assertTrue(validate.call_args.kwargs['full_decode'])
            self.assertFalse((base / 'output' / 'part_001.mp4').exists())
            self.assertFalse((base / 'output' / 'part_001.srt').exists())


@unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), "Portable FFmpeg has not been installed")
class MediaIntegrationTests(unittest.TestCase):
    def test_full_decode_rejects_corrupt_packets_in_valid_container(self):
        with workspace_directory() as directory:
            base = Path(directory)
            output = base / 'corrupt.mp4'
            run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         'color=size=1080x1920:rate=30:duration=0.2', '-f', 'lavfi', '-i',
                         'sine=frequency=440:duration=0.2', '-c:v', 'libx264', '-preset', 'ultrafast',
                         '-c:a', 'aac', '-shortest', str(output)], base)
            validate_export(output, .2, base, full_decode=True)
            data = bytearray(output.read_bytes())
            cursor = 0
            while cursor + 8 <= len(data):
                size = int.from_bytes(data[cursor:cursor + 4], 'big')
                self.assertGreaterEqual(size, 8)
                if data[cursor + 4:cursor + 8] == b'mdat':
                    data[cursor + 8:cursor + size] = b'\0' * (size - 8)
                    break
                cursor += size
            else:
                self.fail('Fixture has no media data atom')
            output.write_bytes(data)
            # The metadata and stream headers remain readable; packet decoding
            # is the extra protection supplied by full_decode.
            validate_export(output, .2, base)
            with self.assertRaises(RuntimeError):
                validate_export(output, .2, base, full_decode=True)

    def test_cinema_preserves_both_source_edges_and_outputs_valid_portrait(self):
        import numpy as np
        import cv2
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / 'wide.mp4'
            run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         "color=red:s=320x180:r=30:d=1,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill",
                         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], base)
            part = {'index': 1, 'duration': .8, 'layout': 'cinema', 'caption_style': 'accent',
                    'subtitles': [], 'cuts': [{'start': 0, 'end': .8, 'focus': []}]}
            output = render_part(source, part, {'width': 320, 'height': 180}, base / 'output', base / 'work', 'libx264')
            video = cv2.VideoCapture(str(output))
            try:
                ok, frame = video.read()
                self.assertTrue(ok)
                left = np.mean(frame[900:1000, 20:80], axis=(0, 1))
                right = np.mean(frame[900:1000, 1000:1060], axis=(0, 1))
                self.assertGreater(left[2], left[0] + 100)
                self.assertGreater(right[0], right[2] + 100)
            finally:
                video.release()

    def _focus_luminance(self, focus, sample_frames=(10, 21, 41)):
        # Three wide vertical bands identify the source area actually selected
        # by FFmpeg. Sample well after each anchor, avoiding transition frames.
        cut = {"start": 10, "end": 15, "focus": focus}
        x, y = crop_expressions(cut, 64, 36)
        cw, ch = crop_size(64, 36)
        with workspace_directory() as directory:
            base = Path(directory)
            output = base / "crop.gray"
            source = "nullsrc=s=64x36:r=10:d=4.3,format=gray,geq=lum='if(lt(X,21),32,if(lt(X,43),128,224))'"
            select = "+".join(f"eq(n,{frame})" for frame in sample_frames)
            filters = f"crop={cw}:{ch}:x='{x}':y='{y}',select='{select}'"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", source,
                         "-vf", filters, "-fps_mode", "passthrough", "-pix_fmt", "gray",
                         "-threads", "1", "-f", "rawvideo", str(output)], base)
            pixels = output.read_bytes()
            self.assertEqual(len(pixels), len(sample_frames) * cw * ch)
            center = ch // 2 * cw + cw // 2
            return [pixels[frame * cw * ch + center] for frame in range(len(sample_frames))]

    def test_two_shot_crop_never_pans_toward_unseen_next_shot(self):
        focus = [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
                 {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.9, "hard_cut": True}]
        # t=1.9 still sees the old composition; t=2.0 and later see the new one.
        self.assertEqual(self._focus_luminance(focus, (19, 20, 21)), [32, 224, 224])

    def test_new_shot_center_reset_survives_confident_neighbor_anchors(self):
        focus = [{"time": 10, "x": 0.1, "y": 0.5, "confidence": 0.9},
                 {"time": 12, "x": 0.5, "y": 0.5, "confidence": 0.0},
                 {"time": 14, "x": 0.9, "y": 0.5, "confidence": 0.9}]
        self.assertEqual(self._focus_luminance(focus), [32, 128, 224])

    def test_all_uncertain_focus_anchors_preserve_resolved_positions(self):
        focus = [{"time": 10, "x": 0.5, "y": 0.5, "confidence": 0.0},
                 {"time": 12, "x": 0.9, "y": 0.5, "confidence": 0.1},
                 {"time": 14, "x": 0.1, "y": 0.5, "confidence": 0.0}]
        self.assertEqual(self._focus_luminance(focus), [128, 224, 32])

    def test_two_cuts_cyrillic_path_and_original_audio(self):
        with workspace_directory(prefix="монтаж с пробелами ") as directory:
            base = Path(directory)
            source = base / "Серия — два говорящих ' [проверка].mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            part = {"index": 1, "duration": 2, "cuts": [
                {"start": 0, "end": 1, "focus": [{"time": 0, "x": 0.2, "y": 0.5, "confidence": 0.9},
                                                      {"time": 0.8, "x": 0.8, "y": 0.5, "confidence": 0.9}]},
                {"start": 2, "end": 3, "focus": [{"time": 2, "x": 0.8, "y": 0.5, "confidence": 0.9}]}],
                "subtitles": [{"start": 0.1, "end": 0.8, "text": "Привет, мир!"}, {"start": 1.1, "end": 1.9, "text": "Второй персонаж."}]}
            result = render_part(source, part, {"width": 640, "height": 360}, base / "output", base / "work", "libx264")
            self.assertTrue(result.is_file())
            self.assertTrue(result.with_suffix(".srt").is_file())
            self.assertFalse((base / "work" / "part_001.partial.mp4").exists())
            metadata = validate_export(result, 2, base)
            self.assertLessEqual(abs(metadata["duration"] - 2), 0.05)

    def test_cancelled_command_does_not_start(self):
        with workspace_directory() as directory:
            with self.assertRaises(InterruptedError):
                run_command([str(FFMPEG), "-version"], Path(directory), lambda: True)

    def test_cancellation_terminates_running_process(self):
        with workspace_directory() as directory:
            started = time.monotonic()
            with self.assertRaises(InterruptedError):
                run_command([str(FFMPEG), "-v", "error", "-re", "-f", "lavfi", "-i",
                             "color=size=128x128:rate=30", "-t", "30", "-f", "null", "-"],
                            Path(directory), lambda: time.monotonic() - started > 0.5)
            self.assertLess(time.monotonic() - started, 5)

    def test_fractional_frame_cuts_do_not_accumulate_audio_drift(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "fractional.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=160x90:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            cuts = [{"start": i * 0.31, "end": i * 0.31 + 0.21,
                     "focus": [{"time": i * 0.31, "x": 0.5, "y": 0.5, "confidence": 0.9}]} for i in range(10)]
            part = {"index": 1, "duration": 2.1, "cuts": cuts, "subtitles": []}
            result = render_part(source, part, {"width": 160, "height": 90}, base / "output", base / "work", "libx264")
            info = inspect_media(result, base)
            streams = {s["codec_type"]: s for s in info["streams"]}
            self.assertLess(abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])), 0.04)
            self.assertLess(abs(float(info["format"]["duration"]) - 2.1), 0.04)

    def test_exact_ninety_seconds_exports_without_overflow(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "ninety.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=160x90:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "90", "-c:v", "libx264",
                         "-preset", "ultrafast", "-c:a", "aac", str(source)], base)
            part = {"index": 1, "duration": 90, "cuts": [{"start": 0, "end": 90,
                    "focus": [{"time": 0, "x": 0.5, "y": 0.5, "confidence": 0.9}]}], "subtitles": []}
            result = render_part(source, part, {"width": 160, "height": 90}, base / "output", base / "work", choose_encoder(base))
            self.assertLessEqual(validate_export(result, 90, base)["duration"], 90)

    def test_storyboard_clamps_audio_tail_to_real_video_frames(self):
        from app.vision import storyboard
        from app.media import video_frame_bounds
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "video_shorter_than_audio.mp4"
            run_command([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                         "color=size=160x90:rate=30:duration=1", "-f", "lavfi", "-i",
                         "sine=frequency=440:sample_rate=48000:duration=1.4", "-t", "1.4",
                         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", str(source)], base)
            info = inspect_media(source, base)
            streams = {stream["codec_type"]: stream for stream in info["streams"]}
            self.assertGreater(float(streams["audio"]["duration"]),
                               float(streams["video"]["duration"]) + 0.2)

            first, last = video_frame_bounds(source, base)
            frames = storyboard(source, max(first, last - 0.05), 1.4, [],
                                {"words": [], "segments": []}, base / "eof-board.jpg", lambda: False)
            self.assertTrue(frames)
            self.assertTrue(all(first <= timestamp <= last for timestamp in frames))
            self.assertTrue((base / "eof-board.jpg").is_file())
            audit = json.loads((base / 'eof-board.storyboard.json').read_text('utf-8'))
            self.assertEqual([row['time'] for row in audit['frames']], frames)
            self.assertTrue(all(row['pts'] is not None and row['time_base'] for row in audit['frames']))
            from PIL import Image
            with Image.open(base / 'eof-board.jpg') as picture:
                self.assertGreater(picture.width, 0)
                self.assertGreater(picture.height, 24)
                self.assertGreater(sum(picture.crop((0, 24, picture.width, picture.height)).convert('L').getextrema()), 0)


class PipelineCheckpointTests(unittest.TestCase):
    def test_shorter_retry_archives_only_obsolete_owned_exports_after_success(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "source.mp4"
            source.write_bytes(b"unchanged")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            original = {"probe": {"duration": 300, "width": 640, "height": 360, "has_audio": True},
                        "transcript": {"words": [], "segments": []}, "shots": [],
                        "events": [{"id": "a", "start": 0, "end": 300, "kind": "story", "importance": 4}]}
            shorter = copy.deepcopy(original)
            shorter["events"][0]["selected_ranges"] = [{"start": 0, "end": 20}]
            def render(source, part, probe, output, work, encoder, cancelled, **kwargs):
                path = output / f"part_{part['index']:03}.mp4"
                path.write_bytes(b"rendered" * 1000)
                path.with_suffix(".srt").write_text("subtitles", encoding="utf-8")
                return path
            with patch("app.analysis.analyze", side_effect=[original, shorter, shorter]), \
                    patch("app.pipeline.choose_encoder", return_value="libx264"), \
                    patch("app.pipeline.render_part", side_effect=render) as renderer, \
                    patch('app.pipeline.prepare_clean_part', side_effect=lambda s, p, pr, *a: (s, p, pr, False)), \
                    patch("app.pipeline.validate_export"):
                run_job(base, lambda *a: None, lambda: False)
                old_plan = json.loads((base / "output" / "plan.json").read_text(encoding="utf-8"))
                unrelated = base / "output" / "part_999.mp4"
                unrelated.write_bytes(b"user file")
                renderer.side_effect = InterruptedError("cancelled")
                with self.assertRaises(InterruptedError):
                    run_job(base, lambda *a: None, lambda: False)
                self.assertFalse((base / "previous_exports").exists())
                self.assertTrue((base / "output" / "part_003.mp4").is_file())
                renderer.side_effect = render
                outputs = run_job(base, lambda *a: None, lambda: False)
            self.assertEqual(outputs, ["part_001.mp4", "part_001.srt"])
            self.assertEqual(sorted(p.name for p in (base / "output").glob("*.mp4")),
                             ["part_001.mp4", "part_999.mp4"])
            archive = next((base / "previous_exports").iterdir())
            self.assertEqual(json.loads((archive / "plan.json").read_text(encoding="utf-8")), old_plan)
            self.assertEqual(sorted(p.name for p in archive.glob("*.mp4")), ["part_002.mp4", "part_003.mp4"])
            self.assertTrue((archive / "part_002.srt").is_file())
            self.assertTrue((archive / "part_003.checkpoint.json").is_file())
            self.assertEqual(unrelated.read_bytes(), b"user file")

    def test_resume_reuses_only_valid_output_and_changed_subtitles_rebuild(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "исходная серия.mp4"
            source.write_bytes(b"source")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            analysis = {"probe": {"duration": 5, "width": 640, "height": 360, "has_audio": True},
                        "transcript": {"words": [], "segments": []}, "shots": [],
                        "events": [{"id": "a", "start": 0, "end": 5, "kind": "story", "importance": 4}]}
            def fake_render(source, part, probe, output, work, encoder, cancelled, **kwargs):
                path = output / "part_001.mp4"
                path.write_bytes(b"rendered" * 1000)
                path.with_suffix(".srt").write_text("original subtitles", encoding="utf-8")
                return path
            with patch("app.analysis.analyze", return_value=analysis), patch("app.pipeline.choose_encoder", return_value="libx264"), \
                    patch("app.pipeline.render_part", side_effect=fake_render) as renderer, \
                    patch('app.pipeline.prepare_clean_part', side_effect=lambda s, p, pr, *a: (s.with_suffix('.clean.mkv'), p, pr, False)) as clean_preparer, \
                    patch("app.pipeline.validate_export"):
                outputs = run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(renderer.call_args.args[0], source.with_suffix('.clean.mkv'))
                self.assertEqual(clean_preparer.call_count, 1)
                self.assertEqual(outputs, ["part_001.mp4", "part_001.srt"])
                checkpoint=json.loads((base/"render/part_001.json").read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["requested_encoder"],"libx264")
                self.assertIsNone(checkpoint["encoder"])
                timing=json.loads((base/"timings.json").read_text(encoding="utf-8"))
                self.assertEqual(timing["status"],"completed")
                self.assertEqual(timing["parts"][0]["encoder"],None)
                manifests=list((base/"runs").glob("*.json"))
                self.assertEqual(len(manifests),1)
                manifest=json.loads(manifests[0].read_text(encoding="utf-8"))
                self.assertEqual(manifest["identity"]["git_commit"],timing["identity"]["git_commit"])
                self.assertRegex(manifest["identity"]["source_files_sha256"]["app/pipeline.py"],r"^[0-9a-f]{64}$")
                run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(renderer.call_count, 1)
                (base / "output" / "part_001.srt").write_text("tampered", encoding="utf-8")
                run_job(base, lambda *args: None, lambda: False)
                self.assertEqual(renderer.call_count, 2)

    def test_cancel_before_analysis_preserves_job(self):
        with workspace_directory() as directory:
            base = Path(directory)
            source = base / "input.mp4"
            source.write_bytes(b"source")
            (base / "source.json").write_text(json.dumps({"path": str(source)}), encoding="utf-8")
            with patch("app.analysis.analyze") as analyzer:
                with self.assertRaises(InterruptedError):
                    run_job(base, lambda *args: None, lambda: True)
                analyzer.assert_not_called()
