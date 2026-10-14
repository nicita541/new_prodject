"""Actual source decoding and request fanout; no performance claims from mocks."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from PIL import Image

from app.config import TEMP, FFMPEG, FFPROBE
from app.media_probe import run_process
from app.bounded_storyboard import build_bounded_storyboard
from app.scene_detection import _select_boundary_verifications
from app.scene_analysis import bounded_chunks, analyze_scenes
from app.vision import inference_samples, LocalVision
from app.story_review import candidate_units


class BoundarySpacingTests(unittest.TestCase):
    def test_bucket_edge_cannot_double_review_the_same_nearby_visual_change(self):
        def row(time):
            return {'time': time, 'proposal': {'origins': ['perceptual_discontinuity']},
                    'measured': {'classification': 'ambiguous_boundary',
                    'background_distance': .5, 'perceptual_distance': .5}}
        rows = [row(1.499), row(1.501), row(4.499), row(4.501)]
        chosen = _select_boundary_verifications(rows)
        self.assertEqual(len(chosen), 2)
        self.assertGreaterEqual(max(chosen)-min(chosen), 1.5)
        self.assertEqual(len(rows), 4)

    def test_close_explicit_state_and_dialogue_probes_remain_distinct(self):
        rows = [{'time': .7, 'proposal': {'origins': ['state_probe']},
                 'measured': {'classification': 'ambiguous_boundary'}},
                {'time': 2.1, 'proposal': {'origins': []},
                 'measured': {'classification': 'ambiguous_boundary',
                             'asr_continuity': {'dialogue_break': True}}}]
        self.assertEqual(_select_boundary_verifications(rows), {.7, 2.1})


@unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), 'Portable FFmpeg/FFprobe absent')
class PagedSourceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TEMP/('analysis-performance-'+uuid.uuid4().hex)
        cls.directory.mkdir(parents=True)
        cls.source = cls.directory/'source.mp4'
        run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     'testsrc2=s=160x90:r=12:d=12', '-c:v', 'libx264',
                     '-pix_fmt', 'yuv420p', cls.source], cls.directory/'encode.log', lambda: False)

    @classmethod
    def tearDownClass(cls):
        cls.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(cls.directory)

    def setUp(self):
        self.job = self.directory/uuid.uuid4().hex
        self.job.mkdir()

    def test_two_readable_pages_use_one_decode_and_keep_all_source_samples(self):
        times = [i*.3 for i in range(36)]
        destination = self.job/'current.jpg'
        with patch('app.bounded_storyboard.run_process', wraps=run_process) as execute:
            result = build_bounded_storyboard(self.source,0,12,destination,lambda:False,
                                             times=times,max_frames=36)
        self.assertEqual(sum(Path(call.args[0][0]) == FFMPEG for call in execute.call_args_list), 1)
        board = json.loads(destination.with_suffix('.storyboard.json').read_text('utf-8'))
        self.assertEqual(len(board['frames']), 36)
        self.assertEqual(len(board['pages']), 2)
        self.assertEqual(result, [frame['time'] for frame in board['frames']])
        self.assertEqual([frame['requested_time'] for frame in board['frames']], times)
        for path, digest in zip(board['pages'], board['page_sha256']):
            with Image.open(path) as page:
                self.assertEqual(page.size,(960,1224))
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),digest)
        for frame in board['frames']:
            n,d = map(int,frame['time_base'].split('/'))
            self.assertEqual(frame['time'],frame['pts']*n/d)
            self.assertTrue(0 <= frame['time'] < 12)

    def test_multiple_storyboards_hash_an_unchanged_source_once(self):
        source = self.job/'source.mp4'
        shutil.copy2(self.source,source)
        calls = []
        from app.source_identity import _hash_source
        def digest_source(path, cancelled):
            calls.append(path)
            return _hash_source(path, cancelled)
        with patch('app.source_identity._hash_source',side_effect=digest_source):
            for number in range(3):
                build_bounded_storyboard(source,number,number+1,self.job/f'page-{number}.jpg',
                                         lambda:False,times=[number+.2])
            self.assertEqual(len(calls),1)
            # Even a byte change with the same file size must invalidate the stamp.
            contents = bytearray(source.read_bytes());contents[-1] ^= 1;source.write_bytes(contents)
            build_bounded_storyboard(source,0,1,self.job/'modified.jpg',lambda:False,times=[.2])
            self.assertEqual(len(calls),2)

    def test_larger_chunks_preserve_sampling_and_speech_ownership(self):
        scene = {'id':'scene', 'start':0, 'end':12}
        transcript = {'segments':[{'start':0,'end':12,'text':'speech'}],
                      'words':[{'start':i,'end':i+.8,'text':'word'} for i in range(12)]}
        old = bounded_chunks(scene,transcript,[],max_frames=18)
        new = bounded_chunks(scene,transcript,[],max_frames=LocalVision.max_current_frames)
        self.assertLess(len(new),len(old))
        self.assertEqual(new[0]['start'],0)
        self.assertEqual(new[-1]['end'],12)
        for left,right in zip(new,new[1:]):
            self.assertEqual(left['end'],right['start'])
            self.assertFalse(any(word['start'] < left['end'] < word['end'] for word in transcript['words']))
        for chunk in new:
            units = candidate_units(chunk['start'],chunk['end'],transcript,[],annotated=True,max_unit_seconds=4)
            for recovery in (False,True):
                samples = inference_samples(chunk['start'],chunk['end'],units,recovery=recovery)
                self.assertLessEqual(len(samples),36)
                for unit in units:
                    self.assertTrue(any(unit['start'] <= timestamp < unit['end'] for timestamp in samples))

    def test_production_submits_readable_current_pages_with_scene_ownership(self):
        class Vision:
            supports_image_pages = True
            max_current_frames = 36
            def __init__(self):
                self.requests = []
            def query(self,prompt,image,max_tokens,schema):
                self.requests.append((prompt,image))
                state = {'locations':[], 'character_state':'', 'objects':[]}
                return {'summary':'Source footage', 'kind':'story', 'importance':4, 'uncertain':False,
                        'semantic_confidence':.95, 'visual_confidence':.95, 'context_confidence':.95,
                        'selection_confidence':.95, 'uncertainty_reasons':[], 'action_units':[],
                        'keep_units':schema['properties']['keep_units']['items']['enum'],
                        'narrative_bridge':False, 'state_before':state, 'state_after':state}
        vision = Vision()
        scene = {'id':'scene', 'start':0, 'end':12}
        transcript = {'segments':[], 'words':[]}
        events = analyze_scenes(self.source,[scene],transcript,[],self.job,vision,'pages',
                                lambda *args:None,lambda:False)
        self.assertEqual(len(events),1)
        self.assertEqual(len(vision.requests),len(bounded_chunks(scene,transcript,[],max_frames=36)))
        self.assertTrue(any(len(json.loads(prompt.rsplit('\n',1)[-1])['CURRENT SCENE']['frame_times']) > 18
                            for prompt,_ in vision.requests))
        for prompt, images in vision.requests:
            payload = json.loads(prompt.rsplit('\n',1)[-1])
            images = images if isinstance(images,list) else [images]
            self.assertLessEqual(len(images),2)
            self.assertEqual(payload['image_order'],['CURRENT']*len(images))
            for image in images:
                with Image.open(image) as page:
                    self.assertLessEqual(page.height,1224)
        # Changing capacity must invalidate the decision cache even for the same provider type.
        count = len(vision.requests);vision.max_current_frames = 18
        analyze_scenes(self.source,[scene],transcript,[],self.job,vision,'pages',lambda *args:None,lambda:False)
        self.assertEqual(len(vision.requests)-count,len(bounded_chunks(scene,transcript,[],max_frames=18)))

    def test_duplicate_requested_positions_decode_one_actual_source_frame(self):
        destination = self.job/'same-frame.jpg'
        with patch('app.bounded_storyboard.run_process',wraps=run_process) as execute:
            times = build_bounded_storyboard(self.source,0,1,destination,lambda:False,times=[.001,.002,.003])
        self.assertEqual(times,[1/12]*3)
        calls = [call.args[0] for call in execute.call_args_list if Path(call.args[0][0]) == FFMPEG]
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][calls[0].index('-frames:v')+1],'1')


if __name__ == '__main__':
    unittest.main()
