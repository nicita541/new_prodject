"""Downstream metadata churn must not resend unchanged unresolved source work."""
import copy

from app.final_quality import recovery_stalled,source_recovery_identity


def gate(owners, downstream=()):
    return {'status':'unresolved','problems':[
        {'code':'unresolved_source_selection','event':owner,'recovery_stage':'selection_adjudication'}
        for owner in owners]+list(downstream)}


def history(before,after,identities=('same-source','same-source')):
    return [{'gate':before,'source_recovery_identity':identities[0]},
            {'gate':after,'source_recovery_identity':identities[1]}]


def test_same_failed_source_owners_stop_even_when_relation_errors_change():
    first=gate(['a','b'],[{'code':'story_structure_unresolved','event':'a','recovery_stage':'story_structure'}])
    second=gate(['a','b'],[{'code':'unexplained_story_structure_unit','event':'a','unit':'u',
                           'recovery_stage':'story_structure'}])
    assert recovery_stalled(history(first,second))


def test_resolved_owner_new_owner_or_changed_role_can_continue():
    before=gate(['a','b'])
    assert not recovery_stalled(history(before,gate(['b'])))
    assert not recovery_stalled(history(before,gate(['a','b','c'])))
    changed=gate(['a','b']);changed['problems'][0]['recovery_stage']='source_roles'
    assert not recovery_stalled(history(before,changed))


def test_changed_source_selection_or_boundaries_allow_different_evidence():
    before=gate(['a']);after=gate(['a'],[{'code':'story_structure_unresolved'}])
    assert not recovery_stalled(history(before,after,('old-source','new-source')))
    assert not recovery_stalled(history(before,before,('old-source','new-source')))


def test_relation_only_work_does_not_get_misclassified_as_source_stall():
    assert not recovery_stalled(history(gate([], [{'code':'story_structure_unresolved'}]),
                                       gate([], [{'code':'dialogue_relations_unresolved'}])))


def test_identity_ignores_failed_response_metadata_but_tracks_actual_source_scope():
    analysis={'probe':{'duration':100},'transcript':{'segments':[],'words':[]},
        'events':[{'id':'a','start':0,'end':10,'selected_ranges':[{'start':0,'end':10}],
                   'units':[{'id':'u','start':0,'end':10,'text':'Original source words'}]}]}
    original=copy.deepcopy(analysis)
    identity=source_recovery_identity(analysis)
    analysis['events'][0].update(analysis_unresolved_reasons=['story_structure_unresolved'],
        selection_adjudication={'decisions':[{'confidence':.85}]},story_structure={'status':'unresolved'})
    assert source_recovery_identity(analysis)==identity
    analysis['events'][0]['selected_ranges'][0]['end']=8
    assert source_recovery_identity(analysis)==identity  # Failed fallback is not new CURRENT evidence.
    analysis['events'][0]['units'][0]['end']=8
    assert source_recovery_identity(analysis)!=identity
    assert original['events'][0]['selected_ranges'][0]['end']==10
