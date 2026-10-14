"""A pending source-window focus survives source repair and warm assembly."""
import copy
from unittest.mock import Mock,patch

from app.quality_recovery import recover_final_quality
from tests.test_final_quality import fixture


def test_nonboundary_repair_preserves_pending_framing_obligation(tmp_path):
    analysis,_=fixture()
    analysis['scoped_framing_pending_event_ids']=['e']
    analysis['events'][0]['framing_refresh']={'status':'pending','provider':'local'}
    gate={'problems':[{'code':'selection_conflict','recovery_stage':'selection_adjudication','event':'e'}]}
    with patch('app.selection_gate.source_selection_readiness',return_value={
            'status':'unresolved','unresolved':[{'event':'e'}]}), \
         patch('app.selection_adjudication.adjudicate_event',side_effect=lambda s,e,*a,**k:e), \
         patch('app.analysis_result.analysis_result',side_effect=lambda d,p,pr,t,s,e,**kw:{'events':e}), \
         patch('app.scoped_owner_refresh.finish_scoped_framing') as focus:
        result=recover_final_quality(tmp_path/'unused',analysis,None,gate,tmp_path,Mock(),Mock(),lambda:False)
    assert result['scoped_framing_pending_event_ids']==['e']
    assert result['events'][0]['framing_refresh']['status']=='pending'
    focus.assert_not_called()


def test_native_analysis_assembly_restores_pending_obligation(tmp_path):
    from app.analysis_result import analysis_result
    analysis,_=fixture();analysis['probe']['fps']=24
    analysis['events'][0]['framing_refresh']={'status':'pending','provider':'local'}
    result=analysis_result(tmp_path,'deepseek_plan',analysis['probe'],analysis['transcript'],
                           analysis['shots'],analysis['events'],scenes=analysis['scenes'])
    assert result['scoped_framing_pending_event_ids']==['e']
    assert result['events']==analysis['events']


def test_plan_only_pending_framing_never_opens_a_model_session(tmp_path):
    import pytest
    from app.quality_recovery import finish_pending_framing
    analysis,_=fixture()
    analysis['events'][0]['framing_refresh']={'status':'pending','provider':'local'}
    with patch('app.vision.vision_session',side_effect=AssertionError('Plan-only cannot run inference')) as session:
        with pytest.raises(ValueError,match='уточнения кадрирования'):
            finish_pending_framing(tmp_path/'unused',analysis,tmp_path,Mock(),lambda:False,allow_new_session=False)
    session.assert_not_called()
