"""Committed stages must survive crashes without overwriting source evidence."""
import json
from unittest.mock import patch

import pytest

from app.analysis_continuation import StageJournal
from app.json_store import atomic_json, read_json
from app.pipeline_diagnostics import Diagnostics
from app.source_evidence import capture


def journal(path):
    return StageJournal(path,'a'*64,{'words':[],'segments':[]},[],{},
                        Diagnostics(path),lambda *_:None,lambda:False)


def artifact_path(path,name='titles'):
    record=read_json(path/f'continuation/stages/{name}.json')
    return path/'continuation'/record['artifact']['path']


def test_completed_source_artifact_is_immutable_and_keeps_first_producer(tmp_path):
    stage=journal(tmp_path)
    stage.save('titles',['question'],{'accepted':[1]},'antigravity_manual')
    path=artifact_path(tmp_path); original=path.read_bytes()
    stage.save('titles',['question'],{'accepted':[1]},'deepseek_plan')
    assert path.read_bytes()==original
    assert read_json(tmp_path/'continuation/stages/titles.json')['producer']=='antigravity_manual'
    result=stage.load('titles',['question']);result['accepted'].append(2)
    assert stage.load('titles',['question'])=={'accepted':[1]}


def test_crash_after_artifact_before_manifest_preserves_previous_commit(tmp_path):
    stage=journal(tmp_path)
    stage.save('titles',['old'],{'old':True},'local')
    pointer=tmp_path/'continuation/stages/titles.json'; previous=pointer.read_bytes()
    def fail_commit(path,value):
        if path==pointer: raise OSError('simulated disk full at commit')
        atomic_json(path,value)
    with patch('app.analysis_continuation.atomic_json',side_effect=fail_commit):
        with pytest.raises(OSError): stage.save('titles',['new'],{'new':True},'deepseek_plan')
    assert pointer.read_bytes()==previous
    assert stage.load('titles',['old'])=={'old':True}
    assert stage.load('titles',['new']) is None
    stage.save('titles',['new'],{'new':True},'deepseek_plan')
    assert stage.load('titles',['new'])=={'new':True}


def test_corrupted_artifact_is_a_miss_and_repair_preserves_damaged_bytes(tmp_path):
    stage=journal(tmp_path);stage.save('titles',[],{'ready':True},'local')
    original=artifact_path(tmp_path); original.write_bytes(b'{torn')
    assert stage.load('titles',[]) is None
    stage.save('titles',[],{'ready':True},'deepseek_plan')
    assert original.read_bytes()==b'{torn'
    assert artifact_path(tmp_path)!=original
    assert stage.load('titles',[])=={'ready':True}


def test_artifact_pointer_cannot_escape_store_or_hide_tampered_output(tmp_path):
    stage=journal(tmp_path);stage.save('titles',[],{'ready':True},'local')
    pointer=tmp_path/'continuation/stages/titles.json'
    valid=read_json(pointer)
    forged={**valid,'artifact':{**valid['artifact'],'path':'../../outside.json'}}
    atomic_json(pointer,forged)
    assert stage.load('titles',[]) is None
    atomic_json(pointer,{**valid,'output':{'ready':False}})
    assert stage.load('titles',[]) is None


def test_legacy_embedded_stage_remains_readable_but_bad_hash_is_rejected(tmp_path):
    stage=journal(tmp_path);stage.save('titles',[],{'legacy':True},'local')
    pointer=tmp_path/'continuation/stages/titles.json'
    record=read_json(artifact_path(tmp_path));atomic_json(pointer,record)
    assert stage.load('titles',[])=={'legacy':True}
    atomic_json(pointer,{**record,'output':{'legacy':False}})
    assert stage.load('titles',[]) is None


def test_source_facts_are_independent_of_editorial_code_and_do_not_mutate_inputs(tmp_path):
    stage=journal(tmp_path)
    transcript={'words':[],'segments':[],'provenance':{'mode':'provided'}}
    probe={'duration':10,'audio_stream':0}; shots=[{'start':0,'end':10}]
    perception={'source':{'sha256':'a'*64},'samples':[{'time':0,'motion_score':0}]}
    preparation={'transcript':{'mode':'provided'},'audio':{'audio_stream':0}}
    saved=capture(stage,probe,transcript,shots,[],perception,preparation)
    stored=artifact_path(tmp_path,'source_evidence');before=stored.read_bytes()
    stage.context['story_code']='changed-story';stage.context['late_code']='changed-framing'
    stage.context['profile']={'retention':'different'}
    assert capture(stage,probe,transcript,shots,[],perception,preparation)==saved
    assert stored.read_bytes()==before
    shots[0]['end']=1;perception['samples'][0]['motion_score']=99
    assert json.loads(before)['output']['shots'][0]['end']==10
    assert saved['perception']['samples'][0]['motion_score']==0
