"""Recovery wiring preserves native owners and orders dependent work locally."""
import copy
from unittest.mock import Mock,patch

from app.quality_recovery import recover_final_quality,problem_owners,needs_model_recovery
from tests.test_final_quality import fixture


def assemble(directory,provider,probe,transcript,shots,events,**kwargs):
    return {'events':events,'scenes':kwargs['scenes']}


def test_failed_range_list_localizes_selection_without_unrelated_dispatch(tmp_path):
    analysis,_=fixture()
    other=copy.deepcopy(analysis['events'][0]);other.update(id='unrelated',start=10,end=18)
    analysis['events'].append(other)
    gate={'problems':[{'code':'unexplained_retained_ranges','recovery_stage':'selection_adjudication',
                       'ranges':[{'start':1,'end':2}]}]}
    with patch('app.selection_gate.source_selection_readiness',return_value={'status':'unresolved',
            'unresolved':[{'event':'e'},{'event':'unrelated'}]}), \
         patch('app.selection_adjudication.adjudicate_event',side_effect=lambda s,e,*a,**k:e) as query, \
         patch('app.scoped_relations.recover_relations') as relations, \
         patch('app.analysis_result.analysis_result',side_effect=assemble):
        result=recover_final_quality(tmp_path/'unused',analysis,None,gate,tmp_path,Mock(),Mock(),lambda:False)
    assert [c.args[1]['id'] for c in query.call_args_list]==['e']
    assert query.call_args.kwargs['questions']==['Разреши конкретную проблему финальной проверки: unexplained_retained_ranges']
    assert result['events'][1]==other
    relations.assert_not_called()


def test_changed_evidence_calls_scoped_relation_adapter_with_original_dependencies(tmp_path):
    analysis,_=fixture();original=copy.deepcopy(analysis)
    gate={'problems':[{'code':'selection_conflict','recovery_stage':'selection_adjudication','event':'e'}]}
    calls=[{'status':'unresolved','unresolved':[{'event':'e'}]}, {'status':'passed','unresolved':[]}]
    def repair(source,event,*args,**kwargs):
        result=copy.deepcopy(event);result['unit_evidence'][0]['evidence']='New native source proof'
        return result
    def relations(events,transcript,previous,targets,*args,**kwargs):
        assert previous==original and targets=={'e'}
        assert events[0]['story_structure']['status']=='unresolved'
        return {'events':events,'story_structure':{'status':'accepted','history':[]},
                'dialogue_relations':{'status':'accepted'},'recovery_scope':[{'event':'e','unit':'q'}]}
    with patch('app.selection_gate.source_selection_readiness',side_effect=calls), \
         patch('app.selection_adjudication.adjudicate_event',side_effect=repair), \
         patch('app.scoped_relations.recover_relations',side_effect=relations) as scoped, \
         patch('app.analysis_result.analysis_result',side_effect=assemble):
        result=recover_final_quality(tmp_path/'unused',analysis,None,gate,tmp_path,Mock(),Mock(),lambda:False)
    assert scoped.call_count==1 and analysis==original
    assert result['events'][0]['unit_evidence'][0]['evidence']=='New native source proof'
    assert (tmp_path/'story_structure-result.json').is_file()
    assert (tmp_path/'dialogue_relations-result.json').is_file()


def test_unknown_relation_owner_and_invalid_range_do_not_expand_scope(tmp_path):
    analysis,_=fixture()
    problems=[{'code':'missing','recovery_stage':'story_structure','event':'unknown',
               'range':{'start':float('nan'),'end':1000}}]
    assert not problem_owners(problems,analysis['events'])
    problems[0]['range']={'start':2,'end':1}
    with patch('app.scoped_relations.recover_relations') as relations, \
         patch('app.analysis_result.analysis_result',side_effect=assemble):
        recover_final_quality(tmp_path/'unused',analysis,None,{'problems':problems},tmp_path,Mock(),Mock(),lambda:False)
    relations.assert_not_called()


def test_model_session_eligibility_excludes_deterministic_plan_failures():
    assert not needs_model_recovery({'problems':[{'code':'cut_asr_word','recovery_stage':'planner'},
        {'code':'missing_required_dialogue_endpoint','recovery_stage':'continuity'}]})
    assert needs_model_recovery({'problems':[{'code':'missing_original_semantic_ending','recovery_stage':'planner'}]})
    assert needs_model_recovery({'problems':[{'code':'unresolved_transition','recovery_stage':'continuity',
        'transition':{'gap':{'start':1,'end':2}}}]})


def test_no_problem_preserves_events_without_any_model_request(tmp_path):
    analysis,_=fixture();vision=Mock()
    with patch('app.analysis_result.analysis_result',side_effect=assemble):
        result=recover_final_quality(tmp_path/'unused',analysis,None,{'problems':[]},tmp_path,vision,Mock(),lambda:False)
    assert result['events']==analysis['events']
    vision.query.assert_not_called()


def test_opaque_source_failure_does_not_become_accepted_downstream_only(tmp_path):
    import json
    analysis,_=fixture()
    analysis['events'][0].update(analysis_unresolved=True,analysis_unresolved_reasons=[])
    analysis['story_structure']={'status':'accepted','history':[]}
    gate={'problems':[{'code':'story_structure_unresolved','recovery_stage':'story_structure','event':'e'}]}
    with patch('app.scoped_relations.recover_relations') as relations, \
         patch('app.analysis_result.analysis_result',side_effect=assemble):
        result=recover_final_quality(tmp_path/'unused',analysis,None,gate,tmp_path,Mock(),Mock(),lambda:False)
    relations.assert_not_called()
    assert result['events'][0]['analysis_unresolved']
    assert 'source_analysis_unresolved' in result['events'][0]['analysis_unresolved_reasons']
    saved=json.loads((tmp_path/'story_structure-result.json').read_text('utf-8'))
    assert saved['status']=='unresolved'
