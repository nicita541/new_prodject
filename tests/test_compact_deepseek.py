"""Less wire text without losing source evidence, cache lineage or validation."""
import copy,hashlib,json
from unittest.mock import Mock
import pytest
from app import deepseek as api
from app.selection_adjudication import ADJUDICATION_PROMPT,adjudication_schema
from tests.test_selection_adjudication import answer


def packet():
    units=[{'id':'A','start':0.,'end':1.,'text':'Да','frame_indices':[1],'boundary_reason':['source_unit']},
           {'id':'B','start':1.,'end':2.,'text':'','frame_indices':[2],'boundary_reason':['source_unit']}]
    words=[{'start':0.,'end':.5,'text':'Да','probability':.99}]
    prior=[{'start':-1.,'end':0.,'text':'Вопрос','probability':.99}]
    asr={'words':words,'segments':[{'start':0.,'end':1.,'text':'Да'}]}
    before={'words':prior,'segments':[{'start':-1.,'end':0.,'text':'Вопрос'}]}
    payload={'CURRENT':{'start':0.,'end':2.,'units':units,'frames':[{'index':1,'time':.5},{'index':2,'time':1.5}],
                       'ASR':asr,'confirmed_exclusions':[]},
        'CONTEXT_ONLY':[{'role':'BEFORE_CONTEXT_ONLY','frames':[{'index':1,'time':-.5,'source_sha256':'source'}],'ASR':before}],
        'CONTEXT_ASR_ONLY':[{'role':'BEFORE_CONTEXT_ONLY','start':-8.,'end':0.,'ASR':before}],
        'image_roles':['CURRENT','BEFORE_CONTEXT_ONLY'],'questions':['Проверить источник ответа'],
        'HYPOTHESES':{'summary':'Старое описание','prior_decisions':[{'summary':'Старое описание','uncertain':True}],
                      'previous_selected_ranges':[{'start':0.,'end':2.}]}}
    return payload


def prompt(payload):
    return ADJUDICATION_PROMPT+'\n'+json.dumps(payload,ensure_ascii=False,sort_keys=True)


def expand(schema):
    root=schema
    def visit(node):
        if isinstance(node,list): return [visit(v) for v in node]
        if not isinstance(node,dict): return node
        if set(node)=={'$ref'}: return visit(root['$defs'][node['$ref'].split('/')[-1]])
        return {k:visit(v) for k,v in node.items() if k!='$defs'}
    return visit(schema)


def test_factored_schema_expands_to_exact_native_contract():
    data=packet(); schema=adjudication_schema(data['CURRENT']['units'],data['CURRENT']['frames'])
    compact=api._schema_specification(schema)
    assert expand(json.loads(compact))==schema
    assert len(compact)<len(json.dumps(schema,ensure_ascii=False))
    schema['$id']='https://schema.example/own-scope'
    assert json.loads(api._schema_specification(schema))==schema


def test_compact_packet_preserves_source_facts_without_asr_and_history_duplicates():
    data=packet(); before=copy.deepcopy(data)
    compact=api._selection_wire_prompt(prompt(data))
    result=json.loads(compact.split('\n')[-1])
    assert data==before and len(compact)<len(prompt(data))
    assert result['CURRENT']['units']==[{k:u[k] for k in ('id','start','end','text','frame_indices')} for u in data['CURRENT']['units']]
    assert result['CURRENT']['frames']==data['CURRENT']['frames']
    assert result['CURRENT']['confirmed_exclusions']==data['CURRENT']['confirmed_exclusions']
    assert result['image_roles']==data['image_roles'] and result['questions']==data['questions']
    assert 'ASR' not in result['CURRENT'] and 'ASR' not in result['CONTEXT_ONLY'][0]
    assert result['CONTEXT_ASR_ONLY'][0]['ASR']['words']==[[-1.,0.,'Вопрос']]
    assert result['HYPOTHESES']['descriptions']==['Старое описание']


