import unittest

from app.quality import debug_timeline, summarize_plan


class PlanQualityTests(unittest.TestCase):
    def plan(self):
        return {
            "warnings": [
                "event_0001: Сохранена атмосфера или фрагмент профилем монтажа",
                "event_0002: Проверьте неопределённый переход",
                "event_0003: Сокращение не подтверждено",
                "Общая проверка экспорта",
            ],
            "events": [
                {"id": "event_0001", "start": 0, "end": 20,
                 "selected_ranges": [{"start": 0, "end": 10}],
                 "protected_atmosphere_ranges": [{"start": 2, "end": 4}],
                 "protected_atmosphere_units": ["u1"], "story_warnings": []},
                {"id": "event_0002", "start": 20, "end": 30,
                 "selected_ranges": [{"start": 20, "end": 30}], "uncertain": True,
                 "story_warnings": []},
                {"id": "event_0003", "start": 30, "end": 40,
                 "selected_ranges": [], "story_warnings": []},
            ],
            "parts": [{"cuts": [
                {"start": 0, "end": 10, "event_ids": ["event_0001"]},
                {"start": 20, "end": 30, "event_ids": ["event_0002"]},
            ]}],
        }

    def test_stale_removed_event_warning_is_dropped_and_profile_note_is_separate(self):
        summary = summarize_plan(self.plan())
        self.assertTrue(summary["available"])
        self.assertEqual([row["category"] for row in summary["notes"]], ["profile"])
        self.assertNotIn("event_0003", [row.get("event_id") for row in summary["warnings"]])
        self.assertEqual([row["category"] for row in summary["warnings"]], ["uncertainty", "review"])

    def test_debug_only_contains_exact_kept_evidence(self):
        plan = self.plan()
        plan["events"][0]["manual_editorial_review"] = {
            "ranges": [{"start": 3, "end": 8}], "reason": "Подтверждено вручную <script>"
        }
        result = debug_timeline(plan)
        self.assertTrue(result["available"])
        self.assertEqual([(row["kind"], row["start"], row["end"]) for row in result["reasons"]], [
            ("uncertainty", 2, 4), ("manual", 3, 8), ("uncertainty", 20, 30),
        ])
        manual = next(row for row in result["reasons"] if row["kind"] == "manual")
        self.assertIn("<script>", manual["detail"])

    def test_story_and_reaction_require_matching_verified_decisions(self):
        plan = self.plan()
        event = plan["events"][0]
        event["story_omission_review"] = {
            "verified_units": [
                {"id": "u2", "start": 5, "end": 6},
                {"id": "u3", "start": 6, "end": 7},
                {"id": "u4", "start": 8, "end": 9},
            ],
            "decision": {"decisions": [
                {"unit": "u2", "current_episode_story": True, "story_change": True,
                 "reaction_or_humor": False, "confidence": .95, "evidence": "Действие"},
                {"unit": "u3", "current_episode_story": True, "reaction_or_humor": True,
                 "story_change": False, "confidence": .92, "evidence": "Реакция"},
                {"unit": "u4", "current_episode_story": True, "story_change": True,
                 "confidence": .6, "evidence": "Недостаточная уверенность"},
            ]},
        }
        rows = debug_timeline(plan)["reasons"]
        self.assertIn(("story", 5, 6), [(r["kind"], r["start"], r["end"]) for r in rows])
        self.assertIn(("reaction", 6, 7), [(r["kind"], r["start"], r["end"]) for r in rows])
        self.assertNotIn(("story", 8, 9), [(r["kind"], r["start"], r["end"]) for r in rows])

    def test_story_debug_rejects_truthy_strings_and_nonfinite_confidence(self):
        plan = self.plan()
        event = plan["events"][0]
        event["story_omission_review"] = {
            "verified_units": [{"id": "u2", "start": 5, "end": 6}],
            "decision": {"decisions": [{"unit": "u2", "current_episode_story": "yes",
                                           "story_change": True, "reaction_or_humor": False,
                                           "confidence": float("nan"), "evidence": "weak"}]},
        }
        self.assertNotIn("story", [row["kind"] for row in debug_timeline(plan)["reasons"]])

    def test_specific_reaction_and_removed_neutral_scenery_have_source_proof(self):
        plan = self.plan()
        event = plan['events'][0]
        event.pop('protected_atmosphere_ranges')
        event.pop('protected_atmosphere_units')
        event['units'] = [{'id':'reaction','start':4,'end':7}, {'id':'neutral','start':10,'end':15}]
        event['unit_evidence'] = [
            {'unit':'reaction','kind':'character_reaction','confidence':.95,'decision':'keep',
             'frame_indices':[1,2], 'speech_quote':'', 'evidence':'После реплики глаза девушки расширяются, затем появляются слёзы.'},
            {'unit':'neutral','kind':'neutral_scenery','confidence':.95,'decision':'drop',
             'frame_indices':[3,4], 'speech_quote':'', 'evidence':'Пустая комната остаётся неподвижной, персонажей и нового события нет.'}]
        rows = debug_timeline(plan)['reasons']
        self.assertIn(('character_reaction',4,7),[(r['kind'],r['start'],r['end']) for r in rows])
        neutral = next(r for r in rows if r['kind']=='neutral_scenery')
        self.assertFalse(neutral['retained'])
        self.assertEqual((neutral['start'],neutral['end']),(10,15))
        self.assertNotIn('Причина модели: атмосфера', [r['title'] for r in rows])

    def test_unit_warnings_are_filtered_by_exact_range_and_unknown_ids_are_retained(self):
        plan = {
            "warnings": ["event_0001: u001: removed-unit warning",
                         "event_0001: u002: kept-unit warning",
                         "event_0001: t003: no interval mapping"],
            "events": [{"id": "event_0001", "start": 0, "end": 10,
                        "selected_ranges": [{"start": 0, "end": 5}],
                        "diagnostic_unit_ranges": [
                            {"id": "u001", "start": 5, "end": 10},
                            {"id": "u002", "start": 1, "end": 2}],
                        "story_warnings": []}],
            "parts": [{"cuts": [{"start": 0, "end": 5, "event_ids": ["event_0001"]}]}],
        }
        result = summarize_plan(plan)["warnings"]
        self.assertEqual([row["unit_id"] for row in result], ["u002", "t003"])
        self.assertEqual(result[1]["category"], "uncertainty")
        self.assertIn("t003:", result[1]["text"])

    def test_missing_provenance_or_final_ranges_is_unavailable(self):
        self.assertEqual(debug_timeline({"parts": [{"cuts": []}], "events": []}),
                         {"available": False, "reasons": []})
        plan = self.plan()
        plan["parts"] = []
        self.assertFalse(summarize_plan(plan)["available"])

    def test_nonfinite_or_out_of_source_intervals_are_rejected(self):
        plan = self.plan()
        plan["source"] = {"duration": 25}
        self.assertFalse(debug_timeline(plan)["available"])
        plan = self.plan()
        plan["parts"][0]["cuts"][0]["end"] = float("inf")
        self.assertFalse(summarize_plan(plan)["available"])
        plan = self.plan()
        del plan["events"][0]["selected_ranges"]
        self.assertFalse(debug_timeline(plan)["available"])
        plan = self.plan()
        plan["parts"][0]["cuts"][0]["start"] = True
        self.assertFalse(summarize_plan(plan)["available"])


if __name__ == "__main__":
    unittest.main()
