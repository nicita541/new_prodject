"""Fixture/input contract checks; production semantic quality is an opt-in run."""
import json
import math
from pathlib import Path
import shutil
import unittest
import uuid

from app.config import ROOT, TEMP
from app.media_probe import probe_media
from tests.raw_video_fixtures import FIXTURE_NAMES, FPS, build_fixture


FORBIDDEN = {'location','characters','character_state','state_before','state_after','action_units',
             'narrative_bridge','requires','story_arc_id','story_phase','importance','summary',
             'action_transition','expected','groundtruth'}


class RawFixtureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TEMP/('raw-fixture-contract-'+uuid.uuid4().hex)
        cls.fixtures = {name:build_fixture(name,cls.directory/name) for name in FIXTURE_NAMES}

    @classmethod
    def tearDownClass(cls):
        cls.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(cls.directory)

    def assertNoAnswers(self,value):
        if isinstance(value,dict):
            self.assertFalse(set(value)&FORBIDDEN)
            for item in value.values():
                self.assertNoAnswers(item)
        elif isinstance(value,list):
            for item in value:
                self.assertNoAnswers(item)

    def test_all_seven_sources_are_actual_decodable_media_without_semantic_inputs(self):
        self.assertEqual(len(self.fixtures),7)
        for name,(source,transcript) in self.fixtures.items():
            with self.subTest(name=name):
                self.assertEqual(source.name,'source.mp4')
                self.assertGreater(source.stat().st_size,10000)
                probe = probe_media(source)
                self.assertEqual((probe['width'],probe['height']),(640,360))
                self.assertAlmostEqual(probe['fps'],FPS,places=3)
                self.assertTrue(probe['has_audio'])
                self.assertGreaterEqual(probe['duration'],12)
                self.assertEqual(set(transcript),{'words','segments'})
                self.assertNoAnswers(transcript)
                manifest = json.loads((source.parent/'input.json').read_text('utf-8'))
                self.assertEqual(set(manifest),{'source','transcript'})
                self.assertNoAnswers(manifest)
                self.assertTrue((source.parent/'review/contact_sheet.jpg').is_file())

    def test_supplied_asr_is_ordinary_timed_text_inside_source_bounds(self):
        for name,(source,transcript) in self.fixtures.items():
            with self.subTest(name=name):
                duration = probe_media(source)['duration']
                self.assertTrue(transcript['words'])
                self.assertTrue(transcript['segments'])
                for key in ('words','segments'):
                    for record in transcript[key]:
                        self.assertEqual(set(record),{'start','end','text'})
                        self.assertTrue(all(math.isfinite(record[k]) for k in ('start','end')))
                        self.assertLess(record['start'],record['end'])
                        self.assertGreaterEqual(record['start'],0)
                        self.assertLessEqual(record['end'],duration)
                        self.assertTrue(record['text'].strip())
                for word in transcript['words']:
                    self.assertTrue(any(s['start']<=word['start']<word['end']<=s['end'] for s in transcript['segments']))

    def test_inputs_have_real_temporal_pixels_and_review_labels_stay_separate(self):
        for name,(source,_) in self.fixtures.items():
            with self.subTest(name=name):
                frames = sorted((source.parent/'frames').glob('*.png'))
                self.assertGreaterEqual(len(frames),12*FPS)
                # Purely physical checks, not an expected semantic response.
                self.assertGreater(len({frame.read_bytes() for frame in frames[::12]}),1)
                self.assertNotIn('review',json.loads((source.parent/'input.json').read_text('utf-8')))

    def test_unknown_fixture_and_outside_workspace_are_rejected_before_writes(self):
        with self.assertRaises(ValueError):
            build_fixture('invented',self.directory/'invalid')
        self.assertFalse((self.directory/'invalid').exists())
        with self.assertRaises(ValueError):
            build_fixture(FIXTURE_NAMES[0],ROOT.parent/'raw-fixtures-outside-workspace')


if __name__ == '__main__':
    unittest.main()
