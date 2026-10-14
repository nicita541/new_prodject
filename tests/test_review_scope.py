"""Draft scopes narrow provider CURRENT without approving untouched source."""
import copy
from unittest.mock import Mock
import pytest
from app.review_scope import source_windows, project_events, candidate_plan, accepted_prefix
from app.planner import build_plan, validate_plan
from tests.test_planner import analysis


def event(identifier='event', start=0, end=30):
    return {'id':identifier,'scene_id':identifier,'start':start,'end':end,'kind':'story','importance':3,
        'requires':[],'focus':[],'boundary_times':[], 'analysis_unresolved':True,
        'units':[{'id':f'u{i}','start':float(t),'end':float(t+5),'text':''} for i,t in enumerate(range(start,end,5))],
        'selected_ranges':[{'start':float(start+5),'end':float(start+10)}, {'start':float(start+20),'end':float(start+25)}]}


def draft(identifier='event', ranges=((5,10),(20,25))):
    return {'draft':True,'parts':[{'cuts':[{'event_ids':[identifier],'start':a,'end':b} for a,b in ranges]}]}


def test_selected_windows_cover_only_needed_real_units_and_preserve_unresolved_source():
    original=event(); before=copy.deepcopy(original)
    windows, counters=source_windows([original],draft(),{'words':[]},[])
    assert [(w['start'],w['end']) for w in windows]==[(5,10),(20,25)]
    assert counters['review_units']==2 and counters['source_units']==6
    current=project_events([original],windows)
    assert [u['id'] for e in current for u in e['units']]==['u1','u4']
    assert all(e['analysis_unresolved'] for e in current)
    assert original==before and current[1]['id']=='event.scope_0001'


def test_cropped_window_does_not_inherit_whole_parent_state():
    original=event(); original.update(state_before={'location':'whole start'},state_after={'location':'whole end'})
    windows,_=source_windows([original],draft(),{},[])
    result=project_events([original],windows)
    assert all(e['state_before'] is None and e['state_after'] is None for e in result)


def test_cropped_window_keeps_only_its_verified_story_geometry():
    from app.source_roles import verified_story_ranges,confirmed_exclusions
    original=event(); original['verified_current_story_ranges']=[{'start':0.,'end':30.}]
    windows,_=source_windows([original],draft(),{},[])
    result=project_events([original],windows)
    assert [verified_story_ranges(e) for e in result]==[[{'start':5.,'end':10.}],[{'start':20.,'end':25.}]]
    assert all(confirmed_exclusions(e)==[] for e in result)


def test_cropped_sequence_reuses_parent_proof_without_inventing_new_boundaries():
    from app.source_roles import confirmed_exclusions,verified_story_ranges
    original=event(); original['confirmed_opening_ranges']=[{'start':5.,'end':20.}]
    proof={'start':5.,'end':20.,'version':8,'kind':'opening','boundaries_verified':True,
        'anchors_verified':True,'confidence':.95,'checkpoint':'a'*64+'.json',
        'anchors':[{'unit':'u1','type':'theme_credit','visible_text':'Opening theme'}]}
    original['confirmed_opening_proofs']=[proof]
    original['verified_current_story_ranges']=[{'start':0.,'end':30.}]
    windows,_=source_windows([original],draft(ranges=((10,15),)),{},[])
    child=project_events([original],windows)[0]
    assert child['source_window']['parent_sequence_proofs']==[proof]
    assert 'confirmed_opening_proofs' not in child
    assert confirmed_exclusions(child)==[{'start':10.,'end':15.}]
    assert verified_story_ranges(child)==[]


def test_final_plan_cannot_expand_speech_handles_into_unreviewed_source():
    from app.review_scope import attach_scope
    data=analysis(30); original=event(); original.pop('analysis_unresolved')
    original.update(unit_selection_version=1,selected_ranges=[{'start':5.,'end':10.}])
    windows,_=source_windows([original],draft(ranges=((5,10),)),{},[])
    data['events']=project_events([original],windows)
    attach_scope(data)
    result=build_plan(data)
    assert all(5 <= c['start'] < c['end'] <= 10 for p in result['parts'] for c in p['cuts'])
    outside=copy.deepcopy(result); outside['parts'][0]['cuts'][0]['start']=4.9
    with pytest.raises(ValueError,match='source_scope_unreviewed'):
        validate_plan(outside,data)


def test_dramatic_plan_preserves_reviewed_scope_with_speech_padding():
    from app.review_scope import attach_scope
    from app.dramatic_planner import build_dramatic_plan
    from tests.test_profile_planner_integration import analysis_fixture
    from app.source_ranges import subtract_ranges
    data = analysis_fixture()
    data['transcript'] = {'words':[{'start':20.1,'end':21.9,'text':'Dialogue'}],
                          'segments':[{'start':20.1,'end':21.9,'text':'Dialogue'}]}
    attach_scope(data)
    plan = build_dramatic_plan(data)
    assert plan['parts']
    assert all(not subtract_ranges([c],data['review_scope']['ranges'])
               for p in plan['parts'] for c in p['cuts'])


