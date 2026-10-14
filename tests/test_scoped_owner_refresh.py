"""Boundary-owner downstream refresh; model/native stages are capture fakes."""
import copy
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from app.config import TEMP, STORY_MODEL
from app.scoped_owner_refresh import refresh_scoped_owners, finish_scoped_framing, reconcile_scoped_dependencies


def event(identifier,start,end,unit='unit'):
    return {'id':identifier,'scene_id':'source-scene','start':start,'end':end,'kind':'story','importance':4,
        'summary':'Actual CURRENT source contribution.','requires':[],
        'units':[{'id':unit,'start':start,'end':end,'text':''}],
        'selected_ranges':[{'start':start,'end':end}],
        'unit_evidence':[{'unit':unit,'decision':'keep','kind':'physical_action','evidence':'Concrete visible CURRENT source action.',
            'confidence':.95,'frame_indices':[1],'frame_times':[(start+end)/2],'frame_count':1,
            'speech_quote':'','view_start':start,'view_end':end}],
        'understanding_confidence':.95,'selection_confidence':.95,'selection_status':'accepted',
        'uncertain':False,'selection_uncertain':False,'analysis_unresolved':False,
        'focus':[{'time':start,'x':.5,'y':.5,'confidence':.0}]}


class ScopedOwnerRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory=TEMP/('scoped-owner-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.source=self.directory/'source.mp4'
        self.source.write_bytes(b'fixture-source')
        self.layout('cinema')
        self.old=event('old',0,10)
        self.old['units']=[{'id':'early','start':0,'end':5,'text':''},{'id':'late','start':5,'end':10,'text':''}]
        self.old['unit_evidence']=[event('temp',0,5,'early')['unit_evidence'][0],
                                   event('temp',5,10,'late')['unit_evidence'][0]]
        self.first=event('first',0,5,'new-early')
        self.second=event('second',5,10,'new-late')
        self.dependent=event('dependent',20,25)
        self.outside=event('outside',40,45)
        self.analysis={'events':[self.old,self.dependent,self.outside], 'provider':'antigravity_manual',
                       'probe':{'duration':45},'transcript':{'segments':[],'words':[]},'shots':[],
                       'story_structure':{'status':'passed','relations':[]}}
        self.boundary={'events':[self.first,self.second,self.dependent,self.outside],
            'changed_event_ids':['first','second'],'removed_event_ids':['old'],
            'ownership':{'old':['first','second'],'dependent':['dependent'],'outside':['outside']},
            'framing_required_event_ids':['first','second']}
        class Vision:
            model=STORY_MODEL;thinking=True
        self.vision=Vision()

    def tearDown(self):shutil.rmtree(self.directory)

    def layout(self,name):
        (self.directory/'render-settings.json').write_text(json.dumps({'layout':name,'caption_style':'classic'}),encoding='utf-8')

    def refresh(self):
        return refresh_scoped_owners(self.source,self.analysis,self.boundary,self.directory,self.vision,
                                     lambda *a:None,lambda:False)

    def test_no_changed_owner_has_zero_specialists_and_framing(self):
        self.boundary.update(changed_event_ids=[],removed_event_ids=[])
        with patch('app.story.clean_credit_continuations') as credits,patch('app.framing.refine_focus') as focus:
            result=self.refresh()
        self.assertEqual(result['status'],'not_required')
        self.assertFalse(credits.called)
        self.assertFalse(focus.called)
        self.assertEqual(result['events'],self.boundary['events'])

    def test_requires_remaps_only_the_actual_previously_evidenced_source_unit(self):
        self.dependent['requires']=['old']
        relation={'type':'cause','from':{'event':'old','unit':'early'},
                  'to':{'event':'dependent','unit':'unit'},'confidence':.95,
                  'evidence':'The retained early action directly causes this later response.'}
        self.analysis['story_structure']['relations']=[relation]
        result=self.refresh()
        dependent=next(e for e in result['events'] if e['id']=='dependent')
        self.assertEqual(dependent['requires'],['first'])
        self.assertEqual(result['dependency_unresolved'],[])
        self.assertEqual(dependent['unit_evidence'],self.dependent['unit_evidence'])
        self.assertEqual(result['events'][-1],self.outside)
        self.assertNotIn('story_relations',dependent)
        self.assertEqual(self.dependent['requires'],['old'])

    def test_ambiguous_dependency_has_no_dangling_id_and_no_invented_relation(self):
        self.dependent['requires']=['old']
        result=self.refresh()
        dependent=next(e for e in result['events'] if e['id']=='dependent')
        self.assertEqual(dependent['requires'],[])
        self.assertEqual(dependent['story_structure']['status'],'unresolved')
        self.assertEqual(result['dependency_unresolved'][0]['candidate_event_ids'],['first','second'])
        self.assertEqual(dependent['unit_evidence'],self.dependent['unit_evidence'])
        self.assertNotIn('story_relations',dependent)

    def test_old_dependency_cannot_be_remapped_to_dropped_or_unproven_source(self):
        self.dependent['requires']=['old']
        self.first['unit_evidence']=[]
        self.analysis['story_structure']['relations']=[{'type':'cause','from':{'event':'old','unit':'early'},
            'to':{'event':'dependent','unit':'unit'},'confidence':.95,
            'evidence':'Concrete prior dependency points to the actual early source unit.'}]
        result=self.refresh()
        self.assertEqual(result['dependency_unresolved'][0]['reason'],'source_dependency_not_positively_covered')
        self.assertEqual(result['events'][2]['requires'],[])

    def test_malformed_prior_relation_does_not_create_a_dependency(self):
        self.dependent['requires']=['old']
        relation={'type':'cause','from':{'event':'old','unit':'early'},
            'to':{'event':'dependent','unit':'unit'},'confidence':.95,
            'evidence':'Concrete prior dependency points to the actual early source unit.'}
        for malformed in (dict(relation,confidence=float('inf')),
                          {**relation,'to':{'event':'dependent','unit':'unseen-unit'}}):
            with self.subTest(relation=malformed):
                self.analysis['story_structure']['relations']=[malformed]
                result=self.refresh()
                self.assertEqual(result['events'][2]['requires'],[])
                self.assertEqual(result['dependency_unresolved'][0]['reason'],'source_dependency_unit_missing')

    def test_untyped_primary_unresolved_flag_is_not_downgraded_to_relation_only(self):
        self.dependent.update(requires=['old'],analysis_unresolved=True)
        self.dependent.pop('analysis_unresolved_reasons',None)
        result=self.refresh()
        dependent=result['events'][2]
        self.assertIn('source_analysis_unresolved',dependent['analysis_unresolved_reasons'])
        from app.selection_gate import source_selection_readiness
        self.assertEqual(source_selection_readiness([dependent])['status'],'unresolved')

    def test_dependency_is_restored_only_by_fresh_source_supported_relation(self):
        self.dependent['requires']=['old']
        events=self.refresh()['events']
        for row in events:
            row.update(story_structure={'status':'accepted'},analysis_unresolved=False,analysis_unresolved_reasons=[])
        from app.story_structure_pass import source_units
        nodes,_,_=source_units(events,self.analysis['transcript'])
        by_id={n['ref']['event']:n for n in nodes}
        source,target=by_id['first'],by_id['dependent']
        support=[{'ref':n['ref'],'proof':n['proofs'][0]['id'],'quote':''} for n in (source,target)]
        relation={'type':'cause','from':source['ref'],'to':target['ref'],'confidence':.95,
                  'evidence':'A directly evidenced source action causes the later owned response.','support':support}
        graph={'status':'passed','units':[{'ref':n['ref'],'status':'accepted'} for n in nodes],
               'relations':[relation]}
        result=reconcile_scoped_dependencies(events,graph,self.analysis['transcript'])
        self.assertEqual(result['status'],'complete')
        dependent=result['events'][2]
        self.assertEqual(dependent['requires'],['first'])
        self.assertNotIn('dependency_refresh_unresolved',dependent)
        self.assertNotIn('story_relations',dependent)
        self.assertEqual(result['events'][-1],events[-1])
        invalid=copy.deepcopy(graph)
        invalid['relations'][0]['support'][0]['proof']='UNPROVED_NATIVE_ID'
        unresolved=reconcile_scoped_dependencies(events,invalid,self.analysis['transcript'])
        self.assertEqual(unresolved['status'],'unresolved')
        self.assertEqual(unresolved['events'][2]['requires'],[])

    def test_passed_graph_without_actual_dependency_edge_does_not_erase_pending_requirement(self):
        self.dependent['requires']=['old']
        events=self.refresh()['events']
        for row in events:
            row.update(story_structure={'status':'accepted'},analysis_unresolved=False,analysis_unresolved_reasons=[])
        result=reconcile_scoped_dependencies(events,{'status':'passed','relations':[],'units':[]},self.analysis['transcript'])
        self.assertEqual(result['status'],'unresolved')
        self.assertTrue(result['events'][2]['dependency_refresh_unresolved'])
        self.assertEqual(result['events'][2]['story_structure']['status'],'unresolved')

    def test_only_concrete_old_hints_trigger_specialists_and_old_exclusion_is_not_copied(self):
        self.old.update(contains_credits=True,credits_kind='opening',
                        excluded_credit_ranges=[{'start':0,'end':10}],
                        confirmed_opening_proofs=[{'checkpoint':'OLD_NATIVE_OWNER_PROOF'}])
        def role_rows(events,*a,**kwargs):
            self.assertEqual(kwargs['event_ids'],{'first','second'})
            result=copy.deepcopy(events)
            result[-1]['sentinel']='ILLEGAL_UNRELATED_CHANGE'
            return result
        with (patch('app.story.clean_credit_continuations',side_effect=lambda e,*a:e) as credits,
              patch('app.titles.refine_titles',side_effect=lambda e,*a:e) as titles,
              patch('app.source_roles.refine_source_roles',side_effect=role_rows) as roles,
              patch('app.closing.refine_closing_novelty') as closing):
            result=self.refresh()
        self.assertEqual([e['id'] for e in credits.call_args.args[0]],['first','second'])
        self.assertEqual([e['id'] for e in titles.call_args.args[0]],['first','second'])
        self.assertEqual(roles.call_count,1)
        self.assertFalse(closing.called)
        for child in result['events'][:2]:
            self.assertNotIn('confirmed_opening_proofs',child)
            self.assertNotIn('excluded_credit_ranges',child)
            self.assertNotIn('review_targets',child)
        self.assertEqual(result['events'][-1],self.outside)

    def test_position_or_silence_does_not_create_a_new_specialist_target(self):
        with (patch('app.story.clean_credit_continuations') as credits,
              patch('app.titles.refine_titles') as titles,
              patch('app.source_roles.refine_source_roles') as roles,
              patch('app.closing.refine_closing_novelty') as closing):
            self.refresh()
        self.assertFalse(any(fn.called for fn in (credits,titles,roles,closing)))

    def test_legacy_credit_candidate_reaches_native_independent_sequence_check(self):
        self.old.update(contains_credits=True,credits_kind='opening')
        (self.directory/'source.json').write_text(json.dumps({'path':str(self.source)}),encoding='utf-8')
        (self.directory/'probe.json').write_text(json.dumps(self.analysis['probe']),encoding='utf-8')
        class LegacyVision:
            supports_image_pages=False;model=STORY_MODEL;projector=STORY_MODEL;thinking=False
            def __init__(self):self.calls=[]
            def query(self,prompt,images,**kwargs):
                self.calls.append(prompt)
                ids=kwargs['schema']['properties']['decisions']['items']['properties']['unit']['enum']
                return {'anchors':[],'decisions':[{'unit':identifier,'credit_montage':False,
                    'continuous_narrative':True,'same_sequence':False,'speech_role':'none','anchor':'none',
                    'confidence':.95,'evidence':'Concrete continuous CURRENT narrative with no production anchor.'} for identifier in ids]}
        self.vision=LegacyVision()
        with (patch('app.production.sequence_sheet',return_value=[self.directory/'native-candidate.jpg']) as media,
              patch('app.titles.refine_titles',side_effect=lambda events,*a:events),
              patch('app.source_roles.refine_source_roles',side_effect=lambda events,*a,**k:events)):
            result=self.refresh()
        self.assertEqual(len(self.vision.calls),2)
        self.assertTrue(all('opening' in prompt for prompt in self.vision.calls))
        self.assertEqual([(call.args[1][0]['start'],call.args[1][-1]['end']) for call in media.call_args_list],[(0,5),(5,10)])
        self.assertTrue(all('excluded_credit_ranges' not in row for row in result['events'][:2]))
        self.assertEqual(result['events'][-1],self.outside)

    def test_specialist_cannot_change_current_source_geometry(self):
        self.old['title_candidate']=True
        def invalid(events,*a):
            events[0]['end']=1000
            return events
        with patch('app.titles.refine_titles',side_effect=invalid),self.assertRaisesRegex(ValueError,'ownership'):
            self.refresh()

    def test_portrait_framing_changes_only_new_children_and_restores_session_defaults(self):
        self.layout('portrait')
        self.first['requires']=['outside']
        def frame(source,probe,transcript,shots,events,*a):
            self.assertEqual([e['id'] for e in events],['first','second'])
            self.assertTrue(all(e['requires']==[] for e in events))
            self.assertFalse(self.vision.thinking)
            for e in events:e['focus']=[{'time':e['start'],'x':.7,'y':.5,'confidence':.95}]
            return events
        with patch('app.framing.refine_focus',side_effect=frame) as focus:
            result=self.refresh()
        self.assertEqual(focus.call_count,1)
        self.assertTrue(self.vision.thinking)
        self.assertEqual(result['events'][0]['requires'],['outside'])
        self.assertEqual(result['events'][0]['focus'][0]['x'],.7)
        self.assertEqual(result['events'][-1],self.outside)

    def test_deepseek_plan_does_not_start_nested_local_focus(self):
        self.layout('portrait')
        self.analysis['provider']='deepseek_plan'
        with patch('app.vision.vision_session') as sessions,patch('app.framing.refine_focus') as focus:
            result=self.refresh()
        self.assertFalse(sessions.called)
        self.assertFalse(focus.called)
        self.assertEqual(result['framing_pending_event_ids'],['first','second'])
        self.assertTrue(all(e['framing_refresh']['provider']=='local' for e in result['events'][:2]))

    def test_empty_unresolved_source_keeps_focus_obligation_without_dispatch(self):
        self.layout('portrait')
        self.first.update(selected_ranges=[],selection_status='unresolved',selection_empty_verified=False,
                          analysis_unresolved=True)
        with patch('app.vision.vision_session') as sessions,patch('app.framing.refine_focus') as focus:
            result=finish_scoped_framing(self.source,self.analysis,self.boundary['events'],['first'],
                self.directory,lambda *a:None,lambda:False,vision=self.vision)
        self.assertEqual(result['status'],'pending')
        self.assertEqual(result['pending_event_ids'],['first'])
        self.assertEqual(result['events'][0]['framing_refresh']['reason'],'source_selection_not_ready')
        self.assertFalse(focus.called)
        self.assertFalse(sessions.called)
        self.assertEqual(result['events'][-1],self.outside)

    def test_resolved_all_drop_source_needs_no_focus(self):
        self.layout('portrait')
        self.first.update(selected_ranges=[],selection_status='accepted',selection_empty_verified=True)
        self.first['unit_evidence'][0].update(decision='drop',kind='neutral_scenery')
        from app.selection_gate import source_selection_readiness
        self.assertEqual(source_selection_readiness([self.first])['status'],'passed')
        with patch('app.vision.vision_session') as sessions,patch('app.framing.refine_focus') as focus:
            result=finish_scoped_framing(self.source,self.analysis,self.boundary['events'],['first'],
                self.directory,lambda *a:None,lambda:False,vision=self.vision)
        self.assertEqual(result['status'],'not_required')
        self.assertEqual(result['pending_event_ids'],[])
        self.assertFalse(focus.called)
        self.assertFalse(sessions.called)

    def test_empty_pending_owner_is_framed_only_after_its_source_selection_passes(self):
        self.layout('portrait')
        self.first.update(selected_ranges=[],selection_status='unresolved',selection_empty_verified=False,
                          analysis_unresolved=True)
        pending=finish_scoped_framing(self.source,self.analysis,self.boundary['events'],['first'],
            self.directory,lambda *a:None,lambda:False,vision=self.vision)
        ready=copy.deepcopy(pending['events'])
        ready[0].update(selected_ranges=[{'start':0,'end':5}],selection_status='accepted',analysis_unresolved=False)
        def focus(source,probe,transcript,shots,events,*a):
            events[0]['focus']=[{'time':0,'x':.8,'y':.5,'confidence':.95}]
            return events
        with patch('app.framing.refine_focus',side_effect=focus) as reviewed:
            result=finish_scoped_framing(self.source,self.analysis,ready,pending['pending_event_ids'],
                self.directory,lambda *a:None,lambda:False,vision=self.vision)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['pending_event_ids'],[])
        self.assertEqual(result['reviewed_event_ids'],['first'])
        self.assertEqual([e['id'] for e in reviewed.call_args.args[4]],['first'])
        self.assertEqual(result['events'][0]['focus'][0]['x'],.8)
        self.assertEqual(result['events'][1:],ready[1:])

    def test_owned_framing_stage_routes_only_selected_new_children_after_session_exit(self):
        self.layout('portrait')
        self.analysis['provider']='deepseek_plan'
        entries=[]
        @contextmanager
        def session(directory,cancelled,provider,**settings):
            entries.append((provider,settings))
            yield self.vision
        with patch('app.vision.vision_session',side_effect=session),patch('app.framing.refine_focus',
                side_effect=lambda source,probe,transcript,shots,events,*a:events) as focus:
            result=finish_scoped_framing(self.source,self.analysis,self.boundary['events'],['first'],
                self.directory,lambda *a:None,lambda:False,allow_new_session=True)
        self.assertEqual(entries[0][0],'local')
        self.assertEqual(entries[0][1]['model'],STORY_MODEL)
        self.assertEqual([e['id'] for e in focus.call_args.args[4]],['first'])
        self.assertEqual(result['reviewed_event_ids'],['first'])
        self.assertEqual(result['events'][1],self.second)

    def test_explicit_new_session_cannot_nest_under_active_incompatible_provider(self):
        self.layout('portrait')
        self.analysis['provider']='deepseek_plan'
        with patch('app.vision.vision_session') as sessions,self.assertRaisesRegex(ValueError,'Close'):
            finish_scoped_framing(self.source,self.analysis,self.boundary['events'],['first'],self.directory,
                lambda *a:None,lambda:False,vision=self.vision,allow_new_session=True)
        self.assertFalse(sessions.called)


if __name__=='__main__':unittest.main()
