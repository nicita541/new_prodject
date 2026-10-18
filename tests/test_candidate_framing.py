"""Final-candidate framing uses real native compiler fixtures and no inference."""
import copy
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from app import candidate_framing as framing
from app.content_identity import digest
from app.standalone_planner import build_standalone_candidates
from app.planner import validate_plan
from app.final_quality import inspect_final_quality
from tests.test_standalone_planner import source_fixture


class Journal:
    def __init__(self):
        self.saved = {}
    def load(self, name, inputs):
        return copy.deepcopy(self.saved.get((name, digest(inputs))))
    def save(self, name, inputs, output, producer):
        self.saved[name, digest(inputs)] = copy.deepcopy(output)


class CandidateFramingTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / '.test-temp'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'authored source identity; no decoding')
        self.analysis = source_fixture(groups=2)
        self.compiled = build_standalone_candidates(self.analysis)
        self.assertEqual(2, len(self.compiled['candidates']))
        self.journal = Journal()
        self.report = Mock()
        self.factory = Mock()
        self.refine = Mock(side_effect=self.focus)
        self.patches = [patch.object(framing, 'vision_session', self.factory),
                        patch.object(framing, 'refine_focus', self.refine)]
        for context in self.patches:
            context.start()
            self.addCleanup(context.stop)

    def focus(self, source, probe, transcript, shots, events, directory, vision, report, cancelled):
        result = copy.deepcopy(events)
        for event in result:
            event['focus'] = [{'time': r['start'], 'x': .25, 'y': .5, 'confidence': .9}
                              for r in event['selected_ranges']]
            event['focus_warnings'] = []
        return result

    def run_framing(self, compiled=None, **kwargs):
        return framing.frame_final_candidates(self.source, compiled or self.compiled, self.root,
            'deepseek_plan', self.report, kwargs.pop('cancelled', lambda: False), journal=self.journal,
            layout=kwargs.pop('layout', 'portrait'), **kwargs)

    def test_only_final_cuts_with_no_canonical_mutation(self):
        before = copy.deepcopy(self.compiled)
        result = self.run_framing()
        self.assertEqual(before, self.compiled)
        self.assertEqual(2, self.refine.call_count)
        self.assertEqual(2, self.factory.call_count)
        for call, candidate, updated in zip(self.refine.call_args_list, before['candidates'], result['candidates']):
            events = call.args[4]
            cuts = candidate['plan']['parts'][0]['cuts']
            for event in events:
                for selection in event['selected_ranges']:
                    self.assertTrue(any(c['start'] <= selection['start'] < selection['end'] <= c['end'] for c in cuts))
            self.assertEqual([e['selected_ranges'] for e in candidate['scoped_analysis']['events']],
                             [e['selected_ranges'] for e in updated['scoped_analysis']['events']])
            self.assertEqual(.25, updated['plan']['parts'][0]['cuts'][0]['focus'][0]['x'])
            self.assertEqual(self.root / 'candidate-framing' / candidate['id'], call.args[5])
            validate_plan(updated['plan'], updated['scoped_analysis'])
            self.assertEqual('passed', inspect_final_quality(updated['scoped_analysis'], updated['plan'])['status'])
        for saved in self.journal.saved.values():
            self.assertEqual({'events'}, set(saved))
            for event in saved['events']:
                self.assertEqual({'id', 'focus', 'focus_warnings'}, set(event))

    def test_warm_cache_opens_no_sessions_and_preserves_current_captions_and_rank(self):
        self.run_framing()
        self.factory.reset_mock()
        self.refine.reset_mock()
        styled = copy.deepcopy(self.compiled)
        styled['candidates'].reverse()
        for candidate in styled['candidates']:
            candidate['rank'] = 42
            candidate['plan']['parts'][0].update(index=42, caption_style='current-style',
                subtitles=[{'start': 0, 'end': 1, 'text': 'CURRENT CAPTION'}])
        result = self.run_framing(styled)
        self.factory.assert_not_called()
        self.refine.assert_not_called()
        for candidate in result['candidates']:
            part = candidate['plan']['parts'][0]
            self.assertEqual(42, part['index'])
            self.assertEqual('current-style', part['caption_style'])
            self.assertEqual('CURRENT CAPTION', part['subtitles'][0]['text'])
            self.assertEqual(.25, part['cuts'][0]['focus'][0]['x'])

    def test_cinema_empty_and_plan_only_do_not_infer(self):
        self.assertEqual(self.compiled, self.run_framing(layout='cinema'))
        self.assertEqual({'candidates': []}, self.run_framing({'candidates': []}))
        result = self.run_framing(allow_new_session=False)
        self.factory.assert_not_called()
        self.refine.assert_not_called()
        self.assertTrue(all(c['plan']['parts'][0]['layout'] == 'cinema' for c in result['candidates']))
        self.assertFalse(self.journal.saved)

    def test_warning_or_unknown_focus_preserves_full_frame(self):
        def uncertain(*args):
            events = self.focus(*args)
            for event in events:
                event['focus_warnings'] = ['speaker not confirmed']
                for anchor in event['focus']:
                    anchor['confidence'] = 0
            return events
        self.refine.side_effect = uncertain
        result = self.run_framing()
        for candidate in result['candidates']:
            self.assertEqual('cinema', candidate['plan']['parts'][0]['layout'])
            self.assertIn('framing_fallback', candidate['plan']['parts'][0])
            self.assertTrue(candidate['plan']['warnings'])

    def test_cancellation_propagates_and_does_not_save(self):
        self.refine.side_effect = InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            self.run_framing()
        self.assertFalse(self.journal.saved)
        self.refine.reset_mock()
        with self.assertRaises(InterruptedError):
            self.run_framing(cancelled=lambda: True)
        self.refine.assert_not_called()

    def test_source_or_native_proof_change_invalidates_focus(self):
        self.run_framing()
        self.refine.reset_mock()
        self.source.write_bytes(b'changed source bytes')
        self.run_framing()
        self.assertEqual(2, self.refine.call_count)
        self.refine.reset_mock()
        changed = copy.deepcopy(self.compiled)
        changed['candidates'][0]['scoped_analysis']['events'][0]['summary'] += ' updated proof'
        self.run_framing(changed)
        self.assertEqual(1, self.refine.call_count)

    def test_focus_rebuild_cannot_change_geometry(self):
        from app.standalone_planner import _plan
        def changed_geometry(*args):
            plan = _plan(*args)
            plan['parts'][0]['cuts'][0]['end'] -= .1
            return plan
        with patch.object(framing, '_plan', side_effect=changed_geometry):
            with self.assertRaisesRegex(ValueError, 'geometry'):
                self.run_framing()

    def test_one_local_runtime_owner_across_cold_candidates(self):
        starts, closes = [], []
        class FakeVision:
            def __enter__(self):
                starts.append(True)
                return self
            def __exit__(self, *args):
                closes.append(True)
            def query(self):
                return None
        self.factory.return_value = FakeVision()
        def focus_with_query(*args):
            args[6].query()
            return self.focus(*args)
        self.refine.side_effect = focus_with_query
        self.run_framing()
        self.assertEqual([True], starts)
        self.assertEqual([True], closes)
        self.assertEqual(1, self.factory.call_count)


if __name__ == '__main__':
    unittest.main()
