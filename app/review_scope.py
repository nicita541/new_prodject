"""Non-exportable candidate plans and source-owned CURRENT review windows."""
from __future__ import annotations
import copy
from pathlib import Path
from .content_identity import digest
from .json_store import atomic_json, read_json
from .source_ranges import intersect_ranges, merge_ranges
from .cancellation import check_cancelled

VERSION = 2
BOUNDARY_CONTEXT = 5.
PREFIX = ('story_refinement', 'credit_continuations', 'titles', 'closing_novelty',
          'source_roles', 'global_visual_verification')


def scope_barriers(analysis):
    """Unreviewed source is outside CURRENT, never a confirmed exclusion."""
    if not analysis.get('review_scope'):
        return []
    from .source_ranges import subtract_ranges
    return subtract_ranges([{'start':0.,'end':analysis['probe']['duration']}], analysis['review_scope']['ranges'])


def attach_scope(result):
    result['review_scope'] = {'version':VERSION, 'ranges':merge_ranges(result['events'])}
    return result


def accepted_prefix(events, journal, directory, transcript, shots, duration):
    """Read exact completed outputs only; never call a provider on a miss."""
    from .story import preserve_dialogue_in_credits
    from .eyecatch import detect_eyecatches, apply_eyecatch_exclusions
    current, restored = copy.deepcopy(events), {}
    for name in PREFIX:
        saved = journal.load(name, current)
        if saved is None:
            break
        current = saved
        restored[name] = read_json(Path(directory)/'continuation/stages'/f'{name}.json')['producer']
        if name == 'story_refinement':
            current = preserve_dialogue_in_credits(current, transcript)
        if name == 'credit_continuations':
            eyecatches = detect_eyecatches(current, transcript, shots, duration)
            if eyecatches:
                current = apply_eyecatch_exclusions(current, eyecatches)
    return current, restored


def candidate_plan(events, transcript, shots, probe, directory):
    from .planner import build_plan
    candidate = {'probe': probe, 'transcript': transcript, 'shots': shots,
                 'events': copy.deepcopy(events), 'selection_gate': {'status': 'unresolved'}}
    preferences = read_json(Path(directory)/'planning-preferences.json', {})
    if 'preferred_part_count' in preferences:
        candidate['preferred_part_count'] = preferences['preferred_part_count']
    # Draft geometry is real; no confidence, exclusion or acceptance flags are
    # changed to get through planning. Only final planning can authorize export.
    return build_plan(candidate, draft=True)


def check_regions(events):
    """Cheap first-pass hints choose specialist checks, never exclusion proof."""
    regions = []
    for event in events:
        kind = event.get('credits_kind',event.get('kind'))
        credits = kind in ('opening','ending') or event.get('contains_credits') or event.get('credit_montage')
        tasks = []
        if credits:
            tasks = ['credits','titles','source_roles']
            if kind == 'ending':
                tasks.append('closing')
        elif event.get('kind') == 'eyecatch' or event.get('title_candidate') or event.get('visible_production_title'):
            tasks = ['titles']
        if tasks:
            regions.append({'start':max(0.,event['start']-BOUNDARY_CONTEXT),
                            'end':event['end']+BOUNDARY_CONTEXT,'checks':tasks,'reason':'detected_credit_or_title'})
        if event.get('source_role_unresolved'):
            regions.append({'start':event['start'],'end':event['end'],
                            'checks':['source_roles'],'reason':'unresolved_source_role'})
    return regions


def target_units(event, units, task):
    """Select whole actual units inside this check's permitted source region."""
    regions = event.get('review_target_ranges')
    if regions is None:
        return units
    return [u for u in units if any(task in r['checks'] and u['start'] < r['end']
                                  and r['start'] < u['end'] for r in regions)]


