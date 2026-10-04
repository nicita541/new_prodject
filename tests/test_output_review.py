import unittest

from scripts.review_outputs import sample_times


class OutputReviewTests(unittest.TestCase):
    def test_audio_tail_does_not_request_a_nonexistent_video_frame(self):
        # Real part 7: the next 5-second sample is beyond its last frame,
        # although still inside the montage's audio/container duration.
        samples = sample_times(85.529, 30, 2565)
        self.assertEqual(samples[-1], 80.5)
        self.assertTrue(all(time <= 2564 / 30 for time in samples))

    def test_regular_video_keeps_chronological_five_second_samples(self):
        self.assertEqual(sample_times(16, 30, 480), [0.5, 5.5, 10.5, 15.5])
