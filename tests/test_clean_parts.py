import copy
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.config import TEMP, FFMPEG
from app.clean_parts import prepare_clean_part, clean_clock_part, clean_identity
from app.media import run_command, render_part, validate_export, crop_expressions, inspect_media


class CleanPartsTests(unittest.TestCase):
    def setUp(self):
        self.root = TEMP / ('clean_test_' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'placeholder')
        self.probe = {'width': 320, 'height': 180, 'audio_stream': 0}
        self.part = {'index': 1, 'duration': 2.2, 'layout': 'portrait',
            'subtitles': [{'start': .1, 'end': 1, 'text': 'Caption stays separate'}],
            'cuts': [{'start': .4, 'end': 1.5, 'focus': [{'time': .4, 'x': .1, 'y': .5}]},
                     {'start': 2, 'end': 3.1, 'focus': [{'time': 2, 'x': .9, 'y': .5}]}]}

    def test_clean_identity_ignores_captions_and_focus_but_tracks_source_cuts_audio(self):
        identity = clean_identity(self.source, self.part, self.probe)
        changed = copy.deepcopy(self.part)
        changed['subtitles'][0]['text'] = 'New words'
        changed['cuts'][0]['focus'][0]['x'] = .8
        self.assertEqual(identity, clean_identity(self.source, changed, self.probe))
        changed['cuts'][0]['end'] += .1
        self.assertNotEqual(identity, clean_identity(self.source, changed, self.probe))
        self.assertNotEqual(identity, clean_identity(self.source, self.part, {**self.probe, 'audio_stream': 1}))
        self.source.write_bytes(b'changed source')
        self.assertNotEqual(identity, clean_identity(self.source, self.part, self.probe))

    def test_master_clock_preserves_abrupt_focus_at_cut_and_own_subtitles(self):
        clean = clean_clock_part(self.part)
        self.assertEqual(len(clean['cuts']), 1)
        self.assertEqual(clean['subtitles'], self.part['subtitles'])
        focus = clean['cuts'][0]['focus']
        self.assertAlmostEqual(focus[1]['time'], 1.1)
        self.assertTrue(focus[1]['hard_cut'])
        expression, _ = crop_expressions(clean['cuts'][0], 320, 180)
        def position(t):
            return eval(expression.replace('if(', 'choose('), {'__builtins__': {}},
                {'t': t, 'choose': lambda cond, a, b: a if cond else b,
                 'lt': lambda a, b: a < b, 'clip': lambda a, lo, hi: min(max(a, lo), hi)})
        self.assertEqual(position(1.099), 0)
        self.assertEqual(position(1.1), 220)

    def test_preview_does_not_build_full_clean_part_and_cancellation_does_not_publish(self):
        with patch('app.clean_parts.run_render_command') as render:
            result = prepare_clean_part(self.source, self.part, self.probe, self.root, create=False)
            self.assertEqual(result[:3], (self.source, self.part, self.probe))
            render.assert_not_called()
            with self.assertRaises(InterruptedError):
                prepare_clean_part(self.source, self.part, self.probe, self.root, lambda: True)
        self.assertFalse(list((self.root / 'clean').glob('**/clean.mkv')))

    def test_focus_exit_movement_survives_next_cut_reset(self):
        self.part['cuts'][0]['focus'].append({'time': 1.5, 'x': .5, 'y': .5})
        focus = clean_clock_part(self.part)['cuts'][0]['focus']
        self.assertAlmostEqual(focus[1]['time'], 1.1 - .000001)
        self.assertEqual(focus[1]['x'], .5)
        self.assertAlmostEqual(focus[2]['time'], 1.1)
        self.assertTrue(focus[2]['hard_cut'])

    def test_real_clean_part_is_lossless_unstyled_and_reused_for_changed_captions(self):
        run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=320x180:rate=30', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000', '-f', 'lavfi', '-i',
            'sine=frequency=880:sample_rate=48000', '-map', '0:v:0', '-map', '1:a:0', '-map', '2:a:0',
            '-t', '4', '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(self.source)], self.root)
        self.probe['audio_stream'] = 1
        progress = []
        clean, part, probe, hit = prepare_clean_part(self.source, self.part, self.probe, self.root,
            on_progress=progress.append)
        self.assertFalse(hit)
        self.assertTrue(progress)
        self.assertTrue(all(0 <= p < 1 for p in progress))
        script = (clean.parent / 'clean.ffscript').read_text('utf-8')
        self.assertNotIn('ass=', script)
        self.assertNotIn('crop=', script)
        self.assertNotIn('amix=', script)
        media = inspect_media(clean, self.root)
        self.assertEqual(len([s for s in media['streams'] if s['codec_type'] == 'audio']), 1)
        # Only the selected second track survives, with no mixed original first track.
        import numpy as np
        pcm = self.root / 'audio.f32'
        run_command([str(FFMPEG), '-v', 'error', '-y', '-ss', '0.2', '-i', str(clean), '-t', '0.1',
            '-map', '0:a:0', '-ac', '1', '-ar', '48000', '-f', 'f32le', str(pcm)], self.root)
        samples = np.fromfile(pcm, dtype=np.float32)
        frequency = np.argmax(abs(np.fft.rfft(samples))) * 48000 / len(samples)
        self.assertAlmostEqual(frequency, 880, delta=10)
        # The first decoded clean frame is pixel-identical to its source frame.
        def frame_hash(path, seek):
            return run_command([str(FFMPEG), '-v', 'error', '-ss', str(seek), '-i', str(path),
                '-map', '0:v:0', '-frames:v', '1', '-f', 'md5', '-'], self.root).strip()
        self.assertEqual(frame_hash(clean, 0), frame_hash(self.source, .4))
        self.assertEqual(frame_hash(clean, 1.1), frame_hash(self.source, 2))
        changed = copy.deepcopy(self.part)
        changed['subtitles'][0]['text'] = 'Changed subtitle'
        with patch('app.clean_parts.run_render_command', side_effect=AssertionError('cut source twice')):
            reused = prepare_clean_part(self.source, changed, self.probe, self.root)
        self.assertTrue(reused[3])
        self.assertEqual(reused[0], clean)
        # Final styling receives one already assembled input and keeps timing.
        final = render_part(clean, part, probe, self.root / 'final', self.root / 'render', 'libx264')
        self.assertAlmostEqual(validate_export(final, 2.2, self.root)['duration'], 2.2, delta=.04)
        # Truncation invalidates the master and a failed repair cannot bless it.
        clean.write_bytes(b'broken')
        with patch('app.clean_parts.run_render_command', side_effect=RuntimeError('repair failed')):
            with self.assertRaises(RuntimeError):
                prepare_clean_part(self.source, changed, self.probe, self.root)

