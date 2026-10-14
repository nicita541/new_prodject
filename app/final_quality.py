"""Inspect source evidence and report pre-render quality failures; never run recovery."""
from __future__ import annotations


import copy
import math

from app.content_identity import evidence_digest as gate_identity

from .selection_gate import selection_readiness, source_selection_problems, positive_ranges, _covers
from .selection_adjudication import _source_text
from app.source_ranges import merge_ranges
from .source_roles import confirmed_exclusions
from app.source_ranges import subtract_ranges as _subtract

VERSION = 4
POLICY = {'max_recovery_passes':3, 'word_tolerance':.002,
          'uncertainty_retention':False, 'required_production_passes':['story_structure','dialogue_relations']}


def _planned_source(events,retained):
    prepared,selected = copy.deepcopy(events),set()
    for event in prepared:
        pieces = merge_ranges([{'start':max(event['start'],r['start']),'end':min(event['end'],r['end'])}
            for r in retained if r['start'] < event['end'] and r['end'] > event['start']])
        if pieces:
            event['selected_ranges'] = pieces
            selected.add(event['id'])
    return prepared,selected


def _confidence(value):
    return type(value) in (int,float) and math.isfinite(value) and .9<=value<=1


def _source_part_endings(events,transcript,parts,arcs,*,speech_overrides=()):
    """Resolve each actual part end from original source proofs, never plan claims."""
    from .story_structure_pass import source_units,_quote_in
    from .speech_handles import ending_matches
    try:
        nodes,_,_=source_units(events,transcript)
    except (ValueError,KeyError,TypeError):
        nodes=[]
    known={(n['ref']['event'],n['ref']['unit']):n for n in nodes}
    retained=[cut for part in parts for cut in part['cuts']]
    speech=[{**row,'id':f'r{i:04}'} for i,row in enumerate(transcript.get('segments',[])) if _covers(retained,[row])]
    verified={}
    for part in parts:
        boundary=part['cuts'][-1]['end']
        for arc in arcs:
            proof=arc.get('verification') or {}
            closing=arc.get('closing_unit') or {}
            node=known.get((closing.get('event'),closing.get('unit')))
            supports=[s for s in proof.get('proofs',[]) if s.get('ref')==closing]
            supported=bool(node and any(s.get('proof')==p['id'] and
                (not s.get('quote') or _quote_in(s['quote'],node['ASR']))
                for s in supports for p in node['proofs']))
            pieces=[{'start':max(node['start'],r['start']),'end':min(node['end'],r['end'])}
                for r in arc.get('source_ranges',[]) if node and node['start']<r['end'] and node['end']>r['start']]
            if ((abs(arc['end']-boundary)<=.002 or ending_matches(arc['end'],boundary,transcript,part['cuts'],overrides=speech_overrides)) and arc.get('complete_ending') is True
                    and arc.get('ending_verified') is True and arc.get('uncertain') is False
                    and proof.get('supported') is True and _confidence(proof.get('confidence'))
                    and supported and pieces and _covers(part['cuts'],pieces)):
                verified[part['index']]={'kind':'closure','time':boundary,'arc_id':arc['id'],
                    'confidence':proof['confidence'],'verification':copy.deepcopy(proof)}
                break
        if part['index'] in verified:
            continue
        before=[s for s in speech if s['end']<=boundary+.002]
        after=[s for s in speech if s['start']>=boundary-.002]
        for event in events:
            for ending in event.get('part_endings',[]):
                proof=ending.get('verification') or {}
                time=ending.get('time')
                context_matches=True
                if ending.get('context_signature'):
                    from .endings import _ending_context, _ending_context_hash
                    try:
                        context_matches=ending['context_signature']==_ending_context_hash(
                            _ending_context(ending,transcript,retained))
                    except (KeyError,TypeError,ValueError):
                        context_matches=False
                if (type(time) in (int,float) and math.isfinite(time)
                        and (abs(time-boundary)<=.002 or ending_matches(time,boundary,transcript,part['cuts'],overrides=speech_overrides))
                        and ending.get('kind') in ('closure','cliffhanger','transition')
                        and _confidence(ending.get('confidence')) and proof.get('supported') is True
                        and _confidence(proof.get('confidence')) and proof.get('evidence')
                        and ending.get('id') and proof.get('boundary')==ending['id']
                        and context_matches
                        and proof.get('last_reply')==(before[-1]['id'] if before else 'none')
                        and proof.get('next_reply')==(after[0]['id'] if after else 'none')):
                    verified[part['index']]=copy.deepcopy(ending)
                    break
    return verified


