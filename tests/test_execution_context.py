"""Correlation must survive nested/retried calls without changing cache identity."""
from contextvars import copy_context
import json
from unittest.mock import patch

import pytest

from app.execution_context import scope, snapshot
from app.model_perf import measure_request, purpose
from app.pipeline_diagnostics import Diagnostics
from app.token_usage import record, summary


def rows(path):
    return [json.loads(line) for line in path.read_text('utf-8').splitlines()]


def test_nested_attempt_stage_and_request_match_actual_tokens_and_restore(tmp_path):
    with scope(job_id='job', attempt_id='a'*32):
        diagnostics = Diagnostics(tmp_path)
        diagnostics.start(run_id='a'*32)
        with diagnostics.stage('dialogue_relations'), purpose('pacing'):
            with measure_request(tmp_path, 'deepseek-flash', pages=2, prompt_chars=100,
                                 max_tokens=100, thinking=False, cpu=False) as trace:
                response = {'usage':{'prompt_tokens':30,'completion_tokens':10,'total_tokens':40}}
                trace.response(response)
                record(tmp_path,'deepseek','deepseek-flash',response)
                assert copy_context().run(snapshot) == snapshot()
        assert snapshot() == {'job_id':'job','attempt_id':'a'*32}
    assert snapshot() == {}
    usage = rows(tmp_path/'token-usage.jsonl')[0]
    perf = rows(tmp_path/'model-performance.jsonl')
    assert usage['request_id'] == perf[0]['id'] == perf[1]['id']
    assert usage['attempt_id'] == perf[0]['attempt_id'] == 'a'*32
    assert usage['stage'] == 'dialogue_relations'
    assert usage['purpose'] == 'pacing'
    assert perf[0]['analysis_stage'] == 'dialogue_relations'
    assert summary(tmp_path,attempt_id='a'*32)['all_tokens'] == 40
    assert summary(tmp_path,attempt_id='b'*32)['all_tokens'] == 0
    assert json.loads((tmp_path/'diagnostics/pipeline/run.json').read_text())['run_id'] == 'a'*32


def test_context_rejects_media_and_resets_after_failure():
    for fields in ({'prompt':'private'},{'stage':'C:/private/frame.jpg'},
                   {'transport_attempt':True},{'attempt_id':'line\nsecret'}):
        with pytest.raises(ValueError), scope(**fields):
            pass
    with pytest.raises(RuntimeError), scope(stage='framing'):
        raise RuntimeError('private')
    assert snapshot() == {}


def test_cloud_format_retry_and_cache_have_truthful_separate_transport_records(tmp_path):
    from app import deepseek
    schema={'type':'object','properties':{'keep':{'type':'boolean'}},'required':['keep'],
            'additionalProperties':False}
    def answer(text):
        return {'choices':[{'message':{'content':text}}],
                'usage':{'prompt_tokens':30,'completion_tokens':10,'total_tokens':40}}
    client=deepseek.DeepSeekVision(tmp_path,lambda:False)
    with patch.object(deepseek,'RESPONSES',tmp_path/'responses'), \
         patch.object(deepseek,'_key',return_value='fake-test-key'), \
         patch.object(deepseek.time,'sleep'), \
         patch.object(deepseek.time,'monotonic',side_effect=range(10000)), \
         patch.object(client,'_fetch',side_effect=[answer('{}'),answer('{"keep":true}')]) as fetch:
        with scope(job_id='job',attempt_id='a'*32,stage='story_structure_analysis'):
            assert client.query('supplied source only',schema=schema)=={'keep':True}
            assert client.query('supplied source only',schema=schema)=={'keep':True}
        assert fetch.call_count==2
    usage=rows(tmp_path/'token-usage.jsonl')
    assert [row['transport_attempt'] for row in usage]==[1,2]
    assert len({row['logical_request_id'] for row in usage})==1
    assert len({row['request_id'] for row in usage})==2
    assert summary(tmp_path)['all_tokens']==80
    starts=[row for row in rows(tmp_path/'model-performance.jsonl') if row['event']=='request_start']
    assert {row['id'] for row in starts}=={row['request_id'] for row in usage}
    timeline=rows(tmp_path/'diagnostics/pipeline/timeline.jsonl')
    assert sum(row['action']=='cache_hit' for row in timeline)==1


def test_optional_cache_diagnostic_failure_never_triggers_another_paid_request(tmp_path):
    from app import deepseek
    client=deepseek.DeepSeekVision(tmp_path,lambda:False)
    raw={'choices':[{'message':{'content':'{"ok":true}'}}]}
    with patch.object(deepseek,'RESPONSES',tmp_path/'responses'), \
         patch.object(deepseek,'_key',return_value='fake-test-key'), \
         patch.object(client,'_fetch',return_value=raw) as fetch:
        assert client.query('source')=={'ok':True}
        with patch.object(Diagnostics,'event',side_effect=OSError('disk full')):
            assert client.query('source')=={'ok':True}
        assert fetch.call_count==1


def test_remote_latency_is_not_reported_as_local_model_time(tmp_path):
    from scripts.export_safe_ai_diagnostics import model_perf_summary
    with measure_request(tmp_path,'deepseek-flash',pages=0,prompt_chars=5,
                         max_tokens=10,thinking=False,cpu=False):
        pass
    result=model_perf_summary(tmp_path)
    assert result['overall_local_models'] is None
    assert result['overall_remote_models']['requests']==1
