"""Pure whole-candidate source contracts; no inference or invented legacy proof."""
from __future__ import annotations

import copy
import math

from .content_identity import digest
from .source_ranges import merge_ranges, intersect_ranges, subtract_ranges
from .source_text import source_text, tokens, quote_in

CONTRACT = 'standalone_candidate_proved_v1'
SOURCE_JOIN_POLICY = {'version': 2}
PROPOSAL_POLICY = {'version': 1}


def _valid_proposal_policy(policy):
    return type(policy) is dict and set(policy) == {'version'} and type(policy['version']) is int and policy['version'] == 1


def _proposal_observations(case):
    observations = case.get('proposal_observations', [])
    if type(observations) is not list or observations is case.get('frames'):
        raise ValueError('Proposal observations must be a separate owned catalog')
    known = {unit['id']: unit for unit in case['units']}
    seen = set()
    for frame in observations:
        unit = known.get(frame.get('unit'))
        sha = frame.get('sha256')
        if (type(frame.get('index')) is not int or frame['index'] < 1 or frame['index'] in seen
                or unit is None or type(frame.get('time')) not in (int, float)
                or not math.isfinite(frame['time']) or not unit['start'] <= frame['time'] < unit['end']
                or not isinstance(sha, str) or len(sha) != 64
                or any(char not in '0123456789abcdef' for char in sha)
                or frame.get('source_sha256', case['source_sha256']) != case['source_sha256']):
            raise ValueError('Invalid proposal original-frame ownership')
        seen.add(frame['index'])
    return observations
CRITERIA = ('self_contained_opening', 'causal_development', 'complete_ending',
            'necessary_context_retained', 'speech_complete', 'actions_complete',
            'no_nonstory_material', 'suitable_pacing')


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


TEXT = {'type': 'string', 'maxLength': 500}


def _source_join_policy(analysis, case):
    policy = analysis.get('source_join_policy')
    if policy != case.get('source_join_policy') or (policy is not None and (
            type(policy) is not dict or set(policy) != {'version'}
            or type(policy['version']) is not int or policy['version'] not in (1, 2))):
        raise ValueError('Candidate source join policy changed or is unsupported')
    return policy


def physical_digest(analysis):
    return digest({key: analysis[key] for key in ('probe', 'transcript', 'shots')})


def source_catalog(analysis, source_sha):
    from .discovery_regions import _speech_envelopes
    duration = analysis['probe']['duration']
    if (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0
            or not isinstance(source_sha, str) or len(source_sha) != 64
            or any(c not in '0123456789abcdef' for c in source_sha)):
        raise ValueError('Invalid candidate source identity')
    speech = _speech_envelopes(analysis['transcript'], duration)
    edges = {0., float(duration)}
    for a, b in speech:
        edges.update((a, b))
    for shot in analysis['shots']:
        if (any(type(shot.get(name)) not in (int, float) or not math.isfinite(shot[name])
                for name in ('start', 'end')) or not 0 <= shot['start'] < shot['end'] <= duration+.002):
            raise ValueError('Invalid source shot')
        for name in ('start', 'end'):
            # Shot detector persists millisecond geometry; clamp its rounded
            # terminal edge to the precise physical duration without rewriting it.
            edge = min(shot[name], duration)
            if not any(a < edge < b for a, b in speech):
                edges.add(float(edge))
    ordered = sorted(edges)
    return [{'id': 'u_'+digest({'source': source_sha, 'start': a, 'end': b})[:16],
             'start': a, 'end': b, 'text': source_text(analysis['transcript'], a, b),
             'shot_ids': [shot['id'] for shot in analysis['shots'] if shot['start'] < b and a < shot['end']]}
            for a, b in zip(ordered, ordered[1:]) if a < b]


def candidate_cases(analysis, episode_map, source_sha):
    if episode_map.get('source_sha256') != source_sha or episode_map.get('authority') != 'hypothesis_only':
        raise ValueError('Candidate discovery is not bound to this source')
    catalog = source_catalog(analysis, source_sha)
    windows = {window['id']: window for window in episode_map['windows']}
    if len(windows) != len(episode_map['windows']):
        raise ValueError('Duplicate source survey window')
    result, seen = [], set()
    for hypothesis in episode_map['hypotheses']:
        ident = hypothesis['id']
        if ident in seen:
            raise ValueError('Duplicate candidate hypothesis')
        seen.add(ident)
        refs = list(dict.fromkeys([*hypothesis['window_ids'], *hypothesis['prerequisite_window_ids']]))
        if not refs or any(ref not in windows for ref in refs):
            raise ValueError('Unknown candidate discovery context')
        ranges = merge_ranges([{'start': windows[ref]['start'], 'end': windows[ref]['end']} for ref in refs])
        # Include intervening original context, even when discovery references
        # disconnected windows. A later multi-cut review must see what it omits.
        ranges = [{'start': ranges[0]['start'], 'end': ranges[-1]['end']}]
        units = [copy.deepcopy(unit) for unit in catalog if any(
            unit['start'] < span['end'] and span['start'] < unit['end'] for span in ranges)]
        if not units:
            continue
        result.append({'contract': CONTRACT, 'id': ident, 'source_sha256': source_sha,
            'physical_digest': physical_digest(analysis), 'units': units,
            'hypothesis': copy.deepcopy(hypothesis), 'frames': [],
            'source_ranges': merge_ranges([{'start': u['start'], 'end': u['end']} for u in units])})
        if analysis.get('source_join_policy') is not None:
            result[-1]['source_join_policy'] = copy.deepcopy(analysis['source_join_policy'])
        if analysis.get('proposal_policy') is not None:
            if not _valid_proposal_policy(analysis['proposal_policy']):
                raise ValueError('Unsupported proposal policy')
            result[-1]['proposal_policy'] = copy.deepcopy(PROPOSAL_POLICY)
    return result