def inspect_final_quality(analysis, plan=None):
    problems, evidence_chain = [], []
    events = copy.deepcopy(analysis.get('events', []))
    transcript = analysis.get('transcript', {})
    for event in events:
        for unit in event.get('units', []):
            unit['text'] = _source_text(transcript,unit['start'],unit['end'])
    production = analysis.get('quality_policy') == 'source_proved_v1'

    def add(code, stage, **details):
        value = {'code':code, 'recovery_stage':stage, **details}
        if value not in problems:
            problems.append(value)

    if production or analysis.get('selection_gate') is not None:
        for row in selection_readiness(events)['unresolved']:
            owner = next(e for e in events if e['id'] == row['event'])
            reasons = set(owner.get('analysis_unresolved_reasons', []))
            stage = 'source_roles' if 'source_role_unresolved' in set(row['problems']) | reasons else (
                'selection_adjudication' if source_selection_problems(owner) else (
                'story_structure' if reasons and reasons <= {'story_structure_unresolved', 'dialogue_relations_unresolved'}
                    and 'story_structure_unresolved' in reasons else (
                'dialogue_relations' if reasons and reasons <= {'dialogue_relations_unresolved'} else 'selection_adjudication')
            ))
            add('unresolved_source_selection', stage, **row)
    if production:
        from .story_structure_pass import ROLES
        for scene in analysis.get('scenes', []):
            reasons = scene.get('uncertainty_reasons', [])
            if any(reason in ('ambiguous_internal_boundary','semantic_boundary_unresolved','unverified_scene_boundary') for reason in reasons):
                add('semantic_scene_ambiguity','semantic_boundary',scene=scene.get('id'),reasons=reasons)
        for event in events:
            if not event.get('selected_ranges'):
                continue
            for name in POLICY['required_production_passes']:
                if event.get(name, {}).get('status') != 'accepted':
                    add(name+'_unresolved',name,event=event['id'],
                        refs=event.get(name, {}).get('unresolved_refs', []))
            for unit in event.get('units', []):
                if not any(r['start'] < unit['end'] and r['end'] > unit['start'] for r in event.get('selected_ranges', [])):
                    continue
                ref = {'event':event['id'],'unit':unit['id']}
                assignment = next((row for row in event.get('story_structure', {}).get('units', [])
                                   if row.get('ref') == ref),None)
                roles = assignment.get('roles') if assignment else None
                if (not assignment or assignment.get('status') != 'accepted' or not isinstance(roles,list)
                        or not roles or any(role not in ROLES[:-1] for role in roles)):
                    add('unexplained_story_structure_unit','story_structure',event=event['id'],unit=unit['id'])
                coverage = next((row for row in event.get('dialogue_relations', {}).get('coverage', [])
                                 if row.get('ref') == ref),None)
                pieces = [{'start':max(unit['start'],r['start']),'end':min(unit['end'],r['end'])}
                          for r in event['selected_ranges'] if r['start'] < unit['end'] and r['end'] > unit['start']]
                if (not coverage or coverage.get('status') != 'CURRENT'
                        or coverage.get('dialogue_status') not in ('paired','not_dialogue_dependency')
                        or not _covers(coverage.get('source_ranges', []),pieces)):
                    add('unexplained_dialogue_unit','dialogue_relations',event=event['id'],unit=unit['id'])
    if plan is None:
        return {'version':VERSION,'status':'unresolved' if problems else 'passed',
                'problems':problems,'evidence_chain':[], 'phase':'before_planner'}
    cuts = [cut for part in plan['parts'] for cut in part['cuts']]
    retained = merge_ranges(cuts)
    source_endings={}
    if production:
        from .story_structure import build_story_arcs
        arcs=build_story_arcs(events,transcript)
        source_endings=_source_part_endings(events,transcript,plan['parts'],arcs,
                                          speech_overrides=analysis.get('speech_handle_overrides', []))
        for part in plan['parts']:
            if part['index'] not in source_endings:
                add('missing_original_semantic_ending','planner',part=part['index'],source_time=part['cuts'][-1]['end'])
    for part in plan['parts']:
        for cut in part['cuts']:
            for side in ('start','end'):
                if any(w['start']+.002 < cut[side] < w['end']-.002 for w in transcript.get('words', [])):
                    add('cut_asr_word','planner',part=part['index'],source_time=cut[side])
            if any(cut['start'] < excluded['end'] and cut['end'] > excluded['start']
                   for event in events for excluded in confirmed_exclusions(event)):
                add('retained_confirmed_exclusion','selection_adjudication',part=part['index'],range=cut)
    # Small nonverbal margins protect actual consonants beyond ASR timestamps.
    # They are independently recomputed, never accepted from plan metadata,
    # and do not authorize a new spoken word or a semantic bridge.
    if production:
        from .speech_handles import semantic_ranges
        try:
            retained = semantic_ranges(plan,events,transcript,analysis['probe']['duration'],
                                       overrides=analysis.get('speech_handle_overrides', []))
        except (ValueError,KeyError,TypeError):
            add('invalid_speech_handles','planner')
    # Every retained source span needs specific positive proof, with ASR
    # reconstructed from original words rather than a cached unit description.
    proof_ranges = []
    for original in events:
        event = copy.deepcopy(original)
        for unit in event.get('units', []):
            unit['text'] = _source_text(transcript,unit['start'],unit['end'])
        proof_ranges.extend(positive_ranges(event))
        for unit in event.get('units', []):
            pieces = [{'start':max(unit['start'],r['start']),'end':min(unit['end'],r['end'])}
                for r in retained if r['start'] < unit['end'] and r['end'] > unit['start']]
            if not pieces:
                continue
            proofs = [record for record in event.get('unit_evidence', []) if record.get('unit') == unit['id']
                      and record.get('decision') != 'drop' and positive_ranges({**event,'unit_evidence':[record]})]
            if production and not _covers(positive_ranges({**event,'unit_evidence':proofs}),pieces):
                add('unexplained_retained_unit','selection_adjudication',event=event['id'],unit=unit['id'],ranges=pieces)
            evidence_chain.append({'ref':{'event':event['id'],'unit':unit['id']},'ranges':pieces,
                'scene':event.get('scene_id'),'source_proofs':proofs,
                'semantic_understanding':{'source':event.get('summary_source'),'confidence':event.get('understanding_confidence')},
                'story_relations':[r for r in event.get('story_relations', []) if
                    {'event':event['id'],'unit':unit['id']} in (r.get('from'),r.get('to'))],
                'selection_reasons':[r['kind'] for r in proofs],
                'continuity_reasons':[b for b in plan.get('planner_diagnostics', {}).get('bridges', [])
                    if b['source_event'] == event['id'] and b.get('source_unit',unit['id']) == unit['id']],
                'part_boundary_reasons':[(source_endings.get(p['index']) or {'kind':'unresolved_source_ending'}) if production
                    else p.get('ending') or {'kind':'complete_source_boundary'}
                    for p in plan['parts'] if any(c['start'] < unit['end'] and c['end'] > unit['start'] for c in p['cuts'])]})
    if production and not _covers(proof_ranges,retained):
        add('unexplained_retained_ranges','selection_adjudication',ranges=retained)
    final_events = plan.get('events', events)
    for event in final_events:
        source_event = next((e for e in events if e['id'] == event['id']),None)
        known = {u['id'] for u in (source_event or event).get('units', [])}
        if not set(event.get('action_units', [])) <= known:
            add('unknown_action_ownership','selection_adjudication',event=event['id'])
        if event.get('uncertain') or event.get('selection_uncertain') or event.get('fallback') or event.get('analysis_unresolved'):
            add('generic_uncertainty_retention','selection_adjudication',event=event['id'])
        if event.get('protected_atmosphere_units') or event.get('protected_atmosphere_ranges'):
            add('generic_protected_atmosphere','selection_adjudication',event=event['id'])
    # Plans are derived decisions. Removing their metadata cannot erase a
    # confirmed dependency or physical action in the source analysis.
    for event in events:
        planned = next((e for e in final_events if e['id'] == event['id']),{})
        for unit in event.get('units', []):
            if unit['id'] not in set(event.get('action_units', [])) | set(planned.get('action_units', [])):
                continue
            pieces = [{'start':max(unit['start'],r['start']),'end':min(unit['end'],r['end'])}
                for r in retained if r['start'] < unit['end'] and r['end'] > unit['start']]
            consequential = _subtract([unit],confirmed_exclusions(event))
            if pieces and not _covers(pieces,consequential):
                add('consequential_action_truncated','selection_adjudication',event=event['id'],unit=unit['id'])
            for part in plan['parts'][:-1]:
                boundary = part['cuts'][-1]['end']
                if unit['start']+.002 < boundary < unit['end']-.002:
                    add('part_boundary_inside_action','planner',event=event['id'],unit=unit['id'],source_time=boundary)
        for pair in event.get('dialogue_relations', {}).get('pairs', []):
            if pair.get('status') != 'confirmed' or not pair.get('requires_answer'):
                continue
            q,a = _covers(retained,pair['question_ranges']),_covers(retained,pair['answer_ranges'])
            touched = any(r['start'] < kept['end'] and r['end'] > kept['start']
                          for r in [*pair['question_ranges'],*pair['answer_ranges']] for kept in retained)
            if touched and not (q and a):
                add('missing_required_dialogue_endpoint','continuity',pair=pair)
            elif q and not any(_covers(part['cuts'],[*pair['question_ranges'],*pair['answer_ranges']]) for part in plan['parts']):
                add('question_response_split_between_parts','planner',pair=pair)
    audit = plan.get('planner_diagnostics', {})
    transitions = list(audit.get('transitions', []))
    if production:
        from .source_continuity import resolve_source_continuity
        prepared,selected = _planned_source(events,retained)
        derived = resolve_source_continuity(prepared,selected,transcript,analysis['probe']['duration'])
        transitions.extend(derived['transitions'])
        for bridge in derived['bridges']:
            if not _covers(retained,bridge['ranges']):
                add('required_source_continuity_not_retained','planner',bridge=bridge)
    for transition in transitions:
        if transition.get('status') not in ('consistent',):
            add('unresolved_transition','continuity',transition=transition)
    for bridge in audit.get('bridges', []):
        if bridge.get('uncertain') or not bridge.get('evidence') or any(
                row.get('kind') == 'endpoint_context' for row in bridge.get('evidence', []) if isinstance(row,dict)):
            add('unverified_bridge','continuity',bridge=bridge)
    if production:
        from .story_structure import build_story_arcs
        arcs = build_story_arcs(events,transcript)
        for part in plan['parts']:
            boundary = part['cuts'][-1]['end']
            verified = part['index'] in source_endings
            for arc in arcs:
                if (arc.get('source_unit_refs') and not arc.get('uncertain',True)
                        and arc['start']+.002 < boundary < arc['end']-.002 and not verified):
                    add('unverified_boundary_inside_story_arc','planner',part=part['index'],
                        arc=arc['id'],source_time=boundary)
    return {'version':VERSION,'status':'unresolved' if problems else 'passed',
            'problems':problems,'evidence_chain':evidence_chain,'phase':'before_render',
            'retained_duration':sum(p['duration'] for p in plan['parts'])}