def test_different_or_uncertain_speech_is_never_silently_lost():
    data=packet(); data['CURRENT']['ASR']['words'][0]['text']='Другое'
    data['CONTEXT_ONLY'][0]['ASR']= {'words':[{'start':-.8,'end':-.1,'text':'Другое'}],'segments':[]}
    result=json.loads(api._selection_wire_prompt(prompt(data)).split('\n')[-1])
    assert result['CURRENT']['ASR']['words'][0][2]=='Другое'
    assert result['CONTEXT_ONLY'][0]['ASR']['words'][0][2]=='Другое'
    data['CURRENT']['ASR']['words'][0]['probability']=.3
    result=json.loads(api._selection_wire_prompt(prompt(data)).split('\n')[-1])
    assert result['CURRENT']['ASR']['low_confidence_words'][0]['probability']==.3


def test_unknown_and_source_validation_retry_packets_keep_full_instructions():
    data=packet(); original=prompt(data)
    retry=original+'\nThe previous response failed source validation'
    assert api._selection_wire_prompt(retry)==retry
    assert api._selection_wire_prompt('another task')=='another task'
    data['new_contract_field']=True
    assert api._selection_wire_prompt(prompt(data))==prompt(data)


@pytest.fixture
def vision(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'RESPONSES',tmp_path/'responses')
    monkeypatch.setattr(api,'_key',lambda:'offline-test')
    monkeypatch.setattr(api.time,'sleep',lambda *a:None)
    ticks=iter(range(10000)); monkeypatch.setattr(api.time,'monotonic',lambda:next(ticks))
    return api.DeepSeekVision(tmp_path,lambda:False)


def envelope(value):
    return {'choices':[{'message':{'content':json.dumps(value)}}]}


def old_body(text,schema):
    specification=json.dumps(schema,ensure_ascii=False)
    text+= ('\nThe following JSON schema is a specification, DO NOT output it. '
        'Return a concrete JSON instance with actual values matching the specification. '
        'Do not return schema definitions or type/properties/enum keys. '
        'Return compact JSON only, no explanation.\nSchema specification: '+specification)+api._response_discipline(schema)
    return {'model':api.MODEL,'messages':[{'role':'system','content':api.SYSTEM},
        {'role':'user','content':[{'type':'text','text':text}]}],
        'max_tokens':api.answer_budget(2400),'temperature':.15,'thinking':{'type':'disabled'},
        'response_format':{'type':'json_object'},'stream':False}


def test_existing_full_packet_response_cache_survives_wire_change(vision,monkeypatch):
    data=packet(); schema=adjudication_schema(data['CURRENT']['units'],data['CURRENT']['frames'])
    value=answer(data); body=old_body(prompt(data),schema)
    key=hashlib.sha256(json.dumps({'profile':api.PROFILE,'request':body},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    api.atomic_json(api.target_cache_path(key),{'request':key,'result':value})
    fetch=Mock(side_effect=AssertionError('Accepted old answer must not be sent again'))
    monkeypatch.setattr(vision,'_fetch',fetch)
    assert vision.query(prompt(data),max_tokens=2400,schema=schema)==value
    fetch.assert_not_called()


def test_images_unchanged_and_full_schema_rejects_wrong_unit_frames(vision,tmp_path,monkeypatch):
    data=packet(); schema=adjudication_schema(data['CURRENT']['units'],data['CURRENT']['frames'])
    value=answer(data); invalid=copy.deepcopy(value)
    invalid['unit_evidence'][0]['frame_indices']=[2]
    images=[tmp_path/'current.jpg',tmp_path/'before.jpg']
    for i,path in enumerate(images): path.write_bytes(('source'+str(i)).encode())
    fetch=Mock(side_effect=[envelope(invalid),envelope(value)])
    monkeypatch.setattr(vision,'_fetch',fetch)
    assert vision.query(prompt(data),images,max_tokens=2400,schema=schema)==value
    assert fetch.call_count==2
    first,second=[c.args[0]['messages'][1]['content'] for c in fetch.call_args_list]
    assert first[1:]==second[1:] and len(first)==3
    assert first[0]['text'].startswith(api._SELECTION_WIRE_INSTRUCTION)
    assert second[0]['text'].startswith(api._SELECTION_WIRE_INSTRUCTION)
    assert 'previous response was rejected' in second[0]['text']
    assert 'boundary_reason' not in second[0]['text']