def proposal_schema(case):
    ref = {'type': 'string', 'enum': [unit['id'] for unit in case['units']]}
    properties = {'viable': {'type': 'boolean'}, 'title': TEXT, 'reason': TEXT,
        'interest': {'type': 'integer', 'minimum': 1, 'maximum': 5},
        'cuts': {'type': 'array', 'items': _object({'first': ref, 'last': ref})}}
    if case.get('proposal_policy') is not None:
        if not _valid_proposal_policy(case['proposal_policy']):
            raise ValueError('Unsupported proposal policy')
        _proposal_observations(case)
        properties['beats'] = {'type': 'array', 'items': _object({
            'role': {'type': 'string', 'enum': ['setup', 'development', 'payoff']},
            'kind': {'type': 'string', 'enum': ['speech', 'appearance', 'change']},
            'first': ref, 'last': ref, 'quote': TEXT,
            'frames': {'type': 'array', 'items': {'type': 'integer', 'enum':
                [frame['index'] for frame in case.get('proposal_observations', [])]}},
            'states': {'type': 'array', 'items': TEXT}})}
    return _object(properties)


def _validate(raw, schema):
    from .deepseek import _validate as validate
    validate(raw, schema)


def proposal_ranges(case, raw):
    _validate(raw, proposal_schema(case))
    result = _proposal_cut_ranges(case, raw)
    if case.get('proposal_policy') is not None:
        _proposal_beats(case, raw, result)
    return result


def _proposal_cut_ranges(case, raw):
    """Pure source geometry used by offline binding and trim verification."""
    if (not isinstance(raw, dict) or type(raw.get('viable')) is not bool
            or not isinstance(raw.get('cuts'), list)):
        raise ValueError('Invalid proposal source selection')
    units = case['units']
    positions = {unit['id']: index for index, unit in enumerate(units)}
    result, previous = [], -1
    if raw['viable'] and not raw['cuts']:
        raise ValueError('A viable candidate requires actual source cuts')
    for cut in raw['cuts']:
        if (not isinstance(cut, dict) or set(cut) != {'first', 'last'}
                or any(not isinstance(cut[key], str) or cut[key] not in positions for key in ('first', 'last'))):
            raise ValueError('Invalid proposal source cut')
        a, b = positions[cut['first']], positions[cut['last']]
        if a > b or a <= previous or any(abs(left['end']-right['start']) > 1e-6
                for left, right in zip(units[a:b+1], units[a+1:b+1])):
            raise ValueError('Candidate cuts repeat, reverse or cross unobserved source')
        result.append({'start': units[a]['start'], 'end': units[b]['end']})
        previous = b
    return merge_ranges(result)


def _proposal_beats(case, proposal, ranges):
    """Bind untrusted story hypotheses to owned source facts, never approve them."""
    units = case['units']
    positions = {unit['id']: index for index, unit in enumerate(units)}
    observations = _proposal_observations(case)
    frames = {frame['index']: frame for frame in observations}
    if len(frames) != len(observations):
        raise ValueError('Duplicate proposal observation')
    beats = proposal['beats']
    if not isinstance(beats, list) or any(not isinstance(beat, dict)
            or set(beat) != {'role', 'kind', 'first', 'last', 'quote', 'frames', 'states'}
            or beat['role'] not in ('setup', 'development', 'payoff')
            or beat['kind'] not in ('speech', 'appearance', 'change')
            or any(not isinstance(beat[key], str) or beat[key] not in positions for key in ('first', 'last'))
            or not isinstance(beat['quote'], str) or len(beat['quote']) > 500
            or not isinstance(beat['frames'], list)
            or any(type(index) is not int or index not in frames for index in beat['frames'])
            or not isinstance(beat['states'], list)
            or any(not isinstance(state, str) or len(state) > 500 for state in beat['states']) for beat in beats):
        raise ValueError('Invalid source-bound proposal beat')
    if not proposal['viable'] and (beats or proposal['cuts']):
        raise ValueError('Nonviable proposal must have no beats or cuts')
    if proposal['viable'] and not {'setup', 'development', 'payoff'} <= {beat['role'] for beat in beats}:
        raise ValueError('Viable proposal requires setup, development and payoff beats')
    resolved, previous = [], -1
    roles = {'setup': 0, 'development': 1, 'payoff': 2}
    if [roles[beat['role']] for beat in beats] != sorted(roles[beat['role']] for beat in beats):
        raise ValueError('Proposal beat roles must follow setup, development and payoff')
    for beat in beats:
        a, b = positions[beat['first']], positions[beat['last']]
        if a > b or a < previous or any(abs(left['end']-right['start']) > 1e-6
                for left, right in zip(units[a:b+1], units[a+1:b+1])):
            raise ValueError('Proposal beat span is reversed or disconnected')
        previous = a
        span = {'start': units[a]['start'], 'end': units[b]['end']}
        if not any(row['start'] <= span['start'] and span['end'] <= row['end'] for row in ranges):
            raise ValueError('Proposal beat is not wholly retained in one source cut')
        observed = []
        for index in beat['frames']:
            frame = frames[index]
            owner = next((unit for unit in units if unit['id'] == frame['unit']), None)
            sha = frame.get('sha256')
            if (owner is None or type(frame.get('time')) not in (int, float)
                    or not math.isfinite(frame['time'])
                    or not owner['start'] <= frame['time'] < owner['end']
                    or not span['start'] <= frame['time'] < span['end']
                    or not isinstance(sha, str) or len(sha) != 64
                    or any(char not in '0123456789abcdef' for char in sha)
                    or frame.get('source_sha256', case['source_sha256']) != case['source_sha256']):
                raise ValueError('Proposal observation leaves its source owner')
            observed.append({key: frame[key] for key in ('index', 'unit', 'time', 'sha256')})
        if beat['kind'] == 'speech':
            if a != b or not beat['quote'].strip() or beat['quote'] not in units[a]['text'] or observed or beat['states']:
                raise ValueError('Speech beat requires an exact quote from its own unit')
        elif beat['kind'] == 'appearance':
            if a != b or beat['quote'] or len(observed) != 1 or len(beat['states']) != 1 or not beat['states'][0].strip():
                raise ValueError('Appearance beat requires one owned observation')
        elif (beat['quote'] or len(observed) != 2 or len(beat['states']) != 2
                or any(not state.strip() for state in beat['states'])
                or beat['states'][0].strip().casefold() == beat['states'][1].strip().casefold()
                or observed[0]['time'] >= observed[1]['time']
                or observed[0]['sha256'] == observed[1]['sha256']):
            raise ValueError('Change beat requires ordered distinct original observations')
        resolved.append({'role': beat['role'], 'kind': beat['kind'], 'first': beat['first'],
            'last': beat['last'], **span, 'quote': beat['quote'],
            'observations': observed, 'states': copy.deepcopy(beat['states'])})
    return resolved


