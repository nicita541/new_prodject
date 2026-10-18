"""Authored cut-only screening mechanisms; no real editorial acceptance/inference."""
import copy
import builtins
import importlib
import importlib.util
import json

import pytest

from app.candidate_screen import (CONTRACT, CRITERIA, PROMPT, bind_record, inspect_screen,
                              project_candidate, proposal_from_repair, screen_schema)


def fixture():
    analysis = {'probe': {'duration': 30.}, 'transcript': {'words': [
        {'start': 10.3, 'end': 11., 'text': 'Retained opening'},
        {'start': 12., 'end': 13., 'text': 'Retained development'},
        {'start': 17., 'end': 18., 'text': 'OMITTED SECRET EXPLANATION'},
        {'start': 20.2, 'end': 22., 'text': 'Retained ending'}]},
        'episode_map': {'hypothesis': 'SECRET HYPOTHESIS'}}
    case = {'source_sha256': 'a'*64, 'units': [
        {'id': 'original-unit-A', 'start': 0., 'end': 10.2},
        {'id': 'original-unit-B', 'start': 10.2, 'end': 15.},
        {'id': 'original-unit-C', 'start': 15., 'end': 20.},
        {'id': 'original-unit-D', 'start': 20., 'end': 30.}],
        'frames': [{'index': index, 'unit': unit, 'time': time,
                    'sha256': format(index, '064x'), 'path': f'/private/original-{index}.jpg'}
                   for index, unit, time in ((1, 'original-unit-A', 10.1),
                     (2, 'original-unit-B', 10.5), (3, 'original-unit-B', 13.),
                     (4, 'original-unit-C', 17.), (5, 'original-unit-D', 20.1),
                     (6, 'original-unit-D', 22.4), (7, 'original-unit-D', 25.))],
        'hypothesis': 'SECRET HYPOTHESIS', 'native_verdict': 'APPROVED WITH SECRET CONTEXT'}
    plan = {'parts': [{'cuts': [{'start': 10., 'end': 14.}, {'start': 20., 'end': 22.5}]}],
            'reason': 'SECRET PROPOSER REASON'}
    return analysis, case, plan


def projected():
    return project_candidate(*fixture())


def approved(projection):
    units = projection['payload']['units']
    first, middle, last = units[0], units[1], units[-1]
    return {'resolved': True, 'is_story': True, 'title': 'Authored viewer interpretation',
        'criteria': {key: True for key in CRITERIA},
        'issues': [], 'proofs': [
            {'phase': 'opening', 'unit': first['id'], 'mode': 'visual', 'quote': '',
             'frames': first['frame_indices'], 'evidence': 'The retained opening image supplies the visible setup.'},
            {'phase': 'development', 'unit': middle['id'], 'mode': 'speech',
             'quote': middle['text'], 'frames': [], 'evidence': 'The retained reply develops the situation.'},
            {'phase': 'ending', 'unit': last['id'], 'mode': 'speech',
             'quote': last['text'], 'frames': [], 'evidence': 'The retained final reply resolves the situation.'}]}


def test_projection_uses_output_clock_and_contains_no_omitted_context():
    result = projected()
    payload = result['payload']
    assert payload['duration'] == 6.5
    assert payload['cuts'] == [{'index': 1, 'start': 0., 'end': 4.},
                               {'index': 2, 'start': 4., 'end': 6.5}]
    assert [(unit['cut'], unit['start'], unit['end'], unit['text']) for unit in payload['units']] == [
        (1, 0., pytest.approx(.2), ''),
        (1, pytest.approx(.2), 4., 'Retained opening Retained development'),
        (2, 4., 6.5, 'Retained ending')]
    assert [frame['index'] for frame in result['frames']] == [1, 2, 3, 5, 6]
    assert [frame['time'] for frame in result['frames']] == pytest.approx([.1, .5, 3., 4.1, 6.4])
    assert all(frame['time'] < payload['duration'] for frame in payload['frames'])
    serialized = json.dumps(payload)
    for forbidden in ('OMITTED', 'SECRET', 'source_sha256', 'source_ranges', 'source_refs', 'source_start',
                      'source_end', 'original-unit', 'native_verdict', 'reason', '/private/'):
        assert forbidden not in serialized
    # Paths and exact original pixels are reused privately, never copied into model facts.
    assert result['frames'][0]['path'] == '/private/original-1.jpg'
    assert result['frames'][0]['sha256'] == format(1, '064x')


