import unittest
from unittest.mock import Mock

from app.story_review import apply_global_selection, validate_global_omissions
from app.pacing import apply_review, condense_beat


class NarrativeBridgeTests(unittest.TestCase):
    def test_narrative_bridge_event_immune_to_global_omission(self):
        # Event connecting State A to State B without speech (e.g. capture/transition)
        events = [
            {'id': 'e01', 'start': 0.0, 'end': 10.0, 'kind': 'story', 'importance': 4,
             'summary': 'Диалог персонажей перед похищением.'},
            {'id': 'e02', 'start': 10.0, 'end': 15.0, 'kind': 'story', 'importance': 3,
             'summary': 'Безречевой переход: героев связывают веревками и бросают в фургон.',
             'narrative_bridge': True},
            {'id': 'e03', 'start': 15.0, 'end': 25.0, 'kind': 'story', 'importance': 4,
             'summary': 'Герои уже связаны внутри движущегося фургона.'},
        ]
        # LLM proposes to omit e02 under 'nonstory' because there was no dialogue
        decisions = {
            'keep': ['e01', 'e03'],
            'omit': [{
                'event': 'e02',
                'reason': 'nonstory',
                'evidence': 'Сцена без диалогов, только связывают и грузят.',
                'confidence': 0.95,
                'reaction_or_humor': False,
            }],
            'dependencies': [{'event': 'e03', 'requires': ['e01']}],
            'summary': 'Похищение героев',
        }
        
        apply_global_selection(events, decisions)
        
        # e02 MUST NOT be globally excluded because it is a narrative bridge!
        self.assertFalse(events[1].get('global_excluded', False),
                         "Narrative bridge event was incorrectly excluded!")

    def test_condense_beat_splits_long_silent_action_into_head_and_tail(self):
        # Long hold (4.5s) of silent action/transition
        unit = {'id': 's001', 'start': 10.0, 'end': 14.5}
        beats = condense_beat(unit, max_hold=1.5)
        self.assertEqual(len(beats), 2)
        # Head beat starts at 10.0
        self.assertEqual(beats[0]['start'], 10.0)
        self.assertLessEqual(beats[0]['end'] - beats[0]['start'], 1.6)
        # Tail beat ends at 14.5
        self.assertEqual(beats[1]['end'], 14.5)
        self.assertLessEqual(beats[1]['end'] - beats[1]['start'], 1.6)
        # Middle hold is excised
        self.assertLess(beats[0]['end'], beats[1]['start'])

    def test_condense_beat_preserves_short_action(self):
        # Short action unit (2.5s) should not be split
        unit = {'id': 's002', 'start': 5.0, 'end': 7.5}
        beats = condense_beat(unit)
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0], {'start': 5.0, 'end': 7.5})

    def test_pacing_apply_review_protects_narrative_bridge_and_applies_condensation(self):
        # Event with a 4.0s silent transition unit
        event = {
            'id': 'e01', 'start': 0.0, 'end': 10.0,
            'selected_ranges': [{'start': 0.0, 'end': 10.0}],
        }
        units = [{'id': 'A', 'start': 2.0, 'end': 6.0}]
        
        # Reviewer identifies unit A as a narrative_bridge with condense=True
        raw = {
            'uncertain': False,
            'decisions': [{
                'unit': 'A',
                'keep': True,
                'reason': 'narrative_bridge',
                'story_change': True,
                'reaction_or_humor': False,
                'condense': True,
                'evidence': 'Героя хватают и связывают верёвкой; без этого переход не понятен.',
            }]
        }
        
        apply_review(event, units, raw)
        
        # Unit was not excluded as pacing_removed
        self.assertEqual(event.get('pacing_removed', []), [])
        # But the 4.0s hold was condensed: ranges now contain initiation and completion beats
        ranges = event['selected_ranges']
        self.assertTrue(len(ranges) >= 2, f"Expected condensed ranges, got {ranges}")
        # Range should preserve context before (0-2), start beat of action (~2.0-3.4), end beat (~4.6-6.0), context after (6-10)
        total_duration = sum(r['end'] - r['start'] for r in ranges)
        self.assertLess(total_duration, 10.0, "Middle static hold was not condensed!")
        self.assertTrue(len(event.get('condensed_beats', [])) > 0)


if __name__ == '__main__':
    unittest.main()
