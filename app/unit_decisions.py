"""One native decision per source unit; redundant lists are exact projections."""
from __future__ import annotations

import copy

CONTRACT = 'unit_decisions_v2'
LEGACY_CONTRACT = 'unit_decisions_v1'


def prompt(*, contract=LEGACY_CONTRACT):
    if contract not in (LEGACY_CONTRACT, CONTRACT):
        raise ValueError('Unsupported unit decision contract')
    from .selection_adjudication import ADJUDICATION_PROMPT
    value = ADJUDICATION_PROMPT.replace(
        'Partition every supplied CURRENT source-unit ID exactly once into keep_units or drop_units.',
        'Return every supplied CURRENT source-unit ID exactly once in unit_evidence, with its decision=keep or decision=drop.')
    value = value.replace('action_units must be kept units with physical_action/state_transition evidence.',
        'Physical action is represented only by physical_action/state_transition evidence on a kept record.')
    value = value.replace('they cannot describe a silent lead-in and are not action_units.',
        'they cannot describe a silent lead-in and do not establish a visible physical action.')
    for old, new in (('keep_units', 'decision=keep'), ('drop_units', 'decision=drop')):
        value = value.replace(old, new)
    value += '\nReturn no redundant keep/drop/action ID lists. Each unit_evidence record owns its one decision.'
    if contract == CONTRACT:
        value += ('\nFor physical_action/state_transition, motion must contain exactly two observations: '
            'the earlier owned CURRENT frame/state and the later owned CURRENT frame/state that demonstrate '
            'a concrete visible change WITHIN THIS SAME UNIT. Both frames must also be in its frame_indices. '
            'Never borrow the action from another unit or BEFORE/AFTER context, even when it is visible elsewhere '
            'on the same page. One static image or two copies of one source timestamp cannot prove motion. '
            'Do not invent an earlier/later state. All other evidence kinds must return motion=[]. '
            'If motion is not observable within the supplied unit, do not claim physical_action/state_transition; '
            'report the actual evidenced contribution or explicit unresolved ownership instead.')
    return value


def schema(units, frames=None, *, contract=LEGACY_CONTRACT):
    if contract not in (LEGACY_CONTRACT, CONTRACT):
        raise ValueError('Unsupported unit decision contract')
    from .selection_adjudication import adjudication_schema
    result = copy.deepcopy(adjudication_schema(units, frames))
    for name in ('keep_units', 'drop_units', 'action_units'):
        del result['properties'][name]
        result['required'].remove(name)
    item = result['properties']['unit_evidence']['items']
    for branch in item.get('oneOf', [item]):
        branch['properties']['decision'] = {'type': 'string', 'enum': ['keep', 'drop']}
        branch['required'].append('decision')
        if contract == CONTRACT:
            frame = copy.deepcopy(branch['properties']['frame_indices']['items'])
            branch['properties']['motion'] = {'type': 'array', 'maxItems': 2,
                'items': {'type': 'object', 'properties': {'frame': frame,
                    'state': {'type': 'string', 'minLength': 1, 'maxLength': 240}},
                    'required': ['frame', 'state'], 'additionalProperties': False}}
            branch['required'].append('motion')
            if frames is not None:
                indices = frame.get('enum', [])
                if len({frames[index-1]['time'] for index in indices}) < 2:
                    branch['properties']['kind']['enum'] = [kind for kind in branch['properties']['kind']['enum']
                                                           if kind not in ('physical_action', 'state_transition')]
                    branch['properties']['motion']['maxItems'] = 0
    return result


def validate(raw, units, frames, exclusions=(), *, contract=LEGACY_CONTRACT):
    from .selection_adjudication import validate_adjudication, ACTION_KINDS
    expected = schema(units, contract=contract)
    if not isinstance(raw, dict) or set(raw) != set(expected['required']):
        raise ValueError('Unit decisions require the complete native contract')
    records = raw.get('unit_evidence')
    fields = set(expected['properties']['unit_evidence']['items']['required'])
    if (not isinstance(records, list) or any(not isinstance(row, dict) or set(row) != fields
            or row.get('decision') not in ('keep', 'drop') for row in records)):
        raise ValueError('Each source unit requires one explicit decision and evidence')
    if contract == CONTRACT:
        _validate_motion(records, units, frames)
    # No semantic repair: keep/drop and action membership follow only the
    # model's explicit decision and grounded physical evidence kind.
    legacy = {k: copy.deepcopy(v) for k, v in raw.items() if k != 'unit_evidence'}
    legacy['unit_evidence'] = [{k: copy.deepcopy(v) for k, v in row.items() if k not in ('decision', 'motion')} for row in records]
    legacy['keep_units'] = [r['unit'] for r in records if r['decision'] == 'keep']
    legacy['drop_units'] = [r['unit'] for r in records if r['decision'] == 'drop']
    legacy['action_units'] = [r['unit'] for r in records if r['decision'] == 'keep' and r['kind'] in ACTION_KINDS]
    result = validate_adjudication(legacy, units, frames, exclusions)
    if contract == CONTRACT:
        for checked, native in zip(result['unit_evidence'], records):
            checked['motion'] = copy.deepcopy(native['motion'])
    return result


def _validate_motion(records, units, frames):
    known = {unit['id']: unit for unit in units}
    lookup = {index+1: frame['time'] for index, frame in enumerate(frames)}
    for row in records:
        _motion_pair(row, known.get(row.get('unit')), lookup)


def _motion_pair(row, unit, lookup):
    motion = row.get('motion')
    if row.get('kind') not in ('physical_action', 'state_transition'):
        if motion != []:
            raise ValueError('Only physical_action/state_transition may carry motion proof')
        return
    if not unit or not isinstance(motion, list) or len(motion) != 2:
        raise ValueError('Motion requires two ordered own CURRENT frame/state observations')
    for observation in motion:
        if (not isinstance(observation, dict) or set(observation) != {'frame', 'state'}
                or type(observation['frame']) is not int or observation['frame'] not in lookup
                or observation['frame'] not in row.get('frame_indices', [])
                or not unit['start'] <= lookup[observation['frame']] < unit['end']
                or not isinstance(observation['state'], str) or not observation['state'].strip()
                or len(observation['state']) > 240):
            raise ValueError('Motion observations require own declared CURRENT frame and concrete state')
    if (lookup[motion[0]['frame']] >= lookup[motion[1]['frame']]
            or ' '.join(motion[0]['state'].split()).casefold() == ' '.join(motion[1]['state'].split()).casefold()):
        raise ValueError('Motion needs distinct ordered timestamps and different observed states')


def persisted_motion_valid(record, unit):
    """Recheck temporal claims against canonical saved owned frame/time pairs."""
    try:
        indices, times = record['frame_indices'], record['frame_times']
        if len(indices) != len(times) or len(set(indices)) != len(indices):
            return False
        _motion_pair(record, unit, dict(zip(indices, times)))
        return True
    except (ValueError, TypeError, KeyError):
        return False