def test_projection_does_not_mutate_inputs_and_does_not_invent_images_for_padding():
    inputs = fixture()
    before = copy.deepcopy(inputs)
    inputs[1]['frames'] = [frame for frame in inputs[1]['frames'] if frame['index'] != 1]
    result = project_candidate(*inputs)
    assert result['payload']['units'][0]['text'] == ''
    assert result['payload']['units'][0]['frame_indices'] == []
    assert all(frame['index'] != 1 for frame in result['frames'])
    assert inputs[0] == before[0] and inputs[2] == before[2]


def test_ready_requires_own_cut_only_proofs_and_exact_binding():
    projection = projected()
    verdict = approved(projection)
    record = bind_record(projection, verdict)
    assert inspect_screen(projection, record)['status'] == 'ready'
    assert record['contract'] == CONTRACT
    verdict['proofs'].clear()
    assert len(record['verdict']['proofs']) == 3


def test_optional_notes_do_not_replace_blocking_criteria_or_issues():
    projection = projected()
    verdict = approved(projection)
    verdict['notes'] = ['An earlier establishing shot would be optional polish.']
    assert inspect_screen(projection, bind_record(projection, verdict))['status'] == 'ready'
    verdict['criteria']['resolved_ending'] = False
    assert inspect_screen(projection, bind_record(projection, verdict))['status'] == 'needs_review'
    verdict['criteria']['resolved_ending'] = True
    verdict['issues'] = ['The required final answer is omitted.']
    assert inspect_screen(projection, bind_record(projection, verdict))['status'] == 'needs_review'


@pytest.mark.parametrize('notes', ['not an array', [123], ['x'*501]])
def test_malformed_optional_notes_are_unresolved(notes):
    projection = projected()
    verdict = approved(projection)
    verdict['notes'] = notes
    assert inspect_screen(projection, bind_record(projection, verdict))['status'] == 'unresolved'


@pytest.mark.parametrize('changes,status', [
    ({'resolved': False, 'is_story': False}, 'needs_review'),
    ({'is_story': False}, 'declined'),
    ({'issues': ['The final question remains unanswered.']}, 'needs_review'),
    ({'criteria': {key: key != 'resolved_ending' for key in CRITERIA}}, 'needs_review')])
def test_negative_or_incomplete_blind_verdict_never_upgraded_by_native_context(changes, status):
    projection = projected()
    raw = approved(projection)
    raw.update(changes)
    raw['proofs'] = []
    record = bind_record(projection, raw)
    record['native_context_claim'] = 'Source reviewer says the omitted continuation resolves it.'
    assert inspect_screen(projection, record)['status'] == status


@pytest.mark.parametrize('change', ['foreign_image', 'omitted_quote', 'wrong_opening', 'wrong_ending',
                                  'reordered_phases', 'missing_phase', 'no_evidence'])
def test_invalid_approval_proof_is_unresolved(change):
    projection = projected()
    raw = approved(projection)
    if change == 'foreign_image':
        raw['proofs'][0]['frames'] = [5]
    elif change == 'omitted_quote':
        raw['proofs'][1]['quote'] = 'OMITTED SECRET EXPLANATION'
    elif change == 'wrong_opening':
        raw['proofs'][0].update(unit=projection['payload']['units'][-1]['id'], frames=[5])
    elif change == 'wrong_ending':
        raw['proofs'][2].update(unit=projection['payload']['units'][1]['id'],
                               quote=projection['payload']['units'][1]['text'])
    elif change == 'reordered_phases':
        raw['proofs'][1], raw['proofs'][2] = raw['proofs'][2], raw['proofs'][1]
        raw['proofs'][1]['phase'], raw['proofs'][2]['phase'] = 'development', 'ending'
    elif change == 'missing_phase':
        raw['proofs'].pop()
    else:
        raw['proofs'][0]['evidence'] = ' '
    assert inspect_screen(projection, bind_record(projection, raw))['status'] == 'unresolved'


@pytest.mark.parametrize('changed', ['timeline', 'source', 'image', 'output_time', 'unit_text'])
def test_review_record_cannot_cross_source_timeline_or_tampered_projection(changed):
    original = projected()
    record = bind_record(original, approved(original))
    analysis, case, plan = fixture()
    if changed == 'timeline':
        plan['parts'][0]['cuts'][-1]['end'] = 22.6
    elif changed == 'source':
        case['source_sha256'] = 'c'*64
    elif changed == 'image':
        case['frames'][0]['sha256'] = 'd'*64
    new = project_candidate(analysis, case, plan)
    if changed == 'output_time':
        new['payload']['frames'][0]['time'] += .1
    elif changed == 'unit_text':
        new['payload']['units'][1]['text'] = 'Invented replacement'
    assert inspect_screen(new, record)['status'] == 'unresolved'


