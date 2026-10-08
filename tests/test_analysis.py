import unittest
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from app.analysis import analysis_windows, candidate_units, validated_event, apply_unit_selection, global_story_review, normalize_transcript
from app.analysis import atomic_json, load_json, shot_checkpoint
from app.analysis import analysis_provider, vision_session
from app.analysis import storyboard_times
from app.analysis import apply_global_selection
from app.planner import build_plan
from app.config import TEMP


@contextmanager
def analysis_directory():
    # Match repository fixtures: Windows sandbox cannot reopen mode=0o700
    # directories created by tempfile.TemporaryDirectory.
    directory = TEMP / ('test-analysis-' + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(directory)


class AnalysisValidationTests(unittest.TestCase):
    def test_global_omission_is_honored_but_dependency_can_restore_it(self):
        events=[{'id':'context','start':0,'end':10,'kind':'story','importance':4,'summary':'Повтор','requires':[]},
                {'id':'action','start':10,'end':30,'kind':'story','importance':4,'summary':'Новое','requires':[]}]
        decision={'keep':['action'],'omit':[{'event':'context','reason':'repeated_information',
                                           'evidence':'Повтор известного','confidence':.95}]}
        apply_global_selection(events,decision)
        data={'probe':{'duration':30,'width':1920,'height':1080,'has_audio':True},
              'events':events,'transcript':{'segments':[],'words':[]},'shots':[]}
        self.assertEqual(build_plan(data)['selected_event_ids'],['action'])
        # An event ID alone is no retention proof. A direct dependency may
        # restore its concrete source unit, never an arbitrary endpoint.
        events[1]['requires']=['context']
        self.assertEqual(build_plan(data)['selected_event_ids'],['action'])
        events[0].update(units=[{'id':'cause','start':6,'end':10}],keep_units=['cause'])
        self.assertEqual(build_plan(data)['selected_event_ids'],['context','action'])

    def test_editorial_profile_preserves_repetition_and_low_plot_atmosphere_globally(self):
        from app.editorial import DEFAULT_PROFILE
        profile={**DEFAULT_PROFILE,'remove_exact_repetition':False,'remove_empty_holds':False}
        events=[{'id':'repeat','start':0,'end':5,'kind':'story','importance':1,'requires':[]},
                {'id':'plot','start':5,'end':10,'kind':'story','importance':4,'requires':[]}]
        apply_global_selection(events,{'keep':['plot'],'omit':[{'event':'repeat',
            'reason':'repeated_information','evidence':'Same exchange retained earlier',
            'confidence':.95,'reaction_or_humor':False}]},profile)
        self.assertNotIn('global_excluded',events[0])
        events=[{'id':'reaction','start':0,'end':5,'kind':'story','importance':1,'requires':[]},
                {'id':'plot','start':5,'end':10,'kind':'story','importance':4,'requires':[]}]
        apply_global_selection(events,{'keep':['plot'],'omit':[{'event':'reaction',
            'reason':'nonstory','evidence':'No new plot fact',
            'confidence':.95,'reaction_or_humor':True}]})
        self.assertNotIn('global_excluded',events[0])

    def test_uncertainty_and_low_confidence_prevent_global_omission(self):
        for uncertain,confidence,refined_uncertain in [(True,.95,False),(False,.8,False),(False,.95,True)]:
            events=[{'id':'one','uncertain':uncertain,'selection_uncertain':refined_uncertain},{'id':'two'}]
            apply_global_selection(events,{'keep':['two'],'omit':[{'event':'one','reason':'redundant_exchange',
                                                                  'evidence':'Повтор','confidence':confidence}]})
            self.assertNotIn('global_excluded',events[0])

    def test_incomplete_global_partition_cannot_drop_an_event(self):
        with self.assertRaises(ValueError):
            apply_global_selection([{'id':'one'},{'id':'two'}],{'keep':['two'],'omit':[]})

    def test_truncated_global_facts_cannot_authorize_whole_event_removal(self):
        events=[{'id':'one'},{'id':'two'}]
        apply_global_selection(events,{'keep':['two'],'omit':[{'event':'one','reason':'repeated_information',
                                                              'evidence':'Повтор','confidence':.95}],
                                      'incomplete_event_ids':['one']})
        self.assertNotIn('global_excluded',events[0])

    def test_storyboard_covers_all_units_before_supplementary_shots(self):
        transcript={'words':[], 'segments':[{'start':i,'end':i+2.5,'text':'Реплика'} for i in range(0,36,3)]}
        shots=[{'start':i*.5,'end':(i+1)*.5} for i in range(80)]
        units=candidate_units(0,40,transcript,shots)
        times=storyboard_times(0,40,shots,transcript)
        self.assertGreaterEqual(len(times),max(17,len(units)))
        self.assertEqual(times,sorted(set(times)))
        self.assertTrue(all(0 <= t < 40 for t in times))
        for unit in units:
            self.assertTrue(any(unit['start'] <= t < unit['end'] for t in times),unit)

    def test_short_storyboard_covers_start_and_end_of_silent_action(self):
        times=storyboard_times(10,12,[{'start':10,'end':12}],{'words':[],'segments':[]})
        self.assertTrue(any(t<10.5 for t in times))
        self.assertTrue(any(t>11.5 for t in times))

    def test_cloud_selection_is_explicit_and_local_never_starts_api_client(self):
        with analysis_directory() as job:
            self.assertEqual(analysis_provider(job), 'local')
            with patch('app.analysis.LocalVision') as local, patch('app.deepseek.DeepSeekVision') as cloud:
                vision_session(job, lambda: False)
                local.assert_called_once()
                cloud.assert_not_called()
                atomic_json(job / 'analysis-settings.json', {'provider': 'deepseek'})
                vision_session(job, lambda: False, analysis_provider(job), thinking=True)
                cloud.assert_called_once()
                self.assertNotIn('thinking', cloud.call_args.kwargs)
            atomic_json(job / 'analysis-settings.json', {'provider': 'arbitrary-external-server'})
            with self.assertRaises(ValueError):
                analysis_provider(job)

    def test_shot_upgrade_rebuilds_legacy_and_threshold_caches(self):
        old = [{'id': 'old', 'start': 0, 'end': 10}]
        corrected = [{'id': 'first', 'start': 0, 'end': 6}, {'id': 'second', 'start': 6, 'end': 10}]
        with analysis_directory() as job:
            source = job / 'episode.mp4'
            atomic_json(job / 'shots.json', old)
            with patch('app.analysis.detect_shots', return_value=corrected) as detect:
                self.assertEqual(shot_checkpoint(source, 'original-sha', 10, job, lambda: False), corrected)
                detect.assert_called_once()
            with patch('app.analysis.detect_shots') as detect:
                self.assertEqual(shot_checkpoint(source, 'original-sha', 10, job, lambda: False), corrected)
                detect.assert_not_called()
            meta = load_json(job / 'shots.meta.json')
            meta['threshold'] = .24
            atomic_json(job / 'shots.meta.json', meta)
            with patch('app.analysis.detect_shots', return_value=corrected) as detect:
                shot_checkpoint(source, 'original-sha', 10, job, lambda: False)
                detect.assert_called_once()
            with patch('app.analysis.detect_shots', return_value=corrected) as detect:
                shot_checkpoint(source, 'different-sha', 10, job, lambda: False)
                detect.assert_called_once()

    def test_vad_long_gaps_do_not_join_distinct_replies(self):
        transcript = {'segments': [{'start': 0, 'end': 48, 'text': 'Не говорите!'}],
                      'words': [{'start': 0, 'end': 0.2, 'text': 'Не'}, {'start': 47, 'end': 48, 'text': 'говорите!'}]}
        result = normalize_transcript(transcript, 48)
        self.assertEqual(len(result['segments']), 2)
        self.assertEqual(result['raw_segments'], transcript['segments'])

    def test_model_cannot_choose_arbitrary_time_or_forward_dependency(self):
        event = validated_event({'start': -100, 'end': 9999, 'requires': ['future', 'prior'],
                                 'focus': [{'frame': 1, 'x': 0.8, 'y': 0.5}, {'frame': 99, 'x': 0.1}, {'frame': 2, 'x': float('nan')}]},
                                'current', 10, 20, [12, 18], {'prior'})
        self.assertEqual((event['start'], event['end']), (10, 20))
        self.assertEqual(event['requires'], ['prior'])
        self.assertEqual(len(event['focus']), 1)
        self.assertEqual(event['focus'][0]['time'], 12)

    def test_visual_windows_cover_entire_episode_including_silence(self):
        windows = analysis_windows(123, {'segments': [], 'words': []})
        self.assertEqual(windows[0][0], 0)
        self.assertEqual(windows[-1][1], 123)
        self.assertTrue(all(a[1] == b[0] for a, b in zip(windows, windows[1:])))

    def test_unit_selection_rejects_unknown_ids(self):
        event = {'start': 0, 'end': 10, 'importance': 4, 'uncertain': False}
        units = [{'id': 'u000', 'start': 0, 'end': 10}]
        with self.assertRaises(ValueError):
            apply_unit_selection(event, {'keep_units': ['invented']}, units)

    def test_missing_selection_records_unresolved_without_keep_all(self):
        event = {'start': 0, 'end': 10, 'importance': 4, 'uncertain': False}
        apply_unit_selection(event, {}, [{'id': 'u000', 'start': 0, 'end': 10}])
        self.assertTrue(event['uncertain'])
        self.assertEqual(event['selected_ranges'], [])
        self.assertTrue(event['analysis_unresolved'])

    def test_units_split_at_actual_reply_boundaries(self):
        transcript = {'segments': [{'start': 0, 'end': 4, 'text': 'Один.'}, {'start': 5, 'end': 9, 'text': 'Два.'}],
                      'words': [{'start': 0, 'end': 3, 'text': 'Один.'}, {'start': 5, 'end': 8, 'text': 'Два.'}]}
        units = candidate_units(0, 10, transcript)
        self.assertEqual([u['end'] for u in units], [4, 9, 10])

    def test_source_speech_onset_separates_long_neutral_prefix_from_causal_reply(self):
        transcript={'segments':[{'start':10,'end':12,'text':'Я нашёл письмо.'}],
                    'words':[{'start':10,'end':10.5,'text':'Я'},
                             {'start':10.5,'end':11,'text':'нашёл'}, {'start':11,'end':12,'text':'письмо.'}]}
        units=candidate_units(0,20,transcript,annotated=True,include_speech_onsets=True)
        self.assertEqual([(u['start'],u['end'],u['text']) for u in units],
                         [(0,10,''),(10,12,'Я нашёл письмо.'),(12,20,'')])
        self.assertIn('speech_start',units[1]['boundary_reason'])

    def test_silent_action_can_be_selected_without_entire_waiting_window(self):
        transcript = {'segments': [{'start': 20, 'end': 25, 'text': 'Привет.'}],
                      'words': [{'start': 20, 'end': 25, 'text': 'Привет.'}]}
        shots = [{'start': value} for value in (0, 5, 10, 15, 22, 30)]
        units = candidate_units(0, 40, transcript, shots)
        boundaries = [unit['start'] for unit in units]
        self.assertTrue({5, 10, 15, 30}.issubset(set(boundaries)))
        self.assertNotIn(22, boundaries)
        self.assertTrue(any(unit['text'] == 'Привет.' for unit in units))

    def test_technical_source_units_bound_uncut_silence_without_semantic_claims(self):
        units = candidate_units(0, 19, {'segments': [], 'words': []},
                                annotated=True, max_unit_seconds=4)
        self.assertEqual([(u['start'], u['end']) for u in units],
                         [(0, 4), (4, 8), (8, 12), (12, 16), (16, 19)])
        self.assertTrue(all(u['text'] == '' for u in units))
        self.assertTrue(all('technical_selection_interval' in u['boundary_reason'] for u in units[1:]))

    def test_technical_unit_edge_snaps_to_real_asr_word_edge(self):
        transcript = {'segments': [], 'words': [{'start': 3, 'end': 5, 'text': 'слово'}]}
        units = candidate_units(0, 12, transcript, annotated=True, max_unit_seconds=4)
        self.assertEqual(units[0]['end'], 3)
        self.assertTrue(all(not 3 < u['end'] < 5 for u in units))
        self.assertEqual(units[-1]['end'], 12)

    def test_global_pass_bounds_context_without_losing_episode_tail(self):
        class FakeVision:
            prompts = []
            def token_count(self, text):
                self.prompts.append(text)
                return len(text) // 2
            def query(self, prompt, max_tokens, schema=None):
                return {'keep': ['event_0035'], 'dependencies': None}
        vision = FakeVision()
        events = [{'id': f'event_{i:04d}', 'summary': 'Событие' * 200, 'kind': 'story', 'importance': 4} for i in range(36)]
        result = global_story_review(vision, events)
        self.assertEqual(result['dependencies'], [])
        self.assertLessEqual(len(vision.prompts[-1]) // 2, 5300)
        self.assertIn('event_0035', vision.prompts[-1])

    def test_global_pass_retries_hallucinated_source_references(self):
        class FakeVision:
            calls = 0
            def token_count(self, text): return 100
            def query(self, prompt, max_tokens, schema=None):
                self.calls += 1
                return {'keep': ['invented' if self.calls < 3 else 'event_0000']}
        vision = FakeVision()
        event = {'id': 'event_0000', 'summary': 'Событие', 'kind': 'story', 'importance': 4}
        self.assertEqual(global_story_review(vision, [event])['keep'], ['event_0000'])
        self.assertEqual(vision.calls, 3)

    def test_cloud_global_review_preserves_complete_middle_facts(self):
        from app.deepseek import DeepSeekVision
        from unittest.mock import patch
        from pathlib import Path
        vision = DeepSeekVision(Path('F:/new_prodject/temp/global-test'), lambda:False, cache_only=True)
        events = [{'id':f'event_{i:04d}', 'summary':'Начало. '*45+'Важная причина в середине. '+'Конец. '*45,
                   'kind':'story', 'importance':4} for i in range(36)]
        response = {'keep':[e['id'] for e in events], 'omit':[], 'dependencies':[], 'summary':'История'}
        with patch.object(DeepSeekVision, 'query', return_value=response) as query:
            result = global_story_review(vision, events)
        self.assertEqual(result['incomplete_event_ids'], [])
        prompt = query.call_args.args[0]
        self.assertEqual(prompt.count('Важная причина в середине.'), 36)
        self.assertNotIn('[middle omitted]', prompt)
        self.assertEqual(vision.text_budget, 64000)
        self.assertTrue(vision.cache_only)
