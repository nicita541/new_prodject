"""Semantic grouping regressions independent of model output or chunk length."""
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.config import FFMPEG, TEMP
from app.media import run_command
from app.media_probe import adaptive_shot_evidence
from app.json_store import load_json
from app.scene_detection import analysis_chunks, detect_semantic_scenes, scene_checkpoint


EMPTY = {'words': [], 'segments': []}


def shot(index, start, end, location=None, **features):
    return {'id': f'shot_{index:04d}', 'start': start, 'end': end,
            'features': {**({'location': location} if location is not None else {}), **features}}


def visual(color):
    histogram = [0.0] * 64
    histogram[color] = 1.0
    return {'descriptor': {'histogram': histogram, 'spatial': [color / 63] * 15}, 'reliability': 1.0}


class SemanticSceneTests(unittest.TestCase):
    def test_a_four_second_binding_between_conversation_and_car_is_preserved(self):
        shots = [shot(0, 0, 20, 'room', characters=['hero']),
                 shot(1, 20, 24, 'street', characters=['hero'], character_state='being_bound'),
                 shot(2, 24, 45, 'car', characters=['hero'], character_state='bound')]
        # Speech spans both boundaries; a spoken line must not hide the move.
        transcript = {'segments': [{'start': 0, 'end': 45, 'text': 'long spoken line'}],
                      'words': [{'start': 19.8, 'end': 20.1, 'text': 'word'},
                                {'start': 23.8, 'end': 24.1, 'text': 'word'}]}
        scenes = detect_semantic_scenes(shots, transcript, 45)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 20.1), (20.1, 24.1), (24.1, 45)])
        self.assertEqual(scenes[1]['shot_ids'], ['shot_0001'])
        self.assertIn('location_change', scenes[1]['boundary_reason'])
        self.assertEqual(scenes[1]['evidence']['raw_boundary_time'], 20)
        self.assertEqual(scenes[2]['evidence']['raw_boundary_time'], 24)
        self.assertFalse(any(w['start'] < s['start'] < w['end'] or w['start'] < s['end'] < w['end']
                             for s in scenes for w in transcript['words']))

    def test_b_ninety_second_dialogue_is_one_semantic_scene(self):
        shots = [shot(i, i * 15, (i + 1) * 15, 'room', background='office',
                      characters=['hero' if i % 2 == 0 else 'girl']) for i in range(6)]
        scenes = detect_semantic_scenes(shots, EMPTY, 90)
        self.assertEqual(len(scenes), 1)
        self.assertEqual((scenes[0]['start'], scenes[0]['end']), (0, 90))
        chunks = analysis_chunks(scenes[0], EMPTY)
        self.assertEqual([(c['start'], c['end']) for c in chunks], [(0, 40), (40, 80), (80, 90)])
        self.assertEqual({c['parent_scene_id'] for c in chunks}, {scenes[0]['id']})

    def test_c_reverse_shot_camera_cuts_do_not_fragment_fast_dialogue(self):
        shots = [shot(i, i * 1.5, (i + 1) * 1.5, 'room',
                      background='left_wall' if i % 2 else 'right_wall',
                      characters=['hero' if i % 2 else 'girl']) for i in range(40)]
        transcript = {'segments': [{'start': 0, 'end': 60, 'text': 'conversation'}], 'words': []}
        scenes = detect_semantic_scenes(shots, transcript, 60)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(len(scenes[0]['shot_ids']), 40)
        self.assertFalse(scenes[0]['uncertain'])

    def test_physical_state_change_in_same_location_is_not_smoothed_away(self):
        shots = [shot(0, 0, 20, 'room', character_state='free'),
                 shot(1, 20, 22, 'room', character_state='bound', state_transition=True),
                 shot(2, 22, 40, 'room', character_state='bound')]
        scenes = detect_semantic_scenes(shots, EMPTY, 40)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 20), (20, 40)])
        self.assertIn('physical_state_transition', scenes[1]['boundary_reason'])
        self.assertIn('shot_0001', scenes[1]['shot_ids'])

    def test_reverse_shot_continuity_uses_real_descriptors_without_location_labels(self):
        shots = [shot(i, i * 2, (i + 1) * 2, **visual(4 if i % 2 else 50)) for i in range(45)]
        scenes = detect_semantic_scenes(shots, EMPTY, 90)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(len(scenes[0]['shot_ids']), 45)
        self.assertTrue(all(d['reasons'] == ['camera_or_background_continuity']
                            for d in scenes[0]['evidence']['boundary_decisions']))

    def test_different_backgrounds_and_characters_with_recurrence_are_camera_cuts(self):
        shots = [shot(i, i * 2, (i + 1) * 2,
                      background='left_wall' if i % 2 else 'right_wall',
                      characters=['hero' if i % 2 else 'girl']) for i in range(12)]
        scenes = detect_semantic_scenes(shots, EMPTY, 24)
        self.assertEqual(len(scenes), 1)

    def test_short_isolated_visual_transition_remains_with_uncertainty(self):
        shots = [shot(0, 0, 20, **visual(4)), shot(1, 20, 22, **visual(50)), shot(2, 22, 42, **visual(4))]
        transcript = {'segments': [], 'words': [{'start': 1, 'end': 19, 'text': 'before'},
                                               {'start': 23, 'end': 41, 'text': 'after'}]}
        scenes = detect_semantic_scenes(shots, transcript, 42)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 20), (20, 22), (22, 42)])
        self.assertIn('short_visual_transition', scenes[1]['boundary_reason'])
        self.assertTrue(scenes[1]['uncertain'])

    def test_missing_visual_evidence_is_explicitly_uncertain(self):
        shots = [shot(0, 0, 40), shot(1, 40, 80), shot(2, 80, 90)]
        scenes = detect_semantic_scenes(shots, EMPTY, 90)
        self.assertEqual(len(scenes), 1)
        self.assertTrue(scenes[0]['uncertain'])
        self.assertIn('weak_visual_evidence', scenes[0]['evidence']['uncertainty_reasons'])
        self.assertLess(scenes[0]['confidence'], .6)
        self.assertEqual(len(scenes[0]['evidence']['boundary_decisions']), 2)

    def test_word_crossing_chunk_limit_is_not_cut(self):
        scene = {'id': 'scene_0012', 'start': 0, 'end': 95}
        transcript = {'segments': [], 'words': [{'start': 39.8, 'end': 40.8, 'text': 'word'},
                                               {'start': 79.6, 'end': 80.4, 'text': 'word'}]}
        chunks = analysis_chunks(scene, transcript)
        self.assertEqual(chunks[0]['end'], 39.8)
        self.assertEqual(chunks[0]['start'], 0)
        self.assertEqual(chunks[-1]['end'], 95)
        for before, after in zip(chunks, chunks[1:]):
            self.assertEqual(before['end'], after['start'])
        for chunk in chunks:
            self.assertLessEqual(chunk['end'] - chunk['start'], 40)
            self.assertFalse(any(w['start'] < chunk['end'] < w['end'] for w in transcript['words']))

    def test_phrase_ending_preferred_inside_chunk_size_limit(self):
        chunks = analysis_chunks({'id': 'scene', 'start': 10, 'end': 100},
                                 {'words': [], 'segments': [{'start': 10, 'end': 46, 'text': 'phrase'}]})
        self.assertEqual(chunks[0]['end'], 46)
        self.assertEqual(chunks[-1]['end'], 100)
        self.assertEqual({c['parent_scene_id'] for c in chunks}, {'scene'})

    def test_overlapping_asr_words_are_not_cut_after_moving_boundary(self):
        transcript = {'segments': [], 'words': [{'start': 38.5, 'end': 39.8, 'text': 'first'},
                                               {'start': 39.7, 'end': 40.7, 'text': 'second'}]}
        chunks = analysis_chunks({'id': 'scene', 'start': 0, 'end': 90}, transcript)
        self.assertEqual(chunks[0]['end'], 38.5)
        self.assertFalse(any(w['start'] < c['end'] < w['end'] for c in chunks for w in transcript['words']))

    def test_indivisible_long_word_is_explicit_size_exception(self):
        chunks = analysis_chunks({'id': 'scene', 'start': 0, 'end': 90},
                                 {'segments': [], 'words': [{'start': 0, 'end': 45, 'text': 'word'}]})
        self.assertEqual(chunks[0]['end'], 45)
        self.assertTrue(chunks[0]['oversize_word'])

    def test_two_transitions_inside_one_word_keep_positive_safe_scenes(self):
        shots = [shot(0, 0, 20, 'room'), shot(1, 20, 21, 'street'), shot(2, 21, 40, 'car')]
        transcript = {'segments': [], 'words': [{'start': 19, 'end': 22, 'text': 'long_word'}]}
        scenes = detect_semantic_scenes(shots, transcript, 40)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 19), (19, 22), (22, 40)])
        self.assertTrue(scenes[1]['uncertain'])
        self.assertIn('large_word_safe_boundary_adjustment', scenes[1]['evidence']['uncertainty_reasons'])
        self.assertEqual([s['evidence']['raw_boundary_time'] for s in scenes], [0, 20, 21])
        self.assertFalse(any(19 < s['start'] < 22 or 19 < s['end'] < 22 for s in scenes))

    def test_impossible_word_safe_partition_keeps_raw_candidates_in_evidence(self):
        scenes = detect_semantic_scenes([shot(0, 0, 2, 'room'), shot(1, 2, 3, 'street'), shot(2, 3, 5, 'car')],
                                        {'segments': [], 'words': [{'start': 0, 'end': 5, 'text': 'word'}]}, 5)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 5)])
        self.assertTrue(scenes[0]['uncertain'])
        self.assertEqual(len(scenes[0]['evidence']['unsplittable_scene_candidates']), 3)
        self.assertEqual(scenes[0]['shot_ids'], ['shot_0000', 'shot_0001', 'shot_0002'])

    def test_temporal_gap_is_recorded_without_inventing_shot_ids(self):
        scenes = detect_semantic_scenes([shot(0, 0, 10), shot(1, 13, 20)], EMPTY, 20)
        self.assertEqual(len(scenes), 2)
        self.assertIn('temporal_discontinuity', scenes[1]['boundary_reason'])
        self.assertTrue(scenes[1]['uncertain'])
        self.assertEqual(scenes[1]['evidence']['boundary_decisions'][0]['signals']['temporal_gap'], 3)

    def test_invalid_source_intervals_are_rejected(self):
        with self.assertRaises(ValueError):
            detect_semantic_scenes([shot(0, 0, 10), shot(1, 9, 20)], EMPTY, 20)
        with self.assertRaises(ValueError):
            detect_semantic_scenes([], EMPTY, float('nan'))

    def test_suppressed_location_change_preserves_original_shot_and_word_safe_coverage(self):
        source_shot = shot(0, 0, 20, 'room')
        raw = adaptive_shot_evidence([(10, .17)], 20)
        raw[0]['features'] = {'location': 'car', 'character_state': 'bound'}
        source_shot['raw_shot_candidates'] = raw
        transcript = {'words': [{'start': 9.8, 'end': 10.1, 'text': 'word'}], 'segments': []}
        scenes = detect_semantic_scenes([source_shot], transcript, 20)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 10.1), (10.1, 20)])
        self.assertTrue(all(s['shot_ids'] == ['shot_0000'] for s in scenes))
        self.assertEqual(scenes[1]['candidate_ids'], [raw[0]['id']])
        self.assertIn('suppressed_shot_recovered', scenes[1]['boundary_reason'])
        self.assertEqual(scenes[1]['evidence']['raw_boundary_time'], 10)
        decision = scenes[1]['evidence']['boundary_decisions'][0]
        self.assertEqual(decision['source_candidate'], raw[0])
        self.assertEqual(decision['right_original_shot_id'], 'shot_0000')
        self.assertFalse(any(9.8 < s['start'] < 10.1 or 9.8 < s['end'] < 10.1 for s in scenes))
        self.assertEqual(scenes, detect_semantic_scenes([source_shot], transcript, 20))
        self.assertNotIn('parent_shot_id', source_shot)
        self.assertEqual(source_shot['raw_shot_candidates'], raw)

    def test_dense_suppressed_camera_motion_remains_one_scene_but_is_auditable(self):
        raw = adaptive_shot_evidence([(5 + index * .1, .22) for index in range(12)], 20)
        source_shot = {**shot(0, 0, 20, 'room'), 'raw_shot_candidates': raw}
        scenes = detect_semantic_scenes([source_shot], EMPTY, 20)
        self.assertEqual(len(scenes), 1)
        self.assertEqual((scenes[0]['start'], scenes[0]['end']), (0, 20))
        self.assertEqual(scenes[0]['candidate_ids'], [row['id'] for row in raw])
        self.assertEqual(len(scenes[0]['evidence']['boundary_decisions']), 12)
        self.assertTrue(all(not d['accepted'] for d in scenes[0]['evidence']['boundary_decisions']))
        self.assertFalse(scenes[0]['uncertain'])

    def test_indivisible_word_retains_all_suppressed_transition_evidence(self):
        raw = adaptive_shot_evidence([(10, .17), (11, .17)], 20)
        raw[0]['features'], raw[1]['features'] = {'location': 'street'}, {'location': 'car'}
        scenes = detect_semantic_scenes([{**shot(0, 0, 20, 'room'), 'raw_shot_candidates': raw}],
                                        {'words': [{'start': 0, 'end': 20, 'text': 'word'}], 'segments': []}, 20)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 20)])
        self.assertEqual(scenes[0]['candidate_ids'], [row['id'] for row in raw])
        self.assertEqual(len(scenes[0]['evidence']['source_segments']), 3)
        self.assertEqual(len(scenes[0]['evidence']['boundary_decisions']), 2)
        self.assertTrue(scenes[0]['uncertain'])

    def test_suppressed_physical_transition_flag_is_not_repeated_on_later_probes(self):
        raw = adaptive_shot_evidence([(5, .17), (6, .17), (7, .17)], 20)
        raw[0]['features'] = {'character_state': 'bound', 'state_transition': True}
        source_shot = {**shot(0, 0, 20, 'room', character_state='free'), 'raw_shot_candidates': raw}
        scenes = detect_semantic_scenes([source_shot], EMPTY, 20)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 5), (5, 20)])
        self.assertIn('physical_state_transition', scenes[1]['boundary_reason'])
        self.assertEqual(sum(d['accepted'] for s in scenes for d in s['evidence']['boundary_decisions']), 1)


class SceneCheckpointTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.directory = TEMP / ('scene_detection_test_' + uuid.uuid4().hex)
        self.directory.mkdir()
        self.source = self.directory / 'source.mp4'
        self.source.write_bytes(b'source')

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_cache_depends_on_source_transcript_settings_and_real_features(self):
        shots = [shot(0, 0, 10, 'room')]
        actual = {'shot_0000': {'location': 'room', 'origin': 'source_frames',
                               'samples': [{'time': 5.0}], 'reliability': 1}}
        with patch('app.scene_detection.extract_visual_features', return_value=actual) as extract:
            first_status, second_status = {}, {}
            first = scene_checkpoint(self.source, 'source-hash', 10, shots, EMPTY, self.directory, lambda: False,
                                     cache_status=first_status)
            second = scene_checkpoint(self.source, 'source-hash', 10, shots, EMPTY, self.directory, lambda: False,
                                      cache_status=second_status)
            self.assertEqual(extract.call_count, 1)
            self.assertFalse(first_status['cache_hit'])
            self.assertTrue(second_status['cache_hit'])
            self.assertEqual(first, second)
            changed_transcript = {'segments': [{'start': 0, 'end': 5, 'text': 'new phrase'}], 'words': []}
            changed_status = {}
            scene_checkpoint(self.source, 'source-hash', 10, shots, changed_transcript, self.directory, lambda: False,
                             cache_status=changed_status)
            self.assertFalse(changed_status['cache_hit'])
            self.assertEqual(extract.call_count, 1)
            changed_setting_status = {}
            scene_checkpoint(self.source, 'source-hash', 10, shots, changed_transcript,
                             self.directory, lambda: False, settings={'visual_change_threshold': .7},
                             cache_status=changed_setting_status)
            self.assertFalse(changed_setting_status['cache_hit'])
            self.assertEqual(extract.call_count, 1)
            self.source.write_bytes(b'a-different-source')
            scene_checkpoint(self.source, 'source-hash', 10, shots, EMPTY, self.directory, lambda: False)
            self.assertEqual(extract.call_count, 2)

    def test_cancelled_checkpoint_does_not_read_or_extract_source(self):
        with patch('app.scene_detection.extract_visual_features') as extract, self.assertRaises(InterruptedError):
            scene_checkpoint(self.directory / 'missing.mp4', 'hash', 10, [], EMPTY, self.directory, lambda: True)
        extract.assert_not_called()

    def test_raw_candidate_change_invalidates_features_and_same_inputs_reuse_scenes(self):
        raw = adaptive_shot_evidence([(5, .17)], 10)
        shots = [{**shot(0, 0, 10), 'raw_shot_candidates': raw}]
        features = {'shot_0000': {'location': 'room', 'samples': [{'time': 2}], 'origin': 'source_frames'},
                    f"shot_0000:candidate:{raw[0]['id']}": {'location': 'car', 'samples': [{'time': 7}],
                                                           'origin': 'source_frames'}}
        with patch('app.scene_detection.extract_visual_features', return_value=features) as extract:
            first = scene_checkpoint(self.source, 'source', 10, shots, EMPTY, self.directory, lambda: False)
            reused_status = {}
            reused = scene_checkpoint(self.source, 'source', 10, shots, EMPTY, self.directory, lambda: False,
                                      cache_status=reused_status)
            self.assertEqual(first, reused)
            self.assertTrue(reused_status['cache_hit'])
            self.assertTrue(reused_status['visual_cache_hit'])
            self.assertEqual(extract.call_count, 1)
            raw[0]['scene_score'] = raw[0]['score'] = .19
            changed_status = {}
            changed = scene_checkpoint(self.source, 'source', 10, shots, EMPTY, self.directory, lambda: False,
                                       cache_status=changed_status)
            self.assertEqual(extract.call_count, 2)
            self.assertFalse(changed_status['cache_hit'])
            self.assertFalse(changed_status['visual_cache_hit'])
            self.assertNotEqual(first[0]['evidence']['checkpoint']['identity'],
                                changed[0]['evidence']['checkpoint']['identity'])

    @unittest.skipUnless(FFMPEG.is_file(), 'Portable FFmpeg has not been installed')
    def test_real_source_frames_and_actual_pts_drive_scene_grouping(self):
        run_command([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     "color=red:s=160x90:r=10:d=3,drawgrid=w=20:h=20:t=2:c=white",
                     '-f', 'lavfi', '-i', "color=blue:s=160x90:r=10:d=3,drawgrid=w=20:h=20:t=2:c=white",
                     '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
                     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.source)], self.directory)
        shots = [shot(0, 0, 3), shot(1, 3, 6)]
        transcript = {'words': [{'start': 0, 'end': 1, 'text': 'before'},
                                {'start': 4, 'end': 5, 'text': 'after'}], 'segments': []}
        scenes = scene_checkpoint(self.source, 'real-source', 6, shots, transcript, self.directory, lambda: False)
        self.assertEqual(len(scenes), 2)
        self.assertIn('visual_context_change', scenes[1]['boundary_reason'])
        self.assertTrue(scenes[1]['uncertain'])  # descriptors cannot name a location
        self.assertTrue(all(s['evidence']['sampled_times'] for s in scenes))
        self.assertTrue(all(s['evidence']['checkpoint']['visual_origin'] == 'source_frames' for s in scenes))
        self.assertTrue((self.directory / 'scene-features.json').is_file())
        self.assertTrue((self.directory / 'scene-features' / 'frame-000001.jpg').is_file())

    @unittest.skipUnless(FFMPEG.is_file(), 'Portable FFmpeg has not been installed')
    def test_real_source_location_change_is_recovered_from_dense_suppressed_candidates(self):
        run_command([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     "color=red:s=160x90:r=10:d=3,drawgrid=w=20:h=20:t=2:c=white",
                     '-f', 'lavfi', '-i', "color=blue:s=160x90:r=10:d=3,drawgrid=w=20:h=20:t=2:c=white",
                     '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
                     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.source)], self.directory)
        raw = adaptive_shot_evidence([(index * .5, .22) for index in range(1, 12)], 6)
        self.assertTrue(all(not row['accepted'] for row in raw))
        shots = [{**shot(0, 0, 6), 'raw_shot_candidates': raw}]
        transcript = {'words': [{'start': 2.85, 'end': 3.1, 'text': 'crossing'}], 'segments': []}
        scenes = scene_checkpoint(self.source, 'real-source', 6, shots, transcript, self.directory, lambda: False)
        self.assertEqual([(s['start'], s['end']) for s in scenes], [(0, 3.1), (3.1, 6)])
        self.assertTrue(all(s['shot_ids'] == ['shot_0000'] for s in scenes))
        self.assertIn('suppressed_shot_recovered', scenes[1]['boundary_reason'])
        self.assertIn('visual_context_change', scenes[1]['boundary_reason'])
        self.assertTrue(scenes[1]['uncertain'])  # Image descriptors cannot label the real location.
        boundary = next(d for d in scenes[1]['evidence']['boundary_decisions'] if d['accepted'])
        self.assertEqual(boundary['time'], 3)
        self.assertEqual(boundary['source_candidate']['suppression_reason'], 'below_adaptive_threshold')
        self.assertEqual(scenes[1]['evidence']['raw_boundary_time'], 3)
        features = load_json(self.directory / 'scene-features.json')
        self.assertEqual(len(features), len(raw) + 1)
        candidate_feature = features[f"shot_0000:candidate:{boundary['source_candidate']['id']}"]
        self.assertEqual(candidate_feature['origin'], 'source_frames')
        self.assertTrue(all(3 <= sample['time'] < 3.5 for sample in candidate_feature['samples']))
        self.assertTrue(scenes[0]['evidence']['sampled_times'])
        self.assertTrue(scenes[1]['evidence']['sampled_times'])
        status = {}
        reused = scene_checkpoint(self.source, 'real-source', 6, shots, transcript, self.directory, lambda: False,
                                  cache_status=status)
        self.assertEqual(scenes, reused)
        self.assertTrue(status['cache_hit'])
        self.assertTrue(status['visual_cache_hit'])


if __name__ == '__main__':
    unittest.main()