def test_long_original_asr_has_representable_quote_and_real_negative_can_have_no_proofs():
    analysis, case, plan = fixture()
    long_quote = ' '.join(['original']*100)
    analysis['transcript']['words'][0]['text'] = long_quote
    projection = project_candidate(analysis, case, plan)
    raw = approved(projection)
    assert len(raw['proofs'][1]['quote']) > 500
    assert inspect_screen(projection, bind_record(projection, raw))['status'] == 'ready'
    schema = screen_schema(projection)
    assert schema['properties']['proofs']['items']['properties']['quote']['maxLength'] >= len(raw['proofs'][1]['quote'])
    assert schema['properties']['proofs'].get('minItems', 0) == 0
    raw.update(resolved=True, is_story=False, proofs=[])
    assert inspect_screen(projection, bind_record(projection, raw))['status'] == 'declined'
    assert 'confidence' not in json.dumps(schema)
    assert 'NEW viewer' in PROMPT


def test_relocated_image_paths_do_not_change_screen_evidence_binding():
    analysis, case, plan = fixture()
    first = project_candidate(analysis, case, plan)
    for frame in case['frames']:
        frame['path'] = '/new-storage/' + frame['path'].split('/')[-1]
    second = project_candidate(analysis, case, plan)
    assert first['binding'] == second['binding']
    assert inspect_screen(second, bind_record(first, approved(first)))['status'] == 'ready'


def test_unowned_source_gap_or_replayed_cut_fails_projection():
    analysis, case, plan = fixture()
    case['units'].pop(1)
    case['frames'] = [frame for frame in case['frames'] if frame['unit'] != 'original-unit-B']
    with pytest.raises(ValueError, match='unowned'):
        project_candidate(analysis, case, plan)
    analysis, case, plan = fixture()
    plan['parts'][0]['cuts'].reverse()
    with pytest.raises(ValueError, match='reorder'):
        project_candidate(analysis, case, plan)


def test_screen_import_and_pure_evaluation_never_import_provider_or_model(monkeypatch):
    import app.candidate_screen as screen
    original_import = builtins.__import__
    observed = set()
    forbidden = {'app.vision', 'app.deepseek', 'app.analysis_provider', 'app.flash_story_trial',
                 'app.candidate_analysis', 'app.model_perf', 'app.pipeline', 'app.antigravity_exchange'}

    def observed_import(name, globals=None, locals=None, fromlist=(), level=0):
        package = (globals or {}).get('__package__')
        absolute = importlib.util.resolve_name('.'*level+name, package) if level else name
        observed.add(absolute)
        assert not any(absolute == prefix or absolute.startswith(prefix+'.') for prefix in forbidden), absolute
        return original_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as protected:
        protected.setattr(builtins, '__import__', observed_import)
        importlib.reload(screen)
        projection = screen.project_candidate(*fixture())
        assert screen.screen_schema(projection)['type'] == 'object'
        verdict = approved(projection)
        assert screen.inspect_screen(projection, screen.bind_record(projection, verdict))['status'] == 'ready'
        analysis, case, plan, projection, record, proposal, _ = repair_fixture()
        assert screen.proposal_from_repair(analysis, case, plan, projection, record, proposal) is not None
        analysis, case, plan, projection, record, proposal = beat_repair_fixture()
        assert screen.proposal_from_repair(analysis, case, plan, projection, record, proposal) is not None
    assert 'app.content_identity' in observed
    assert 'app.source_text' in observed
    assert 'app.source_ranges' in observed


