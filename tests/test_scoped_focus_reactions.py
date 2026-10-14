"""Exact source-sample reuse and independent reaction/humor preferences."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from app.editorial import DEFAULT_PROFILE, DRAMATIC_PROFILE
from app.editorial_reactions import preserve_reaction, preserve_unit_reaction, reaction_instruction
from app.framing import refine_focus
from app.pacing import apply_review
from app.story import _positive_story_proof, verify_omissions
from app.story_review import apply_global_selection
from tests.test_framing import FakeReader, FakeVision, fixtures


def focus_fixture(tmp_path):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'exact source identity')
    (tmp_path/'analysis.meta.json').write_text(json.dumps({'source':'fixture-source','version':2}), 'utf-8')
    return source, fixtures()


def focus_run(source, data, tmp_path, answers, reader=FakeReader):
    events, shots, transcript = data
    vision = FakeVision(answers)
    with patch('app.framing.MAX_SAMPLE_INTERVAL',1000), patch('app.framing._FrameReader',side_effect=reader):
        result = refine_focus(source, {'fps':30}, transcript, shots, events, tmp_path, vision,
                              lambda *a:None, lambda:False)
    return result, vision


GOOD = {'x':.3,'y':.4,'confidence':.9,'visible_speaker':True}


def test_focus_sample_reuse_survives_changed_event_projection_and_analysis_metadata(tmp_path):
    source, data = focus_fixture(tmp_path)
    initial, first = focus_run(source,data,tmp_path,[GOOD,{**GOOD,'x':.7}])
    assert len(first.calls)==2
    events, shots, transcript = copy.deepcopy(data)
    for i,event in enumerate(events):
        event.update(id=f'reprojected{i}',requires=[],importance=4,summary='Changed unrelated summary.')
    (tmp_path/'analysis.meta.json').write_text(json.dumps({'source':'fixture-source','version':99}), 'utf-8')
    # Even the native event traversal can change; raw source answers have no
    # dependency on previous focus. Each current traversal still derives it.
    result,replay = focus_run(source,(list(reversed(events)),shots,transcript),tmp_path,[])
    assert replay.calls==[]
    assert [e['focus'][0]['x'] for e in result]==[.7,.3]
    subset,replay = focus_run(source,([events[1]],shots,transcript),tmp_path,[])
    assert replay.calls==[]
    assert subset[0]['focus']==initial[1]['focus']


@pytest.mark.parametrize('change', ['phrase','pixels','source','schema','model'])
def test_focus_cache_requires_exact_actual_source_evidence_and_contract(tmp_path,change):
    source,data = focus_fixture(tmp_path)
    focus_run(source,data,tmp_path,[GOOD,{**GOOD,'x':.7}])
    events,shots,transcript=copy.deepcopy(data)
    for event in events:
        event['summary']='Force event projection validation.'
    reader=FakeReader
    expected=1
    if change=='phrase':
        transcript['segments'][1]['text']='A changed actual phrase.'
    elif change=='pixels':
        class ChangedFrameReader(FakeReader):
            def frame(self,timestamp):
                return np.full((360,640,3),200 if timestamp>=10 else 100,dtype=np.uint8)
        reader=ChangedFrameReader
    elif change=='source':
        source.write_bytes(b'an actually different source')
        expected=2
    elif change in ('schema','model'):
        expected=2
    vision=FakeVision([copy.deepcopy(GOOD) for _ in range(expected)])
    if change=='model':
        vision.model=tmp_path/'different-model.gguf'
    from app.framing import FOCUS_SCHEMA
    schema=copy.deepcopy(FOCUS_SCHEMA)
    if change=='schema':
        schema['description']='A changed exact response contract.'
    with patch('app.framing.FOCUS_SCHEMA',schema),patch('app.framing.MAX_SAMPLE_INTERVAL',1000), \
         patch('app.framing._FrameReader',side_effect=reader):
        refine_focus(source,{'fps':30},transcript,shots,events,tmp_path,vision,lambda *a:None,lambda:False)
    assert len(vision.calls)==expected


@pytest.mark.parametrize('invalid_x',[float('nan'),.31])
def test_corrupt_sample_requeries_only_that_sample(tmp_path,invalid_x):
    source,data=focus_fixture(tmp_path)
    focus_run(source,data,tmp_path,[GOOD,{**GOOD,'x':.7}])
    for path in (tmp_path/'focus'/'samples').glob('*.json'):
        saved=json.loads(path.read_text('utf-8'))
        if saved['answer']['x']==.3:
            saved['answer']['x']=invalid_x
            path.write_text(json.dumps(saved),'utf-8')
    for event in data[0]:
        event['summary']='Force sample lookup.'
    result,replay=focus_run(source,data,tmp_path,[GOOD])
    assert len(replay.calls)==1
    assert [e['focus'][0]['x'] for e in result]==[.3,.7]


def test_reusing_uncertain_answer_recomputes_current_cut_fallback(tmp_path):
    source,_=focus_fixture(tmp_path)
    events=[{'id':'one','start':0,'end':10,'kind':'story','importance':4,'requires':[]}]
    shots=[{'id':'single-shot','start':0,'end':10}]
    transcript={'segments':[{'start':0,'end':1,'text':'First.'},{'start':3,'end':5,'text':'Second.'}],
                'words':[{'start':.1,'end':.5,'text':'First.'},{'start':3.1,'end':3.5,'text':'Second.'}]}
    first,_=focus_run(source,(events,shots,transcript),tmp_path,
        [GOOD,{'x':.9,'y':.5,'confidence':.3,'visible_speaker':False}])
    assert first[0]['focus'][1]['held'] is True
    events[0]['selected_ranges']=[{'start':0,'end':2},{'start':3,'end':6}]
    second,replay=focus_run(source,(events,shots,transcript),tmp_path,
        [{'x':.75,'y':.5,'confidence':.9,'visible_speaker':False}])
    assert len(replay.calls)==1
    assert 'CURRENT single frame' in replay.calls[0][0]
    assert second[0]['focus'][1]['main_fallback'] is True
    assert 'held' not in second[0]['focus'][1]
    assert second[0]['focus'][1]['x']==.75


@pytest.mark.parametrize('kind,balanced,dramatic', [
    ('character_reaction',True,False),('emotional_pause',True,False),
    ('comedic_payoff',True,True),(None,True,True),('none',True,True)])
def test_typed_reaction_preference_keeps_humor_separate(kind,balanced,dramatic):
    record={'reaction_or_humor':True,'reaction_kind':kind}
    assert preserve_reaction(DEFAULT_PROFILE,record) is balanced
    assert preserve_reaction(DRAMATIC_PROFILE,record) is dramatic
    assert not preserve_reaction({**DEFAULT_PROFILE,'preserve_humor':False},
                                 {'reaction_or_humor':True,'reaction_kind':'comedic_payoff'})
    assert 'non-comedic' in reaction_instruction(DRAMATIC_PROFILE)


def proof(kind='character_reaction',**changes):
    return {'unit':'u0','keep':False,'story_change':False,'reaction_or_humor':True,
        'reaction_kind':kind,'current_episode_story':True,'confidence':.98,
        'evidence':'Her gaze and mouth change in response to the immediately preceding reply.',
        'retained_witness':'none','frame_indices':[1],**changes}


def test_profile_preference_does_not_weaken_ownership_concrete_frames_or_confidence():
    frames=[{'frame':1,'unit':'u0','source':1}]
    assert _positive_story_proof(proof(),DEFAULT_PROFILE,frames)
    assert not _positive_story_proof(proof(),DRAMATIC_PROFILE,frames)
    assert _positive_story_proof(proof('comedic_payoff'),DRAMATIC_PROFILE,frames)
    for changes in ({'confidence':.89},{'current_episode_story':False},{'frame_indices':[]},{'frame_indices':[2]}):
        assert not _positive_story_proof(proof(**changes),DEFAULT_PROFILE,frames)
    # A real causal change remains independently protected in Dramatic mode.
    assert _positive_story_proof(proof(story_change=True),DRAMATIC_PROFILE,frames)


@pytest.mark.parametrize('kind,approved', [('character_reaction',True),('emotional_pause',True),
                                        ('comedic_payoff',False),('none',False)])
def test_independent_omission_uses_typed_preference_without_new_deletion_reasons(kind,approved):
    units=[{'id':'u0','start':0,'end':3,'text':''}]
    omission=[{'unit':'u0','reason':'waiting'}]
    frames=[{'frame':1,'unit':'u0','source':1}]
    vision=Mock()
    vision.query.return_value={'decisions':[proof(kind)]}
    accepted,_=verify_omissions(units,set(),omission,None,frames,vision,DRAMATIC_PROFILE)
    assert bool(accepted) is approved
    for changes in ({'keep':True},{'story_change':True},{'confidence':.89}):
        vision.query.return_value={'decisions':[proof(kind,**changes)]}
        assert not verify_omissions(units,set(),omission,None,frames,vision,DRAMATIC_PROFILE)[0]


@pytest.mark.parametrize('kind,removed', [('character_reaction',True),('emotional_pause',True),
                                       ('comedic_payoff',False),(None,False)])
def test_pacing_retains_existing_independent_source_and_action_gates(kind,removed):
    event={'start':0,'end':4,'selected_ranges':[{'start':0,'end':4}],
           'protected_atmosphere_ranges':[{'start':1,'end':3}]}
    units=[{'id':'A','start':1,'end':3}]
    decision={'unit':'A','keep':False,'reason':'waiting','story_change':False,
              'reaction_or_humor':True,'evidence':'A repeated held response adds no distinct cause or payoff.'}
    if kind:
        decision['reaction_kind']=kind
    reviewed=copy.deepcopy(event)
    apply_review(reviewed,units,{'uncertain':False,'decisions':[decision]},DRAMATIC_PROFILE)
    assert bool(reviewed['pacing_removed']) is removed
    if removed:
        assert reviewed['protected_atmosphere_ranges']==[]
    for protection in ({'verified_current_story_ranges':[{'start':1,'end':3}]}, {'causal':True}):
        protected=copy.deepcopy(event)
        current=copy.deepcopy(decision)
        if 'causal' in protection:
            current['story_change']=True
        else:
            protected.update(protection)
        apply_review(protected,units,{'uncertain':False,'decisions':[current]},DRAMATIC_PROFILE)
        assert protected['selected_ranges']==event['selected_ranges']


@pytest.mark.parametrize('kind,drop', [('character_reaction',True),('emotional_pause',True),
                                    ('comedic_payoff',False),('physical_action',False)])
def test_global_omission_respects_typed_preferences_and_keeps_action_proof(kind,drop):
    event={'id':'e0','start':0,'end':4,'kind':'story','importance':4,
           'unit_evidence':[{'unit':'u0','kind':kind,'decision':'keep','confidence':.98,'frame_indices':[1]}]}
    omission={'event':'e0','reason':'repeated_information','confidence':.95,
              'evidence':'Its necessary information is already retained with the full payoff.',
              'reaction_or_humor':True,'reaction_kind':kind if kind!='physical_action' else 'none'}
    decisions={'keep':[],'omit':[omission],'dependencies':[]}
    reviewed=copy.deepcopy(event)
    apply_global_selection([reviewed],decisions,DRAMATIC_PROFILE)
    assert reviewed.get('global_excluded',False) is drop
    original=copy.deepcopy(event)
    apply_global_selection([original],decisions,DEFAULT_PROFILE)
    assert not original.get('global_excluded',False)


def test_closing_only_uses_accepted_typed_source_proof_to_disambiguate_legacy_flag():
    event={'selection_status':'accepted','unit_evidence':[{'unit':'u0','kind':'character_reaction',
        'decision':'keep','confidence':.98,'frame_indices':[1],'evidence':'An ordinary non-comedic glance.'}]}
    assert not preserve_unit_reaction(DRAMATIC_PROFILE,event,'u0',flagged=True)
    for changes in ({'selection_status':'unresolved'}, {'unit_evidence':[]}):
        assert preserve_unit_reaction(DRAMATIC_PROFILE,{**event,**changes},'u0',flagged=True)
    event['unit_evidence'][0]['kind']='comedic_payoff'
    assert preserve_unit_reaction(DRAMATIC_PROFILE,event,'u0',flagged=True)


def test_condense_flag_cannot_bypass_independent_story_or_enabled_reaction_protection():
    for protection in ({'verified_current_story_ranges':[{'start':0,'end':10}]},
                       {'reaction':True}):
        event={'start':0,'end':10,'selected_ranges':[{'start':0,'end':10}]}
        item={'unit':'A','keep':True,'reason':'setup','story_change':False,'condense':True,
              'reaction_or_humor':False,'evidence':'A held interval between visible beats.'}
        if 'reaction' in protection:
            item.update(reaction_or_humor=True,reaction_kind='comedic_payoff')
        else:
            event.update(protection)
        apply_review(event,[{'id':'A','start':0,'end':10}],{'uncertain':False,'decisions':[item]},DRAMATIC_PROFILE)
        assert event['selected_ranges']==[{'start':0,'end':10}]
