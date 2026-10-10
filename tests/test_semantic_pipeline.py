"""Semantic ownership, visible action coverage and auditable inference failures."""
import json
import shutil
import unittest
import urllib.error
import uuid
from unittest.mock import patch

from app.config import TEMP, FFMPEG, FFPROBE
from app.media import run_command
from app.media_probe import atomic_json, load_json
from app.pipeline_diagnostics import Diagnostics
from app.scene_analysis import analyze_scenes, query_scene, bounded_chunks, frame_backed_scenes
from app.scene_detection import detect_semantic_scenes
from app.story_review import candidate_units
from app.vision import storyboard_samples, storyboard_times, storyboard, inference_samples


EMPTY = {'words': [], 'segments': []}


class FakeVision:
    supports_image_pages = True

    def __init__(self):
        self.requests = []

    def query(self, prompt, image=None, max_tokens=1000, schema=None):
        self.requests.append((prompt, image))
        return {'summary': 'Текущие действия.', 'kind': 'story', 'importance': 4, 'uncertain': False,
                'semantic_confidence':.95,'visual_confidence':.95,'context_confidence':.95,
                'selection_confidence':.95,
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

    @staticmethod
    def fake_inference_board(source, start, end, units, destination, cancelled, *,
                             recovery=False, context=False, sample_limit=None):
        destination.write_bytes(b'bounded-source-collage-placeholder')
        times = [start, max(start, end-.05)] if context else inference_samples(start,end,units,recovery=recovery)
        if sample_limit is not None and len(times) > sample_limit:
            times = [times[round(i*(len(times)-1)/(sample_limit-1))] for i in range(sample_limit)]
        assert len(times) <= (2 if context else 12)
        frames = [{'index':i+1, 'time':time,
                   'unit_ids':[u['id'] for u in units if u['start'] <= time < u['end']],
                   'reasons':['context_only' if context else 'recovery_source_sample' if recovery else 'source_unit_sample']}
                  for i,time in enumerate(times)]
        atomic_json(destination.with_suffix('.storyboard.json'),
                    {'start':start,'end':end,'frames':frames,'pages':[str(destination)],'context':context})
        return times

    def analyze(self, scenes, shots, vision, signature='same'):
        with patch('app.vision.storyboard', side_effect=self.fake_board), \
                patch('app.vision.inference_storyboard', side_effect=self.fake_inference_board):
            return analyze_scenes(self.job/'source.mp4', scenes, EMPTY, shots, self.job, vision,
                                  signature, lambda *args: None, lambda: False)

    def test_technical_chunks_remain_one_scene_event_and_reuse_cache(self):
        shots = [{'id': f's{i}', 'start': i*15, 'end': (i+1)*15, 'location': 'room'} for i in range(6)]
        scenes = detect_semantic_scenes(shots, EMPTY, 90)
        vision = FakeVision()
        events = self.analyze(scenes, shots, vision)
        self.assertEqual(len(events), 1)
        expected_chunks = bounded_chunks(scenes[0], EMPTY, shots)
        self.assertEqual(len(vision.requests), len(expected_chunks))
        self.assertEqual(events[0]['analysis_chunks'], expected_chunks)
        self.assertEqual(events[0]['end'], 90)
        self.assertEqual({c['parent_scene_id'] for c in events[0]['analysis_chunks']}, {scenes[0]['id']})
        self.assertTrue((self.job/'visual/event_0000.jpg').is_file())
        cached = self.analyze(scenes, shots, vision)
        self.assertEqual(events, cached)
        self.assertEqual(len(vision.requests), len(expected_chunks))

    def test_neighbor_images_and_transcript_are_context_only(self):
        shots = [{'id': 'before', 'start': 0, 'end': 20, 'location': 'room'},
                 {'id': 'action', 'start': 20, 'end': 24, 'location': 'street'},
                 {'id': 'after', 'start': 24, 'end': 45, 'location': 'car'}]
        scenes = detect_semantic_scenes(shots, EMPTY, 45)
        vision = FakeVision()
        events = self.analyze(scenes, shots, vision)
        prompt, images = next((prompt, images) for prompt,images in vision.requests
                             if json.loads(prompt.rsplit('\n',1)[-1])['CURRENT SCENE']['chunk']['start']==20
                             and json.loads(prompt.rsplit('\n',1)[-1])['CURRENT SCENE']['chunk']['end']==24)
        payload = json.loads(prompt[prompt.index('\n{')+1:])
        self.assertEqual(payload['PREVIOUS SCENE']['role'], 'context_only')
        self.assertEqual(payload['NEXT SCENE']['role'], 'context_only')
        self.assertEqual(payload['CURRENT SCENE']['role'], 'analyse')
        self.assertEqual(len(images), 3)
        self.assertEqual(events[1]['start'], 20)
        boards = load_json(self.job/'diagnostics/pipeline/storyboard.json')
        action = [b for b in boards if b['scene_id']==scenes[1]['id'] and b['role']=='current']
        self.assertTrue(any(20 <= f['time'] < 24 for b in action for f in b['frames']))
        self.assertTrue(all(len(b['frames']) <= 2 for b in boards if b['role']=='context_only'))

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
        chunks = bounded_chunks(scene, EMPTY, shots, max_frames=12)
        self.assertGreater(len(chunks), 3)
        self.assertEqual(chunks[0]['start'], 0)
        self.assertEqual(chunks[-1]['end'], 90)
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(chunks,chunks[1:])))
        self.assertEqual({c['parent_scene_id'] for c in chunks}, {scene['id']})
        for chunk in chunks:
            units = candidate_units(chunk['start'],chunk['end'],EMPTY,shots,annotated=True,max_unit_seconds=4)
            for recovery in (False,True):
                self.assertLessEqual(len(inference_samples(chunk['start'],chunk['end'],units,recovery=recovery)),12)
        known_edges = {u[key] for u in candidate_units(0,90,EMPTY,shots,annotated=True,max_unit_seconds=4)
                       for key in ('start','end')}
        self.assertTrue(all(c['start'] in known_edges and c['end'] in known_edges for c in chunks))

    def test_short_silence_edge_can_split_recovery_frame_overflow(self):
        # An 80ms pre-speech unit and a 3.76s phrase fit the initial view
        # (12 samples), but need 13 samples during recovery. Both units are
        # word-safe; the short pause must not make the phrase indivisible.
        for offset in (0, 178.25):
            with self.subTest(offset=offset):
                start, speech_start, end = offset, offset+.08, offset+3.84
                transcript = {'segments': [{'start': speech_start, 'end': end, 'text': 'Реплика'}],
                              'words': [{'start': speech_start, 'end': end, 'text': 'Реплика'}]}
                scene = {'id': 'scene_pause', 'start': start, 'end': end}
                units = candidate_units(start, end, transcript, [], annotated=True, max_unit_seconds=4)
                self.assertEqual(len(inference_samples(start, end, units)), 12)
                self.assertEqual(len(inference_samples(start, end, units, recovery=True)), 13)
                chunks = bounded_chunks(scene, transcript, [], max_frames=12)
                self.assertEqual([(c['start'], c['end']) for c in chunks],
                                 [(start, speech_start), (speech_start, end)])
                self.assertEqual({c['parent_scene_id'] for c in chunks}, {scene['id']})
                for chunk in chunks:
                    child_units = candidate_units(chunk['start'], chunk['end'], transcript, [],
                                                  annotated=True, max_unit_seconds=4)
                    for recovery in (False, True):
                        self.assertLessEqual(len(inference_samples(chunk['start'], chunk['end'],
                                                                    child_units, recovery=recovery)), 12)

    def test_truly_indivisible_oversize_word_still_fails_without_cutting_speech(self):
        scene = {'id': 'scene_word', 'start': 0, 'end': 9}
        transcript = {'segments': [{'start': 0, 'end': 9, 'text': 'Слово'}],
                      'words': [{'start': 0, 'end': 9, 'text': 'Слово'}]}
        with self.assertRaisesRegex(ValueError, 'Indivisible source unit'):
            bounded_chunks(scene, transcript, [], max_frames=12)

    def test_frame_empty_scene_keeps_its_interval_without_borrowing_a_picture(self):
        scenes = [{'id': 'before', 'start': 0, 'end': .04},
                  {'id': 'gap', 'start': .04, 'end': .08},
                  {'id': 'after', 'start': .08, 'end': .2}]
        result = frame_backed_scenes(scenes, [0, .1])
        self.assertEqual([(s['id'], s['start'], s['end']) for s in result],
                         [('before', 0, .08), ('after', .08, .2)])
        self.assertEqual(result[0]['evidence']['frame_empty_intervals'], [scenes[1]])
        self.assertEqual(scenes[0]['end'], .04)
        self.assertNotIn('evidence', scenes[0])

    def test_leading_and_trailing_frame_empty_intervals_keep_total_source_coverage(self):
        scenes = [{'id': 'lead', 'start': 0, 'end': .01},
                  {'id': 'middle', 'start': .01, 'end': .11},
                  {'id': 'tail', 'start': .11, 'end': .2}]
        result = frame_backed_scenes(scenes, [.1])
        self.assertEqual([(s['start'], s['end']) for s in result], [(0, .2)])
        self.assertEqual([s['id'] for s in result[0]['evidence']['frame_empty_intervals']], ['lead', 'tail'])

    def test_frame_empty_does_not_mean_short_and_frame_on_end_belongs_to_next_scene(self):
        scenes = [{'id': 'hold', 'start': 0, 'end': 3},
                  {'id': 'gap', 'start': 3, 'end': 10},
                  {'id': 'next', 'start': 10, 'end': 11}]
        self.assertEqual([s['id'] for s in frame_backed_scenes(scenes, [0, 10])], ['hold', 'next'])
        self.assertEqual(frame_backed_scenes(scenes, [0, 3, 10]), scenes)
        with self.assertRaisesRegex(ValueError, 'no video frames'):
            frame_backed_scenes(scenes, [11])

    def test_frame_empty_coalescing_cannot_cross_an_unrepresented_source_gap(self):
        scenes = [{'id': 'before', 'start': 0, 'end': .1},
                  {'id': 'gap', 'start': .2, 'end': .3}]
        with self.assertRaisesRegex(ValueError, 'not adjacent'):
            frame_backed_scenes(scenes, [0])

    @unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), 'Portable FFmpeg/FFprobe absent')
    def test_real_frame_empty_neighbor_and_current_are_coalesced_without_losing_speech(self):
        source = self.job/'frame-gap.mp4'
        run_command([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     'testsrc2=s=160x90:r=12:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                    cwd=self.job)
        transcript = {'segments': [{'start': .04, 'end': .08, 'text': 'Да'}],
                      'words': [{'start': .04, 'end': .08, 'text': 'Да'}]}
        scenes = [{'id': 'before', 'start': 0, 'end': .04},
                  {'id': 'gap', 'start': .04, 'end': .08},
                  {'id': 'after', 'start': .08, 'end': 1}]
        events = analyze_scenes(source, scenes, transcript, [], self.job, FakeVision(), 'frame-gap',
                                lambda *args: None, lambda: False)
        self.assertEqual([(event['start'], event['end']) for event in events], [(0, .08), (.08, 1)])
        self.assertIn('Да', ' '.join(unit['text'] for unit in events[0]['units']))
        self.assertEqual(events[0]['scene_evidence']['frame_empty_intervals'][0]['id'], 'gap')
        self.assertTrue(all(unit['start'] <= .04 and unit['end'] >= .08
                            for unit in events[0]['units'] if 'Да' in unit['text']))
        for event in events:
            for chunk in event['chunk_analyses']:
                board = load_json(self.job/'visual'/f'{event["id"]}_chunk_{chunk["chunk_id"].rsplit("_",1)[-1]}.storyboard.json')
                self.assertTrue(all(board['start'] <= frame['time'] < board['end'] for frame in board['frames']))

    @unittest.skipUnless(FFMPEG.is_file() and FFPROBE.is_file(), 'Portable FFmpeg/FFprobe absent')
    def test_real_bounded_current_pages_preserve_red_blue_green_pixels_and_source_pts(self):
        from PIL import Image
        source = self.job/'bounded-colors.mp4'
        run_command([str(FFMPEG), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x90:r=10:d=2',
                     '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=10:d=1',
                     '-f', 'lavfi', '-i', 'color=green:s=160x90:r=10:d=2',
                     '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
                     '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], self.job)
        shots = [{'start':0,'end':2}, {'start':2,'end':3}, {'start':3,'end':5}]
        scene = {'id':'one-source-scene','start':0,'end':5,'confidence':.9,'boundary_reason':[]}
        vision = FakeVision()
        # Only the diagnostic legacy overview is mocked; submitted CURRENT
        # boards use the real FFmpeg decoder and measured presentation times.
        with patch('app.vision.storyboard', side_effect=self.fake_board):
            events = analyze_scenes(source,[scene],EMPTY,shots,self.job,vision,'bounded-colors',
                                    lambda *args:None,lambda:False)
        event = events[0]
        self.assertEqual((event['scene_id'],event['start'],event['end']),('one-source-scene',0,5))
        self.assertEqual(len(vision.requests),len(event['analysis_chunks']))
        seen, blue_frames, moved_to_actual_pts = set(), 0, False
        for number,chunk in enumerate(event['analysis_chunks']):
            destination = self.job/'visual'/f'event_0000_chunk_{number:03d}.jpg'
            board = load_json(destination.with_suffix('.storyboard.json'))
            prompt,submitted = vision.requests[number]
            payload = json.loads(prompt.rsplit('\n',1)[-1])['CURRENT SCENE']
            self.assertEqual(submitted,destination)
            self.assertEqual(payload['frame_times'],[f['time'] for f in board['frames']])
            self.assertEqual([u['id'] for u in payload['units']],
                             [u['id'] for u in event['units'] if chunk['start'] <= u['start'] < u['end'] <= chunk['end']])
            self.assertLessEqual(len(board['frames']),12)
            self.assertEqual(board['pages'],[str(destination.resolve())])
            with Image.open(destination) as page:
                self.assertLessEqual(page.height,816)
                for index,frame in enumerate(board['frames']):
                    timestamp = frame['time']
                    self.assertTrue(chunk['start'] <= timestamp < chunk['end'])
                    numerator,denominator = map(int,frame['time_base'].split('/'))
                    self.assertEqual(timestamp,frame['pts']*numerator/denominator)
                    moved_to_actual_pts |= timestamp != frame['requested_time']
                    actual_ids = [u['id'] for u in event['units'] if u['start'] <= timestamp < u['end']]
                    self.assertEqual(frame['unit_ids'],actual_ids)
                    pixel = page.getpixel((index%3*320+160,index//3*204+114))
                    color = 'red' if timestamp < 2 else 'blue' if timestamp < 3 else 'green'
                    channel = {'red':0,'green':1,'blue':2}[color]
                    self.assertGreater(pixel[channel],max(pixel[i] for i in range(3) if i!=channel)+80,
                                       (timestamp,pixel,color))
                    seen.add(color)
                    blue_frames += color=='blue'
        self.assertEqual(seen,{'red','blue','green'})
        self.assertGreaterEqual(blue_frames,3)
        self.assertTrue(moved_to_actual_pts)

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

    def test_complete_diagnostic_catalog_exists_even_when_no_recovery_runs(self):
        diagnostics = Diagnostics(self.job)
        diagnostics.start(provider='local')
        expected = ('run.json','timeline.jsonl','shots.json','scenes.json','storyboard.json',
                    'scene_analysis.jsonl','scene_recovery.jsonl','global_story.json',
                    'episode_profile.json','planner.json','decisions.jsonl','warnings.json','summary.json')
        self.assertTrue(all((diagnostics.path/name).is_file() for name in expected))
        self.assertEqual((diagnostics.path/'scene_recovery.jsonl').read_text(), '')

    def test_recovery_uses_doubt_and_hinako_neighbor_replies_to_explain_current_transition(self):
        transcript = {'words': [{'start': 15, 'end': 18, 'text': 'Я не уверен, что справлюсь.'},
                                {'start': 45, 'end': 48, 'text': 'Нужна помощь.'},
                                {'start': 122, 'end': 126, 'text': 'Хинако, что ты тут делаешь?'}],
                      'segments': [{'start': 15, 'end': 18, 'text': 'Я не уверен, что справлюсь.'},
                                   {'start': 45, 'end': 48, 'text': 'Нужна помощь.'},
                                   {'start': 122, 'end': 126, 'text': 'Хинако, что ты тут делаешь?'}]}
        scenes = [{'id': f'scene_{i}', 'start': start, 'end': end, 'confidence': .9,
                   'boundary_reason': ['location_change']} for i,(start,end) in enumerate(((0,20),(20,120),(120,150)))]
        class ContextVision(FakeVision):
            def query(self, prompt, image=None, max_tokens=1000, schema=None):
                raw = super().query(prompt, image, max_tokens, schema)
                payload = json.loads(prompt.rsplit('\n',1)[-1])
                if 'initial_analysis' in payload:
                    assert 'Я не уверен, что справлюсь.' in prompt and 'Хинако, что ты тут делаешь?' in prompt
                    raw.update(summary='Объясняющий разговор связывает сомнение и появление Хинако.', narrative_bridge=True)
                elif payload['CURRENT SCENE']['start'] >= 20 and payload['CURRENT SCENE']['end'] <= 120:
                    raw.update(uncertain=True, semantic_confidence=.4, visual_confidence=.4,
                               context_confidence=.4, uncertainty_reasons=['missing_context'])
                return raw
        vision = ContextVision()
        with patch('app.vision.storyboard', side_effect=self.fake_board), \
                patch('app.vision.inference_storyboard', side_effect=self.fake_inference_board):
            events = analyze_scenes(self.job/'source.mp4', scenes, transcript, [], self.job, vision,
                                    'neighbors', lambda *args: None, lambda: False)
        self.assertFalse(events[1]['uncertain'])
        self.assertEqual(events[1]['summary_source'], 'recovery')
        self.assertTrue(events[1]['narrative_bridge'])
        self.assertIn('Хинако', events[1]['recovery_summary'])

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
        self.assertEqual(len(vision.requests),2*len(event['analysis_chunks']))
        self.assertTrue(event['initial_uncertain'])
        self.assertFalse(event['uncertain'])
        self.assertEqual(event['summary_source'],'recovery')
        self.assertEqual(event['local_summary'].splitlines(),['Разговор.']*len(event['analysis_chunks']))
        self.assertEqual(event['final_summary'].splitlines(),['Героев связывают.']*len(event['analysis_chunks']))
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
        self.assertLess(sum(r['end']-r['start'] for r in event['selected_ranges']),180)
        self.assertTrue(all(c.get('whole_scene_last_resort') is False for c in event['chunk_analyses']))
        self.assertTrue(all(c['selected_ranges']==[] for c in event['chunk_analyses']))
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
        self.assertLess(sum(r['end']-r['start'] for r in event['selected_ranges']),30)
        self.assertTrue(all(c.get('whole_scene_last_resort') is False for c in event['chunk_analyses']))
        self.assertTrue(all(c['selected_ranges']==[] for c in event['chunk_analyses']))
        records=[json.loads(line) for line in (self.job/'diagnostics/pipeline/scene_recovery.jsonl').read_text().splitlines()]
        self.assertIn('recovery network symptom',records[-1]['error'])


if __name__ == '__main__':
    unittest.main()
