"""Short wire IDs prevent episode map JSON truncation without changing evidence."""
import copy,json
from unittest.mock import Mock
import pytest
from app.story_review import global_story_review


def catalog():
    return [{'id':f'event_{i:04}.scope_0003','summary':'Exact source fact with an untouched quotation.',
             'kind':'story','importance':4} for i in range(152)]


def test_large_map_roundtrip_preserves_every_source_owner_and_only_short_wire_refs():
    events=catalog();before=copy.deepcopy(events);vision=Mock()
    vision.token_count.return_value=100
    def answer(prompt,**kwargs):
        rows=json.loads(prompt.split('Events: ')[-1])
        assert rows[100]['summary']==before[100]['summary']
        assert rows[0]['id']=='e0' and rows[-1]['id']=='e151'
        assert kwargs['schema']['properties']['keep']['items']['enum']==sorted(r['id'] for r in rows)
        assert 'Dependencies must be sparse' in prompt
        return {'keep':[r['id'] for r in rows[:-1]],'omit':[{'event':'e151','reason':'nonstory',
            'evidence':'Visible production material belongs outside the current chronological episode.',
            'confidence':.95,'reaction_or_humor':False}],
            'dependencies':[{'event':'e1','requires':['e0']}],'narrative_bridges':['e1'],'summary':'Exact source summary.'}
    vision.query.side_effect=answer
    result=global_story_review(vision,events)
    assert result['keep']==[r['id'] for r in before[:-1]]
    assert result['omit'][0]['event']==before[-1]['id']
    assert result['dependencies']==[{'event':before[1]['id'],'requires':[before[0]['id']]}]
    assert result['narrative_bridges']==[before[1]['id']] and events[1]['narrative_bridge']
    assert result['incomplete_event_ids']==[] and vision.query.call_count==1


def test_unknown_short_reference_still_fails_native_validation():
    vision=Mock();vision.token_count.return_value=100
    vision.query.return_value={'keep':['invented'],'omit':[],'dependencies':[],'summary':'Unsupported.'}
    with pytest.raises(ValueError,match='некорректные ссылки'):
        global_story_review(vision,catalog())
    assert vision.query.call_count==1


def test_canonical_ids_are_bound_even_when_source_summaries_are_equal():
    vision=Mock();vision.token_count.return_value=100;prompts=[]
    def answer(prompt,**kwargs):
        prompts.append(prompt)
        return {'keep':[r['id'] for r in json.loads(prompt.split('Events: ')[-1])],
                'omit':[],'dependencies':[],'summary':'Same facts.'}
    vision.query.side_effect=answer
    first=catalog();second=[{**e,'id':e['id']+'.changed'} for e in first]
    global_story_review(vision,first);global_story_review(vision,second)
    assert prompts[0]!=prompts[1]
