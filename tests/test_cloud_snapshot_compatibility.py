"""Snapshot compatibility never opens a provider or starts inference."""
import copy
import json
from pathlib import Path
import unittest

from app import processing
from app.editorial import DEFAULT_PROFILE
from app.json_store import atomic_json,read_json
from tests.test_final_quality import fixture
from tests.test_media import workspace_directory


def snapshot(directory,provider='antigravity_manual'):
    directory=Path(directory)
    source=directory/'original.mp4'
    source.write_bytes(b'authored source bytes, not encoded media')
    analysis,_=fixture()
    analysis['events'][0]['part_endings'][0]['evidence']='The original response completes the supplied source exchange.'
    analysis['provider']=provider
    analysis['producer']={'provider':provider,'original_result':'immutable-producing-provider'}
    analysis['check_policy']={'version':2,'economy_mode':True}
    atomic_json(directory/'analysis-settings.json',{'provider':provider,'economy_mode':True})
    atomic_json(directory/'editorial-settings.json',DEFAULT_PROFILE)
    atomic_json(directory/'transcript.json',analysis['transcript'])
    atomic_json(directory/'analysis.meta.json',{'source':processing.source_digest(source),'version':16})
    processing.save_snapshot(directory,source,analysis)
    return source,analysis


class CloudSnapshotCompatibilityTests(unittest.TestCase):
    def switch(self,directory,provider):
        atomic_json(directory/'analysis-settings.json',{**read_json(directory/'analysis-settings.json'),'provider':provider})

    def test_either_cloud_transport_reuses_snapshot_without_rewriting_provenance(self):
        for old,new in (('antigravity_manual','deepseek_plan'),('deepseek_plan','antigravity_manual')):
            with self.subTest(old=old,new=new), workspace_directory('cloud-snapshot-') as directory:
                directory=Path(directory)
                source,analysis=snapshot(directory,old)
                before=(directory/'analysis-final.json').read_bytes()
                before_meta=(directory/'analysis-final.meta.json').read_bytes()
                self.switch(directory,new)
                restored=processing.cached_analysis(directory,source)
                self.assertEqual(restored,analysis)
                self.assertEqual(restored['provider'],old)
                self.assertEqual(restored['producer']['provider'],old)
                self.assertEqual((directory/'analysis-final.json').read_bytes(),before)
                self.assertEqual((directory/'analysis-final.meta.json').read_bytes(),before_meta)

    def test_legacy_exact_cloud_provider_manifest_normalizes_only_that_field(self):
        with workspace_directory('legacy-cloud-snapshot-') as directory:
            directory=Path(directory)
            source,analysis=snapshot(directory)
            saved=read_json(directory/'analysis-final.meta.json')
            saved['provider']='antigravity_manual'
            atomic_json(directory/'analysis-final.meta.json',saved)
            self.switch(directory,'deepseek_plan')
            self.assertEqual(processing.cached_analysis(directory,source),analysis)
            saved['unexpected_metadata']='must remain incompatible'
            atomic_json(directory/'analysis-final.meta.json',saved)
            with self.assertRaises(ValueError):
                processing.cached_analysis(directory,source)

    def test_legacy_missing_manifest_allows_only_the_same_cloud_semantics(self):
        with workspace_directory('old-cloud-snapshot-') as directory:
            directory=Path(directory)
            source,analysis=snapshot(directory)
            (directory/'analysis-final.meta.json').unlink()
            self.switch(directory,'deepseek_plan')
            self.assertEqual(processing.cached_analysis(directory,source),analysis)
            self.switch(directory,'deepseek')
            with self.assertRaises(ValueError):
                processing.cached_analysis(directory,source)
            self.switch(directory,'deepseek_plan')
            source.write_bytes(b'different source bytes')
            with self.assertRaises(ValueError):
                processing.cached_analysis(directory,source)

    def test_local_hybrid_and_other_deepseek_modes_remain_distinct(self):
        for provider in ('local','deepseek','hybrid','local_fast_story','local_flash_story','local_flash_story_budgeted'):
            with self.subTest(provider=provider),workspace_directory('distinct-provider-snapshot-') as directory:
                directory=Path(directory)
                source,_=snapshot(directory)
                self.switch(directory,provider)
                with self.assertRaises(ValueError):
                    processing.cached_analysis(directory,source)

    def test_all_non_provider_identity_fields_stay_strict_across_cloud_switch(self):
        for changed in ('source','analysis_content','producer','layout','profile','check_policy','transcript_settings','transcript_checkpoint','manifest_version'):
            with self.subTest(changed=changed),workspace_directory('strict-cloud-snapshot-') as directory:
                directory=Path(directory)
                source,analysis=snapshot(directory)
                self.switch(directory,'deepseek_plan')
                if changed=='source':
                    source.write_bytes(b'changed actual source')
                elif changed in ('analysis_content','producer'):
                    modified=copy.deepcopy(analysis)
                    if changed=='producer':modified['producer']['provider']='deepseek_plan'
                    else:modified['events'][0]['summary']+=' Changed content.'
                    atomic_json(directory/'analysis-final.json',modified)
                elif changed=='layout':
                    atomic_json(directory/'render-settings.json',{'layout':'cinema','caption_style':'classic'})
                elif changed=='profile':
                    atomic_json(directory/'editorial-settings.json',{**DEFAULT_PROFILE,'preserve_humor':False})
                elif changed=='check_policy':
                    atomic_json(directory/'analysis-settings.json',{'provider':'deepseek_plan','economy_mode':False})
                elif changed=='transcript_settings':
                    atomic_json(directory/'analysis-settings.json',{'provider':'deepseek_plan','economy_mode':True,
                        'transcript_mode':'provided','transcript_source_sha256':'a'*64})
                elif changed=='transcript_checkpoint':
                    atomic_json(directory/'transcript.json',{'words':[],'segments':[]})
                elif changed=='manifest_version':
                    atomic_json(directory/'analysis-final.meta.json',{**read_json(directory/'analysis-final.meta.json'),'version':2})
                with self.assertRaises(ValueError):
                    processing.cached_analysis(directory,source)
