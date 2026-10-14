"""Local scope selection never turns uncertain evidence into accepted evidence."""
import copy
from pathlib import Path
import shutil
import unittest
import uuid

from app.config import ROOT
from app.confirmed_selection import project,prune_failed
from app.json_store import atomic_json,read_json
from app.selection_gate import source_selection_problems
from tests.test_final_quality import fixture


def world():
    base,_=fixture();result=copy.deepcopy(base)
    result['events']=[];result['transcript']={'words':[],'segments':[]};result['scenes']=[]
    result['probe']['duration']=result['duration']=24
    for i,ident in enumerate(('a','b','c')):
        event=copy.deepcopy(base['events'][0]);offset=i*8
        event.update(id=ident,scene_id=ident,start=offset,end=offset+8)
        for unit in event['units']:
            unit['start']+=offset;unit['end']+=offset
        for proof in event['unit_evidence']:
            proof['view_start']+=offset;proof['view_end']+=offset
        for row in event['selected_ranges']:
            row['start']+=offset;row['end']+=offset
        event['dialogue_relations']['pairs']=[]
        event['part_endings']=[]
        for assignment in event['story_structure']['units']:
            assignment['ref']['event']=ident
        for coverage in event['dialogue_relations']['coverage']:
            coverage['ref']['event']=ident;coverage['start']+=offset;coverage['end']+=offset
            for row in coverage['source_ranges']:
                row['start']+=offset;row['end']+=offset
        result['events'].append(event)
        result['scenes'].append({'id':ident,'start':offset,'end':offset+8,'uncertainty_reasons':[]})
        for name in ('words','segments'):
            for original in base['transcript'][name]:
                row=copy.deepcopy(original);row['start']+=offset;row['end']+=offset
                result['transcript'][name].append(row)
    return result


class ConfirmedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory=ROOT/'temp'/('confirmed-selection-test-'+uuid.uuid4().hex)
        self.directory.mkdir()
        self.addCleanup(lambda:shutil.rmtree(self.directory))
        atomic_json(self.directory/'analysis.meta.json',{'source':'a'*64})
        atomic_json(self.directory/'selection-policy.json',{'version':1,'mode':'confirmed_only'})

    def test_source_uncertainty_is_omitted_without_mutating_or_relabeling_full_source(self):
        analysis=world();analysis['events'][1]['selection_confidence']=.7
        analysis['scoped_framing_pending_event_ids']=['a','b']
        original=copy.deepcopy(analysis)
        selected=project(analysis,self.directory)
        self.assertEqual([e['id'] for e in selected['events']],['a','c'])
        self.assertEqual(analysis,original)
        archive=read_json(self.directory/selected['selection_scope']['archive'])
        self.assertEqual(archive['full']['events'],original['events'])
        self.assertEqual(archive['full']['events'][1]['selection_confidence'],.7)
        self.assertEqual(selected['scoped_framing_pending_event_ids'],['a'])
        self.assertEqual(archive['full']['scoped_framing_pending_event_ids'],['a','b'])
        self.assertTrue(all(not source_selection_problems(e) for e in selected['events']))

    def test_missing_requirement_removes_transitive_consumers_but_keeps_intact_chain(self):
        analysis=world();analysis['events'][1]['requires']=['a'];analysis['events'][2]['requires']=['b']
        self.assertEqual(len(project(analysis,self.directory)['events']),3)
        analysis['events'][0]['selection_uncertain']=True
        with self.assertRaisesRegex(ValueError,'Нет подтверждённых самостоятельных'):
            project(analysis,self.directory)
        audit=read_json(self.directory/'confirmed-selection/scope.json')
        self.assertEqual({x['event'] for x in audit['omitted']},{'a','b','c'})

    def test_confirmed_question_answer_cannot_leave_one_endpoint(self):
        analysis=world();analysis['events'][1]['uncertain']=True
        analysis['dialogue_relations']={'pairs':[{'status':'confirmed','requires_answer':True,
            'question_ranges':[{'start':1,'end':2.1}],'answer_ranges':[{'start':12.5,'end':14}]}]}
        result=project(analysis,self.directory)
        self.assertEqual([e['id'] for e in result['events']],['c'])
        self.assertEqual(result['selection_scope']['omitted'][0]['reason'],'required_dialogue_endpoint_unavailable')

    def test_missing_causal_unit_cannot_be_erased_as_dependency_metadata(self):
        analysis=world();analysis['events'][0]['uncertain']=True
        analysis['story_structure']={'relations':[{'type':'cause','from':{'event':'a','unit':'q'},
            'to':{'event':'b','unit':'a'}}]}
        result=project(analysis,self.directory)
        self.assertEqual([e['id'] for e in result['events']],['c'])
        self.assertEqual(analysis['story_structure']['relations'][0]['from']['event'],'a')

    def test_downstream_failure_remains_unresolved_for_native_recovery(self):
        analysis=world();analysis['events'][0].update(analysis_unresolved=True,
            analysis_unresolved_reasons=['story_structure_unresolved'])
        result=project(analysis,self.directory)
        self.assertEqual(len(result['events']),3)
        self.assertTrue(result['events'][0]['analysis_unresolved'])
        self.assertEqual(result['selection_gate']['status'],'unresolved')

    def test_stalled_owner_is_removed_and_its_consumers_follow_without_another_query(self):
        analysis=world();analysis['events'][2]['requires']=['b']
        selected=project(analysis,self.directory)
        gate={'problems':[{'code':'dialogue_relations_unresolved','recovery_stage':'dialogue_relations','event':'b'}]}
        result=prune_failed(selected,gate,None,self.directory)
        self.assertEqual([e['id'] for e in result['events']],['a'])
        self.assertEqual(result['selection_scope']['archive'],selected['selection_scope']['archive'])

    def test_absent_policy_preserves_strict_default_and_original_object(self):
        (self.directory/'selection-policy.json').unlink()
        analysis=world();analysis['events'][0]['uncertain']=True
        self.assertIs(project(analysis,self.directory),analysis)
        self.assertIsNone(prune_failed(analysis,{'problems':[]},None,self.directory))
