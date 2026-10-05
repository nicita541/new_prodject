import unittest

from app.audio_analysis import (
    detect_transcript_music_intervals,
    map_cuts_to_part_duck_intervals,
    build_volume_expression,
    merge_intervals,
)


class AudioAnalysisTests(unittest.TestCase):
    def test_detect_transcript_music_intervals_finds_songs(self):
        transcript = {
            'segments': [
                {'start': 0.0, 'end': 10.0, 'text': 'Привет, как дела?'},
                {'start': 15.0, 'end': 35.0, 'text': '♪ Играет красивая песня о любви ♪'},
                {'start': 36.0, 'end': 40.0, 'text': 'Они поют на сцене караоке'},
                {'start': 45.0, 'end': 60.0, 'text': 'Продолжаем разговор.'},
            ]
        }
        intervals = detect_transcript_music_intervals(transcript)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0], (15.0, 35.0))
        self.assertEqual(intervals[1], (36.0, 40.0))

    def test_merge_intervals_combines_adjacent_or_overlapping(self):
        raw = [(10.0, 20.0), (19.5, 25.0), (30.0, 35.0)]
        merged = merge_intervals(raw)
        self.assertEqual(merged, [(10.0, 25.0), (30.0, 35.0)])

    def test_map_cuts_to_part_duck_intervals_offsets_correctly(self):
        cuts = [
            {'start': 10.0, 'end': 20.0},  # Part duration: 0..10
            {'start': 50.0, 'end': 70.0},  # Part duration: 10..30
        ]
        source_music = [
            (15.0, 25.0),  # Overlaps cut 1 at 15..20 -> part time 5..10
            (55.0, 65.0),  # Overlaps cut 2 at 55..65 -> part time 15..25
        ]
        part_ducks = map_cuts_to_part_duck_intervals(cuts, source_music)
        self.assertEqual(part_ducks, [(5.0, 10.0), (15.0, 25.0)])

    def test_build_volume_expression_empty_returns_constant(self):
        expr = build_volume_expression([], base_volume=0.15, duck_volume=0.015)
        self.assertEqual(expr, "0.150000")

    def test_build_volume_expression_with_intervals_produces_valid_ffmpeg_filter(self):
        intervals = [(5.0, 10.0), (15.0, 20.0)]
        expr = build_volume_expression(intervals, base_volume=0.15, duck_volume=0.015)
        self.assertIn(":eval=frame", expr)
        self.assertIn("0.015000", expr)
        self.assertIn("0.150000", expr)
        self.assertIn("between(t\\,5.000000\\,10.000000)", expr)
        self.assertIn("between(t\\,15.000000\\,20.000000)", expr)


if __name__ == '__main__':
    unittest.main()