def test_required_event_context_is_included_and_refs_remapped():
    first=event('setup',0,30); last=event('payoff',30,60); last['requires']=['setup']
    windows,_=source_windows([first,last],draft('payoff',((35,40),)),{'words':[]},[])
    current=project_events([first,last],windows)
    payoff=next(e for e in current if e['source_window']['parent_event']=='payoff')
    assert payoff['requires']==['setup.scope_0000']
    assert any(e['source_window']['parent_event']=='setup' for e in current)


def test_needed_causal_unit_is_reserved_without_inventing_proof():
    source=event(); source['causal_links']=[{'from':'u0','to':'u1'},{'from':'foreign','to':'u1'}]
    windows,counts=source_windows([source],draft(ranges=((5,10),)),{},[])
    result=project_events([source],windows)
    assert [u['id'] for u in result[0]['units']]==['u0','u1']
    assert counts['review_units']==2 and result[0]['analysis_unresolved'] is True


def test_draft_is_non_exportable_and_does_not_fabricate_acceptance(tmp_path):
    original=event(); data=analysis(30); data['events']=[original]
    original['unit_selection_version']=1
    before=copy.deepcopy(data)
    result=candidate_plan(data['events'],data['transcript'],[],data['probe'],tmp_path)
    assert result['draft'] is True and data==before
    with pytest.raises(ValueError,match='экспорта'):
        validate_plan(result,data)
    with pytest.raises(ValueError,match='analysis_unresolved'):
        build_plan(data)


def test_draft_accepts_zero_priority_excluded_source_without_promoting_it(tmp_path):
    data=analysis(60); first=event(); omitted=event('omit',30,60)
    omitted.update(importance=0,selected_ranges=[],global_excluded=True)
    result=candidate_plan([first,omitted],data['transcript'],[],data['probe'],tmp_path)
    assert 'omit' not in result['selected_event_ids'] and omitted['importance']==0


def test_draft_preserves_whole_words_and_actual_needed_context(tmp_path):
    data=analysis(30); source=event(); source['unit_selection_version']=1
    data['events']=[source]
    data['transcript']={'words':[{'start':4.7,'end':5.4,'text':'word'}],
                        'segments':[{'start':4.7,'end':5.4,'text':'word'}]}
    result=candidate_plan([source],data['transcript'],[],data['probe'],tmp_path)
    for part in result['parts']:
        for cut in part['cuts']:
            assert not 4.7 < cut['start'] < 5.4 and not 4.7 < cut['end'] < 5.4


def test_draft_does_not_restore_all_asr_segments_from_a_provisional_scene(tmp_path):
    data=analysis(30); source=event(); source['selected_ranges']=[{'start':5.,'end':10.}]
    words=[{'start':float(i),'end':i+.3,'text':str(i)} for i in range(30)]
    transcript={'words':words,'segments':[{'start':0.,'end':30.,'text':'all words'}]}
    result=candidate_plan([source],transcript,[],data['probe'],tmp_path)
    assert sum(p['duration'] for p in result['parts']) < 7


def test_invalid_unit_gaps_and_unknown_dependencies_do_not_expand_to_full_source():
    source=event(); source['units'].pop(2)
    with pytest.raises(ValueError,match='cover'):
        source_windows([source],draft(),{},[])
    source=event(); source['requires']=['unknown']
    with pytest.raises(ValueError,match='prerequisite'):
        source_windows([source],draft(),{},[])


def test_partial_prefix_never_invokes_model_and_stops_at_first_missing_output(tmp_path):
    journal=Mock(); journal.load.return_value=None
    original=event()
    restored, names=accepted_prefix([original],journal,tmp_path,{'words':[]},[],30)
    assert restored==[original] and names=={}
    journal.load.assert_called_once_with('story_refinement',[original])


def test_accepted_prefix_preserves_producer_and_skips_its_model_callback(tmp_path):
    from app.json_store import atomic_json
    from app.analysis_checks import AnalysisChecks
    original = event()
    accepted = copy.deepcopy(original)
    accepted['summary'] = 'Accepted source understanding'
    journal = Mock()
    journal.load.side_effect = [[accepted], None]
    atomic_json(tmp_path/'continuation/stages/story_refinement.json', {'producer':'antigravity_manual'})
    restored, producers = accepted_prefix([original],journal,tmp_path,{'words':[],'segments':[]},[],30)
    assert restored == [accepted] and producers == {'story_refinement':'antigravity_manual'}
    checks = AnalysisChecks(tmp_path,journal,Mock(),Mock())
    checks.prepared = producers
    callback = Mock(side_effect=AssertionError('Must reuse accepted work'))
    assert checks.run('story_refinement',restored,callback,'deepseek_plan') == restored
    callback.assert_not_called()
    journal.run.assert_not_called()
    checks.diagnostics.event.assert_called_once_with('story_refinement','cache_hit',scope='stage',
        producer='antigravity_manual',source='accepted_full_pass_prefix')


def test_candidate_preferences_invalidate_final_cache_identity():
    from app.analysis import derived_story_identity
    first = derived_story_identity('same','deepseek_plan',economy_mode=True,
        review_settings={'version':1,'planning':{'preferred_part_count':3}})
    changed = derived_story_identity('same','deepseek_plan',economy_mode=True,
        review_settings={'version':1,'planning':{'preferred_part_count':5}})
    assert first != changed


