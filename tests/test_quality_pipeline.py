"""Real run_job orchestration, fake analysis/provider/recovery/render boundaries.

These authored mechanisms do not exercise ASR, VLM, encoding or real video E2E.
"""
import copy
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app import final_quality, pipeline, quality_recovery
from app.config import ROOT
from app.music import DEFAULT_CONFIG
from tests.test_final_quality import fixture, make_plan


class NeverQueryProvider:
    """A session sentinel: quality orchestration must not query this object."""
    def query(self, *args, **kwargs):
        raise AssertionError('Mechanism test must not query a model')


class QualityPipelineTests(unittest.TestCase):
    def setUp(self):
        self.job = ROOT/'temp'/('quality-pipeline-mechanism-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        def cleanup():
            resolved = self.job.resolve()
            resolved.relative_to((ROOT/'temp').resolve())
            shutil.rmtree(resolved)
        self.addCleanup(cleanup)
        self.source = self.job/'source.mp4'
        self.source.write_bytes(b'authored mechanism placeholder, not encoded media')
        (self.job/'source.json').write_text(json.dumps({'path': str(self.source), 'name': 'mechanism.mp4'}), 'utf-8')
        self.trace, self.reports = [], []

    @staticmethod
    def unresolved_analysis():
        value, _ = fixture()
        event = value['events'][0]
        event.update(analysis_unresolved=True, analysis_unresolved_reasons=['story_structure_unresolved'])
        event['story_structure']['status'] = 'unresolved'
        event['story_structure']['units'][0]['status'] = 'unresolved'
        return value

    def run_with_stubs(self, analysis, recover):
        """Keep the real final gate, validators, cache loop, audit and run_job."""
        valid, _ = fixture()
        session_count = []
        self.active_model_sessions = 0
        @contextmanager
        def session(*args, **kwargs):
            session_count.append(kwargs)
            self.active_model_sessions += 1
            try:
                yield NeverQueryProvider()
            finally:
                self.active_model_sessions -= 1
        def analyze(*args, **kwargs):
            self.trace.append('analysis')
            return copy.deepcopy(analysis)
        def recovery(*args, **kwargs):
            self.trace.append('recovery')
            return recover(*args, **kwargs)
        def build(value):
            self.trace.append('builder')
            return make_plan(value, [[{'start': 0, 'end': 8}]])
        def render(source, part, probe, output_dir, workdir, encoder, cancelled, **kwargs):
            self.trace.append('renderer')
            self.assertEqual(probe, valid['probe'])
            self.assertFalse(cancelled())
            output = output_dir/f"part_{part['index']:03}.mp4"
            output.write_bytes(b'authored stub render output; not encoded video')
            output.with_suffix('.srt').write_text('authored stub subtitle export\n', 'utf-8')
            return output
        with ExitStack() as stack:
            self.builder = stack.enter_context(patch.object(pipeline, 'build_plan', side_effect=build))
            self.renderer = stack.enter_context(patch.object(pipeline, 'render_part', side_effect=render))
            stack.enter_context(patch.object(pipeline, 'prepare_clean_part',
                side_effect=lambda s, p, pr, *a: (s, p, pr, False)))
            self.recovery = stack.enter_context(patch.object(quality_recovery, 'recover_final_quality', side_effect=recovery))
            self.encoder = stack.enter_context(patch.object(pipeline, 'choose_encoder', return_value='authored_stub_encoder'))
            stack.enter_context(patch.object(pipeline, '_run_identity', return_value={'verification_kind': 'authored_pipeline_mechanism'}))
            stack.enter_context(patch.object(pipeline, 'setup_environment'))
            stack.enter_context(patch.object(pipeline, 'load_settings', return_value={**DEFAULT_CONFIG, 'enabled': False}))
            stack.enter_context(patch.object(pipeline, 'style_identity', return_value={'verification_kind': 'authored_style_identity'}))
            stack.enter_context(patch.object(pipeline, 'validate_export'))
            stack.enter_context(patch('app.analysis.analyze', side_effect=analyze))
            stack.enter_context(patch('app.analysis_provider.analysis_provider', return_value='authored_mechanism_provider'))
            stack.enter_context(patch('app.vision.vision_session', side_effect=session))
            stack.enter_context(patch('app.semantic_identity.semantic_identity', return_value={'verification_kind': 'authored_semantic_identity'}))
            stack.enter_context(patch('app.part_context.generate'))
            stack.enter_context(patch('app.editorial.load_profile', return_value={'dramatic_condensation': False}))
            try:
                return pipeline.run_job(self.job, lambda *r: self.reports.append(r), lambda: False)
            finally:
                self.sessions = session_count

    def test_unchanged_source_stops_before_render_without_repeating_same_cache(self):
        analysis = self.unresolved_analysis()
        with self.assertRaisesRegex(ValueError, 'analysis_unresolved: final_quality_gate'):
            self.run_with_stubs(analysis, lambda source, value, *args: copy.deepcopy(value))
        self.assertEqual(self.recovery.call_count, 1); self.assertEqual(len(self.sessions), 1)
        self.builder.assert_not_called(); self.renderer.assert_not_called(); self.encoder.assert_not_called()
        gate = json.loads((self.job/'final_quality_gate.json').read_text('utf-8'))
        self.assertEqual(gate['status'], 'unresolved')
        self.assertEqual([row['attempt'] for row in gate['history']], [0, 1])
        self.assertTrue(all(row['gate']['phase'] == 'before_planner' for row in gate['history']))
        self.assertFalse((self.job/'output').exists())
        self.assertEqual(json.loads((self.job/'timings.json').read_text('utf-8'))['status'], 'failed')

    def test_relation_metadata_churn_cannot_repeat_the_same_failed_source_check(self):
        analysis=self.unresolved_analysis()
        analysis['events'][0]['selection_uncertain']=True
        def recover(source,value,*args):
            changed=copy.deepcopy(value)
            changed['events'][0]['dialogue_relations']={'status':'unresolved','coverage':[]}
            return changed
        with self.assertRaisesRegex(ValueError,'повтор той|повтор того'):
            self.run_with_stubs(analysis,recover)
        self.assertEqual(self.recovery.call_count,1)
        self.assertEqual(len(self.sessions),1)
        self.renderer.assert_not_called()
        history=json.loads((self.job/'final_quality_gate.json').read_text('utf-8'))['history']
        self.assertNotEqual(history[0]['gate'],history[1]['gate'])
        self.assertEqual(history[0]['source_recovery_identity'],history[1]['source_recovery_identity'])

    def test_valid_recovered_analysis_resumes_building_and_rendering_after_gate(self):
        valid, _ = fixture()
        outputs = self.run_with_stubs(self.unresolved_analysis(), lambda *args: copy.deepcopy(valid))
        self.assertEqual(outputs, ['part_001.mp4', 'part_001.srt'])
        self.assertEqual(self.trace, ['analysis', 'recovery', 'builder', 'renderer'])
        self.assertEqual(self.recovery.call_count, 1); self.assertEqual(self.builder.call_count, 1)
        self.assertEqual(self.renderer.call_count, 1)
        gate = json.loads((self.job/'final_quality_gate.json').read_text('utf-8'))
        self.assertEqual([row['gate']['status'] for row in gate['history']], ['unresolved', 'passed'])
        self.assertTrue(gate['evidence_chain'])
        self.assertEqual(json.loads((self.job/'timings.json').read_text('utf-8'))['status'], 'completed')

    def test_cached_plan_old_passed_flag_does_not_bypass_current_endpoint_gate(self):
        valid, _ = fixture()
        self.run_with_stubs(valid, lambda *args: self.fail('Valid initial plan must not need recovery'))
        cached = json.loads((self.job/'plan.json').read_text('utf-8'))
        invalid = make_plan(valid, [[{'start': 0, 'end': 4}]])
        cached['parts'] = invalid['parts']
        cached['quality_gate']['status'] = 'passed'  # Stale cached audit is not authority.
        cached['parts'][0].update(layout='portrait', caption_style='classic')
        (self.job/'plan.json').write_text(json.dumps(cached, ensure_ascii=False), 'utf-8')
        for suffix in ('.mp4', '.srt'):
            output = self.job/'output'/('part_001'+suffix)
            output.resolve().relative_to(self.job.resolve())
            output.unlink()
        self.trace = []
        outputs = self.run_with_stubs(valid, lambda *args: copy.deepcopy(valid))
        self.assertEqual(outputs, ['part_001.mp4', 'part_001.srt'])
        self.assertEqual(self.trace, ['analysis', 'recovery', 'builder', 'renderer'])
        self.assertEqual(self.recovery.call_count, 1)
        self.assertEqual(self.builder.call_count, 1)  # Retry rebuild; initial attempt uses cached plan.
        gate = json.loads((self.job/'final_quality_gate.json').read_text('utf-8'))
        self.assertEqual(gate['history'][0]['gate']['phase'], 'before_render')
        self.assertIn('missing_required_dialogue_endpoint',
                      {p['code'] for p in gate['history'][0]['gate']['problems']})
        self.assertEqual(gate['history'][-1]['gate']['status'], 'passed')

    def test_role_failure_recovery_calls_its_owned_stage_before_finalizing(self):
        analysis,_=fixture()
        analysis['events'][0]['source_role_unresolved']={'category':'unresolved'}
        gate=final_quality.inspect_final_quality(analysis)
        provider=NeverQueryProvider()
        recovered=copy.deepcopy(analysis['events'])
        recovered[0].pop('source_role_unresolved')
        with patch('app.source_roles.refine_source_roles',return_value=recovered) as roles, \
             patch('app.editorial_pipeline.finalize_editorial_selection',return_value=recovered) as finalize, \
             patch('app.analysis_result.analysis_result',return_value=analysis), \
             patch('app.selection_adjudication.adjudicate_event') as adjudicate:
            quality_recovery.recover_final_quality(self.source,analysis,None,gate,self.job,provider,
                                               lambda *a:None,lambda:False)
        self.assertIs(roles.call_args.args[4],provider)
        self.assertEqual(roles.call_args.kwargs,{'retry_unresolved':True,'event_ids':{'e'},'episode_duration':analysis['probe']['duration']})
        finalize.assert_not_called()
        adjudicate.assert_not_called()

    def test_changed_window_framing_starts_after_recovery_model_session_closes(self):
        valid,_=fixture()
        def recover(*args):
            return {**copy.deepcopy(valid),'scoped_framing_pending_event_ids':['e']}
        def focus(source,analysis,events,event_ids,*args,**kwargs):
            self.assertEqual(self.active_model_sessions,0)
            self.assertEqual(event_ids,['e'])
            self.assertTrue(kwargs['allow_new_session'])
            return {'events':events,'pending_event_ids':[]}
        with patch('app.scoped_owner_refresh.finish_scoped_framing',side_effect=focus) as framing:
            outputs=self.run_with_stubs(self.unresolved_analysis(),recover)
        self.assertEqual(outputs,['part_001.mp4','part_001.srt'])
        self.assertEqual(framing.call_count,1)

    def test_pending_framing_on_resume_finishes_before_an_already_passed_gate(self):
        valid,_=fixture()
        valid['events'][0]['framing_refresh']={'status':'pending','provider':'local'}
        def focus(source,analysis,events,event_ids,*args,**kwargs):
            self.assertEqual(self.active_model_sessions,0)
            updated=copy.deepcopy(events)
            updated[0]['framing_refresh']['status']='complete'
            return {'events':updated,'pending_event_ids':[]}
        with patch('app.scoped_owner_refresh.finish_scoped_framing',side_effect=focus) as framing:
            outputs=self.run_with_stubs(valid,lambda *a:self.fail('No source recovery is needed'))
        self.assertEqual(outputs,['part_001.mp4','part_001.srt'])
        self.assertEqual(framing.call_count,1)
        self.assertEqual(framing.call_args.args[3],['e'])


if __name__ == '__main__':
    unittest.main()
