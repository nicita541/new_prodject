"""Native source proof remains mandatory after eliminating redundant ID lists."""
import copy

import pytest

from app.unit_decisions import schema, validate, prompt
from app.unit_decisions import CONTRACT
from tests.test_selection_adjudication import answer


def fixture():
    units = [{'id': 'action', 'start': 0., 'end': 1., 'text': ''},
             {'id': 'waiting', 'start': 1., 'end': 2., 'text': ''}]
    frames = [{'time': .5}, {'time': 1.5}]
    legacy = answer({'CURRENT': {'units': units, 'frames': frames}}, keep=['action'])
    raw = {k: copy.deepcopy(v) for k, v in legacy.items() if k not in ('keep_units', 'drop_units', 'action_units')}
    for row in raw['unit_evidence']:
        row['decision'] = 'keep' if row['unit'] == 'action' else 'drop'
    return raw, units, frames


def test_single_decision_schema_preserves_unit_specific_frame_and_kind_constraints():
    raw, units, frames = fixture()
    original = copy.deepcopy(raw)
    result = validate(raw, units, frames)
    assert result['accepted']
    assert result['keep_units'] == result['action_units'] == ['action']
    assert result['drop_units'] == ['waiting']
    assert raw == original
    contract = schema(units, frames)
    assert not {'keep_units', 'drop_units', 'action_units'} & set(contract['properties'])
    branches = contract['properties']['unit_evidence']['items']['oneOf']
    assert all('decision' in branch['required'] for branch in branches)
    assert branches[0]['properties']['frame_indices']['items']['enum'] == [1]
    assert 'causal_dialogue' not in branches[0]['properties']['kind']['enum']
    assert 'action_units' not in prompt()


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'unknown', 'absent_decision', 'extra_list',
                                 'borrow_frame', 'invent_quote', 'positive_drop', 'link_to_drop'])
def test_no_local_semantic_repair_or_coverage_bypass(case):
    raw, units, frames = fixture()
    if case == 'missing':
        raw['unit_evidence'].pop()
    elif case == 'duplicate':
        raw['unit_evidence'][1] = copy.deepcopy(raw['unit_evidence'][0])
    elif case == 'unknown':
        raw['unit_evidence'][0]['unit'] = 'invented'
    elif case == 'absent_decision':
        del raw['unit_evidence'][0]['decision']
    elif case == 'extra_list':
        raw['keep_units'] = ['action']
    elif case == 'borrow_frame':
        raw['unit_evidence'][0]['frame_indices'] = [2]
    elif case == 'invent_quote':
        raw['unit_evidence'][0]['speech_quote'] = 'Words absent from original ASR'
    elif case == 'positive_drop':
        raw['unit_evidence'][0]['decision'] = 'drop'
    else:
        raw['causal_links'] = [{'from_unit': 'action', 'to_unit': 'waiting', 'relation': 'cause',
                               'evidence': 'A fabricated dependency on discarded source.'}]
    with pytest.raises(ValueError):
        validate(raw, units, frames)


def temporal_fixture():
    raw, units, _ = fixture()
    frames = [{'time': .1}, {'time': .8}, {'time': 1.5}]
    raw['unit_evidence'][0].update(frame_indices=[1, 2], motion=[
        {'frame': 1, 'state': 'The hand is down beside the body.'},
        {'frame': 2, 'state': 'The hand extends toward the cup.'}])
    raw['unit_evidence'][1].update(frame_indices=[3], motion=[])
    return raw, units, frames


def test_temporal_contract_preserves_native_states_and_original_confidence():
    raw, units, frames = temporal_fixture()
    original = copy.deepcopy(raw)
    result = validate(raw, units, frames, contract=CONTRACT)
    assert result['accepted']
    assert result['unit_evidence'][0]['motion'] == raw['unit_evidence'][0]['motion']
    assert result['understanding_confidence'] == raw['understanding_confidence']
    assert raw == original
    from app.deepseek import _validate
    _validate(raw, schema(units, frames, contract=CONTRACT))
    assert 'two observations' in prompt(contract=CONTRACT)


@pytest.mark.parametrize('case', ['absent_motion', 'one_image', 'context_frame', 'undeclared_frame',
                                 'reversed', 'duplicate_pts', 'identical_states', 'nonaction_motion',
                                 'empty_state', 'unknown_observation_field'])
def test_temporal_action_cannot_borrow_or_invent_before_after(case):
    raw, units, frames = temporal_fixture()
    row = raw['unit_evidence'][0]
    if case == 'absent_motion':
        del row['motion']
    elif case == 'one_image':
        row['motion'].pop()
    elif case == 'context_frame':
        row['motion'][1]['frame'] = 3
    elif case == 'undeclared_frame':
        row['frame_indices'] = [1]
    elif case == 'reversed':
        row['motion'].reverse()
    elif case == 'duplicate_pts':
        frames[1]['time'] = frames[0]['time']
    elif case == 'identical_states':
        row['motion'][1]['state'] = row['motion'][0]['state']
    elif case == 'nonaction_motion':
        raw['unit_evidence'][1]['motion'] = copy.deepcopy(row['motion'])
    elif case == 'empty_state':
        row['motion'][1]['state'] = ' '
    else:
        row['motion'][1]['invented'] = True
    with pytest.raises(ValueError):
        validate(raw, units, frames, contract=CONTRACT)


def test_single_source_timestamp_cannot_offer_an_action_kind_in_native_schema():
    _, units, frames = fixture()
    contract = schema(units, frames, contract=CONTRACT)
    branch = contract['properties']['unit_evidence']['items']['oneOf'][0]
    assert 'physical_action' not in branch['properties']['kind']['enum']
    assert 'state_transition' not in branch['properties']['kind']['enum']
    assert branch['properties']['motion']['maxItems'] == 0
    # A v1 answer remains valid under its own historical contract, but cannot
    # be relabelled as native temporal proof by adding locally invented states.
    raw, units, frames = fixture()
    assert validate(raw, units, frames)['accepted']
    with pytest.raises(ValueError):
        validate(raw, units, frames, contract=CONTRACT)


def test_temporal_proof_does_not_raise_confidence_or_override_explicit_uncertainty():
    raw, units, frames = temporal_fixture()
    raw['selection_confidence'] = .55
    result = validate(raw, units, frames, contract=CONTRACT)
    assert not result['accepted']
    assert result['selection_confidence'] == .55
    raw['selection_confidence'] = .99
    raw['resolved'] = False
    assert not validate(raw, units, frames, contract=CONTRACT)['accepted']
