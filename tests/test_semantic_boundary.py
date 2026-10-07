"""Boundary schema/triage/cache mechanisms; semantic quality uses real-model E2E."""
import copy
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP, FFMPEG
from app.media import run_command
from app.scene_detection import production_shots
from app.semantic_boundary import (boundary_schema, validate_boundary, classify_boundary,
                                   embedding_distance, boundary_frames, verify_boundary)


def decision(**changes):
    value = dict(same_location=True, location_changed=False, same_characters=True,
                 character_state_changed=False, object_state_changed=False, physical_transition=False,
                 transition_type='none', confidence=.93, uncertain=False, evidence='Same visible window and people.')
    return {**value, **changes}


class SemanticBoundaryMechanismTests(unittest.TestCase):
    def test_schema_requires_flags_and_concrete_evidence(self):
        schema = boundary_schema()
        self.assertEqual(set(schema['required']), set(decision()))
        self.assertEqual(validate_boundary(decision()), decision())

    def test_nonfinite_boolean_confidence_and_false_flags_are_rejected(self):
        for value in (True, float('nan'), float('inf'), -.1, 1.1, '.9'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_boundary(decision(confidence=value))
        with self.assertRaises(ValueError):
            validate_boundary(decision(same_location='true'))

    def test_contradictory_location_or_unsupported_physical_claim_is_rejected(self):
        for changes in ({'location_changed': True}, {'physical_transition': True},
                        {'transition_type': 'unknown'}, {'evidence': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_boundary(decision(**changes))

    def test_robust_same_scene_skips_vlm_but_state_or_audio_demand_is_ambiguous(self):
        feature = {'reliability': 1, 'perceptual_embedding': [1,0], 'background_embedding': [1,0]}
        self.assertEqual(classify_boundary(feature,feature)['classification'], 'obvious_same_scene')
        for origin in ('motion', 'state_probe', 'audio', 'fade'):
            self.assertEqual(classify_boundary(feature,feature,proposal={'origins':[origin]},recurrent=True)
                             ['classification'], 'ambiguous_boundary')

    def test_perceptual_different_views_need_semantic_evidence_not_rgb_labels(self):
        a = {'reliability': 1, 'perceptual_embedding': [1,0], 'background_embedding': [1,0]}
        b = {'reliability': 1, 'perceptual_embedding': [0,1], 'background_embedding': [0,1]}
        self.assertEqual(classify_boundary(a,b)['classification'], 'ambiguous_boundary')
        self.assertEqual(classify_boundary(a,b,speech={'dialogue_break':True})['classification'], 'obvious_scene_change')
        self.assertIsNone(embedding_distance({}, a))

    def test_production_inputs_drop_all_supplied_semantic_answers_and_preserve_raw_candidates(self):
        original = [{'id': 'shot', 'start': 0, 'end': 10, 'location': 'answer', 'importance': 5,
                     'character_state': 'bound', 'features': {'action_transition': True},
                     'raw_shot_candidates': [{'id':'raw','time':4,'accepted':False,'scene_score':.1,
                                              'location':'another answer'}]}]
        snapshot = copy.deepcopy(original)
        result = production_shots(original,[{'id':'secondary','time':6,'origins':['motion'],'scores':{'motion':.3}}],10)
        self.assertEqual(snapshot, original)
        self.assertNotIn('location', str(result))
        self.assertNotIn('character_state', str(result))
        self.assertEqual([r['time'] for r in result[0]['raw_shot_candidates']], [4,6])
        self.assertEqual(result[0]['raw_shot_candidates'][1]['decision'],'secondary_evidence_proposal')


@unittest.skipUnless(FFMPEG.is_file(), 'Portable FFmpeg absent')
class SourceBoundaryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP/('boundary-source-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.source = self.job/'source.mp4'
        run_command([str(FFMPEG),'-y','-v','error','-f','lavfi','-i',
                     'testsrc2=s=320x180:r=12:d=4','-c:v','libx264','-pix_fmt','yuv420p',str(self.source)], self.job)

    def tearDown(self):
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)

    def test_targeted_frames_record_actual_pts_and_distinct_fractional_cache_keys(self):
        first, records = boundary_frames(self.source,2,0,4,self.job,lambda:False)
        self.assertTrue(first.is_file())
        self.assertEqual(len(records),3)
        self.assertTrue(all(0 <= r['time'] < 4 for r in records))
        self.assertEqual(len({r['frame'] for r in records}),3)
        self.assertEqual(len({r['sha256'] for r in records}),3)

    def test_frame_tampering_is_redecoded_and_cached_cancellation_propagates(self):
        _, records = boundary_frames(self.source,2,0,4,self.job,lambda:False)
        path = self.job/records[0]['frame']
        path.write_bytes(b'changed evidence')
        _, rebuilt = boundary_frames(self.source,2,0,4,self.job,lambda:False)
        self.assertEqual(rebuilt,records)
        with self.assertRaises(InterruptedError):
            boundary_frames(self.source,2,0,4,self.job,lambda:True)

    def test_model_response_cache_reuses_and_prompt_change_invalidates(self):
        class Adapter:
            cache_profile='mechanism-test'
            requests=0
            def query(self,*args,**kwargs):
                self.requests += 1
                return decision()
        adapter = Adapter()
        def verify():
            return verify_boundary(self.source,2,0,4,{'segments':[]},{'classification':'ambiguous_boundary'},
                                   self.job,adapter,lambda:False)
        self.assertEqual(verify(),verify())
        self.assertEqual(adapter.requests,1)
        from app import semantic_boundary
        with patch.object(semantic_boundary,'BOUNDARY_PROMPT',semantic_boundary.BOUNDARY_PROMPT+' Inspect again.'):
            verify()
        self.assertEqual(adapter.requests,2)

    def test_invalid_answer_becomes_explicit_unresolved_not_a_claimed_action(self):
        class Invalid:
            def query(self,*args,**kwargs):
                return decision(physical_transition=True)
        result = verify_boundary(self.source,2,0,4,{'segments':[]},{},self.job,Invalid(),lambda:False)
        self.assertTrue(result['uncertain'])
        self.assertNotIn('physical_transition',result)
        self.assertEqual(result['error_type'],'ValueError')

    def test_uncertain_boundary_gets_one_targeted_original_frame_pair_review(self):
        class Adapter:
            requests=[]
            def query(self,prompt,images,**kwargs):
                self.requests.append((prompt,images))
                return decision(uncertain=len(self.requests)==1,confidence=.8 if len(self.requests)==1 else .93)
        adapter=Adapter()
        result=verify_boundary(self.source,2,0,4,{'segments':[]},{},self.job,adapter,lambda:False)
        self.assertFalse(result['uncertain'])
        self.assertEqual(len(adapter.requests),2)
        self.assertIsInstance(adapter.requests[1][1],list)
        self.assertEqual(len(adapter.requests[1][1]),2)
        self.assertIn('disputed_hypothesis',adapter.requests[1][0])
