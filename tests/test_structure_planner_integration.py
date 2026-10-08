"""Authored provider integration mechanisms; real raw A–J is a separate suite."""
import copy
import shutil
import unittest
import uuid

from app.config import TEMP
from app.dramatic_planner import build_dramatic_plan
from app.story_structure_pass import infer_story_structure
from tests.test_story_structure_pass import fixture, FakeProvider


class StructurePlannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP/('structure-planner-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree,self.directory)

    def source_analysis(self,budget=300):
        event,transcript = fixture(10)
        for row in [*event['units'],*event['selected_ranges'],*transcript['words'],*transcript['segments']]:
            row['start'] *= 7.5;row['end'] *= 7.5
        event['end'] = 300
        for record in event['unit_evidence']:
            record['view_start'] *= 7.5;record['view_end'] *= 7.5
        event.update(kind='story',importance=4,requires=[],unit_selection_version=1)
        # No authored story_arc_id, story_phase, part ending or canonical state
        # enters the structure pass. The fake provider isolates this boundary.
        result = infer_story_structure([event],transcript,self.directory,FakeProvider(),lambda:False)
        self.assertEqual(result['status'],'accepted')
        data = {'probe':{'duration':300,'width':640,'height':360,'has_audio':True},
            'events':result['events'],'transcript':transcript,'shots':[], 'preferred_part_count':6,
            'episode_profile':{'source_duration':300,'retention_budget':{'min':budget,'optimal':budget,'max':budget}}}
        return data,result

    def test_five_inferred_source_arcs_inside_one_scene_produce_five_parts(self):
        data,result = self.source_analysis()
        plan = build_dramatic_plan(data)
        self.assertEqual(len(result['arcs']),5)
        self.assertEqual(len(plan['parts']),5)
        self.assertEqual([p['duration'] for p in plan['parts']],[60]*5)
        self.assertEqual(plan['planner_diagnostics']['part_policy']['preferred_part_count'],6)
        self.assertEqual(len(plan['planner_diagnostics']['candidates'][0]['arc_ids']),5)
        self.assertEqual(plan['selected_event_ids'],['room'])

    def test_budget_selects_one_source_arc_without_selecting_its_entire_parent(self):
        data,result = self.source_analysis(60)
        original = copy.deepcopy(data)
        plan = build_dramatic_plan(data)
        self.assertEqual(sum(p['duration'] for p in plan['parts']),60)
        self.assertEqual(plan['retention_allocation']['selected_ranges'],{'room':[{'start':0,'end':60}]})
        self.assertEqual(plan['retention_allocation']['allocation_history'][0]['candidate'],result['arcs'][0]['id'])
        self.assertEqual(data,original)

    def test_inferred_arc_part_ending_carries_source_proof_and_relation(self):
        data,result = self.source_analysis()
        plan = build_dramatic_plan(data)
        for part,arc in zip(plan['parts'],result['arcs']):
            ending = part['ending']
            self.assertEqual(ending['arc_id'],arc['id'])
            self.assertEqual(ending['verification']['method'],'source_proof_text_relation')
            self.assertFalse(ending['verification']['visual_reverification'])
            self.assertTrue(ending['verification']['proofs'])


if __name__ == '__main__':unittest.main()
