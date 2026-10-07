"""Semantic ownership, visible action coverage and auditable inference failures."""
import json
import shutil
import unittest
import urllib.error
import uuid
from unittest.mock import patch

from app.config import TEMP, FFMPEG
from app.media import run_command
from app.media_probe import atomic_json, load_json
from app.pipeline_diagnostics import Diagnostics
from app.scene_analysis import analyze_scenes, query_scene, bounded_chunks
from app.scene_detection import detect_semantic_scenes
from app.story_review import candidate_units
from app.vision import storyboard_samples, storyboard_times, storyboard


EMPTY = {'words': [], 'segments': []}


class FakeVision:
    supports_image_pages = True

    def __init__(self):
        self.requests = []

    def query(self, prompt, image=None, max_tokens=1000, schema=None):
        self.requests.append((prompt, image))
        return {'summary': 'Текущие действия.', 'kind': 'story', 'importance': 4, 'uncertain': False,
                'semantic_confidence':.95,'visual_confidence':.95,'context_confidence':.95,
                'uncertainty_reasons':[], 'action_units':[], 'narrative_bridge':False,
                'state_before':{'locations':[],'character_state':'','objects':[]},
                'state_after':{'locations':[],'character_state':'','objects':[]},
                'keep_units': schema['properties']['keep_units']['items']['enum']}


class SemanticPipelineTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP / ('semantic-pipeline-' + uuid.uuid4().hex)
        self.job.mkdir(parents=True)

    def tearDown(self):
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    @staticmethod
    def fake_board(source, start, end, shots, transcript, destination, cancelled, **settings):
        destination.write_bytes(b'actual-collage-placeholder')
        frames = storyboard_samples(start, end, shots, transcript)
        atomic_json(destination.with_suffix('.storyboard.json'), {'start': start, 'end': end, 'frames': frames})
        return [f['time'] for f in frames]

    def analyze(self, scenes, shots, vision, signature='same'):
        with patch('app.vision.storyboard', side_effect=self.fake_board):
            return analyze_scenes(self.job/'source.mp4', scenes, EMPTY, shots, self.job, vision,
                                  signature, lambda *args: None, lambda: False)

    def test_technical_chunks_remain_one_scene_event_and_reuse_cache(self):
        shots = [{'id': f's{i}', 'start': i*15, 'end': (i+1)*15, 'location': 'room'} for i in range(6)]
        scenes = detect_semantic_scenes(shots, EMPTY, 90)
        vision = FakeVision()
        events = self.analyze(scenes, shots, vision)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(vision.requests), 3)
        self.assertEqual(events[0]['end'], 90)
        self.assertEqual({c['parent_scene_id'] for c in events[0]['analysis_chunks']}, {scenes[0]['id']})
        self.assertTrue((self.job/'visual/event_0000.jpg').is_file())
        cached = self.analyze(scenes, shots, vision)
        self.assertEqual(events, cached)
        self.assertEqual(len(vision.requests), 3)

    def test_neighbor_images_and_transcript_are_context_only(self):
        shots = [{'id': 'before', 'start': 0, 'end': 20, 'location': 'room'},
                 {'id': 'action', 'start': 20, 'end': 24, 'location': 'street'},
                 {'id': 'after', 'start': 24, 'end': 45, 'location': 'car'}]
        scenes = detect_semantic_scenes(shots, EMPTY, 45)
        vision = FakeVision()
        events = self.analyze(scenes, shots, vision)
        prompt, images = vision.requests[1]
        payload = json.loads(prompt[prompt.index('\n{')+1:])
        self.assertEqual(payload['PREVIOUS SCENE']['role'], 'context_only')
        self.assertEqual(payload['NEXT SCENE']['role'], 'context_only')
        self.assertEqual(payload['CURRENT SCENE']['role'], 'analyse')
        self.assertEqual(len(images), 3)
        self.assertEqual(events[1]['start'], 20)
        boards = load_json(self.job/'diagnostics/pipeline/storyboard.json')
        action = [b for b in boards if b['scene_id']==scenes[1]['id'] and b['role']=='current']
        self.assertTrue(any(20 <= f['time'] < 24 for b in action for f in b['frames']))

    def test_visual_handover_splits_long_reply_at_word_edge(self):
        words = [{'start': i+.05, 'end': i+.9, 'text': f'w{i}'} for i in range(12)]
        transcript = {'words': words, 'segments': [{'start': 0, 'end': 12, 'text': 'long reply'}]}
        units = candidate_units(0, 12, transcript, [{'start':0}, {'start':5.4}, {'start':7.4}], annotated=True)
        boundaries = {u['start'] for u in units} | {u['end'] for u in units}
        self.assertTrue(any(4.9 <= b <= 5.9 for b in boundaries))
        self.assertTrue(any(6.9 <= b <= 7.9 for b in boundaries))
        self.assertFalse(any(w['start'] < b < w['end'] for b in boundaries for w in words))
        self.assertTrue(any('shot_transition' in u['boundary_reason'] for u in units))

    def test_one_second_silent_action_has_multiple_frames_and_a_unit(self):
        shots = [{'start':0,'end':20}, {'start':20,'end':21.2}, {'start':21.2,'end':60}]
        units = candidate_units(0, 60, EMPTY, shots)
        self.assertIn((20.,21.2), [(u['start'],u['end']) for u in units])
        frames = storyboard_samples(0, 60, shots, EMPTY)
        self.assertGreaterEqual(sum(20 <= f['time'] < 21.2 and 'short_action_burst' in f['reasons'] for f in frames), 3)
        self.assertTrue(any(f['time'] < 20 and 'shot_transition' in f['reasons'] for f in frames))
        self.assertTrue(any(21.2 < f['time'] < 21.5 and 'shot_transition' in f['reasons'] for f in frames))

    def test_dense_action_chunks_fit_image_provider_without_becoming_scenes(self):
        shots = [{'id':f's{i}', 'start':i*.5, 'end':(i+1)*.5, 'location':'same'} for i in range(180)]
        scene = detect_semantic_scenes(shots, EMPTY, 90)[0]
        chunks = bounded_chunks(scene, EMPTY, shots)
        self.assertGreater(len(chunks), 3)
        self.assertEqual(chunks[0]['start'], 0)
        self.assertEqual(chunks[-1]['end'], 90)
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(chunks,chunks[1:])))
        self.assertEqual({c['parent_scene_id'] for c in chunks}, {scene['id']})
        self.assertTrue(all(len(storyboard_times(c['start'],c['end'],shots,EMPTY))<=96 for c in chunks))

    def test_real_one_second_action_pixels_are_present_in_submitted_pages(self):
        from PIL import Image
        source = self.job/'short-action.mp4'
        run_command([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x90:r=10:d=2',
                     '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=10:d=1',
                     '-f', 'lavfi', '-i', 'color=green:s=160x90:r=10:d=2',
                     '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
                     '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], self.job)
        shots = [{'start':0,'end':2}, {'start':2,'end':3}, {'start':3,'end':5}]
        destination = self.job/'actual.jpg'
        timestamps = storyboard(source, 0, 5, shots, EMPTY, destination, lambda:False)
        board = load_json(destination.with_suffix('.storyboard.json'))
        action_indices = [i for i,t in enumerate(timestamps) if 2 <= t < 3]
        self.assertGreaterEqual(len(action_indices),3)
        for index in action_indices:
            paged = len(board['pages'])>1
            page_index, position = (index//36,index%36) if paged else (0,index)
            with Image.open(board['pages'][page_index]) as page:
                pixel = page.getpixel((position%2*480+240,position//2*294+150))
                self.assertGreater(pixel[2], max(pixel[:2])+100, (timestamps[index],pixel))

    def test_model_failure_preserves_original_exception_and_attempts(self):
        class Broken:
            def query(self, *args, **kwargs):
                raise urllib.error.URLError('network symptom')
        with self.assertRaisesRegex(RuntimeError, 'network symptom') as caught:
            query_scene(Broken(), 'prompt', None, [{'id':'u000','start':0,'end':5}], 'event',
                        0, 5, [2], set(), Diagnostics(self.job))
        self.assertIsInstance(caught.exception.__cause__, urllib.error.URLError)
        entries = [json.loads(line) for line in (self.job/'diagnostics/pipeline/timeline.jsonl').read_text().splitlines()]
        self.assertEqual([e['attempt'] for e in entries], [1,2,3])
        self.assertEqual({e['error_type'] for e in entries}, {'URLError'})

    def test_diagnostics_preserve_reason_and_redact_credentials(self):
        diagnostics = Diagnostics(self.job)
        diagnostics.start(provider='local', api_key='private')
        diagnostics.warning('scene_analysis', 'missing_context', scene_id='scene_1')
        diagnostics.event('scene_analysis', 'exception', error='Bearer secret-value')
        self.assertNotIn('private', (self.job/'diagnostics/pipeline/run.json').read_text())
        self.assertNotIn('secret-value', (self.job/'diagnostics/pipeline/timeline.jsonl').read_text())
        self.assertEqual(load_json(self.job/'diagnostics/pipeline/warnings.json')[0]['reason'], 'missing_context')

    def test_uncertain_initial_analysis_runs_fresh_recovery_and_clears_uncertainty(self):
        from app.scene_understanding import RECOVERY_PROMPT
        class Recovering(FakeVision):
            def query(self,prompt,image=None,max_tokens=1000,schema=None):
                answer = super().query(prompt,image,max_tokens,schema)
                if prompt.startswith(RECOVERY_PROMPT):
                    answer.update(summary='Героев связывают.',action_units=answer['keep_units'],narrative_bridge=True)
                else:
                    answer.update(summary='Разговор.',uncertain=True,visual_confidence=.4,uncertainty_reasons=['visual_ambiguity'])
                return answer
        shots=[{'id':'s','start':0,'end':10,'location':'room'}]
        vision=Recovering()
        event=self.analyze(detect_semantic_scenes(shots,EMPTY,10),shots,vision)[0]
        self.assertEqual(len(vision.requests),2)
        self.assertTrue(event['initial_uncertain'])
        self.assertFalse(event['uncertain'])
        self.assertEqual(event['summary_source'],'recovery')
        self.assertEqual(event['local_summary'],'Разговор.')
        self.assertEqual(event['final_summary'],'Героев связывают.')
        self.assertTrue((self.job/'diagnostics/pipeline/scene_recovery.jsonl').is_file())

    def test_unresolved_recovery_retains_bounded_context_through_refinement(self):
        from app.scene_refinement import refine_scene_story
        class Unresolved(FakeVision):
            def query(self,*args,**kwargs):
                answer=super().query(*args,**kwargs)
                answer.update(uncertain=True,semantic_confidence=.4,uncertainty_reasons=['missing_context'])
                return answer
        shots=[{'id':'s','start':0,'end':180,'location':'room'}]
        events=self.analyze(detect_semantic_scenes(shots,EMPTY,180),shots,Unresolved())
        event=events[0]
        self.assertEqual(event['understanding_status'],'unresolved')
        self.assertLess(sum(r['end']-r['start'] for r in event['selected_ranges']),25)
        with patch('app.story.refine_story') as refiner:
            refined=refine_scene_story(events,EMPTY,shots,self.job,FakeVision(),lambda *a:None,lambda:False)
            refiner.assert_not_called()
        self.assertEqual(refined[0]['selected_ranges'],event['selected_ranges'])

    def test_recovery_model_failure_keeps_original_error_and_bounded_fallback(self):
        from app.scene_understanding import RECOVERY_PROMPT
        class Failing(FakeVision):
            def query(self,prompt,*args,**kwargs):
                if prompt.startswith(RECOVERY_PROMPT):
                    raise urllib.error.URLError('recovery network symptom')
                answer=super().query(prompt,*args,**kwargs)
                answer.update(uncertain=True,visual_confidence=.4)
                return answer
        shots=[{'id':'s','start':0,'end':30,'location':'room'}]
        event=self.analyze(detect_semantic_scenes(shots,EMPTY,30),shots,Failing())[0]
        self.assertTrue(event['uncertain'])
        self.assertEqual(event['summary_source'],'local')
        self.assertLess(sum(r['end']-r['start'] for r in event['selected_ranges']),6)
        records=[json.loads(line) for line in (self.job/'diagnostics/pipeline/scene_recovery.jsonl').read_text().splitlines()]
        self.assertIn('recovery network symptom',records[-1]['error'])


if __name__ == '__main__':
    unittest.main()