def proposal_binding(case, proposal, plan):
    """Deterministic geometry binding; descriptions remain untrusted hypotheses."""
    if case.get('proposal_policy') is None:
        return None
    if not _valid_proposal_policy(case['proposal_policy']):
        raise ValueError('Unsupported proposal policy')
    ranges = _proposal_cut_ranges(case, proposal)
    beats = _proposal_beats(case, proposal, ranges)
    cuts = [cut for part in plan['parts'] for cut in part['cuts']]
    if any(not any(cut['start'] <= beat['start'] and beat['end'] <= cut['end'] for cut in cuts) for beat in beats):
        raise ValueError('Actual edit omits a bound proposal beat span')
    return {'policy': copy.deepcopy(PROPOSAL_POLICY), 'source_sha256': case['source_sha256'],
        'beats': beats, 'timeline_digest': timeline_digest(plan)}


def validate_proposal_binding(case, proposal, plan, binding):
    if proposal_binding(case, proposal, plan) != binding:
        raise ValueError('Proposal beat binding differs from the actual edit')


def with_cut_context(analysis, case, proposal):
    """Extend source facts around actual audio handles, without changing an edit."""
    from .speech_handles import expand_ranges
    core = proposal_ranges(case, proposal)
    if not core:
        return copy.deepcopy(case)
    actual = expand_ranges(core, analysis['transcript'], analysis['probe']['duration'])
    if analysis.get('audio_boundary_policy') is not None:
        from .audio_boundaries import REACH
        actual = merge_ranges([{'start': max(0., row['start']-REACH),
                                'end': min(analysis['probe']['duration'], row['end']+REACH)} for row in core])
    catalog = source_catalog(analysis, case['source_sha256'])
    required = [i for i, unit in enumerate(catalog) if any(
        unit['start'] < span['end'] and span['start'] < unit['end'] for span in actual)]
    # Neighbors are original context, never additional selected story units.
    low, high = max(0, min(required)-1), min(len(catalog), max(required)+2)
    owned = {unit['id'] for unit in case['units']} | {unit['id'] for unit in catalog[low:high]}
    result = copy.deepcopy(case)
    result['units'] = [unit for unit in catalog if unit['id'] in owned]
    result['source_ranges'] = merge_ranges([{'start': u['start'], 'end': u['end']} for u in result['units']])
    return result


def prototype_plan(analysis, case, proposal, *, draft=False):
    """Compile geometry only. This private proposal has no publication authority."""
    from .standalone_planner import _plan
    from .planner import validate_plan
    if draft:
        analysis, case, proposal = copy.deepcopy(analysis), copy.deepcopy(case), copy.deepcopy(proposal)
        analysis.pop('proposal_policy', None)
        case.pop('proposal_policy', None)
        case.pop('proposal_observations', None)
        proposal.pop('beats', None)
    elif (analysis.get('proposal_policy') != case.get('proposal_policy')
            or (analysis.get('proposal_policy') is not None and not _valid_proposal_policy(analysis['proposal_policy']))
            or (case.get('proposal_policy') is not None and not _valid_proposal_policy(case['proposal_policy']))):
        raise ValueError('Candidate proposal policy changed or is unsupported')
    if draft:
        case = with_cut_context(analysis, case, proposal)
    join_policy = _source_join_policy(analysis, case)
    core = proposal_ranges(case, proposal)
    if not core:
        raise ValueError('No candidate source selection')
    events = [{'id': unit['id'], 'start': unit['start'], 'end': unit['end'],
        'kind': 'story', 'importance': 1, 'requires': [], 'focus': [],
        'summary': unit['text'] or 'Безречевой исходный интервал',
        'source_interval': True, 'selected_ranges': intersect_ranges([unit], core)} for unit in case['units']]
    scoped = {key: copy.deepcopy(analysis[key]) for key in ('probe', 'transcript', 'shots')}
    if join_policy is not None:
        scoped['source_join_policy'] = copy.deepcopy(join_policy)
    if case.get('proposal_policy') is not None:
        scoped['proposal_policy'] = copy.deepcopy(PROPOSAL_POLICY)
    if analysis.get('audio_boundary_policy') is not None:
        from .audio_boundaries import POLICY
        if analysis['audio_boundary_policy'] != POLICY:
            raise ValueError('Unsupported candidate audio boundary policy')
        scoped['audio_boundary_policy'] = copy.deepcopy(analysis['audio_boundary_policy'])
        if not draft and case.get('audio_boundary_evidence') is None:
            raise ValueError('Candidate is missing measured audio boundaries')
    if case.get('audio_boundary_evidence') is not None:
        from .audio_boundaries import validate_evidence
        audio = validate_evidence(case['audio_boundary_evidence'], case['source_sha256'], analysis['probe']['duration'])
        if audio['audio_stream'] != analysis['probe'].get('audio_stream', 0):
            raise ValueError('Candidate boundary evidence uses another audio stream')
        scoped['audio_boundary_evidence'] = copy.deepcopy(audio)
    scoped.update(events=events, quality_policy=CONTRACT, analysis_contract=CONTRACT,
                  source_sha256=case['source_sha256'])
    plan = _plan(scoped, core, draft=draft)
    if any(subtract_ranges([cut], case['source_ranges']) for part in plan['parts'] for cut in part['cuts']):
        raise ValueError('Audio handles leave reviewed candidate source context')
    owners = {owner for part in plan['parts'] for cut in part['cuts'] for owner in cut['event_ids']}
    scoped['events'] = [event for event in events if event['id'] in owners]
    plan['events'] = copy.deepcopy(scoped['events'])
    plan['selected_event_ids'] = [event['id'] for event in scoped['events']]
    plan['source']['sha256'] = case['source_sha256']
    validate_plan(plan, scoped, allow_draft=draft)
    binding = proposal_binding(case, proposal, plan)
    if binding is not None:
        plan['proposal_binding'] = binding
    return plan, scoped