def repair_fixture():
    units = [{'id': f'original-{index}', 'start': index*2., 'end': (index+1)*2.}
             for index in range(7)]
    words = [{'start': unit['start']+.3, 'end': unit['end']-.3,
              'text': f'Original complete payoff {index}.'} for index, unit in enumerate(units)]
    analysis = {'probe': {'duration': 14.}, 'transcript': {'words': words}}
    case = {'source_sha256': 'a'*64, 'units': units,
        'frames': [{'index': index+1, 'unit': unit['id'],
                    'time': {0: 1.9, 3: 6.1, 4: 9.9}.get(index, unit['start']+.8),
                    'sha256': format(index+1, '064x'), 'path': f'/private/frame-{index+1}.jpg'}
                   for index, unit in enumerate(units)]}
    plan = {'semantic_ranges': [{'start': 2., 'end': 6.}, {'start': 10., 'end': 14.}],
            'parts': [{'cuts': [{'start': 1.8, 'end': 6.2}, {'start': 9.8, 'end': 14.}]}]}
    proposal = {'viable': True, 'title': 'Original title', 'reason': 'Original hypothesis reason',
                'interest': 3, 'cuts': [{'first': 'original-1', 'last': 'original-2'},
                                      {'first': 'original-5', 'last': 'original-6'}]}
    projection = project_candidate(analysis, case, plan)
    by_original = {ref['unit']: ident for ident, ref in projection['source_refs'].items()}
    view = {unit['id']: unit for unit in projection['payload']['units']}
    ending_id = by_original['original-2']
    raw = {'resolved': True, 'is_story': True, 'title': 'Ends after beginning the next scene',
           'criteria': {key: key != 'resolved_ending' for key in CRITERIA},
           'issues': ['A later scene starts after the observed payoff.'], 'proofs': [],
           'repair': {'cuts': [{'first': by_original['original-1'], 'last': ending_id}],
                      'reason': 'End at the already visible concrete payoff.',
                      'ending': {'unit': ending_id, 'quote': view[ending_id]['text'], 'frames': [],
                                 'evidence': 'The retained original reply states the concrete outcome.'}}}
    return analysis, case, plan, projection, bind_record(projection, raw), proposal, by_original


def test_private_repair_source_refs_are_bound_but_never_exposed_to_blind_model():
    _, _, _, projection, record, _, by_original = repair_fixture()
    assert 'source_refs' not in projection['payload']
    assert 'original-' not in json.dumps(projection['payload'])
    assert projection['source_refs'][by_original['original-0']]['selectable'] is False
    assert projection['source_refs'][by_original['original-1']]['selectable'] is True
    assert projection['source_refs'][by_original['original-3']]['selectable'] is False
    changed = copy.deepcopy(projection)
    changed['source_refs'][by_original['original-0']]['selectable'] = True
    assert inspect_screen(changed, record)['status'] == 'unresolved'
    schema = screen_schema(projection)
    assert 'repair' not in schema['required']
    repair_schema = schema['properties']['repair']['anyOf'][1]
    endpoint_refs = repair_schema['properties']['cuts']['items']['properties']['first']['enum']
    assert set(endpoint_refs) == {ident for ident, ref in projection['source_refs'].items() if ref['selectable']}


def beat_repair_fixture():
    from app.story_candidates import PROPOSAL_POLICY, proposal_binding
    analysis, case, plan, projection, record, proposal, _ = repair_fixture()
    analysis['proposal_policy'] = dict(PROPOSAL_POLICY)
    case['proposal_policy'] = dict(PROPOSAL_POLICY)
    case['proposal_observations'] = copy.deepcopy(case['frames'])
    for unit, word in zip(case['units'], analysis['transcript']['words'], strict=True):
        unit['text'] = word['text']
    proposal['beats'] = [{'role': role, 'kind': 'speech', 'first': f'original-{i}',
        'last': f'original-{i}', 'quote': case['units'][i]['text'], 'frames': [], 'states': []}
        for role, i in (('setup', 1), ('development', 1), ('payoff', 2))]
    plan['proposal_binding'] = proposal_binding(case, proposal, plan)
    return analysis, case, plan, projection, record, proposal


@pytest.mark.parametrize('defect', ['missing_binding', 'changed_binding', 'dropped_payoff'])
def test_viewer_trim_cannot_drop_or_forge_proposal_beat_binding(defect):
    from app.story_candidates import proposal_binding
    analysis, case, plan, projection, record, proposal = beat_repair_fixture()
    if defect == 'missing_binding':
        plan.pop('proposal_binding')
    elif defect == 'changed_binding':
        plan['proposal_binding']['beats'][0]['quote'] = 'forged quote'
    else:
        proposal['beats'][-1].update(first='original-6', last='original-6', quote=case['units'][6]['text'])
        plan['proposal_binding'] = proposal_binding(case, proposal, plan)
    assert proposal_from_repair(analysis, case, plan, projection, record, proposal) is None


def test_negative_can_suggest_precise_trim_without_mutating_or_approving_anything():
    analysis, case, plan, projection, record, proposal, _ = repair_fixture()
    before = copy.deepcopy((analysis, case, plan, projection, record, proposal))
    repaired = proposal_from_repair(analysis, case, plan, projection, record, proposal)
    assert repaired is not None
    assert repaired['cuts'] == [{'first': 'original-1', 'last': 'original-2'}]
    assert repaired['title'] == proposal['title'] and repaired['interest'] == proposal['interest']
    assert 'export_eligible' not in repaired and 'review' not in repaired
    assert inspect_screen(projection, record)['status'] == 'needs_review'
    assert (analysis, case, plan, projection, record, proposal) == before


