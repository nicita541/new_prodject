import unittest

from app.dramatic_planner import (
    build_dramatic_plan,
    _compress_dialogue_turns,
    _event_dramatic_score
)
from app.planner import validate_plan, SPEECH_LEAD, SPEECH_TAIL


class DramaticPlannerTests(unittest.TestCase):
    def setUp(self):
        self.words = [
            {'start': 5.0, 'end': 6.0, 'text': 'Привет'},
            {'start': 6.2, 'end': 7.5, 'text': 'мир'},
            {'start': 12.0, 'end': 13.5, 'text': 'Как'},
            {'start': 13.6, 'end': 15.0, 'text': 'дела'},
            {'start': 22.0, 'end': 24.0, 'text': 'Конец'},
            {'start': 50.0, 'end': 52.0, 'text': 'Вторая'},
            {'start': 52.1, 'end': 54.0, 'text': 'сцена'},
            {'start': 60.0, 'end': 62.0, 'text': 'Опасность'},
            {'start': 90.0, 'end': 92.0, 'text': 'Финал'},
            {'start': 92.5, 'end': 94.0, 'text': 'серии'}
        ]
        self.segments = [
            {'start': 5.0, 'end': 7.5, 'text': 'Привет мир'},
            {'start': 12.0, 'end': 15.0, 'text': 'Как дела'},
            {'start': 22.0, 'end': 24.0, 'text': 'Конец'},
            {'start': 50.0, 'end': 54.0, 'text': 'Вторая сцена'},
            {'start': 60.0, 'end': 62.0, 'text': 'Опасность'},
            {'start': 90.0, 'end': 94.0, 'text': 'Финал серии'}
        ]
        self.shots = [
            {'start': 0.0}, {'start': 10.0}, {'start': 20.0},
            {'start': 45.0}, {'start': 58.0}, {'start': 85.0}
        ]

    def test_hook_trimming_eliminates_initial_dead_air(self):
        # Event starts at 0.0, but first dialogue is at 5.0
        event = {
            'id': 'e01', 'start': 0.0, 'end': 20.0, 'kind': 'story', 'importance': 4,
            'summary': 'Разговор', 'requires': [],
            'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]
        }
        turns = _compress_dialogue_turns(
            event, self.segments, self.words, [*self.segments, *self.words], duration=100.0
        )
        # First cut should start right before 5.0 (within speech lead 0.18s), not at 0.0
        first_cut = turns[0]
        self.assertGreater(first_cut['start'], 4.5)
        self.assertLessEqual(first_cut['start'], 5.0)

    def test_compress_dialogue_turns_trims_dead_silence_between_turns(self):
        # Between 7.5 and 12.0 is 4.5 seconds of dead silence
        event = {
            'id': 'e01', 'start': 0.0, 'end': 20.0, 'kind': 'story', 'importance': 4,
            'summary': 'Диалог с большой паузой', 'requires': [],
            'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]
        }
        turns = _compress_dialogue_turns(
            event, self.segments, self.words, [*self.segments, *self.words], duration=100.0
        )
        # Should have separated into multiple turns rather than keeping 4.5s of dead air
        self.assertGreaterEqual(len(turns), 2)
        turn1, turn2 = turns[0], turns[1]
        self.assertLessEqual(turn1['end'], 7.5 + SPEECH_TAIL + 0.01)
        self.assertGreaterEqual(turn2['start'], 12.0 - SPEECH_LEAD - 0.01)
        # Dead gap between turns is excluded
        self.assertGreater(turn2['start'] - turn1['end'], 1.0)

    def test_dramatic_plan_protects_narrative_bridges(self):
        # e02 is a silent narrative bridge connecting e01 to e03
        events = [
            {'id': 'e01', 'start': 0.0, 'end': 25.0, 'kind': 'story', 'importance': 4,
             'summary': 'Герои разговаривают.', 'requires': [],
             'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e02', 'start': 25.0, 'end': 35.0, 'kind': 'story', 'importance': 3,
             'summary': 'Героев связывают и увозят в машине.', 'requires': ['e01'],
             'narrative_bridge': True,
             'focus': [{'time': 25.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e03', 'start': 35.0, 'end': 65.0, 'kind': 'story', 'importance': 4,
             'summary': 'Герои уже связаны в плену.', 'requires': ['e02'],
             'focus': [{'time': 50.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]}
        ]
        analysis = {
            'probe': {'duration': 100.0, 'width': 1920, 'height': 1080, 'has_audio': True},
            'events': events,
            'transcript': {'words': self.words, 'segments': self.segments},
            'shots': self.shots
        }
        plan = build_dramatic_plan(analysis)
        validate_plan(plan, analysis)
        self.assertIn('e02', plan['selected_event_ids'])
        retained = {cid for p in plan['parts'] for c in p['cuts'] for cid in c['event_ids']}
        self.assertIn('e02', retained)

    def test_dramatic_plan_snaps_to_cliffhanger_ending(self):
        events = [
            {'id': 'e01', 'start': 0.0, 'end': 30.0, 'kind': 'story', 'importance': 4,
             'summary': 'Первая сцена', 'requires': [],
             'part_endings': [{
                 'time': 24.0 + SPEECH_TAIL,
                 'kind': 'cliffhanger',
                 'evidence': 'Неожиданный клиффхэнгер: выстрел!',
                 'confidence': 0.95
             }],
             'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e02', 'start': 45.0, 'end': 95.0, 'kind': 'story', 'importance': 4,
             'summary': 'Вторая сцена', 'requires': ['e01'],
             'part_endings': [{
                 'time': 94.0 + SPEECH_TAIL,
                 'kind': 'closure',
                 'evidence': 'Финал эпизода',
                 'confidence': 0.9
             }],
             'focus': [{'time': 50.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]}
        ]
        analysis = {
            'probe': {'duration': 100.0, 'width': 1920, 'height': 1080, 'has_audio': True},
            'events': events,
            'transcript': {'words': self.words, 'segments': self.segments},
            'shots': self.shots
        }
        plan = build_dramatic_plan(analysis)
        validate_plan(plan, analysis)
        # Check that part endings were recognized
        self.assertGreater(len(plan['parts']), 0)
        has_ending = any('ending' in p for p in plan['parts'])
        self.assertTrue(has_ending)

    def test_action_beat_continuity_preserved_in_dialogue_gap(self):
        # In a narrative bridge with dialogue (e.g. kidnapping scene),
        # action shots between dialogue turns should be retained rather than jumping 0.0s.
        event = {
            'id': 'e_kidnap', 'start': 0.0, 'end': 30.0, 'kind': 'story', 'importance': 4,
            'summary': 'Похищение на улице', 'requires': [],
            'narrative_bridge': True,
            'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]
        }
        # Dialogue: turn 1 (5.0 - 7.5s), turn 2 (22.0 - 24.0s). Gap is 14.5s.
        # Shots inside gap: ambush at 10.0-13.0s, ropes at 15.0-18.0s
        gap_shots = [
            {'start': 0.0, 'end': 8.0},
            {'start': 10.0, 'end': 13.0},
            {'start': 15.0, 'end': 18.0},
            {'start': 20.0, 'end': 30.0}
        ]
        turns = _compress_dialogue_turns(
            event, self.segments, self.words, [*self.segments, *self.words],
            duration=30.0, shots=gap_shots
        )
        # Should contain dialogue turns AND action beats in the gap
        self.assertGreaterEqual(len(turns), 3)
        # Verify an action beat falling within the 7.5-22.0s gap was retained
        has_mid_action = any(7.5 < t['start'] < 20.0 for t in turns)
        self.assertTrue(has_mid_action)

    def test_prerequisite_setup_pair_included(self):
        # e02 requires e01 (e.g. question "Мою форму?" -> answer "Нет, школьную")
        events = [
            {'id': 'e01', 'start': 0.0, 'end': 20.0, 'kind': 'story', 'importance': 3,
             'summary': 'Горничная приносит одежду в комнату.', 'requires': [],
             'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e02', 'start': 20.0, 'end': 60.0, 'kind': 'story', 'importance': 4,
             'summary': 'Разговор о школьной форме и поступлении.', 'requires': ['e01'],
             'focus': [{'time': 22.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]}
        ]
        analysis = {
            'probe': {'duration': 100.0, 'width': 1920, 'height': 1080, 'has_audio': True},
            'events': events,
            'transcript': {'words': self.words, 'segments': self.segments},
            'shots': self.shots
        }
        plan = build_dramatic_plan(analysis)
        validate_plan(plan, analysis)
        # Both e02 and its prerequisite e01 must be retained in the plan
        self.assertIn('e01', plan['selected_event_ids'])
        self.assertIn('e02', plan['selected_event_ids'])

    def test_contiguous_sequence_closure_fills_gaps(self):
        # e01 (intro), e02 (in-between context bridge), e03 (high dramatic climax)
        events = [
            {'id': 'e01', 'start': 0.0, 'end': 20.0, 'kind': 'story', 'importance': 4,
             'summary': 'Начало сцены', 'requires': [],
             'focus': [{'time': 5.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e02', 'start': 20.0, 'end': 40.0, 'kind': 'story', 'importance': 3,
             'summary': 'Связующий диалог / контекст', 'requires': [],
             'focus': [{'time': 22.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]},
            {'id': 'e03', 'start': 40.0, 'end': 70.0, 'kind': 'story', 'importance': 5,
             'summary': 'Кульминация сцены', 'requires': [],
             'part_endings': [{
                 'time': 62.0 + SPEECH_TAIL,
                 'kind': 'cliffhanger',
                 'evidence': 'Клиффхэнгер',
                 'confidence': 0.95
             }],
             'focus': [{'time': 50.0, 'x': 0.5, 'y': 0.5, 'confidence': 0.8}]}
        ]
        analysis = {
            'probe': {'duration': 100.0, 'width': 1920, 'height': 1080, 'has_audio': True},
            'events': events,
            'transcript': {'words': self.words, 'segments': self.segments},
            'shots': self.shots
        }
        plan = build_dramatic_plan(analysis)
        validate_plan(plan, analysis)
        # In-between story event e02 must not be omitted (no Swiss-cheese gap)
        self.assertIn('e02', plan['selected_event_ids'])


if __name__ == '__main__':
    unittest.main()