def timeline_digest(plan):
    return digest([[{'start': cut['start'], 'end': cut['end']} for cut in part['cuts']] for part in plan['parts']])


def selected_units(case, proposal):
    ranges = proposal_ranges(case, proposal)
    return [unit for unit in case['units'] if any(span['start'] <= unit['start'] and unit['end'] <= span['end']
                                                for span in ranges)]


def review_schema(case, proposal, plan):
    selected = selected_units(case, proposal)
    speech = [unit for unit in selected if tokens(unit['text'])]
    quote = {'type': 'string', 'maxLength': max([500, *[len(unit['text']) for unit in selected]])}
    refs = {'type': 'string', 'enum': [unit['id'] for unit in case['units']]}
    kept = {'type': 'string', 'enum': [unit['id'] for unit in selected]}
    frames = {'type': 'array', 'uniqueItems': True,
              'items': {'type': 'integer', 'enum': [frame['index'] for frame in case['frames']]}}
    proof = _object({'phase': {'type': 'string', 'enum': ['opening', 'development', 'ending']},
        'unit': kept, 'mode': {'type': 'string', 'enum': ['speech', 'appearance', 'change']},
        'quote': quote, 'frames': frames, 'evidence': TEXT,
        'motion': {'type': 'array', 'maxItems': 2, 'items': _object({
            'frame': frames['items'], 'state': TEXT})}})
    proof['allOf'] = [{'oneOf': [
        {'properties': {'mode': {'enum': ['speech']}, 'quote': {'minLength': 1},
                        'unit': {'enum': [u['id'] for u in speech]}, 'frames': {'maxItems': 0},
                        'motion': {'maxItems': 0}}},
        {'properties': {'mode': {'enum': ['appearance']}, 'frames': {'minItems': 1}, 'motion': {'maxItems': 0}}},
        {'properties': {'mode': {'enum': ['change']}, 'frames': {'minItems': 2}, 'motion': {'minItems': 2}}}]}]
    cuts = plan['parts'][0]['cuts']
    owners = []
    for unit in selected:
        own = [frame['index'] for frame in case['frames'] if frame['unit'] == unit['id']
               and _inside(frame['time'], cuts)]
        owners.append({'properties': {'unit': {'enum': [unit['id']]},
            'frames': {'items': {'type': 'integer', 'enum': own}},
            'motion': {'items': {'properties': {'frame': {'type': 'integer', 'enum': own}}}}}})
    proof['allOf'].append({'oneOf': owners})
    boundary = []
    for index, cut in enumerate(plan['parts'][0]['cuts'], 1):
        own = [frame['index'] for frame in case['frames'] if cut['start'] <= frame['time'] < cut['end']]
        for side in ('start', 'end'):
            boundary.append(_object({'cut': {'type': 'integer', 'enum': [index]},
                'side': {'type': 'string', 'enum': [side]}, 'safe': {'type': 'boolean'},
                'frames': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                    'prefixItems': [{'type': 'integer', 'enum': [boundary_anchor(case, cut, side)]}],
                    'items': {'type': 'integer', 'enum': own}}, 'evidence': TEXT}))
    result = _object({'resolved': {'type': 'boolean'}, 'is_story': {'type': 'boolean'},
        'criteria': _object({name: {'type': 'boolean'} for name in CRITERIA}),
        'proofs': {'type': 'array', 'maxItems': 3, 'items': proof},
        'required_units': {'type': 'array', 'uniqueItems': True, 'items': refs},
        'requested_units': {'type': 'array', 'uniqueItems': True, 'items': refs},
        'issues': {'type': 'array', 'items': TEXT},
        'dialogue': {'type': 'array', 'items': _object({'unit': {'type': 'string', 'enum': [u['id'] for u in speech]}, 'quote': quote,
            'status': {'type': 'string', 'enum': ['self_contained', 'question_answered', 'answer', 'rhetorical']},
            'partners': {'type': 'array', 'uniqueItems': True,
                         'items': {'type': 'string', 'enum': [u['id'] for u in speech]}}, 'evidence': TEXT})},
        'boundaries': {'type': 'array', 'items': {'oneOf': boundary}}})
    # Historic answers have no notes. They retain their original blocking issues.
    result['properties']['notes'] = {'type': 'array', 'items': TEXT}
    if case.get('source_join_policy') is not None:
        joins = []
        for join in source_joins(case, plan):
            row = _object({'after_cut': {'type': 'integer', 'enum': [join['after_cut']]},
                'safe_to_omit': {'type': 'boolean'},
                'classification': {'type': 'string', 'enum': ['incidental', 'redundant',
                    'required_cause', 'required_response', 'required_action', 'unresolved']},
                'frames': {'type': 'array', 'minItems': 3, 'maxItems': len(join['omitted_frames'])+2,
                    'uniqueItems': True,
                    'prefixItems': [{'type': 'integer', 'enum': [join['left_frame']]}],
                    'items': {'type': 'integer', 'enum': [join['left_frame'],
                        *join['omitted_frames'], join['right_frame']]}}, 'evidence': TEXT})
            if case['source_join_policy']['version'] == 2:
                observation = _object({'frame': {'type': 'integer', 'enum': join['omitted_frames']},
                    'state': TEXT})
                retained = [frame['index'] for frame in case['frames'] if _inside(frame['time'], cuts)]
                row['properties'].update(change=_object({
                    'kind': {'type': 'string', 'enum': ['none', 'minor_motion', 'speech_only',
                        'physical_event', 'object_change', 'reveal', 'scene_change', 'unresolved']},
                    'before': observation, 'after': observation}),
                    retained_witness=_object({'frames': {'type': 'array', 'uniqueItems': True,
                        'items': {'type': 'integer', 'enum': retained}}, 'evidence': TEXT}))
                row['required'].extend(('change', 'retained_witness'))
            joins.append(row)
        result['properties']['joins'] = {'type': 'array', 'items': {'oneOf': joins}} if joins else {
            'type': 'array', 'maxItems': 0, 'items': {}}
        result['required'].append('joins')
    return result


