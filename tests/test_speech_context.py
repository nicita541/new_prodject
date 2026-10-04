import copy
import unittest

from app.speech_context import protect_speech_context


def fixture(prefix="Не", start=932.37, prefix_end=932.89, next_start=943.7, next_end=946.12):
    transcript = {"segments": [{"start": start, "end": prefix_end, "text": prefix},
                               {"start": next_start, "end": next_end, "text": "хочу прекращать курить."}],
                  "words": [{"start": start, "end": prefix_end, "text": prefix},
                            {"start": next_start, "end": next_end, "text": "хочу прекращать курить."}],
                  "raw_segments": [{"start": start, "end": next_end, "text": prefix + " хочу прекращать курить."}]}
    events = [{"id": "source", "start": 930, "end": 950, "kind": "story", "importance": 4,
               "selected_ranges": [{"start": next_start - 0.25, "end": next_end + 0.3}],
               "requires": [], "summary": "Текст", "story_warnings": ["Существующее предупреждение"],
               "metadata": {"original": True}}]
    return events, transcript


class SpeechContextTests(unittest.TestCase):
    def test_negation_is_restored_without_inventing_gap_speech(self):
        events, transcript = fixture()
        original = copy.deepcopy(events)
        result = protect_speech_context(events, transcript)
        self.assertEqual(events, original)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 932.22, "end": 933.04}, {"start": 943.45, "end": 946.42}])
        self.assertEqual(result[0]["metadata"], {"original": True})
        self.assertEqual(result[0]["story_warnings"][0], "Существующее предупреждение")
        self.assertIn("Разрыв ASR 10.81", result[0]["story_warnings"][1])
        self.assertEqual(result[0]["speech_context_protections"][0]["start"], 932.37)

    def test_interrogative_prefix_same_raw_utterance_is_restored(self):
        events, transcript = fixture("Что", 1205.74, 1206.84, 1212.56, 1214.8)
        events[0].update(start=1200, end=1220)
        transcript["segments"][1]["text"] = "вы предпочитаете?"
        transcript["words"][1]["text"] = "вы предпочитаете?"
        transcript["raw_segments"][0]["text"] = "Что вы предпочитаете?"
        result = protect_speech_context(events, transcript)
        self.assertEqual(result[0]["selected_ranges"][0], {"start": 1205.59, "end": 1206.99})

    def test_raw_utterance_can_contain_another_followup_sentence(self):
        events, transcript = fixture("Что", 1205.74, 1206.84, 1212.56, 1213.82)
        events[0].update(start=1200, end=1220)
        transcript["segments"][1]["text"] = "с тем клиентом в итоге?"
        transcript["words"][1]["text"] = "с тем клиентом в итоге?"
        transcript["segments"].append({"start": 1214.02, "end": 1214.66, "text": "Разобрался?"})
        transcript["words"].append({"start": 1214.02, "end": 1214.66, "text": "Разобрался?"})
        transcript["raw_segments"][0].update(end=1214.66, text="Что с тем клиентом в итоге? Разобрался?")
        result = protect_speech_context(events, transcript)
        self.assertEqual(result[0]["selected_ranges"][0], {"start": 1205.59, "end": 1206.99})

    def test_different_raw_utterances_are_never_joined(self):
        events, transcript = fixture()
        transcript["raw_segments"] = [dict(transcript["segments"][0]), dict(transcript["segments"][1])]
        self.assertEqual(protect_speech_context(events, transcript), events)

    def test_distant_or_punctuated_prefix_is_not_attached(self):
        for mutation in (lambda t: t["segments"][1].update(start=950),
                         lambda t: t["segments"][0].update(text="Не."),
                         lambda t: t["segments"][0].update(text="Не!")):
            events, transcript = fixture()
            mutation(transcript)
            self.assertEqual(protect_speech_context(events, transcript), events)

    def test_raw_text_must_start_with_prefix_and_match_actual_continuation(self):
        for text in ["Он не хочу прекращать курить.", "Не хочу менять работу."]:
            events, transcript = fixture()
            transcript["raw_segments"][0]["text"] = text
            self.assertEqual(protect_speech_context(events, transcript), events)

    def test_prefix_in_different_event_is_retained_and_margin_clamped(self):
        events, transcript = fixture()
        events.insert(0, {"id": "prefix", "start": 932.3, "end": 933, "kind": "story", "importance": 1,
                          "requires": [], "selected_ranges": [{"start": 932.95, "end": 933}], "summary": "Контекст"})
        events[1]["start"] = 933
        result = protect_speech_context(events, transcript)
        self.assertEqual(result[0]["importance"], 4)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 932.3, "end": 933}])
        self.assertEqual(result[1]["selected_ranges"], events[1]["selected_ranges"])

    def test_prefix_at_event_start_and_end_stays_inside_source_event(self):
        events, transcript = fixture()
        events[0].update(start=932.37, end=946.12)
        events[0]["selected_ranges"] = [{"start": 943.7, "end": 946.12}]
        result = protect_speech_context(events, transcript)
        self.assertEqual(result[0]["selected_ranges"][0], {"start": 932.37, "end": 933.04})
        self.assertTrue(all(events[0]["start"] <= interval["start"] < interval["end"] <= events[0]["end"]
                            for interval in result[0]["selected_ranges"]))

    def test_existing_prefix_and_repeated_application_do_not_duplicate_intervals(self):
        events, transcript = fixture()
        first = protect_speech_context(events, transcript)
        self.assertEqual(protect_speech_context(first, transcript), first)

    def test_short_gap_overlapping_margin_merges_in_chronological_order(self):
        events, transcript = fixture(start=932.37, prefix_end=932.89, next_start=933.05, next_end=934)
        events[0]["selected_ranges"][0]["start"] = 933.0
        result = protect_speech_context(events, transcript)
        self.assertEqual(result[0]["selected_ranges"], [{"start": 932.22, "end": 934.3}])
        self.assertEqual(result[0]["story_warnings"], events[0]["story_warnings"])

    def test_without_raw_segments_is_a_safe_deep_copy_noop(self):
        events, transcript = fixture()
        transcript.pop("raw_segments")
        result = protect_speech_context(events, transcript)
        self.assertEqual(result, events)
        result[0]["metadata"]["original"] = False
        self.assertTrue(events[0]["metadata"]["original"])

    def test_unselected_continuation_does_not_restore_prefix(self):
        events, transcript = fixture()
        events[0]["selected_ranges"] = [{"start": 940, "end": 941}]
        self.assertEqual(protect_speech_context(events, transcript), events)