def source_recovery_identity(analysis):
    """Changing diagnostic/relationship metadata cannot authorize another source review."""
    return gate_identity({'transcript':analysis.get('transcript',{}),
        'source':{key:analysis.get('probe',{}).get(key) for key in ('duration','width','height','fps')},
        'events':[{'id':event.get('id'),'start':event.get('start'),'end':event.get('end'),
            # A failed model's fallback changes the proposed selection but not
            # the full CURRENT units already reviewed. It is not new evidence.
            'selected_ranges':None if source_selection_problems(event) else event.get('selected_ranges'),
            'units':[{key:unit.get(key) for key in ('id','start','end','text')} for unit in event.get('units',[])],
            'exclusions':confirmed_exclusions(event)} for event in analysis.get('events',[])],
        'scenes':[{key:scene.get(key) for key in ('id','start','end')} for scene in analysis.get('scenes',[])]})


def recovery_stalled(history):
    if len(history) < 2:
        return False
    previous,current=history[-2],history[-1]
    if current.get('source_recovery_identity') != previous.get('source_recovery_identity'):
        return False
    if current['gate'] == previous['gate']:
        return True
    # Source selection blocks relation recovery. Different downstream coverage
    # counts are not progress when exactly the same source owners still fail.
    def blockers(gate):
        return {(row.get('event'),row.get('recovery_stage')) for row in gate.get('problems',[])
            if row.get('code') == 'unresolved_source_selection' and row.get('event')
            and row.get('recovery_stage') in ('selection_adjudication','source_roles')}
    before,after=blockers(previous['gate']),blockers(current['gate'])
    return bool(before) and before == after


def quality_failure_message(gate, *, stalled=False):
    from collections import Counter
    counts = Counter(p['code'] for p in gate['problems'])
    details = ', '.join(f'{code} ({count})' for code, count in sorted(counts.items()))
    suffix = ('; повторная проверка не изменила результат. Сохранённые ответы требуют '
              'уточнения, повтор того же кэша остановлен' if stalled else '')
    return 'analysis_unresolved: final_quality_gate — '+details+suffix