def test_repair_spanning_parent_cuts_never_restores_their_omitted_source_gap():
    analysis, case, plan, projection, record, proposal, refs = repair_fixture()
    repair = record['verdict']['repair']
    repair['cuts'] = [{'first': refs['original-1'], 'last': refs['original-5']}]
    ending = next(unit for unit in projection['payload']['units'] if unit['id'] == refs['original-5'])
    repair['ending'].update(unit=ending['id'], quote=ending['text'])
    repaired = proposal_from_repair(analysis, case, plan, projection, record, proposal)
    assert repaired['cuts'] == [{'first': 'original-1', 'last': 'original-2'},
                                {'first': 'original-5', 'last': 'original-5'}]
    assert all(cut['first'] not in ('original-3', 'original-4') for cut in repaired['cuts'])


@pytest.mark.parametrize('invalid', ['unchanged', 'context', 'partial_padding', 'reversed',
    'reordered_groups', 'overlap', 'wrong_ending_unit', 'borrowed_ending_quote', 'borrowed_ending_frame',
    'empty_ending', 'no_reason', 'positive', 'unbound', 'tampered_mapping', 'new_timeline'])
def test_invalid_or_nonnegative_repair_cannot_produce_a_new_proposal(invalid):
    analysis, case, plan, projection, record, proposal, refs = repair_fixture()
    repair = record['verdict']['repair']
    if invalid == 'unchanged':
        repair['cuts'] = [{'first': refs['original-1'], 'last': refs['original-6']}]
        last = next(unit for unit in projection['payload']['units'] if unit['id'] == refs['original-6'])
        repair['ending'].update(unit=last['id'], quote=last['text'])
    elif invalid == 'context':
        repair['cuts'][0]['first'] = 'omitted-context-not-a-view-unit'
    elif invalid == 'partial_padding':
        repair['cuts'][0]['first'] = refs['original-0']
    elif invalid == 'reversed':
        repair['cuts'][0] = {'first': refs['original-2'], 'last': refs['original-1']}
    elif invalid == 'reordered_groups':
        repair['cuts'] = [{'first': refs['original-5'], 'last': refs['original-5']},
                          {'first': refs['original-1'], 'last': refs['original-2']}]
    elif invalid == 'overlap':
        repair['cuts'].append(copy.deepcopy(repair['cuts'][0]))
    elif invalid == 'wrong_ending_unit':
        repair['ending']['unit'] = refs['original-5']
    elif invalid == 'borrowed_ending_quote':
        repair['ending']['quote'] = 'An omitted scene supplies this explanation.'
    elif invalid == 'borrowed_ending_frame':
        repair['ending']['frames'] = [6]
    elif invalid == 'empty_ending':
        repair['ending'].update(quote='', frames=[])
    elif invalid == 'no_reason':
        repair['reason'] = ' '
    elif invalid == 'positive':
        raw = approved(projection)
        raw['repair'] = repair
        record = bind_record(projection, raw)
        assert inspect_screen(projection, record)['status'] == 'ready'
    elif invalid == 'unbound':
        record['binding'] = 'b'*64
    elif invalid == 'tampered_mapping':
        projection['source_refs'][refs['original-1']]['start'] = 0.
    else:
        plan['parts'][0]['cuts'][0]['start'] = 1.7
    assert proposal_from_repair(analysis, case, plan, projection, record, proposal) is None


@pytest.mark.parametrize('missing', ['omitted', 'null'])
def test_genuine_negative_without_repair_remains_a_negative(missing):
    analysis, case, plan, projection, record, proposal, _ = repair_fixture()
    if missing == 'omitted':
        record['verdict'].pop('repair')
    else:
        record['verdict']['repair'] = None
    assert inspect_screen(projection, record)['status'] == 'needs_review'
    assert proposal_from_repair(analysis, case, plan, projection, record, proposal) is None


def test_uncertain_negative_may_suggest_observed_visual_payoff_without_becoming_approved():
    analysis, case, plan, projection, record, proposal, refs = repair_fixture()
    record['verdict']['resolved'] = False
    record['verdict']['repair']['ending'].update(quote='', frames=[3])
    assert proposal_from_repair(analysis, case, plan, projection, record, proposal) is not None
    assert inspect_screen(projection, record)['status'] == 'needs_review'


def test_absent_or_nonobject_viewer_record_stays_unresolved():
    analysis, case, plan, projection, record, proposal, _ = repair_fixture()
    for malformed in (None, [], 'not a persisted verdict', 0):
        assert inspect_screen(projection, malformed)['status'] == 'unresolved'
