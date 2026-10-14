"""Exact native relation contracts and bounded recovery of their source owners.

All episode data stays local. Only missing contracts in an explicit dependency
scope may dispatch. Cached model output is always checked by the native pass.
"""
from __future__ import annotations
import copy
from pathlib import Path

from .content_identity import digest, stable_semantics
from .json_store import read_json

VERSION = 1


def accepted_contract(path, identity, previous=None):
    """Return an unchanged accepted request, never relabel another question."""
    signature = digest(identity)
    candidates = []
    try:
        candidates.append(read_json(path,{}))
    except (OSError,ValueError,UnicodeError):
        pass
    for row in (previous or {}).get('history',[]):
        if row.get('checkpoint') == signature:
            candidates.append(row)
    for row in candidates:
        if not isinstance(row,dict):
            continue
        try:
            if (row.get('dependency_contract') == identity and row.get('checkpoint',row.get('signature')) == signature
                    and row.get('decision_hash') == digest(row.get('decision')) and row.get('producer')):
                return copy.deepcopy(row)
        except (ValueError,TypeError):
            continue
    return None


def contract_record(identity, raw, producer):
    return {'signature':digest(identity),'checkpoint':digest(identity),
            'dependency_contract':copy.deepcopy(identity),'decision':copy.deepcopy(raw),
            'decision_hash':digest(raw),'producer':copy.deepcopy(producer)}


def request_identity(implementation, policy, prompt, schema, nodes, current):
    # Native nodes retain exact source identity, word geometry and proof IDs.
    # Prompt/schema bind the actual CURRENT/context/registry contract. No
    # unrelated episode ASR, event summaries or provider identity is included.
    import hashlib
    return {'relation_contract_version':VERSION,'implementation':implementation,
            'contract_code':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'policy':copy.deepcopy(policy),'native_scope':stable_semantics(nodes),
            'CURRENT_refs':[copy.deepcopy(n['ref']) for n in current],
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'schema':copy.deepcopy(schema)}


def _ref(value):
    return (value['event'],value['unit'])


def recovery_scope(events, previous_analysis, changed_ids):
    """Actual owners, evidenced relation endpoints, and bounded neighbors."""
    from . import story_structure_pass as structure
    known = {e['id'] for e in events}
    if any(value not in known for value in changed_ids):
        raise ValueError('Unknown relation recovery owner')
    changed = {(e['id'],u['id']) for e in events if e['id'] in changed_ids for u in e.get('units',[])}
    previous_events = (previous_analysis or {}).get('events',[])
    removed = {e['id'] for e in previous_events}-known
    changed.update((e['id'],u['id']) for e in previous_events if e['id'] in changed_ids | removed for u in e.get('units',[]))
    wanted = set(changed)
    previous_structure = (previous_analysis or {}).get('story_structure',{})
    previous_dialogue = (previous_analysis or {}).get('dialogue_relations',{})
    # Exact former request dependencies identify owners whose source context
    # changed, without recursively turning adjacency into the entire episode.
    for aggregate in (previous_structure,previous_dialogue):
        for row in aggregate.get('history',[]):
            contract = row.get('dependency_contract',{})
            dependencies = {_ref(n['ref']) for n in contract.get('native_scope',[])}
            if changed.intersection(dependencies):
                wanted.update(_ref(r) for r in contract.get('CURRENT_refs',[]))
    relations = [*previous_structure.get('relations',[]),
                 *(r for e in previous_events for r in e.get('story_relations',[]))]
    arcs = [*previous_structure.get('arcs',[]),
            *(a for e in previous_events for a in e.get('inferred_story_arcs',[]))]
    pairs = [*previous_dialogue.get('pairs',[]),
             *(p for e in previous_events for p in e.get('dialogue_relations',{}).get('pairs',[]))]
    groups = [{_ref(r['from']),_ref(r['to'])} for r in relations]
    groups += [{_ref(r) for r in a.get('source_unit_refs',[])} for a in arcs]
    groups += [{_ref(r) for r in [*p.get('question_refs',[]),*p.get('answer_refs',[])]} for p in pairs]
    # Causal chains are genuine dependencies, unlike indiscriminate neighbors.
    while True:
        previous = set(wanted)
        for group in groups:
            if wanted.intersection(group):
                wanted.update(group)
        if wanted == previous:
            break
    ordered = sorted(((e['id'],u['id'],u['start'],u['end']) for e in events for u in e.get('units',[])),key=lambda x:(x[2],x[3],x[:2]))
    context = structure.POLICY['context_units_each_side']
    direct = set(wanted)
    for i,row in enumerate(ordered):
        if row[:2] in direct:
            wanted.update(n[:2] for n in ordered[max(0,i-context):i+context+1])
    return wanted.intersection(row[:2] for row in ordered)


def recover_relations(events, transcript, previous_analysis, changed_ids, job_dir,
                      vision, cancelled, report=lambda *args:None):
    """Rebuild complete native aggregates, dispatching only actual dependencies.

    Exact accepted contracts can be inherited from disk or previous aggregate
    history across cloud provider changes. Unproved legacy results cannot gain
    acceptance through this adapter merely because they were labelled accepted.
    """
    from .story_structure_pass import infer_story_structure
    from .dialogue_relations import infer_dialogue_relations, attach_dialogue_result
    changed_ids = set(changed_ids)
    allowed = recovery_scope(events,previous_analysis,changed_ids)
    report('quality_gate',.68,f'Уточняем связи только зависимых исходных фрагментов: {len(allowed)}')
    structure = infer_story_structure(events,transcript,job_dir,vision,cancelled,
        previous=(previous_analysis or {}).get('story_structure'),dispatch_refs=allowed)
    dialogue = infer_dialogue_relations(structure['events'],transcript,job_dir,vision,cancelled,
        relations=structure,previous=(previous_analysis or {}).get('dialogue_relations'),dispatch_refs=allowed)
    result_events = attach_dialogue_result(structure['events'],dialogue)
    structure['events'] = result_events
    return {'events':result_events,'story_structure':structure,'dialogue_relations':dialogue,
            'recovery_scope':[{'event':e,'unit':u} for e,u in sorted(allowed)]}
