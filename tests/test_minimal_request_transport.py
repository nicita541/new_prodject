"""Inspect outgoing wire data without model inference or external requests."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from app.analysis_checks import AnalysisChecks
from app.antigravity_exchange import ManualVision
from app.json_store import atomic_json, read_json
from app.request_payload import compact_prompt
from app.review_scope import target_units
from tests.test_compact_deepseek import packet, prompt


def test_full_mode_specialist_only_receives_concrete_region_units(tmp_path):
    atomic_json(tmp_path/'analysis-settings.json', {'economy_mode':False})
    journal = Mock()
    journal.run.side_effect = lambda name, inputs, callback, producer: callback()
    checks = AnalysisChecks(tmp_path,journal,Mock(),Mock())
    events = [{'id':'op','start':0.,'end':10.,'kind':'opening'},
              {'id':'long','start':10.,'end':200.,'kind':'story'},
              {'id':'unrelated','start':500.,'end':600.,'kind':'story'}]
    snapshot = copy.deepcopy(events)
    received=[]
    def review(chosen):
        received.extend(chosen)
        units=[{'id':'edge','start':10.,'end':15.}, {'id':'unrelated','start':15.,'end':200.}]
        assert [u['id'] for u in target_units(chosen[1],units,'titles')] == ['edge']
        return chosen
    result=checks.targeted('titles',events,review,'deepseek_plan',task='titles')
    assert [e['id'] for e in received] == ['op','long']
    assert result == snapshot and events == snapshot


@pytest.mark.parametrize('economical',[False,True])
def test_no_specialist_target_means_no_query_in_both_modes(tmp_path,economical):
    atomic_json(tmp_path/'analysis-settings.json',{'economy_mode':economical})
    callback=Mock(side_effect=AssertionError('No concrete question'))
    journal=Mock()
    checks=AnalysisChecks(tmp_path,journal,Mock(),Mock())
    events=[{'id':'story','start':0.,'end':400.,'kind':'story','importance':5}]
    assert checks.targeted('source_roles',events,callback,'antigravity_manual',task='source_roles') is events
    callback.assert_not_called(); journal.run.assert_not_called()


def test_ag_wire_is_compact_and_native_signed_contract_remains_exact(tmp_path):
    original=prompt(packet())
    atomic_json(tmp_path/'analysis.meta.json',{'source':'a'*64})
    atomic_json(tmp_path/'probe.json',{'duration':20.})
    vision=ManualVision(tmp_path,lambda:False)
    directory,identifier,request=vision._prepare_request(original,schema={'type':'object'})
    assert read_json(directory/'request.json')['prompt'] == original
    assert request['id'] == identifier
    wire=(directory/'prompt.txt').read_text('utf-8')
    assert 'boundary_reason' not in wire
    assert len(wire) < len(original)
    assert 'CURRENT' in wire and 'Вопрос' in wire


def test_source_validation_retry_does_not_restore_expanded_packet():
    original=prompt(packet())
    suffix='\nThe previous response failed source validation: wrong CURRENT frame\nReinspect ORIGINAL CURRENT.'
    wire=compact_prompt(original+suffix)
    assert wire.endswith(suffix)
    assert 'boundary_reason' not in wire and 'Вопрос' in wire
    assert len(wire) < len(original+suffix)


def test_batch_children_use_same_compaction_without_cross_task_evidence():
    payload=[{'request_id':str(i),'prompt':prompt(packet()),'image_pages':[f'page_{i:03}.jpg'],
              'schema':{'type':'object'}} for i in range(2)]
    original='Process each independent task below using ONLY its assigned image_pages.\n'+json.dumps(payload,ensure_ascii=False)
    wire=compact_prompt(original)
    value=json.loads(wire.split('\n',1)[1])
    assert [r['image_pages'] for r in value['tasks']] == [['page_000.jpg'],['page_001.jpg']]
    assert all('boundary_reason' not in r['prompt'] for r in value['tasks'])
    assert len(wire) < len(original)


def test_unknown_json_fields_survive_lossless_whitespace_encoding():
    data={'CURRENT':{'future_evidence':{'quote':'  точные слова  ','values':[1,True,None]}}}
    original='New independently scoped question\n'+json.dumps(data,ensure_ascii=False,indent=2)
    assert json.loads(compact_prompt(original).split('\n',1)[1]) == data


def test_prior_wider_accepted_view_is_read_only_and_source_revalidated(tmp_path):
    from app.selection_adjudication import _accepted_prior_view
    from tests.test_selection_adjudication import answer
    data=packet(); current=data['CURRENT']
    vision=Mock(supports_image_pages=True)
    def accepted(text, images, schema):
        return 'original-contract',answer(json.loads(text.split('\n')[-1]))
    vision._continuation_replies.find.side_effect=accepted
    with patch('app.selection_adjudication._board',return_value=([tmp_path/'context.jpg'],[{'time':2.5}],{})):
        prior=_accepted_prior_view(vision,tmp_path/'source',{'start':0.,'end':2.},current['units'],
            current['frames'],{'summary':'Previous source hypothesis'},['Existing question'],
            current['ASR'],[],tmp_path,{},lambda:False,0.,3.,[tmp_path/'current.jpg'],[])
    assert prior['checkpoint']=='accepted-reply:original-contract'
    assert prior['decision']['accepted']
    vision.query.assert_not_called()
    vision._continuation_replies.store.assert_not_called()
    unresolved=answer({'CURRENT':current},selection_confidence=.4)
    vision._continuation_replies.find.side_effect=lambda *a:('unresolved',unresolved)
    with patch('app.selection_adjudication._board',return_value=([tmp_path/'context.jpg'],[{'time':2.5}],{})):
        reused=_accepted_prior_view(vision,tmp_path/'source',{'start':0.,'end':2.},current['units'],
            current['frames'],{},['Question'],current['ASR'],[],tmp_path,{},lambda:False,0.,3.,
            [tmp_path/'current.jpg'],[])
    assert reused['checkpoint']=='accepted-reply:unresolved' and not reused['decision']['accepted']
    wrong=answer(current and {'CURRENT':current}); wrong['unit_evidence'][0]['frame_indices']=[2]
    vision._continuation_replies.find.side_effect=lambda *a:('wrong',wrong)
    with patch('app.selection_adjudication._board',return_value=([tmp_path/'context.jpg'],[{'time':2.5}],{})):
        assert _accepted_prior_view(vision,tmp_path/'source',{'start':0.,'end':2.},current['units'],
            current['frames'],{},['Question'],current['ASR'],[],tmp_path,{},lambda:False,0.,3.,
            [tmp_path/'current.jpg'],[]) is None


def test_local_wire_uses_same_compaction_without_model_start(tmp_path):
    from app.vision import LocalVision
    vision=object.__new__(LocalVision)
    vision.cancelled=lambda:False
    vision.port=12345; vision.api_key='offline-test'; vision.cpu_fallback=False
    response=Mock()
    response.read.return_value=b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
    vision.opener=Mock()
    vision.opener.open.return_value.__enter__=Mock(return_value=response)
    vision.opener.open.return_value.__exit__=Mock(return_value=False)
    value=vision._query_impl(prompt(packet()),None,100,{'type':'object'},Mock(),False)
    body=json.loads(vision.opener.open.call_args.args[0].data)
    assert value == {'ok':True}
    assert 'boundary_reason' not in body['messages'][1]['content'][0]['text']


def test_hybrid_uncertain_review_preserves_only_supplied_pages(tmp_path):
    from app.hybrid import HybridVision
    from tests.test_hybrid import Local, FOCUS, focus
    images=[tmp_path/'current.jpg',tmp_path/'necessary-context.jpg']
    for image in images:image.write_bytes(b'bounded source evidence')
    local=Local(tmp_path,focus(confidence=.3))
    remote=Mock(); remote.query.return_value=focus()
    with patch('app.hybrid.DeepSeekVision',return_value=remote):
        result=HybridVision(tmp_path,lambda:False,local).query('Current focus question',images,schema=FOCUS)
    assert result==focus()
    assert remote.query.call_args.args[1]==images
