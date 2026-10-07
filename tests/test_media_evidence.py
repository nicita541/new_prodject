"""Source-only measurement checks. These are not semantic-quality E2E tests."""
import copy
import json
import shutil
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.config import FFMPEG, FFPROBE, TEMP
from app.media import run_command
from app.media_evidence import (POLICY, _cluster_proposals, embedding_distance, image_evidence,
                                perception_checkpoint, visual_feature_map)
from app.media_probe import detect_shots, raw_shot_evidence


EMPTY = {'words': [], 'segments': []}
SEMANTIC_KEYS = {'location', 'characters', 'character_state', 'state_before', 'state_after',
                 'action_units', 'narrative_bridge', 'requires', 'importance', 'summary', 'story_arc_id', 'story_phase'}


def texture():
    y, x = np.mgrid[:90, :160]
    image = np.full((90, 160, 3), 128, dtype=np.uint8)
    image[((x // 15 + y // 15) % 2).astype(bool)] = 155
    image[:4], image[:, :4] = 90, 90
    return image


class EvidenceUnitTests(unittest.TestCase):
    def test_normalized_embedding_tolerates_lighting_and_subtitle_strip(self):
        rgb = texture()
        rgb[10:40, 15:30] = 30
        first = image_evidence(Image.fromarray(rgb))
        relit = np.clip(rgb.astype(float) * .70 + 35, 0, 255).astype(np.uint8)
        relit[75:90] = 255
        second = image_evidence(Image.fromarray(relit))
        self.assertLess(embedding_distance(first['perceptual_embedding'], second['perceptual_embedding']), .025)
        self.assertLess(embedding_distance(first['background_embedding'], second['background_embedding']), .025)
        self.assertGreater(sum(abs(a - b) for a, b in zip(first['descriptor']['histogram'], second['descriptor']['histogram'])), .1)
        self.assertAlmostEqual(np.linalg.norm(first['perceptual_embedding']), 1, places=5)

    def test_background_vector_is_less_sensitive_to_central_foreground(self):
        rgb = texture()
        first = image_evidence(Image.fromarray(rgb))
        rgb[20:55, 50:110] = [30, 40, 50]
        second = image_evidence(Image.fromarray(rgb))
        self.assertLess(embedding_distance(first['background_embedding'], second['background_embedding']),
                        embedding_distance(first['perceptual_embedding'], second['perceptual_embedding']))

    def test_blank_embedding_does_not_claim_perceptual_similarity(self):
        blank = image_evidence(Image.new('RGB', (160, 90), 'black'))
        self.assertTrue(blank['black'])
        self.assertEqual(blank['reliability'], 0)
        self.assertIsNone(embedding_distance(blank['perceptual_embedding'], blank['perceptual_embedding']))
        self.assertIsNone(embedding_distance([float('nan')], [1]))

    def test_cluster_bounds_secondary_targets_but_preserves_every_raw_candidate(self):
        rows = [{'id': f'p{i}', 'time': i * .2 + .2, 'origins': ['fade_black'],
                 'reasons': ['monotonic_luminance_fade_candidate'], 'scores': {'luminance_delta': -.08}}
                for i in range(20)]
        raw = [{'id': f'r{i}', 'time': i * .1 + 1, 'origins': ['ffmpeg_scene_score'],
                'reasons': ['original_raw_candidate'], 'scores': {'scene_score': .2}} for i in range(15)]
        result = _cluster_proposals([*rows, *raw])
        self.assertLessEqual(len([row for row in result if row['id'].startswith('p')]), 3)
        self.assertEqual(len([row for row in result if row['id'].startswith('r')]), 15)
        self.assertEqual(result, _cluster_proposals([*rows, *raw]))

    def test_interval_map_keeps_internal_ids_and_actual_in_interval_pts(self):
        measured = image_evidence(Image.fromarray(texture()))
        samples = [{'time': .1, 'frame': 'source1.jpg', 'motion_score': 0, **measured},
                   {'time': .3, 'frame': 'source2.jpg', 'motion_score': .7, 'motion_duration': .2,
                    'motion_start': .1, 'crosses_cut': False, **measured},
                   {'time': .8, 'frame': 'source3.jpg', 'motion_score': 0, **measured}]
        perception = {'source': {'duration': 1}, 'samples': samples}
        original = copy.deepcopy(perception)
        features = visual_feature_map(perception, [{'id': 'shot_0:candidate:raw1', 'start': 0, 'end': .5},
                                                   {'id': 'short', 'start': .51, 'end': .6}])
        self.assertEqual([sample['time'] for sample in features['shot_0:candidate:raw1']['samples']], [.1, .3])
        self.assertAlmostEqual(features['shot_0:candidate:raw1']['motion_score'], .7)
        self.assertEqual(features['short']['warning'], 'no_source_sample_in_interval')
        self.assertEqual(perception, original)
        with self.assertRaises(ValueError):
            visual_feature_map(perception, [{'id': 'outside', 'start': 0, 'end': 2}])


@unittest.skipUnless(FFMPEG.is_file(), 'Portable FFmpeg is unavailable')
class RawMeasurementTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.directory = TEMP / ('media_evidence_test_' + uuid.uuid4().hex)
        self.directory.mkdir()

    def tearDown(self):
        shutil.rmtree(self.directory)

    def video(self, frames, *, audio=None, audio_offset=0, rate=8, name='clip'):
        directory = self.directory / name
        directory.mkdir()
        for index, rgb in enumerate(frames):
            Image.fromarray(rgb.astype(np.uint8)).save(directory / f'{index:04d}.png')
        source = directory / 'source.mp4'
        command = [str(FFMPEG), '-y', '-v', 'error', '-framerate', str(rate), '-i', str(directory / '%04d.png')]
        if audio is not None:
            path = directory / 'tone.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
            command += ['-itsoffset', str(audio_offset), '-i', str(path), '-c:a', 'aac', '-shortest']
        command += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '1', str(source)]
        run_command(command, directory)
        return source, directory, len(frames) / rate

    def test_static_reverse_cuts_have_low_intra_shot_motion_and_single_tracking_shot_high_motion(self):
        first, second = texture(), texture()[:, ::-1].copy()
        first[15:65, 15:55] = 35
        second[15:65, 105:145] = 225
        source, directory, duration = self.video([first if index // 8 % 2 == 0 else second for index in range(32)], name='reverse')
        shots = detect_shots(source, duration, directory, lambda: False)
        reverse = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        moving = []
        for index in range(32):
            frame = texture()
            left = 10 + index * 3
            frame[20:55, left:left + 30] = 25
            moving.append(frame)
        source, directory, duration = self.video(moving, name='tracking')
        shots = detect_shots(source, duration, directory, lambda: False)
        tracking = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        self.assertGreater(reverse['motion']['raw_cut_candidates_per_minute'], 25)
        self.assertLess(reverse['motion']['physical_motion_density'], .04)
        self.assertGreater(reverse['motion']['excluded_cut_pairs'], 0)
        self.assertGreater(tracking['motion']['physical_motion_density'], .30)
        self.assertLess(tracking['motion']['accepted_cuts_per_minute'], reverse['motion']['accepted_cuts_per_minute'])
        self.assertTrue(tracking['motion']['available'])
        self.assertFalse(tracking['motion']['physical_semantics_known'])
        self.assertIn('residual_motion_density', tracking['motion'])
        self.assertIn('global_camera_motion_density', tracking['motion'])

    def test_below_base_score_structural_change_and_slow_fade_propose_without_labels(self):
        frames = []
        for index in range(32):
            frame = texture()
            if index >= 16:
                frame[24:52, 65:90] = 35
            frames.append(frame)
        source, directory, duration = self.video(frames, name='structure')
        shots = detect_shots(source, duration, directory, lambda: False)
        self.assertEqual(len(shots), 1)  # Actual FFmpeg base .14 did not create this boundary.
        evidence = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        secondary = [row for row in evidence['proposals'] if row['time'] >= 1.8 and row['time'] <= 2.3
                     and any(origin != 'ffmpeg_scene_score' for origin in row['origins'])]
        self.assertTrue(secondary)
        frames = [np.clip(texture().astype(float) * (1 if i < 8 else max(0, 1 - (i - 8) / 16)), 0, 255).astype(np.uint8)
                  for i in range(32)]
        source, directory, duration = self.video(frames, name='fade')
        evidence = perception_checkpoint(source, duration, detect_shots(source, duration, directory, lambda: False),
                                         EMPTY, directory, lambda: False)
        self.assertTrue(any('fade_black' in row['origins'] for row in evidence['proposals']))
        self.assertTrue(any(row['black'] for row in evidence['samples']))
        self.assertTrue(any('monotonic_luminance_fade_candidate' in row['reasons'] for row in evidence['proposal_evidence']))
        self.assertLessEqual(sum('fade_black' in row['origins'] for row in evidence['proposals']), 4)

    def test_suppressed_raw_camera_cuts_are_excluded_from_motion_but_not_editing_evidence(self):
        left, right = texture(), texture()
        left[15:65, 15:55], right[15:65, 105:145] = 30, 220
        source, directory, duration = self.video([left if index // 8 % 2 == 0 else right for index in range(32)], name='suppressed')
        detected = detect_shots(source, duration, directory, lambda: False)
        raw = [{**row, 'accepted': False} for row in raw_shot_evidence(detected)]
        self.assertTrue(raw)
        shots = [{'id': 'single_accepted', 'start': 0, 'end': duration, 'raw_shot_candidates': raw}]
        evidence = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        self.assertEqual(evidence['motion']['accepted_cuts_per_minute'], 0)
        self.assertGreater(evidence['motion']['raw_cut_candidates_per_minute'], 25)
        self.assertGreater(evidence['motion']['excluded_cut_pairs'], 0)
        self.assertLess(evidence['motion']['physical_motion_density'], .04)
        self.assertEqual(len([row for row in evidence['proposals'] if 'ffmpeg_scene_score' in row['origins']]), len(raw))

    def test_pcm_audio_energy_spectrum_silence_and_asr_are_measured(self):
        rate = 16000
        audio = np.zeros(rate * 4, dtype=float)
        audio[:rate] = .12 * np.sin(np.arange(rate) * 2 * np.pi * 440 / rate)
        audio[rate * 2:] = .30 * np.sin(np.arange(rate * 2) * 2 * np.pi * 1800 / rate)
        source, directory, duration = self.video([texture()] * 32, audio=audio, name='audio')
        transcript = {'words': [{'start': .1, 'end': .7, 'text': 'ASR'}, {'start': .4, 'end': .8, 'text': 'overlap'}],
                      'segments': [{'start': .1, 'end': .8, 'text': 'ASR phrase'}]}
        evidence = perception_checkpoint(source, duration, [{'id': 's', 'start': 0, 'end': duration}], transcript, directory, lambda: False)
        rows = evidence['audio_features']
        self.assertTrue(evidence['audio_available'])
        self.assertTrue(all(row['origin'] == 'source_pcm' and row['sample_rate'] == rate for row in rows))
        first = next(row for row in rows if row['start'] <= .5 < row['end'])
        later = next(row for row in rows if row['start'] <= 2.5 < row['end'])
        self.assertAlmostEqual(first['spectral_centroid'], 440, delta=50)
        self.assertAlmostEqual(later['spectral_centroid'], 1800, delta=70)
        self.assertGreater(later['rms'], first['rms'] * 1.8)
        self.assertTrue(any(row['silence'] for row in rows if 1 <= row['start'] < 1.9))
        self.assertTrue(first['speech'])
        self.assertTrue(all(0 <= row['speech_overlap_ratio'] <= 1 for row in rows))
        self.assertTrue(any('audio_discontinuity' in row['origins'] for row in evidence['proposals']))
        self.assertTrue(all(0 <= row['start'] < row['end'] <= duration for row in rows))

    def test_cache_is_stable_ignores_injected_semantic_labels_and_invalidates_asr(self):
        source, directory, duration = self.video([texture()] * 16, name='cache')
        shots = [{'id': 's', 'start': 0, 'end': duration}]
        first = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        injected = [{**shots[0], 'location': 'invented', 'features': {'character_state': 'bound'}, 'importance': 5}]
        with patch('app.media_evidence._video', side_effect=AssertionError('Must reuse stable source cache')):
            reused = perception_checkpoint(source, duration, injected, EMPTY, directory, lambda: False)
        self.assertEqual(first, reused)
        transcript = {'words': [{'start': 0, 'end': .2, 'text': 'word'}], 'segments': []}
        changed = perception_checkpoint(source, duration, shots, transcript, directory, lambda: False)
        self.assertNotEqual(first['signature'], changed['signature'])
        def assert_no_semantics(value):
            if isinstance(value, dict):
                self.assertFalse(SEMANTIC_KEYS.intersection(value))
                for child in value.values():
                    assert_no_semantics(child)
            elif isinstance(value, list):
                for child in value:
                    assert_no_semantics(child)
        assert_no_semantics(changed)
        json.dumps(changed, allow_nan=False)
        self.assertTrue(all(0 <= row['time'] < duration for row in changed['samples']))
        self.assertTrue(all((directory / row['frame']).is_file() for row in changed['samples']))

    def test_audio_offset_uses_actual_source_pts_and_cache_hit_cancellation_propagates(self):
        tone = .2 * np.sin(np.arange(16000 * 3) * 2 * np.pi * 440 / 16000)
        source, directory, duration = self.video([texture()] * 32, audio=tone, audio_offset=1, name='offset')
        shots = [{'id': 's', 'start': 0, 'end': duration}]
        evidence = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        streams = json.loads(run_command([str(FFPROBE), '-v', 'error', '-show_streams', '-of', 'json', str(source)], directory))['streams']
        audio = next(stream for stream in streams if stream['codec_type'] == 'audio')
        self.assertGreaterEqual(evidence['audio_features'][0]['start'], .90)
        self.assertAlmostEqual(evidence['audio_features'][0]['start'], float(audio['start_time']), places=5)
        self.assertTrue(all(0 <= row['start'] < row['end'] <= duration for row in evidence['audio_features']))
        values = iter([False, False, True])
        with patch('app.media_evidence._video', side_effect=AssertionError('Cancelled cache hit must not decode')):
            with self.assertRaises(InterruptedError):
                perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: next(values))

    def test_missing_cached_source_frame_rebuilds_evidence_before_returning_paths(self):
        source, directory, duration = self.video([texture()] * 16, name='missing_frame')
        shots = [{'id': 's', 'start': 0, 'end': duration}]
        first = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
        frame = directory / first['samples'][0]['frame']
        frame.unlink()
        with patch('app.media_evidence._video', wraps=__import__('app.media_evidence', fromlist=['_video'])._video) as decode:
            rebuilt = perception_checkpoint(source, duration, shots, EMPTY, directory, lambda: False)
            self.assertEqual(decode.call_count, 1)
        self.assertTrue(frame.is_file())
        self.assertEqual(first, rebuilt)

    def test_cancellation_prevents_decode_and_outside_interval_cannot_invent_pts(self):
        with patch('app.media_evidence._video') as video:
            with self.assertRaises(InterruptedError):
                perception_checkpoint(self.directory / 'absent.mp4', 2, [], EMPTY, self.directory, lambda: True)
            video.assert_not_called()
        with self.assertRaises(ValueError):
            perception_checkpoint(self.directory / 'absent.mp4', 2, [{'start': 0, 'end': 3}], EMPTY, self.directory, lambda: False)


if __name__ == '__main__':
    unittest.main()
