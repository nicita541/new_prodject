import unittest

from app.planner import build_plan, validate_plan


def analysis(duration=200):
    return {"probe": {"duration": duration, "width": 1920, "height": 1080, "fps": 30, "has_audio": True},
            "transcript": {"words": [], "segments": []}, "shots": [],
            "events": [{"id": "one", "start": 0, "end": duration, "kind": "story", "importance": 3,
                        "requires": [], "focus": [], "boundary_times": []}]}


class PlannerTests(unittest.TestCase):
    def test_confirmed_title_removal_survives_dialogue_restoration_and_padding(self):
        data=analysis(30)
        data['events'][0].update(selected_ranges=[{'start':1,'end':3},{'start':20,'end':22}],
                                 excluded_title_units=[{'id':'visible-title','start':10,'end':12}])
        data['transcript']={'segments':[{'start':1,'end':3,'text':'Реплика.'},{'start':10,'end':12,'text':'Название серии.'}],
                            'words':[{'start':1,'end':3,'text':'Реплика.'},{'start':10,'end':12,'text':'Название серии.'}]}
        plan=build_plan(data)
        self.assertFalse(any(c['start'] < 12 and c['end'] > 10 for p in plan['parts'] for c in p['cuts']))
        self.assertNotIn('Название серии.', ' '.join(s['text'] for p in plan['parts'] for s in p['subtitles']))

    def test_retained_story_restores_model_omitted_reply_and_preserves_tail(self):
        data = analysis(30)
        data['events'][0]['selected_ranges'] = [{'start':1,'end':3}, {'start':10,'end':12}]
        data['transcript'] = {'segments':[{'start':1,'end':3,'text':'Первая.'},
                                         {'start':6,'end':7,'text':'Пропущенный ответ.'},
                                         {'start':10,'end':12,'text':'Последняя.'}],
                              'words':[{'start':1,'end':3,'text':'Первая.'},
                                       {'start':6,'end':7,'text':'Пропущенный ответ.'},
                                       {'start':10,'end':12,'text':'Последняя.'}]}
        part = build_plan(data)['parts'][0]
        self.assertEqual([(c['start'],c['end']) for c in part['cuts']], [(0.82,3.55),(5.82,7.55),(9.82,12.55)])
        self.assertIn('Пропущенный ответ.', ' '.join(c['text'] for c in part['subtitles']))

    def test_speech_handles_do_not_take_a_piece_of_an_unselected_neighbor(self):
        data = analysis(20)
        event = data['events'][0]
        data['events'] = [{**event,'end':5}, {**event,'id':'omit','start':5,'end':20,'kind':'filler','importance':1}]
        data['transcript'] = {'segments':[{'start':4,'end':5,'text':'Конец.'},{'start':5.2,'end':8,'text':'Следующая.'}],
                              'words':[{'start':4,'end':5,'text':'Конец.'},{'start':5.2,'end':8,'text':'Следующая.'}]}
        part = build_plan(data)['parts'][0]
        self.assertAlmostEqual(part['cuts'][0]['end'],5.16)
        self.assertEqual([c['text'] for c in part['subtitles']],['Конец.'])

    def test_only_actual_shot_boundaries_mark_hard_cuts_in_merged_intervals(self):
        data = analysis(20)
        original = data["events"][0]
        focus = lambda time, **extra: {"time": time, "x": 0.5, "y": 0.5, "confidence": 0.9, **extra}
        data["events"] = [{**original, "id": "a", "end": 10,
                           "focus": [focus(0), focus(4.002), focus(8, hard_cut=True)]},
                          {**original, "id": "b", "start": 10, "end": 20,
                           "focus": [focus(10), focus(12.0019), focus(16.0021)]}]
        data["shots"] = [{"id": str(i), "start": t, "end": t + 4} for i, t in enumerate([0, 4, 12, 16])]
        cut = build_plan(data)["parts"][0]["cuts"][0]
        self.assertEqual(cut["event_ids"], ["a", "b"])
        self.assertEqual([(a["time"], a["hard_cut"]) for a in cut["focus"]],
                         [(0, True), (4.002, True), (8, False), (10, False), (12.0019, True), (16.0021, False)])
        self.assertNotIn("hard_cut", data["events"][0]["focus"][0])

    def test_plan_rejects_nonboolean_hard_cut_metadata(self):
        data = analysis(20)
        plan = build_plan(data)
        plan["parts"][0]["cuts"][0]["focus"][0]["hard_cut"] = "false"
        with self.assertRaisesRegex(ValueError, "смены кадра"):
            validate_plan(plan, data)

    def test_balances_silent_material_without_short_final_remainder(self):
        plan = build_plan(analysis())
        self.assertEqual(len(plan['parts']), 3)
        self.assertLess(max(p['duration'] for p in plan['parts'])-min(p['duration'] for p in plan['parts']),.001)
        cuts = [c for p in plan["parts"] for c in p["cuts"]]
        self.assertEqual(cuts[0]['start'],0)
        self.assertEqual(cuts[-1]['end'],200)
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(cuts,cuts[1:])))

    def test_exact_ninety_second_material_stays_one_part(self):
        self.assertEqual([p['duration'] for p in build_plan(analysis(90))['parts']],[90])

    def test_remote_early_shots_do_not_create_a_tiny_first_part(self):
        data=analysis(200)
        data['shots']=[{'start':i,'end':i+1} for i in range(6)]
        durations=[p['duration'] for p in build_plan(data)['parts']]
        self.assertEqual(len(durations),3)
        self.assertLess(max(durations)-min(durations),.001)

    def test_multiple_removed_gaps_balance_on_output_time(self):
        data=analysis(220)
        data['events'][0].update(unit_selection_version=1,
            selected_ranges=[{'start':0,'end':60},{'start':100,'end':160},{'start':200,'end':220}])
        plan=build_plan(data)
        self.assertEqual([p['duration'] for p in plan['parts']],[70,70])
        self.assertFalse(any(c['start']<100 and c['end']>60 for p in plan['parts'] for c in p['cuts']))

    def test_balanced_cut_chooses_whole_reply_near_target(self):
        data=analysis(170)
        data['transcript']={'segments':[{'start':0,'end':80,'text':'Первая.'},
                                        {'start':80,'end':170,'text':'Вторая.'}],
                            'words':[{'start':0,'end':80,'text':'Первая.'},
                                     {'start':80,'end':170,'text':'Вторая.'}]}
        self.assertEqual([p['duration'] for p in build_plan(data)['parts']],[80,90])

    def test_indivisible_replies_rebalance_when_arithmetic_minimum_is_infeasible(self):
        data=analysis(215)
        replies=[{'start':i*55,'end':min(215,(i+1)*55),'text':'Реплика.'} for i in range(4)]
        data['transcript']={'segments':replies,'words':replies}
        plan=build_plan(data)
        self.assertEqual([p['duration'] for p in plan['parts']],[55,55,55,50])
        self.assertFalse(plan['warnings'])

    def test_causal_dependency_retains_lower_importance_scene(self):
        data = analysis(120)
        original = data["events"][0]
        data["events"] = [{**original, "id": "context", "end": 20, "importance": 1, "kind": "recap"},
                          {**original, "id": "skip", "start": 20, "end": 60, "importance": 1, "kind": "opening"},
                          {**original, "id": "payoff", "start": 60, "end": 120, "importance": 5, "requires": ["context"]}]
        plan = build_plan(data)
        self.assertEqual(plan["selected_event_ids"], ["context", "payoff"])
        self.assertEqual(plan["parts"][0]["duration"], 80)
        self.assertEqual(len(plan["parts"][0]["cuts"]), 2)

    def test_silent_narrative_inside_ending_is_retained(self):
        data = analysis(30)
        data["events"][0].update(kind="ending", importance=4)
        self.assertEqual(build_plan(data)["parts"][0]["duration"], 30)

    def test_model_selected_source_ranges_shorten_window_and_keep_complete_reply(self):
        data = analysis(60)
        data["events"][0]["selected_ranges"] = [{"start": 5, "end": 10}, {"start": 30, "end": 35}]
        data["transcript"] = {"segments": [{"start": 4, "end": 12, "text": "реплика"}],
                              "words": [{"start": 4, "end": 12, "text": "реплика"}]}
        part = build_plan(data)["parts"][0]
        self.assertEqual([(c["start"], c["end"]) for c in part["cuts"]], [(3.82, 12.55), (30, 35)])
        self.assertEqual(part["duration"], 13.73)

    def test_selected_range_cannot_hallucinate_time(self):
        data = analysis(60)
        data["events"][0]["selected_ranges"] = [{"start": 5, "end": 100}]
        with self.assertRaises(ValueError):
            build_plan(data)

    def test_reply_expansion_merges_overlaps_without_repeated_words(self):
        data = analysis(60)
        original = data["events"][0]
        data["events"] = [{**original, "id": "a", "end": 20}, {**original, "id": "b", "start": 20, "end": 40},
                          {**original, "id": "c", "start": 40, "end": 60, "importance": 1, "kind": "filler"}]
        data["transcript"] = {"segments": [{"start": 18, "end": 22, "text": "Целая реплика"}],
                              "words": [{"start": 18, "end": 20.5, "text": "Целая"}, {"start": 20.5, "end": 22, "text": "реплика"}]}
        plan = build_plan(data)
        self.assertEqual(len(plan["parts"][0]["cuts"]), 1)
        self.assertEqual(plan["parts"][0]["subtitles"][0]["text"], "Целая реплика")

    def test_long_reply_splits_at_words(self):
        data = analysis(110)
        data["transcript"]["segments"] = [{"start": 0, "end": 110, "text": "длинная реплика"}]
        data["transcript"]["words"] = [{"start": t, "end": t + 2, "text": "слово"} for t in range(0, 110, 2)]
        plan = build_plan(data)
        self.assertEqual([p["duration"] for p in plan["parts"]], [54, 56])
        self.assertTrue(plan["warnings"])

    def test_regular_reply_does_not_split_to_fill_part(self):
        data = analysis(110)
        data["transcript"]["segments"] = [{"start": 0, "end": 70, "text": "первая"}, {"start": 70, "end": 110, "text": "вторая"}]
        data["transcript"]["words"] = [{"start": 0, "end": 1, "text": "первая"}, {"start": 70, "end": 71, "text": "вторая"}]
        self.assertEqual([p["duration"] for p in build_plan(data)["parts"]], [70, 40])

    def test_short_reply_moves_whole_to_fresh_part_with_only_eight_seconds_left(self):
        data = analysis(130)
        data['events'][0]['selected_ranges'] = [{'start':0,'end':82}, {'start':100,'end':122.74}]
        data['transcript'] = {'segments':[{'start':100,'end':122.74,'text':'Целая короткая реплика.'}],
                              'words':[{'start':100+i,'end':101+i,'text':'слово'} for i in range(22)]}
        plan = build_plan(data)
        self.assertEqual([part['duration'] for part in plan['parts']], [52.735,52.735])
        self.assertTrue(any(c['start']<=100 and c['end']>=122.74 for p in plan['parts'] for c in p['cuts']))
        self.assertFalse(plan['warnings'])

    def test_silence_before_short_reply_closes_part_before_reply_start(self):
        data = analysis(103)
        data['transcript'] = {'segments':[{'start':80,'end':103,'text':'Полная реплика.'}],
                              'words':[{'start':80+i,'end':81+i,'text':'слово'} for i in range(23)]}
        plan = build_plan(data)
        self.assertEqual([part['duration'] for part in plan['parts']], [51.5,51.5])
        self.assertFalse(plan['warnings'])

    def test_long_reply_starts_on_fresh_part_then_legitimately_splits(self):
        data = analysis(150)
        data['events'][0]['selected_ranges'] = [{'start':0,'end':20},{'start':40,'end':150}]
        data['transcript'] = {'segments':[{'start':40,'end':150,'text':'Длинная реплика.'}],
                              'words':[{'start':40+i,'end':42+i,'text':'слово'} for i in range(0,110,2)]}
        plan = build_plan(data)
        self.assertEqual([part['duration'] for part in plan['parts']], [20,54.18,56])
        self.assertTrue(plan['warnings'])

    def test_overlapping_short_reply_cannot_be_split_at_other_segment_end(self):
        data = analysis(120)
        data['transcript'] = {'segments':[{'start':0,'end':85,'text':'Первая.'},
                                         {'start':80,'end':120,'text':'Вторая.'}],
                              'words':[{'start':t,'end':t+1,'text':'слово'} for t in range(0,120)]}
        with self.assertRaisesRegex(ValueError, '90'):
            build_plan(data)

    def test_impossibly_long_word_is_rejected(self):
        data = analysis(110)
        data["transcript"]["words"] = [{"start": 0, "end": 110, "text": "слово"}]
        with self.assertRaisesRegex(ValueError, "90"):
            build_plan(data)

    def test_invalid_dependencies_and_nonfinite_timestamps(self):
        for mutation in [lambda d: d["events"][0].update(requires=["imaginary"]),
                         lambda d: d["events"][0].update(start=float("nan")),
                         lambda d: d["probe"].update(has_audio=False)]:
            data = analysis()
            mutation(data)
            with self.assertRaises(ValueError):
                build_plan(data)

    def test_changed_plan_cannot_repeat_or_invent_subtitles(self):
        data = analysis()
        for mutation in [lambda p: p["parts"][1]["cuts"][0].update(start=0),
                         lambda p: p["parts"][0]["subtitles"].append({"start": 0, "end": 1, "text": "выдумано"})]:
            plan = build_plan(data)
            mutation(plan)
            with self.assertRaises(ValueError):
                validate_plan(plan, data)
