"""ID ownership, scalar compatibility and conservative failure handling for boundary batches."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.error
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP
from app.semantic_boundary import verify_boundary, verify_boundaries, boundary_batch_schema


def decision(**changes):
    return dict({'evidence':'Matching visible fixed landmarks before and after.',
                 'change_scope':'same_scene', 'same_location':True, 'location_changed':False,
                 'same_characters':True, 'character_state_changed':False, 'object_state_changed':False,
                 'physical_transition':False, 'transition_type':'none', 'confidence':.95, 'uncertain':False},**changes)


class Adapter:
    max_boundary_batch = 3
    def __init__(self, handler=None):
        self.requests = []
        self.handler = handler
    def query(self,prompt,image,max_tokens,schema):
        self.requests.append((prompt,image,schema))
        if self.handler:
            return self.handler(prompt,image,schema)
        if 'boundaries' in schema['properties']:
            ids = schema['properties']['boundaries']['items']['properties']['boundary_id']['enum']
            return {'boundaries':[{'boundary_id':ident,**decision()} for ident in reversed(ids)]}
        return decision()


class BoundaryBatchTests(unittest.TestCase):
    def setUp(self):
        self.job = TEMP/('boundary-batch-'+uuid.uuid4().hex)
        self.job.mkdir(parents=True)
        self.source = self.job/'source.mp4'
        self.rows = [{'time':time,'before':0.,'after':4.,'measured':{'classification':'ambiguous_boundary'}}
                     for time in (.5,1.5,2.5)]
        self.frames = patch('app.semantic_boundary.boundary_frames',side_effect=self.evidence)
        self.frames.start()
    def tearDown(self):
        self.frames.stop()
        self.job.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.job)
    def evidence(self,source,time,before,after,job,cancelled):
        if cancelled():
            raise InterruptedError('cancelled')
        image = self.job/f'boundary-{time}.jpg'
        image.write_bytes(b'isolated mechanism fixture')
        frames = []
        for value in (time-.1,time,time+.1):
            path = self.job/f'frame-{value}.jpg'
            path.write_bytes(b'isolated mechanism frame')
            frames.append({'time':value,'frame':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return image,frames
    def run_rows(self,vision,cancelled=lambda:False,rows=None):
        return verify_boundaries(self.source,self.rows if rows is None else rows,{'segments':[]},
                                 self.job,vision,cancelled)

    def test_one_request_maps_reordered_results_to_their_own_source_and_caches(self):
        vision = Adapter()
        result = self.run_rows(vision)
        self.assertEqual(set(result),{.5,1.5,2.5})
        self.assertEqual(len(vision.requests),1)
        self.assertEqual(len(vision.requests[0][1]),3)
        for time,proof in result.items():
            self.assertEqual(proof['frames'][1]['time'],time)
        self.assertEqual(result,self.run_rows(vision))
        self.assertEqual(len(vision.requests),1)

    def test_preexisting_scalar_checkpoints_are_reused_without_new_model_calls(self):
        vision = Adapter()
        for row in self.rows:
            verify_boundary(self.source,row['time'],row['before'],row['after'],{'segments':[]},
                            row['measured'],self.job,vision,lambda:False)
        self.assertEqual(len(vision.requests),3)
        self.run_rows(vision)
        self.assertEqual(len(vision.requests),3)

    def test_one_uncertain_result_gets_its_own_original_pair_without_repeating_initial_request(self):
        def handler(prompt,image,schema):
            if 'boundaries' in schema['properties']:
                ids = schema['properties']['boundaries']['items']['properties']['boundary_id']['enum']
                return {'boundaries':[{'boundary_id':ident,**decision(
                    uncertain=i==1,confidence=.7 if i==1 else .95,change_scope='uncertain' if i==1 else 'same_scene')}
                    for i,ident in enumerate(ids)]}
            self.assertEqual(image,[self.job/'frame-1.4.jpg',self.job/'frame-1.6.jpg'])
            self.assertIn('disputed_hypothesis',prompt)
            return decision(change_scope='story_transition',character_state_changed=True,
                            physical_transition=True,transition_type='binding')
        vision = Adapter(handler)
        result = self.run_rows(vision)
        self.assertEqual(len(vision.requests),2)
        self.assertTrue(result[1.5]['physical_transition'])
        self.assertFalse(result[.5]['physical_transition'])
        self.assertFalse(result[2.5]['physical_transition'])

    def test_wrong_duplicated_missing_or_invalid_decisions_fall_back_to_scalar(self):
        for fault in ('wrong','duplicate','missing','flags'):
            directory = self.job/fault;directory.mkdir()
            with self.subTest(fault=fault):
                def handler(prompt,image,schema):
                    if 'boundaries' not in schema['properties']:
                        return decision()
                    ids = schema['properties']['boundaries']['items']['properties']['boundary_id']['enum']
                    values = [{'boundary_id':ident,**decision()} for ident in ids]
                    if fault=='wrong':values[0]['boundary_id']='unrelated-source'
                    elif fault=='duplicate':values[1]['boundary_id']=values[0]['boundary_id']
                    elif fault=='missing':values.pop()
                    else:values[0]['physical_transition']=True
                    return {'boundaries':values}
                vision=Adapter(handler)
                result=verify_boundaries(self.source,self.rows,{'segments':[]},directory,vision,lambda:False)
                self.assertEqual(len(vision.requests),4)
                self.assertTrue(all(not value.get('physical_transition') for value in result.values()))
                self.assertFalse(list((directory/'boundary-verification').glob('batch-*.json')))

    def test_recovery_failure_keeps_only_that_boundary_unresolved(self):
        def handler(prompt,image,schema):
            if 'boundaries' in schema['properties']:
                ids=schema['properties']['boundaries']['items']['properties']['boundary_id']['enum']
                return {'boundaries':[{'boundary_id':ident,**decision(uncertain=i==0,
                    change_scope='uncertain' if i==0 else 'same_scene',confidence=.6 if i==0 else .95)}
                    for i,ident in enumerate(ids)]}
            raise ValueError('invalid recovery')
        result=self.run_rows(Adapter(handler))
        self.assertTrue(result[.5]['uncertain'])
        self.assertFalse(result[1.5]['uncertain'])
        self.assertNotIn('physical_transition',result[.5])

    def test_cancel_after_query_does_not_publish_or_fall_back(self):
        stopped=False
        def handler(prompt,image,schema):
            nonlocal stopped
            ids=schema['properties']['boundaries']['items']['properties']['boundary_id']['enum']
            stopped=True
            return {'boundaries':[{'boundary_id':ident,**decision()} for ident in ids]}
        vision=Adapter(handler)
        with self.assertRaises(InterruptedError):self.run_rows(vision,lambda:stopped)
        self.assertEqual(len(vision.requests),1)
        self.assertFalse(list((self.job/'boundary-verification').glob('*.json')))

    def test_unadvertised_provider_retains_scalar_contract(self):
        vision=Adapter();vision.max_boundary_batch=1
        self.run_rows(vision)
        self.assertEqual(len(vision.requests),3)
        self.assertTrue(all('boundaries' not in schema['properties'] for _,_,schema in vision.requests))

    def test_control_failure_propagates_without_scalar_retries(self):
        def handler(*args):
            raise urllib.error.HTTPError('http://local.invalid',401,'unauthorized',{},None)
        vision=Adapter(handler)
        with self.assertRaises(urllib.error.HTTPError):self.run_rows(vision)
        self.assertEqual(len(vision.requests),1)
        self.assertFalse(list((self.job/'boundary-verification').glob('*.json')))

    def test_corrupted_batch_cache_rechecks_only_the_damaged_boundary(self):
        vision=Adapter();initial=self.run_rows(vision)
        files=list((self.job/'boundary-verification').glob('batch-*.json'))
        self.assertEqual(len(files),3)
        files[0].write_text('{truncated','utf-8')
        rebuilt=self.run_rows(vision)
        self.assertEqual(len(vision.requests),2)
        self.assertTrue(all(not result['uncertain'] for result in rebuilt.values()))
        for key in initial:
            self.assertEqual(initial[key]['frames'],rebuilt[key]['frames'])

    def test_duplicate_input_ids_are_rejected_before_source_preparation(self):
        with self.assertRaisesRegex(ValueError,'Repeated source boundary'):
            self.run_rows(Adapter(),rows=[self.rows[0],self.rows[0]])

    def test_schema_preserves_individual_scope_and_flag_constraints(self):
        from app.deepseek import _validate
        schema=boundary_batch_schema(['a','b'])
        _validate({'boundaries':[{'boundary_id':'a',**decision()},{'boundary_id':'b',**decision()}]},schema)
        with self.assertRaises(ValueError):
            _validate({'boundaries':[{'boundary_id':'a',**decision(physical_transition=True)},
                                     {'boundary_id':'b',**decision()}]},schema)


if __name__=='__main__':unittest.main()
