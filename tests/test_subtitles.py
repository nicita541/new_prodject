from contextlib import contextmanager
import uuid
import unittest
from pathlib import Path

from app.config import TEMP, FFMPEG
from app.subtitles import make_cues, remap_words, write_ass, write_srt
from app.media import run_command
from PIL import Image


@contextmanager
def workspace_directory():
    # Windows sandbox cannot reopen directories created with mkdtemp(mode=0o700).
    path = TEMP / ("subtitle_test_" + uuid.uuid4().hex)
    path.mkdir()
    yield str(path)


class SubtitleTests(unittest.TestCase):
    def test_accent_captions_preserve_words_in_short_uppercase_blocks(self):
        text = 'Сейчас начинается наша история и все персонажи остаются в кадре'
        words = [{'start': i * .3, 'end': (i + 1) * .3, 'text': word} for i, word in enumerate(text.split())]
        cues = make_cues(words, 'accent')
        self.assertEqual(' '.join(c['text'].replace('\n', ' ') for c in cues), text.upper())
        self.assertTrue(all(len(c['text'].split()) <= 5 for c in cues))
        self.assertTrue(all(c['end'] - c['start'] <= 2.4 for c in cues))

    def test_accent_actual_render_obeys_safe_margins_and_avoids_bottom_controls(self):
        text = 'ШИРОКОПЛЕЧИЙ ПЕРСОНАЖ РАССКАЗЫВАЕТ СВОЮ ИСТОРИЮ'
        words = [{'start': i * .1, 'end': 1 + i * .1, 'text': word} for i, word in enumerate(text.split())]
        cues = make_cues(words, 'accent')
        with workspace_directory() as directory:
            base = Path(directory)
            write_ass(base / 'captions.ass', cues, 1, 2, 'accent', 'cinema')
            run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         'color=black:size=1080x1920:rate=30', '-vf', 'ass=captions.ass',
                         '-ss', '0.3', '-frames:v', '1', str(base / 'accent.png')], base)
            picture = Image.open(base / 'accent.png').convert('L')
            box = picture.crop((0, 1200, 1080, 1800)).getbbox()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box[0], 140)
            self.assertLessEqual(box[2], 940)
            self.assertLess(box[3] + 1200, 1550)

    def test_words_remap_across_disjoint_cuts(self):
        words = [{"start": 1, "end": 2, "text": "Привет!"}, {"start": 12, "end": 13, "text": "Мир."}]
        remapped = remap_words(words, [{"start": 0, "end": 3}, {"start": 10, "end": 14}])
        self.assertEqual([(w["start"], w["end"]) for w in remapped], [(1, 2), (5, 6)])

    def test_cut_does_not_clip_words(self):
        with self.assertRaisesRegex(ValueError, "обрывает слово"):
            remap_words([{"start": 1, "end": 3, "text": "Привет"}], [{"start": 0, "end": 2}])

    def test_long_dialogue_wraps_at_most_two_lines_without_lost_text(self):
        words = [{"start": i / 3, "end": (i + 1) / 3, "text": "персонаж"} for i in range(30)]
        cues = make_cues(words)
        self.assertTrue(all(len(c["text"].splitlines()) <= 2 for c in cues))
        self.assertEqual(" ".join(c["text"].replace("\n", " ") for c in cues), " ".join(w["text"] for w in words))

    def test_srt_and_ass_escape_injected_overrides(self):
        with workspace_directory() as directory:
            base = Path(directory)
            cues = [{"start": 0.123, "end": 1.456, "text": "Русская строка\n{\\pos(0,0)}"}]
            write_srt(base / "test.srt", cues)
            write_ass(base / "test.ass", cues, 3, 10)
            self.assertIn("00:00:00,123 --> 00:00:01,456", (base / "test.srt").read_text(encoding="utf-8"))
            contents = (base / "test.ass").read_text(encoding="utf-8")
            self.assertNotIn(r"{\pos", contents)
            self.assertIn(r"строка\N", contents)
            self.assertIn("Часть 3", contents)

    def test_wide_russian_line_obeys_real_rendered_safe_margins(self):
        text = 'хоть никотинчиком подкрепиться увидала'
        words = [{"start": i * .2, "end": (i + 1) * .2, "text": word}
                 for i, word in enumerate(text.split())]
        cues = make_cues(words)
        self.assertEqual(cues[0]['text'].replace('\n', ' '), text)
        self.assertEqual(len(cues[0]['text'].splitlines()), 2)
        with workspace_directory() as directory:
            base = Path(directory)
            write_ass(base / 'captions.ass', cues, 4, 1)
            run_command([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         'color=black:size=1080x1920:rate=30', '-vf', 'ass=captions.ass',
                         '-frames:v', '1', str(base / 'caption.png')], base)
            picture = Image.open(base / 'caption.png').convert('L')
            # Exclude the part number; measure actual libass glyph pixels.
            box = picture.crop((0, 1300, 1080, 1850)).getbbox()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box[0], 90)
            self.assertLessEqual(box[2], 990)