def test_selective_story_keeps_real_episode_duration(tmp_path):
    from unittest.mock import patch
    from app.scene_refinement import refine_scene_story
    source = event(); source['summary'] = 'Candidate'
    vision = Mock(supports_query_batch=False)
    with patch('app.story.refine_story',side_effect=lambda rows,*a,**kw: rows) as refine:
        result = refine_scene_story([source],{'words':[]},[],tmp_path,vision,Mock(),lambda:False,
                                    episode_duration=1420.173055)
    assert result[0]['end'] == 30
    assert refine.call_args.kwargs['episode_duration'] == 1420.173055


def test_adjudication_dispatches_only_candidate_source_windows(tmp_path):
    from unittest.mock import patch
    from app.selection_gate import adjudicate_selections
    original=event()
    windows,_=source_windows([original],draft(),{},[])
    current=project_events([original],windows)
    calls=[]
    def inspect(source,e,*args,**kwargs):
        calls.extend(u['id'] for u in e['units'])
        return e
    with patch('app.selection_adjudication.adjudicate_event',side_effect=inspect):
        result=adjudicate_selections(None,current,{},[],tmp_path,None,lambda *a:None,lambda:False)
    assert calls==['u1','u4']
    assert all(e['analysis_unresolved'] for e in result)


def test_existing_credit_checks_are_limited_to_detection_plus_five_seconds():
    before=event('before',0,20); opening=event('opening',20,30); after=event('after',30,60)
    opening['kind']='opening'
    windows,counts=source_windows([before,opening,after],draft('after',((45,50),)),{},[])
    targeted=[w for w in windows if 'credits' in w['review_targets']]
    assert [(w['start'],w['end']) for w in targeted] == [(15,20),(20,30),(30,35)]
    assert counts['review_units']==5
    assert not any('closing' in w['review_targets'] for w in windows)
    assert next(w for w in windows if w['start']==45)['review_targets']==[]


def test_existing_ending_check_does_not_scan_unrelated_late_scene():
    normal=event('normal',30,60); ending=event('ending',60,70); ending['kind']='ending'
    windows,_=source_windows([normal,ending],draft('normal',((40,45),)),{},[])
    assert [(w['start'],w['end']) for w in windows if 'closing' in w['review_targets']]==[(55,60),(60,70)]
    assert next(w for w in windows if w['start']==40)['review_targets']==[]


def test_specialist_calls_only_existing_target_windows_and_keeps_others(tmp_path):
    from app.analysis_checks import AnalysisChecks
    journal=Mock(); journal.run.side_effect=lambda name,inputs,callback,producer: callback()
    checks=AnalysisChecks(tmp_path,journal,Mock(),Mock())
    chosen=event('credits'); chosen['review_targets']=['titles']
    untouched=event('story'); untouched['review_targets']=[]
    callback=Mock(side_effect=lambda rows:[{**r,'specialist_checked':True} for r in rows])
    result=checks.targeted('titles',[chosen,untouched],callback,'deepseek_plan',task='titles')
    assert [r['id'] for r in callback.call_args.args[0]]==['credits']
    assert result[0]['specialist_checked'] is True and result[1] is untouched
    callback.reset_mock(); journal.reset_mock()
    assert checks.targeted('titles',[untouched],callback,'deepseek_plan',task='titles')==[untouched]
    callback.assert_not_called(); journal.run.assert_not_called()
    assert any(c.kwargs.get('reason')=='not_needed' for c in checks.diagnostics.event.call_args_list)


def test_cropped_storyboard_uses_its_own_id_without_overwriting_parent(tmp_path):
    from unittest.mock import patch
    source=event(); windows,_=source_windows([source],draft(ranges=((5,10),)),{},[])
    visual=tmp_path/'visual'; visual.mkdir(); original=visual/'event.jpg'; original.write_bytes(b'original-source')
    with patch('app.source_identity.source_identity',return_value={'sha256':'source'}), \
         patch('app.vision.inference_storyboard',return_value=[5.5]) as board:
        result=project_events([source],windows,directory=tmp_path,source=tmp_path/'source.mp4')
    assert board.call_args.args[4] == visual/(result[0]['id']+'.jpg')
    assert result[0]['id']=='event.scope_0000' and original.read_bytes()==b'original-source'


def test_unneeded_old_check_is_dimmed_and_never_reported_completed(tmp_path):
    import json
    from app.json_store import atomic_json
    from app.job_progress import analysis_passes
    audit=tmp_path/'diagnostics/pipeline'; atomic_json(audit/'run.json',{'run_id':'run'})
    (audit/'timeline.jsonl').write_text('\n'.join(json.dumps({'run_id':'run','stage':'titles','action':action,
        **({'reason':'not_needed'} if action=='skipped' else {})}) for action in ('start','skipped','end')),'utf-8')
    row=analysis_passes({'status':'running','stage':'analyze'},tmp_path)['titles']
    assert row['status']=='disabled' and row['phase']=='Не потребовалось'
