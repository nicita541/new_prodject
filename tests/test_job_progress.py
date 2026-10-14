"""Presentation mechanism tests; no worker/model/media encoding is invoked."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app import config, job_progress
from scripts import publish_job_progress as publisher


class JobProgressTests(unittest.TestCase):
    def test_quota_wait_preserves_completed_passes_and_the_actual_counter(self):
        self.lines('timeline.jsonl',[
            {'run_id':'current','stage':stage,'action':action}
            for stage in ('visual_analysis','story_refinement','titles') for action in ('start','end')]+[
            {'run_id':'current','stage':'selection_adjudication','action':'start'}])
        job={**self.job,'stage':'analyze','message':'Лимит Antigravity; автоматически продолжим позже',
            'provider_wait':{'reason':'quota','previous_message':'Проверка конкретного выбора · обработано событий: 50 из 129'}}
        rows=job_progress.analysis_passes(job,self.directory)
        self.assertEqual(rows['titles']['status'],'completed')
        self.assertEqual(rows['selection_adjudication']['status'],'waiting_analysis')
        self.assertEqual(rows['selection_adjudication']['completed'],50)
        self.assertEqual(rows['selection_adjudication']['total'],129)
        cancelled=job_progress.analysis_passes({**job,'status':'cancelled'},self.directory)
        self.assertEqual(cancelled['selection_adjudication']['status'],'cancelled')

    def test_independent_batch_messages_show_their_own_pass_and_counter(self):
        for step,label in [('titles','Поиск титров'),
                           ('closing_novelty','Проверка новых событий в финале'),
                           ('source_roles','Проверяем сюжетную речь'),
                           ('endings','Проверка концовок')]:
            with self.subTest(step=step):
                noun='окон' if step=='endings' else 'событий'
                rows=job_progress.analysis_passes({**self.job,'stage':'condense',
                    'message':f'{label} · обработано {noun}: 3 из 12'},self.directory)
                self.assertEqual(rows[step]['status'],'running')
                self.assertEqual(rows[step]['completed'],3)
                self.assertEqual(rows[step]['total'],12)
                self.assertEqual(rows[step]['fraction'],.25)

    def test_legacy_waiting_stage_preserves_finished_stages_from_current_run(self):
        self.lines('timeline.jsonl', [
            {'run_id':'current','stage':step,'action':action}
            for step in ('prepare','transcribe','scenes') for action in ('start','end')]+[
            {'run_id':'current','stage':'analyze','action':'start'},
            {'run_id':'current','stage':'analyze','action':'exception','error_type':'AnalysisPending'},
            {'run_id':'current','stage':'analyze','action':'end'}])
        rows=self.result(status='waiting_analysis',stage='waiting_analysis')
        for step in ('prepare','transcribe','scenes'):
            self.assertEqual(rows[step],{'status':'completed','fraction':1.0})
        self.assertEqual(rows['analyze']['status'],'waiting_analysis')
        self.assertIsNone(rows['analyze']['fraction'])
        self.assertEqual(rows['render']['status'],'pending')

    def test_preserved_waiting_milestone_and_previous_runs_do_not_fake_completion(self):
        self.lines('timeline.jsonl',[
            {'run_id':'old','stage':'render','action':'start'},
            {'run_id':'current','stage':'prepare','action':'start'},
            {'run_id':'current','stage':'prepare','action':'end'},
            {'run_id':'current','stage':'transcribe','action':'start'}])
        rows=self.result(status='waiting_analysis',stage='waiting_analysis',waiting_stage='transcribe')
        self.assertEqual(rows['prepare']['status'],'completed')
        self.assertEqual(rows['transcribe']['status'],'waiting_analysis')
        self.assertEqual(rows['scenes']['status'],'pending')

    def test_failed_gate_does_not_show_rejected_passes_as_completed(self):
        self.lines('timeline.jsonl', [{'stage': step, 'action': action, 'run_id': 'current'}
                   for step in ('story_structure_analysis', 'dialogue_relations') for action in ('start', 'end')])
        self.write(self.directory/'story_structure-result.json', {'status': 'unresolved', 'unresolved_refs': [{'event': 'e', 'unit': 'u'}]})
        self.write(self.directory/'dialogue_relations-result.json', {'status': 'accepted', 'unresolved_refs': []})
        rows = job_progress.analysis_passes({**self.job, 'status': 'failed', 'stage': 'analyze'}, self.directory)
        self.assertEqual(rows['story_structure_analysis']['status'], 'failed')
        self.assertEqual(rows['story_structure_analysis']['unresolved'], 1)
        self.assertEqual(rows['dialogue_relations']['status'], 'completed')

    def setUp(self):
        config.TEMP.mkdir(exist_ok=True)
        # Normal mkdir preserves the workspace's Windows ACLs; mkdtemp's
        # private 0700 ACL is inaccessible to this managed test process.
        self.root = config.TEMP / ('job_progress_' + uuid.uuid4().hex)
        self.root.mkdir()
        self.job_id = str(uuid.uuid4())
        self.directory = self.root / 'data' / 'jobs' / self.job_id
        self.directory.mkdir(parents=True)
        self.audit = self.directory / 'diagnostics' / 'pipeline'
        self.job = {'id':self.job_id, 'status':'running', 'stage':'scenes', 'progress':.99,
                    'updated_at':'2026-10-08T23:05:31.454746+07:00'}
        self.write(self.audit / 'run.json', {'run_id':'current'})

    def tearDown(self):
        job_progress._json_file.cache_clear()
        job_progress._json_lines.cache_clear()
        job_progress._feature_map_size.cache_clear()
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def lines(self, name, rows, tail=''):
        path = self.audit / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows) + tail, encoding='utf-8')

    def result(self, **changes):
        return job_progress.stage_progress({**self.job, **changes}, self.directory)

    def decisions(self):
        self.write(self.directory / 'scene-features.json', {str(i):{} for i in range(5)})
        self.lines('boundary_decisions.jsonl', [
            {'run_id':'old','source_time':.5,'decision':{}},
            {'run_id':'current','source_time':1.,'decision':{}},
            {'run_id':'current','source_time':1.,'decision':{'accepted':False}},
            {'run_id':'current','source_time':2.,'decision':{}},
            {'run_id':'current','source_time':3.,'decision':None},
            {'run_id':'current','source_time':True,'decision':{}},
            {'run_id':'current','source_time':float('nan'),'decision':{}},
            {'run_id':'current','source_time':float('inf'),'decision':{}},
            {'run_id':'current','source_time':-1.,'decision':{}},
            ['wrong type']], '{"run_id":"current",')

    def render_fixture(self):
        self.write(self.directory / 'plan.json', {'fingerprint':'current-plan','parts':[{'index':1},{'index':2}]})
        media = self.directory / 'output' / 'part_001.mp4'
        media.parent.mkdir()
        media.write_bytes(b'explicitly fake exported media for checkpoint mechanism')
        subtitle = media.with_suffix('.srt')
        subtitle.write_bytes(b'source subtitle')
        stat = media.stat()
        checkpoint = {'fingerprint':'current-plan','size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
                      'srt_hash':hashlib.sha256(subtitle.read_bytes()).hexdigest()}
        self.write(self.directory / 'render' / 'part_001.json', checkpoint)
        (media.parent / 'part_002.mp4').write_bytes(b'partial output must not count')
        return media, checkpoint

    def test_analysis_passes_show_each_completed_and_active_pass(self):
        self.lines('timeline.jsonl', [
            {'run_id':'old','stage':'dialogue_relations','action':'end'},
            {'run_id':'current','stage':'story_refinement','action':'start'},
            {'run_id':'current','stage':'story_refinement','action':'end'},
            {'run_id':'current','stage':'global_visual_verification','action':'start'},
            {'run_id':'current','stage':'global_visual_verification','action':'end'},
            {'run_id':'current','stage':'selection_adjudication','action':'start'}])
        job = {**self.job, 'stage':'analyze', 'message':'Проверка конкретного выбора · обработано событий: 4 из 9'}
        rows = job_progress.analysis_passes(job, self.directory)
        self.assertEqual(rows['global_visual_verification']['status'], 'completed')
        self.assertEqual(rows['titles']['status'], 'completed')
        self.assertEqual(rows['selection_adjudication']['completed'], 4)
        self.assertAlmostEqual(rows['selection_adjudication']['fraction'], 4/9)
        self.assertEqual(rows['dialogue_relations']['status'], 'pending')

    def test_analysis_passes_do_not_transfer_previous_counter_or_hide_failure(self):
        self.lines('timeline.jsonl', [
            {'run_id':'current','stage':'selection_adjudication','action':'end'},
            {'run_id':'current','stage':'global_story','action':'start'},
            {'run_id':'current','stage':'global_story','action':'exception','error_type':'AnalysisPending'},
            {'run_id':'current','stage':'global_story','action':'end'}])
        job = {**self.job, 'stage':'analyze', 'status':'waiting_analysis',
            'message':'Проверка конкретного выбора · обработано событий: 129 из 129'}
        rows = job_progress.analysis_passes(job, self.directory)
        self.assertEqual(rows['global_story']['status'], 'waiting_analysis')
        self.assertIsNone(rows['global_story']['fraction'])
        self.assertNotIn('completed', rows['global_story'])

    def test_analysis_passes_conditional_end_review_skipped_not_success(self):
        self.lines('timeline.jsonl', [
            {'run_id':'current','stage':'endings','action':'start'},
            {'run_id':'current','stage':'endings','action':'end'},
            {'run_id':'current','stage':'story_structure_analysis','action':'start'}])
        rows = job_progress.analysis_passes({**self.job,'stage':'analyze'}, self.directory)
        self.assertEqual(rows['ending_selection_adjudication']['status'], 'not_required')
        self.assertEqual(rows['endings']['status'], 'completed')
        self.assertEqual(rows['story_structure_analysis']['status'], 'running')

    def test_text_pass_counters_belong_only_to_current_pass(self):
        for step, caption in (('story_structure_analysis','Сюжетные связи'), ('dialogue_relations','Связи реплик')):
            with self.subTest(step=step):
                self.lines('timeline.jsonl', [{'run_id':'current','stage':step,'action':'start'}])
                job={**self.job,'stage':'analyze','message':f'{caption} · обработано фрагментов: 4 из 9'}
                rows=job_progress.analysis_passes(job,self.directory)
                self.assertEqual((rows[step]['completed'],rows[step]['total']), (4,9))
                self.assertAlmostEqual(rows[step]['fraction'],4/9)
                other=job_progress.analysis_passes({**job,'message':'Темп · обработано фрагментов: 129 из 129'},self.directory)
                self.assertNotIn('completed',other[step])

    def test_current_run_unique_boundary_decisions_not_model_acceptance(self):
        self.decisions()
        row = self.result()['scenes']
        self.assertEqual((row['completed'],row['total'],row['fraction']), (2,4,.5))
        self.assertEqual(row['status'],'running')

    def test_global_before_item_and_batch_completed_counters_are_distinct(self):
        before=self.result(stage='global_verify',message='Независимая визуальная проверка 7 из 129')['analyze']
        self.assertEqual((before['completed'],before['total']),(6,129))
        batch=self.result(stage='global_verify',message='Независимая проверка · обработано событий: 7 из 129')['analyze']
        self.assertEqual((batch['completed'],batch['total']),(7,129))
        completed=self.result(stage='global_verify',message='Независимая проверка · обработано событий: 129 из 129')['analyze']
        self.assertEqual(completed['fraction'],1)

    def test_asr_source_fraction_is_bound_to_current_run_and_probe(self):
        self.job['stage'] = 'transcribe'
        self.write(self.directory/'probe.json', {'duration':120})
        progress = {'run_id':'current', 'duration':120, 'fraction':.35, 'phase':'decode'}
        self.write(self.directory/'asr-progress.json', progress)
        self.assertEqual(self.result()['transcribe']['fraction'], .35)
        for updates in ({'run_id':'old'}, {'duration':60}, {'fraction':float('nan')}, {'fraction':True}):
            self.write(self.directory/'asr-progress.json', {**progress, **updates})
            self.assertIsNone(self.result()['transcribe']['fraction'])

    def test_large_feature_map_counts_streamed_intervals_without_full_json_cache(self):
        features={str(i):{'embedding':[.42]*18000,'description':'escaped quote "+ brace }'} for i in range(5)}
        self.write(self.directory/'scene-features.json',features)
        with patch.object(job_progress,'MAX_FILE_BYTES',100):
            self.assertEqual(self.result()['scenes']['total'],4)
        path=str(self.directory/'scene-features.json')
        with patch.object(job_progress,'_json_file',side_effect=AssertionError('feature embeddings must not be cached')):
            self.assertEqual(job_progress._feature_count(Path(path)),5)
        self.assertEqual(job_progress._feature_map_size.cache_info().maxsize,32)

    def test_malformed_feature_map_or_duplicate_keys_has_no_invented_total(self):
        path=self.directory/'scene-features.json'
        for raw in ('{"a":{},"a":{}}','{"a":{},"b":[]}','{"a":{},"b":','{"a":{}} trailing',
                    '{"a":{},}', '{"a":{},"b":true}'):
            with self.subTest(raw=raw):
                path.write_text(raw,encoding='utf-8')
                self.assertIsNone(self.result()['scenes']['fraction'])

    def test_failed_cancelled_interrupted_preserve_real_partial_counter(self):
        self.decisions()
        for status in ('failed','cancelled','interrupted'):
            with self.subTest(status=status):
                row = self.result(status=status)['scenes']
                self.assertEqual(row['status'],status)
                self.assertEqual((row['completed'],row['total']), (2,4))

    def test_missing_corrupt_run_does_not_reuse_named_old_decisions(self):
        self.decisions()
        for invalid in ([],{'run_id':[]},None):
            with self.subTest(invalid=invalid):
                self.write(self.audit / 'run.json',invalid)
                self.assertEqual(self.result()['scenes']['completed'],0)

    def test_missing_counter_is_indeterminate_not_overall_percentage(self):
        row = self.result()['scenes']
        self.assertIsNone(row['fraction'])
        self.assertNotIn('total',row)
        self.assertEqual(self.result(stage='quality_gate')['plan']['status'],'running')

    def test_timeline_reentered_stage_invalidates_downstream_old_completion(self):
        rows = [{'run_id':'current','stage':step,'action':'end'} for step in ('prepare','transcribe','scenes','analyze','condense')]
        rows.append({'run_id':'current','stage':'analyze','action':'start'})
        self.lines('timeline.jsonl',rows)
        result=self.result(stage='analyze')
        self.assertEqual(result['scenes']['status'],'completed')
        self.assertEqual(result['analyze']['status'],'running')
        self.assertEqual(result['condense']['status'],'pending')

    def test_timeline_exception_finally_end_does_not_assert_completion(self):
        self.lines('timeline.jsonl',[
            {'run_id':'old','stage':'condense','action':'end'},
            {'run_id':'current','stage':'analyze','action':'start'},
            {'run_id':'current','stage':'analyze','action':'exception'},
            {'run_id':'current','stage':'analyze','action':'end'}])
        self.assertEqual(self.result(stage='framing')['analyze']['status'],'pending')
        self.assertEqual(self.result(stage='framing')['condense']['status'],'pending')

    def test_item_report_is_before_work_and_free_text_is_not_published(self):
        for stage,message in [('analyze','private-source: Смысловая сцена 3 из 10'),
                              ('condense','Проверяем темп и титры: сцена 3 из 10'),
                              ('framing','Кадрирование: сцена 3 из 10')]:
            with self.subTest(stage=stage):
                row=self.result(stage=stage,message=message)[stage]
                self.assertEqual((row['completed'],row['total'],row['fraction']),(2,10,.2))
                self.assertNotIn('private-source',json.dumps(row))

    def test_render_requires_actual_path_fingerprint_stat_and_subtitle_hash(self):
        media,checkpoint=self.render_fixture()
        row=self.result(stage='rendering')['render']
        self.assertEqual((row['completed'],row['total'],row['fraction']),(1,2,.5))
        for field,value in [('fingerprint','old-plan'),('size',checkpoint['size']+1),
                            ('mtime_ns',checkpoint['mtime_ns']-1),('srt_hash','stale')]:
            with self.subTest(field=field):
                self.write(self.directory/'render'/'part_001.json',{**checkpoint,field:value})
                self.assertEqual(self.result(stage='rendering')['render']['completed'],0)
        self.write(self.directory/'render'/'part_001.json',checkpoint)
        media.with_suffix('.srt').write_bytes(b'changed subtitle')
        self.assertEqual(self.result(stage='rendering')['render']['completed'],0)

    def test_wrong_work_path_or_mp4_without_commit_never_counts(self):
        _,checkpoint=self.render_fixture()
        (self.directory/'render'/'part_001.json').unlink()
        self.write(self.directory/'work'/'part_001.json',checkpoint)
        self.assertEqual(self.result(stage='rendering')['render']['completed'],0)

    def test_malformed_types_partial_json_and_unknown_stages_are_tolerated(self):
        self.write(self.audit/'run.json',[])
        self.write(self.directory/'scene-features.json',[])
        self.lines('timeline.jsonl',[[],None,{'stage':[],'action':'end'}],'{"partial":')
        self.assertIsNone(self.result(message=[])['scenes']['fraction'])
        for stage in (None,[],{},'unknown'):
            self.assertTrue(all(row['status']=='pending' for row in self.result(stage=stage).values()))
        self.write(self.directory/'plan.json',[])
        self.assertIsNone(self.result(stage='render')['render']['fraction'])
        self.write(self.directory/'plan.json',{'fingerprint':'x','parts':[{'index':1},{'index':1}]})
        self.assertIsNone(self.result(stage='render')['render']['fraction'])

    def test_queued_and_completed_are_explicit_and_projection_does_not_mutate(self):
        original=copy.deepcopy(self.job)
        self.assertTrue(all(row['status']=='pending' for row in self.result(status='queued').values()))
        self.assertTrue(all(row=={'status':'completed','fraction':1.} for row in self.result(status='completed').values()))
        self.result()
        self.assertEqual(self.job,original)

    def test_cache_retains_only_two_large_file_versions(self):
        for index in range(4):
            self.write(self.audit/'timeline.jsonl',{'n':index})
            job_progress._lines(self.audit/'timeline.jsonl')
            self.write(self.directory/'scene-features.json',{'n':index})
            job_progress._read(self.directory/'scene-features.json')
        self.assertEqual(job_progress._json_lines.cache_info().maxsize,2)
        self.assertLessEqual(job_progress._json_lines.cache_info().currsize,2)
        self.assertEqual(job_progress._json_file.cache_info().maxsize,2)
        self.assertLessEqual(job_progress._json_file.cache_info().currsize,2)

    def test_publisher_atomic_whitelisted_snapshot_preserves_job_and_diagnostics(self):
        self.decisions()
        job={**self.job,'status':'failed','source_path':'private/path','error':'private error',
             'message':'secret arbitrary text','api_key':'do-not-publish'}
        self.write(self.directory/'job.json',job)
        paths=list(self.directory.rglob('*'))
        before={p:p.read_bytes() for p in paths if p.is_file()}
        snapshot=publisher.publish_once(self.job_id,root=self.root)
        self.assertEqual(set(snapshot),{'version','job_id','status','stage','updated_at','job_updated_at','stage_progress'})
        self.assertEqual(snapshot['job_updated_at'],job['updated_at'])
        self.assertEqual(snapshot['stage_progress']['scenes']['completed'],2)
        encoded=json.dumps(snapshot)
        for text in ('private','secret','api_key','do-not-publish'):
            self.assertNotIn(text,encoded)
        output=self.root/'frontend'/'dist'/'assets'/'job-progress'/(self.job_id+'.json')
        self.assertEqual(json.loads(output.read_text('utf-8')),snapshot)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertEqual(list(output.parent.glob('*.tmp')),[])

    def test_publisher_corrupt_job_preserves_last_terminal_snapshot(self):
        self.write(self.directory/'job.json',{**self.job,'status':'failed'})
        publisher.publish_once(self.job_id,root=self.root)
        output=self.root/'frontend'/'dist'/'assets'/'job-progress'/(self.job_id+'.json')
        before=output.read_bytes()
        (self.directory/'job.json').write_text('{"id":',encoding='utf-8')
        self.assertIsNone(publisher.publish_once(self.job_id,root=self.root))
        self.assertEqual(output.read_bytes(),before)
        self.write(self.directory/'job.json',{**self.job,'status':[]})
        self.assertIsNone(publisher.publish_once(self.job_id,root=self.root))

    def test_publisher_rejects_traversal_or_outside_workspace(self):
        with self.assertRaises(ValueError):
            publisher.publish_once('../job',root=self.root)
        with self.assertRaises(ValueError):
            publisher.publish_once(self.job_id,root=config.ROOT.parent)

    def test_retry_same_id_publishes_new_job_timestamp_and_current_run_only(self):
        self.decisions()
        self.write(self.directory/'job.json',{**self.job,'status':'failed'})
        failed=publisher.publish_once(self.job_id,root=self.root)
        retried={**self.job,'updated_at':'2026-10-08T23:10:31.454746+07:00'}
        self.write(self.directory/'job.json',retried)
        self.write(self.audit/'run.json',{'run_id':'retry'})
        current=publisher.publish_once(self.job_id,root=self.root)
        self.assertEqual(current['job_updated_at'],retried['updated_at'])
        self.assertNotEqual(current['job_updated_at'],failed['job_updated_at'])
        self.assertEqual(current['stage_progress']['scenes']['completed'],0)

    def test_publisher_terminal_stops_and_running_polls_three_seconds(self):
        terminal={'job_id':self.job_id,'status':'failed','stage':'scenes'}
        with patch.object(publisher,'publish_once',return_value=terminal), patch.object(publisher.time,'sleep') as sleep:
            self.assertEqual(publisher.main(['--job',self.job_id]),0)
            sleep.assert_not_called()
        with patch.object(publisher,'publish_once',side_effect=[{**terminal,'status':'running'},terminal]), patch.object(publisher.time,'sleep') as sleep:
            self.assertEqual(publisher.main(['--job',self.job_id]),0)
            sleep.assert_called_once_with(3)


if __name__=='__main__':
    unittest.main()