def source_windows(events, plan, transcript, shots):
    """Expand draft cuts to complete actual units and prerequisite events."""
    from .story_review import candidate_units
    if plan.get('draft') is not True:
        raise ValueError('Candidate scope requires an explicit draft plan')
    by_id = {e['id']: e for e in events}
    if len(by_id) != len(events):
        raise ValueError('Duplicate source event')
    targets = {}
    for part in plan['parts']:
        for cut in part['cuts']:
            for identifier in cut['event_ids']:
                if identifier not in by_id:
                    raise ValueError('Unknown candidate source event')
                event = by_id[identifier]
                pieces = intersect_ranges([cut], [event])
                if pieces:
                    targets.setdefault(identifier, []).extend(pieces)
    regions = check_regions(events)
    for event in events:
        for region in regions:
            pieces = intersect_ranges([event],[region])
            if pieces:
                targets.setdefault(event['id'],[]).extend(pieces)
    pending = list(targets)
    while pending:
        identifier = pending.pop()
        for required in by_id[identifier].get('requires', []):
            if required not in by_id or by_id[required]['end'] > by_id[identifier]['start'] + .002:
                raise ValueError('Invalid candidate prerequisite')
            if required not in targets:
                event = by_id[required]
                targets[required] = copy.deepcopy(event.get('selected_ranges') or [event])
                pending.append(required)
    windows = []
    total_units = selected_units = 0
    for event in events:
        units = copy.deepcopy(event.get('units') or candidate_units(event['start'], event['end'], transcript, shots))
        units.sort(key=lambda u: u['start'])
        if (not units or abs(units[0]['start']-event['start']) > 1e-6
                or abs(units[-1]['end']-event['end']) > 1e-6
                or len({u['id'] for u in units}) != len(units)
                or any(abs(a['end']-b['start']) > 1e-6 for a,b in zip(units, units[1:]))):
            raise ValueError('Original source units must cover their parent')
        total_units += len(units)
        selected = [u for u in units if any(u['start'] < r['end'] and r['start'] < u['end']
                                          for r in targets.get(event['id'], []))]
        # Existing source hypotheses may reserve prerequisites, never approve
        # them. Every added unit still goes through the native proof gate.
        selected_ids = {u['id'] for u in selected}
        known = {u['id'] for u in units}
        while True:
            before = set(selected_ids)
            for link in event.get('causal_links', []):
                if isinstance(link, dict) and link.get('to') in selected_ids and link.get('from') in known:
                    selected_ids.add(link['from'])
            if selected_ids == before:
                break
        selected = [u for u in units if u['id'] in selected_ids]
        selected_units += len(selected)
        groups = []
        tasks = {u['id']:sorted({task for region in regions
                 if u['start'] < region['end'] and region['start'] < u['end'] for task in region['checks']}) for u in selected}
        for unit in selected:
            if (groups and abs(groups[-1][-1]['end']-unit['start']) < 1e-6
                    and tasks[groups[-1][-1]['id']] == tasks[unit['id']]):
                groups[-1].append(unit)
            else:
                groups.append([unit])
        for number, group in enumerate(groups):
            whole = len(groups)==1 and group[0]['start']==event['start'] and group[-1]['end']==event['end']
            windows.append({'parent': event['id'], 'id': event['id'] if whole else event['id']+f'.scope_{number:04}',
                            'start': group[0]['start'], 'end': group[-1]['end'], 'units': group,
                            'review_targets':tasks[group[0]['id']],
                            'candidate_ranges': merge_ranges(targets[event['id']])})
    if not windows:
        raise ValueError('No source units in candidate montage')
    return windows, {'source_events':len(events), 'review_windows':len(windows),
                     'source_units':total_units, 'review_units':selected_units}