def _inside(time, ranges):
    return any(span['start'] <= time < span['end'] for span in ranges)


def validate_case(analysis, case):
    if (analysis.get('proposal_policy') != case.get('proposal_policy')
            or (case.get('proposal_policy') is not None and (
                not _valid_proposal_policy(case['proposal_policy'])
                or not _valid_proposal_policy(analysis.get('proposal_policy'))))):
        raise ValueError('Candidate proposal policy changed or is unsupported')
    if case.get('proposal_policy') is not None:
        _proposal_observations(case)
    if (case.get('contract') != CONTRACT or case.get('source_sha256') != analysis.get('source_sha256')
            or case.get('physical_digest') != physical_digest(analysis)):
        raise ValueError('Candidate source evidence changed')
    _source_join_policy(analysis, case)
    if analysis.get('audio_boundary_policy') is not None and case.get('audio_boundary_evidence') is None:
        raise ValueError('Candidate is missing measured audio boundaries')
    if case.get('audio_boundary_evidence') is not None:
        from .audio_boundaries import validate_evidence
        audio = validate_evidence(case['audio_boundary_evidence'], case['source_sha256'], analysis['probe']['duration'])
        if audio['audio_stream'] != analysis['probe'].get('audio_stream', 0):
            raise ValueError('Candidate boundary evidence uses another audio stream')
    catalog = {unit['id']: unit for unit in source_catalog(analysis, case['source_sha256'])}
    if (not case['units'] or len({u['id'] for u in case['units']}) != len(case['units'])
            or any(catalog.get(unit['id']) != unit for unit in case['units'])
            or case['units'] != sorted(case['units'], key=lambda unit: unit['start'])):
        raise ValueError('Candidate physical interval ownership changed')
    known = {unit['id']: unit for unit in case['units']}
    if case.get('source_ranges') != merge_ranges([{'start': u['start'], 'end': u['end']} for u in case['units']]):
        raise ValueError('Candidate source ranges do not match its original catalog')
    seen = set()
    for frame in case['frames']:
        unit = known.get(frame.get('unit'))
        if (type(frame.get('index')) is not int or frame['index'] < 1 or frame['index'] in seen
                or not unit or type(frame.get('time')) not in (int, float) or not math.isfinite(frame['time'])
                or not unit['start'] <= frame['time'] < unit['end']
                or not isinstance(frame.get('sha256'), str) or len(frame['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in frame['sha256'])):
            raise ValueError('Invalid candidate original-frame ownership')
        seen.add(frame['index'])


def _proof_valid(row, unit, frames, retained):
    if not row['evidence'].strip():
        raise ValueError('A story proof needs concrete source evidence')
    for index in row['frames']:
        frame = frames[index]
        if frame['unit'] != unit['id'] or not _inside(frame['time'], retained):
            raise ValueError('Story proof borrows another unit or omitted image')
    if row['quote'] and not quote_in(row['quote'], unit['text']):
        raise ValueError('Story proof invents original ASR')
    if row['mode'] == 'speech' and (not row['quote'].strip() or row['motion']):
        raise ValueError('Spoken story proof requires its own exact ASR')
    if row['mode'] == 'appearance' and (not row['frames'] or row['motion']):
        raise ValueError('Appearance proof requires its own original frame')
    if row['mode'] == 'change':
        from .unit_decisions import _motion_pair
        _motion_pair({'kind': 'physical_action', 'motion': row['motion'], 'frame_indices': row['frames']},
                     unit, {index: frame['time'] for index, frame in frames.items()})
        if frames[row['motion'][0]['frame']]['sha256'] == frames[row['motion'][1]['frame']]['sha256']:
            raise ValueError('Identical original images cannot prove a visible state change')


def boundary_anchor(case, cut, side):
    candidates = [frame for frame in case['frames'] if cut['start'] <= frame['time'] < cut['end']]
    if not candidates:
        raise ValueError('No source frame at a proposed boundary')
    return min(candidates, key=lambda frame: frame['time'])['index'] if side == 'start' else max(
        candidates, key=lambda frame: frame['time'])['index']


def source_joins(case, plan):
    """Describe omitted original observations between actual audible cuts."""
    cuts = plan['parts'][0]['cuts']
    joins = []
    for index, (left, right) in enumerate(zip(cuts, cuts[1:]), 1):
        a, b = left['end'], right['start']
        if a >= b:
            continue
        joins.append({'after_cut': index, 'start': a, 'end': b,
            'left_frame': boundary_anchor(case, left, 'end'),
            'right_frame': boundary_anchor(case, right, 'start'),
            'omitted_frames': [frame['index'] for frame in sorted(case['frames'], key=lambda frame: frame['time'])
                               if a <= frame['time'] < b],
            'unit_ids': [unit['id'] for unit in case['units'] if unit['start'] < b and a < unit['end']]})
    return joins


def _join_change_safe(row, join, frames, cuts):
    change = row['change']
    if change['kind'] == 'unresolved':
        return False
    before, after = change['before'], change['after']
    pair = [before['frame'], after['frame']]
    if any(index not in join['omitted_frames'] or index not in row['frames'][1:-1] for index in pair):
        raise ValueError('A source change proof borrows an uncited or foreign omitted image')
    if (not before['state'].strip() or not after['state'].strip()
            or not frames[pair[0]]['time'] < frames[pair[1]]['time']):
        return False
    if change['kind'] in ('none', 'speech_only'):
        return True
    if frames[pair[0]]['sha256'] == frames[pair[1]]['sha256']:
        return False
    if change['kind'] == 'minor_motion':
        return True
    if before['state'].strip().casefold() == after['state'].strip().casefold():
        return False
    witness = row['retained_witness']
    cited = witness['frames']
    if any(not _inside(frames[index]['time'], cuts) for index in cited):
        raise ValueError('A retained change witness borrows an omitted image')
    return (len(cited) >= 2 and bool(witness['evidence'].strip())
        and all(frames[left]['time'] < frames[right]['time'] for left, right in zip(cited, cited[1:]))
        and len({frames[index]['sha256'] for index in cited}) >= 2
        and any(all(cut['start'] <= frames[index]['time'] < cut['end'] for index in cited) for cut in cuts))


def review_status(analysis, case, proposal, plan, raw):
    validate_case(analysis, case)
    _validate(raw, review_schema(case, proposal, plan))
    kept = selected_units(case, proposal)
    known = {unit['id']: unit for unit in kept}
    frames = {frame['index']: frame for frame in case['frames']}
    retained = [cut for part in plan['parts'] for cut in part['cuts']]
    potential = (raw['resolved'] and raw['is_story'] and all(raw['criteria'].values())
        and not raw['issues'] and not raw['requested_units'] and set(raw['required_units']) <= set(known))
    # A genuine incomplete/negative judgement is reusable, not a schema error.
    if not potential:
        return 'needs_review' if raw['is_story'] else 'declined'
    if case.get('source_join_policy') is not None:
        joins = {join['after_cut']: join for join in source_joins(case, plan)}
        actual = [row['after_cut'] for row in raw['joins']]
        if len(actual) != len(joins) or set(actual) != set(joins):
            raise ValueError('Every actual source gap requires one native join check')
        safe = True
        for row in raw['joins']:
            join = joins[row['after_cut']]
            cited = row['frames']
            if (not row['evidence'].strip() or len(cited) < 3
                    or cited[0] != join['left_frame'] or cited[-1] != join['right_frame']
                    or any(index not in join['omitted_frames'] for index in cited[1:-1])
                    or cited != sorted(cited, key=lambda index: frames[index]['time'])):
                raise ValueError('A source join proof needs both retained edges and its own omitted images')
            safe = safe and row['safe_to_omit'] and row['classification'] in ('incidental', 'redundant')
            if case['source_join_policy']['version'] == 2:
                # Factual omitted events cannot be waived by a rhetorical safe
                # judgement: the same event needs its own continuous kept proof.
                change_safe = _join_change_safe(row, join, frames, plan['parts'][0]['cuts'])
                safe = safe and change_safe
        if not safe:
            return 'needs_review'
    phases = [row['phase'] for row in raw['proofs']]
    if len(phases) != 3 or set(phases) != {'opening', 'development', 'ending'}:
        raise ValueError('An approved story requires source-backed opening, development and ending')
    for row in raw['proofs']:
        _proof_valid(row, known[row['unit']], frames, retained)
    by_phase = {row['phase']: row for row in raw['proofs']}
    if (not retained[0]['start'] <= known[by_phase['opening']['unit']]['start'] < retained[0]['end']
            or not retained[-1]['start'] < known[by_phase['ending']['unit']]['end'] <= retained[-1]['end']
            or not known[by_phase['opening']['unit']]['start'] <= known[by_phase['development']['unit']]['start']
            <= known[by_phase['ending']['unit']]['start']):
        raise ValueError('Story evidence does not match the actual opening or ending')
    speech = {unit['id']: unit for unit in kept if tokens(unit['text'])}
    if len(raw['dialogue']) != len(speech) or {row['unit'] for row in raw['dialogue']} != set(speech):
        raise ValueError('Retained dialogue requires complete native dependency coverage')
    for row in raw['dialogue']:
        if tokens(row['quote']) != tokens(speech[row['unit']]['text']) or not row['evidence'].strip():
            raise ValueError('Dialogue coverage must quote the complete original utterance')
        if row['status'] in ('question_answered', 'answer'):
            if not row['partners'] or any(ref == row['unit'] or ref not in speech for ref in row['partners']):
                raise ValueError('A dialogue dependency needs its actual retained partner')
        elif row['partners']:
            raise ValueError('Independent dialogue cannot invent a dependency')
    cuts = plan['parts'][0]['cuts']
    required = {(index, side) for index in range(1, len(cuts)+1) for side in ('start', 'end')}
    actual = [(row['cut'], row['side']) for row in raw['boundaries']]
    if len(actual) != len(required) or set(actual) != required:
        raise ValueError('Every actual edit boundary requires a native source check')
    for row in raw['boundaries']:
        cut = cuts[row['cut']-1]
        if (not row['safe'] or not row['evidence'].strip()
                or boundary_anchor(case, cut, row['side']) not in row['frames']
                or any(not cut['start'] <= frames[index]['time'] < cut['end'] for index in row['frames'])):
            raise ValueError('A boundary proof does not establish the actual retained edge')
    return 'ready'


def proposal_from_source_joins(analysis, case, proposal, plan, record):
    """Restore one bound negative's observed source-unit runs, never approve it.

    Only explicit blocking motion or a substantive omitted event can add owned
    units. Caller owns the single repair budget, audible-delta checks and fresh
    source/viewer qualification. Invalid or ungrounded records return None.
    """
    try:
        if (record.get('status') != 'needs_review' or case.get('source_join_policy') != {'version': 2}
                or any(key in record for key in ('repair_attempt', 'qualification_history', 'original_proposal'))):
            return None
        validate_case(analysis, case)
        expected, _ = prototype_plan(analysis, case, proposal)
        if case.get('proposal_policy') is not None:
            validate_proposal_binding(case, proposal, plan, record.get('proposal_binding'))
            validate_proposal_binding(case, proposal, plan, plan.get('proposal_binding'))
        if (plan['source']['sha256'] != case['source_sha256']
                or record['timeline_digest'] != timeline_digest(plan) or timeline_digest(plan) != timeline_digest(expected)):
            return None
        bound = record['case']
        if any(bound.get(key) != case.get(key) for key in
               ('source_sha256', 'physical_digest', 'source_join_policy', 'proposal_policy',
                'proposal_observations', 'units', 'source_ranges')):
            return None
        frame_facts = lambda value: [{key: frame[key] for key in ('index', 'unit', 'time', 'sha256')}
            for frame in value['frames']]
        if frame_facts(bound) != frame_facts(case):
            return None
        review = record['review']
        _validate(review, review_schema(case, proposal, plan))
        if (not review['resolved'] or not review['is_story'] or review['requested_units']
                or review_status(analysis, case, proposal, plan, review) != 'needs_review'):
            return None
        joins = {join['after_cut']: join for join in source_joins(case, plan)}
        if len({row['after_cut'] for row in review['joins']}) != len(review['joins']):
            return None
        frames = {frame['index']: frame for frame in case['frames']}
        units = case['units']
        positions = {unit['id']: index for index, unit in enumerate(units)}
        core = proposal_ranges(case, proposal)
        selected = {unit['id'] for unit in selected_units(case, proposal)}
        added = set()
        for row in review['joins']:
            kind = row['change']['kind']
            substantive = kind in ('physical_event', 'object_change', 'reveal', 'scene_change')
            blocking_motion = (kind == 'minor_motion' and not row['safe_to_omit']
                and row['classification'] in ('required_cause', 'required_response', 'required_action'))
            if not substantive and not blocking_motion:
                continue
            join = joins[row['after_cut']]
            cited = row['frames']
            if (not row['evidence'].strip() or cited[0] != join['left_frame'] or cited[-1] != join['right_frame']
                    or any(index not in join['omitted_frames'] for index in cited[1:-1])
                    or cited != sorted(cited, key=lambda index: frames[index]['time'])):
                return None
            before, after = row['change']['before'], row['change']['after']
            pair = [before['frame'], after['frame']]
            if (any(index not in join['omitted_frames'] or index not in cited[1:-1] for index in pair)
                    or not before['state'].strip() or not after['state'].strip()
                    or not frames[pair[0]]['time'] < frames[pair[1]]['time']
                    or frames[pair[0]]['sha256'] == frames[pair[1]]['sha256']
                    or substantive and before['state'].strip().casefold() == after['state'].strip().casefold()):
                return None
            if substantive and _join_change_safe(row, join, frames, plan['parts'][0]['cuts']):
                continue
            a, b = [positions[frames[index]['unit']] for index in pair]
            run = units[a:b+1]
            if not run or any(abs(left['end']-right['start']) > 1e-6 for left, right in zip(run, run[1:])):
                return None
            cuts = plan['parts'][0]['cuts']
            # Whole owners of an old audible handle must survive remeasurement.
            # Inspect only the immediate neighbors of the observed run; do not
            # walk through unobserved units towards a distant retained edge.
            for index, edge, cut, side in (
                    (a-1, join['start'], cuts[join['after_cut']-1], 'left'),
                    (b+1, join['end'], cuts[join['after_cut']], 'right')):
                if not 0 <= index < len(units):
                    continue
                neighbor = units[index]
                if (neighbor['start'] < edge < neighbor['end']
                        and neighbor['start'] < cut['end'] and cut['start'] < neighbor['end']):
                    contiguous = (abs(neighbor['end']-run[0]['start']) <= 1e-6 if side == 'left'
                                  else abs(run[-1]['end']-neighbor['start']) <= 1e-6)
                    if not contiguous:
                        return None
                    run = [neighbor, *run] if side == 'left' else [*run, neighbor]
            for unit in run:
                if (not unit['start'] < join['end'] or not join['start'] < unit['end']
                        or any(other['after_cut'] != join['after_cut'] and unit['start'] < other['end']
                               and other['start'] < unit['end'] for other in joins.values())):
                    return None
                if unit['id'] not in selected:
                    if unit['start'] < core[0]['start'] or unit['end'] > core[-1]['end']:
                        return None
                    added.add(unit['id'])
        if not added:
            return None
        groups, previous = [], None
        for index, unit in enumerate(units):
            if unit['id'] not in selected | added:
                continue
            if previous is not None and index == previous+1 and abs(units[previous]['end']-unit['start']) <= 1e-6:
                groups[-1]['last'] = unit['id']
            else:
                groups.append({'first': unit['id'], 'last': unit['id']})
            previous = index
        result = copy.deepcopy(proposal)
        result['cuts'] = groups
        changed = proposal_ranges(case, result)
        if subtract_ranges(core, changed) or not subtract_ranges(changed, core):
            return None
        return result
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def inspect_candidate_quality(analysis, plan=None):
    try:
        record = analysis['candidate_evidence']
        case, proposal, review = record['case'], record['proposal'], record['review']
        expected, _ = prototype_plan(analysis, case, proposal)
        if plan is None:
            plan = expected
        if (record['timeline_digest'] != timeline_digest(expected)
                or timeline_digest(plan) != record['timeline_digest']):
            raise ValueError('Candidate source timeline differs from the reviewed edit')
        if case.get('proposal_policy') is not None:
            validate_proposal_binding(case, proposal, expected, record.get('proposal_binding'))
            validate_proposal_binding(case, proposal, plan, plan.get('proposal_binding'))
        from .planner import validate_plan
        validate_plan(plan, analysis)
        if review_status(analysis, case, proposal, expected, review) != 'ready':
            raise ValueError('Candidate has no complete native story approval')
        from .candidate_screen import project_candidate, inspect_screen
        screen = inspect_screen(project_candidate(analysis, case, expected), record['screen'])
        if screen['status'] != 'ready':
            raise ValueError('Candidate has no complete cut-only viewer approval')
        return {'version': 1, 'status': 'passed', 'contract': CONTRACT, 'problems': [],
                'evidence_chain': copy.deepcopy(review['proofs']),
                'viewer_screen': {'status': 'passed', 'contract': record['screen']['contract'],
                                  'binding': record['screen']['binding']}}
    except (KeyError, TypeError, ValueError) as error:
        return {'version': 1, 'status': 'unresolved', 'contract': CONTRACT,
                'problems': [{'code': 'candidate_evidence_unresolved', 'detail': str(error),
                              'recovery_stage': 'candidate_review'}], 'evidence_chain': []}


def compile_candidates(analysis, settings):
    from .standalone_planner import _settings
    settings = _settings(settings)
    ready, declined, drafts = [], [], []
    for record in analysis['candidate_records']:
        case, proposal = record['case'], record.get('proposal')
        try:
            if proposal is None or not proposal['viable']:
                raise ValueError('No source-backed edit proposal')
            plan, scoped = prototype_plan(analysis, case, proposal)
            scoped['candidate_evidence'] = copy.deepcopy(record)
            quality = inspect_candidate_quality(scoped, plan)
            if quality['status'] != 'passed' or plan['parts'][0]['duration'] > settings['max_duration']:
                raise ValueError('Candidate story is not fully qualified')
            ident = 'short_'+digest({'source': case['source_sha256'], 'ranges': plan['semantic_ranges']})[:20]
            plan.update(candidate_id=ident, export_eligible=True, quality_gate=quality,
                        candidate_contract=CONTRACT, candidate_evidence_digest=digest(record))
            ready.append({'id': ident, 'arc_id': case['id'], 'status': 'ready', 'export_eligible': True,
                'source_ranges': copy.deepcopy(plan['semantic_ranges']), 'source_contract_digest': digest(record),
                'duration': plan['parts'][0]['duration'], 'score': {'total': proposal['interest']},
                'plan': plan, 'scoped_analysis': scoped})
        except (KeyError, TypeError, ValueError) as error:
            declined.append({'arc_id': case['id'], 'reason': record.get('status', 'candidate_unresolved'),
                             'detail': str(error), 'export_eligible': False})
            # Review drafts are always continuous originals, including omitted
            # context. They cannot masquerade as an approved multiple-cut edit.
            try:
                spans = proposal_ranges(case, proposal) if proposal else []
            except (KeyError, TypeError, ValueError):
                spans = []
            if spans:
                spans = [{'start': spans[0]['start'], 'end': spans[-1]['end']}]
            else:
                spans = sorted(case['source_ranges'], key=lambda span: span['end']-span['start'], reverse=True)[:1]
            if not spans or spans[0]['end']-spans[0]['start'] > settings['max_duration']:
                continue
            rows = [unit for unit in case['units'] if spans[0]['start'] <= unit['start'] and unit['end'] <= spans[0]['end']]
            if not rows:
                continue
            fallback = {'viable': True, 'title': '', 'reason': '', 'interest': 1,
                        'cuts': [{'first': rows[0]['id'], 'last': rows[-1]['id']}]}
            try:
                draft, _ = prototype_plan(analysis, case, fallback, draft=True)
                drafts.append({'id': 'draft_'+digest({'source': case['source_sha256'], 'cuts': draft['parts']})[:20],
                    'status': 'needs_editorial_review', 'export_eligible': False,
                    'reason': 'candidate_story_not_approved', 'plan': draft})
            except (KeyError, TypeError, ValueError):
                pass
    chosen, retained = [], []
    while ready and len(chosen) < settings['max_clips']:
        def rank(candidate):
            overlap = sum(span['end']-span['start'] for span in intersect_ranges(candidate['source_ranges'], retained))
            novelty = 1-overlap/max(candidate['duration'], 1e-6)
            distance = max(settings['preferred_min_duration']-candidate['duration'],
                           candidate['duration']-settings['preferred_max_duration'], 0)
            return (-candidate['score']['total']*novelty, distance, candidate['source_ranges'][0]['start'], candidate['id'])
        candidate = min(ready, key=rank)
        ready.remove(candidate)
        if not subtract_ranges(candidate['source_ranges'], retained):
            declined.append({'arc_id': candidate['arc_id'], 'reason': 'duplicate_source_selection', 'export_eligible': False})
            continue
        candidate['rank'] = len(chosen)+1
        chosen.append(candidate)
        retained = merge_ranges([*retained, *candidate['source_ranges']])
    declined.extend({'arc_id': candidate['arc_id'], 'reason': 'requested_count_reached', 'export_eligible': False}
                    for candidate in ready)
    unique_drafts = {draft['id']: draft for draft in drafts}
    return {'version': 1, 'settings': settings, 'candidates': chosen, 'declined': declined,
            'drafts': list(unique_drafts.values())[:settings['max_clips']]}