def project_events(events, windows, *, directory=None, source=None, cancelled=lambda:False):
    by_id = {e['id']:e for e in events}
    first = {}
    for window in windows:
        first.setdefault(window['parent'], window['id'])
    result = []
    range_fields = ('protected_atmosphere_ranges','minimal_context_ranges', 'excluded_credit_ranges',
        'excluded_closing_ranges','excluded_review_ranges','excluded_title_units', 'verified_story_ranges',
        'verified_current_story_ranges','confirmed_credit_sequence_ranges','nonstory_role_ranges')
    for window in windows:
        check_cancelled(cancelled)
        parent = by_id[window['parent']]
        child = copy.deepcopy(parent)
        child.update(id=window['id'], start=window['start'], end=window['end'], units=copy.deepcopy(window['units']))
        child['review_targets'] = list(window.get('review_targets',[]))
        units = {u['id'] for u in child['units']}
        child['source_window'] = {'version':VERSION,'parent_event':parent['id'],
            'parent_start':parent['start'],'parent_end':parent['end'],
            'original_unit_ids':[u['id'] for u in child['units']]}
        child['requires'] = list(dict.fromkeys(first[i] for i in parent.get('requires', []) if i in first))
        child['selected_ranges'] = intersect_ranges(parent.get('selected_ranges') or window['candidate_ranges'], [window])
        if not child['selected_ranges']:
            # Required context still has to pass the unchanged source gate.
            child['selected_ranges'] = [{'start':window['start'],'end':window['end']}]
            child.update(selection_needs_adjudication=True, selection_uncertain=True)
        for key in ('action_units','dialogue_units','protected_atmosphere_units','atmosphere_review_units'):
            if key in child:
                child[key] = [i for i in child[key] if i in units]
        if 'unit_evidence' in child:
            child['unit_evidence'] = [r for r in child['unit_evidence'] if r.get('unit') in units]
        for key in range_fields:
            if isinstance(child.get(key), list) and all(isinstance(r,dict) and 'start' in r and 'end' in r for r in child[key]):
                child[key] = [{**r,**piece} for r in child[key] for piece in intersect_ranges([r],[window])]
        child['focus'] = [r for r in child.get('focus',[]) if child['start'] <= r['time'] <= child['end']]
        child['boundary_times'] = [t for t in child.get('boundary_times',[]) if child['start'] <= t <= child['end']]
        changed = (child['start'],child['end']) != (parent['start'],parent['end'])
        if changed:
            from .source_roles import authoritative_opening_ranges, authoritative_ending_ranges, verified_story_ranges
            sequence = [*authoritative_opening_ranges(parent),*authoritative_ending_ranges(parent)]
            child['verified_current_story_ranges'] = intersect_ranges(verified_story_ranges(parent),[window])
            if sequence:
                # Preserve the original boundary proof; never relabel cropped
                # bounds as independently verified opening/ending boundaries.
                child['source_window']['parent_sequence_proofs'] = copy.deepcopy(
                    [*parent.get('confirmed_opening_proofs',[]),*parent.get('confirmed_nonstory_ending_proofs',[])])
                child['excluded_credit_ranges'] = merge_ranges(
                    [*child.get('excluded_credit_ranges',[]),*intersect_ranges(sequence,[window])])
            for key in ('confirmed_opening_ranges','confirmed_opening_proofs',
                        'confirmed_nonstory_ending_ranges','confirmed_nonstory_ending_proofs'):
                child.pop(key,None)
            child['state_before'] = None
            child['state_after'] = None
            child['causal_links'] = [r for r in child.get('causal_links',[]) if isinstance(r,dict)
                                    and r.get('from') in units and r.get('to') in units]
            for key in ('analysis_chunks','chunk_analyses','part_endings','story_structure','dialogue_relations'):
                child.pop(key, None)
            if directory is not None:
                from .vision import inference_storyboard
                from .source_identity import source_identity
                source_identity(Path(source),cancelled)
                filename = child['id']+'.jpg'
                image = Path(directory)/'visual'/filename
                image.resolve().relative_to((Path(directory)/'visual').resolve())
                image.parent.mkdir(parents=True,exist_ok=True)
                # The storyboard is candidate context, not selection proof.
                # Native adjudication retains its dense bounded CURRENT views.
                times = inference_storyboard(Path(source),child['start'],child['end'],child['units'],image,cancelled,
                                             sample_limit=18)
                child.update(image=filename, frames=times)
        result.append(child)
    return result


def prepare_review_scope(events, transcript, shots, probe, directory, source, journal, checks, diagnostics, report, cancelled):
    baseline, prepared = accepted_prefix(events,journal,directory,transcript,shots,probe['duration'])
    plan = candidate_plan(baseline,transcript,shots,probe,directory)
    windows, counters = source_windows(baseline,plan,transcript,shots)
    folder = Path(directory)/'review-scope'
    atomic_json(folder/'source-catalog.json',baseline)
    atomic_json(folder/'draft-plan.json',plan)
    atomic_json(folder/'scope.json',{'version':VERSION, **counters, 'windows':windows,
                                  'accepted_prefix':list(prepared), 'fingerprint':digest(windows),
                                  'check_regions':check_regions(baseline),
                                  'check_units':{task:sum(len(w['units']) for w in windows if task in w['review_targets'])
                                    for task in ('credits','titles','closing','source_roles')}})
    diagnostics.event('review_scope','selected',**counters)
    report('analyze',.48,f"Проверяем выбранные фрагменты: {counters['review_units']} из {counters['source_units']}")
    projected = project_events(baseline,windows,directory=directory if 'story_refinement' not in prepared else None,
                               source=source,cancelled=cancelled)
    checks.prepared = prepared
    return projected
