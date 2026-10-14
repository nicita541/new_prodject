"""Exact native relation contracts and bounded recovery of their source owners.

All episode data stays local. Only missing contracts in an explicit dependency
scope may dispatch. Cached model output is always checked by the native pass.
"""
from __future__ import annotations
import copy
from functools import lru_cache
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


def _source_proof_bindings(job_dir, nodes):
    """Bind native text inheritance to available original-image proof records."""
    if job_dir is None:
        return None
    import re
    directory = Path(job_dir).resolve()
    meta = read_json(directory/'analysis.meta.json',{})
    source = meta.get('source')
    bindings = {}
    for node in nodes:
        for proof in node.get('proofs',[]):
            checkpoint = proof.get('checkpoint')
            if not isinstance(checkpoint,str) or not re.fullmatch(r'[0-9a-f]{64}',checkpoint):
                continue
            if checkpoint in bindings:
                continue
            path = directory/'selection-adjudication'/(checkpoint+'.json')
            if not path.is_file():
                continue  # Other accepted native passes own their existing proof references.
            native = read_json(path)
            evidence = native.get('source_evidence')
            if not isinstance(evidence,dict):
                continue
            if source and evidence.get('source',{}).get('sha256') != source:
                raise ValueError('Inherited relation proof belongs to another source')
            for name,expected in evidence.get('images',{}).items():
                image = Path(name).resolve()
                image.relative_to(directory)
                stat = image.stat()
                actual = _image_hash(str(image),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
                if actual != expected:
                    raise ValueError('Inherited relation proof image changed')
            bindings[checkpoint] = copy.deepcopy(evidence)
    return {'source_sha256':source,'native_image_proofs':bindings}


@lru_cache(maxsize=4096)
def _image_hash(path,size,mtime_ns,ctime_ns):
    import hashlib
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def request_identity(implementation, policy, prompt, schema, nodes, current, job_dir=None):
    # Native nodes retain exact source identity, word geometry and proof IDs.
    # Prompt/schema bind the actual CURRENT/context/registry contract. No
    # unrelated episode ASR, event summaries or provider identity is included.
    import hashlib
    return {'relation_contract_version':VERSION,'implementation':implementation,
            'contract_code':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'policy':copy.deepcopy(policy),'native_scope':stable_semantics(nodes),
            'source_proof_bindings':_source_proof_bindings(job_dir,nodes),
            'CURRENT_refs':[copy.deepcopy(n['ref']) for n in current],
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'schema':copy.deepcopy(schema)}


def _ref(value):
    return (value['event'],value['unit'])


def extra_context_nodes(previous, current, nodes):
    owners = {_ref(n['ref']) for n in current}
    wanted = {_ref(r) for row in (previous or {}).get('context_bindings',[])
              if _ref(row['owner']) in owners for r in row['refs']}
    return [n for n in nodes if _ref(n['ref']) in wanted-owners]


def prior_batch_size(previous, nodes, cursor, cap):
    """Retain accepted source cohort boundaries after a local insert/split.

    The first run keeps ordinary cross-owner packing. During repair the old
    CURRENT source intervals prevent one inserted unit from shifting every
    remaining batch. New units are still whole, and ordinary caps still apply.
    """
    boundaries=[]
    for row in (previous or {}).get('history',[]):
        contract=row.get('dependency_contract',{})
        current={_ref(r) for r in contract.get('CURRENT_refs',[])}
        owned=[n for n in contract.get('native_scope',[]) if _ref(n['ref']) in current]
        if owned:
            boundaries.append((min(n['start'] for n in owned),max(n['end'] for n in owned)))
    start=nodes[cursor]['start']
    end=next((right for left,right in sorted(boundaries) if left <= start < right),None)
    if end is None:
        end=next((left for left,right in sorted(boundaries) if left > start),None)
    if end is None:
        return cap
    return max(1,next((i for i,n in enumerate(nodes[cursor:cursor+cap]) if n['start'] >= end-1e-6),cap))


def _context_bindings(events, previous_analysis, changed_ids):
    """Keep actual far endpoints available; old refs only select new source context."""
    previous_analysis = previous_analysis or {}
    actual = {(e['id'],u['id']):u for e in events for u in e.get('units',[])}
    prior = {(e['id'],u['id']):u for e in previous_analysis.get('events',[]) for u in e.get('units',[])}
    removed = {r for r in prior if r not in actual}
    changed = {r for r in actual if r[0] in changed_ids} | removed
    def translated(ref):
        key = _ref(ref)
        if key in actual:
            return {key}
        old = prior.get(key)
        return {k for k,u in actual.items() if old and u['start'] < old['end'] and old['start'] < u['end']}
    bindings = {}
    for name in ('story_structure','dialogue_relations'):
        for row in previous_analysis.get(name,{}).get('context_bindings',[]):
            for owner in translated(row['owner']):
                bindings.setdefault(owner,set()).update(k for r in row['refs'] for k in translated(r))
    story = previous_analysis.get('story_structure',{})
    dialogue = previous_analysis.get('dialogue_relations',{})
    groups = [[r['from'],r['to']] for r in story.get('relations',[])]
    groups += [a.get('source_unit_refs',[]) for a in story.get('arcs',[])]
    groups += [[*p.get('question_refs',[]),*p.get('answer_refs',[])] for p in dialogue.get('pairs',[])]
    for group in groups:
        if not changed.intersection(_ref(r) for r in group):
            continue
        mapped = {key for ref in group for key in translated(ref)}
        for owner in mapped:
            bindings.setdefault(owner,set()).update(mapped-{owner})
    return [{'owner':{'event':owner[0],'unit':owner[1]},
             'refs':[{'event':e,'unit':u} for e,u in sorted(refs-{owner})]}
            for owner,refs in sorted(bindings.items()) if refs-{owner}]


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
    Initial CURRENT batches retain ordinary cross-owner packing. Recovery keeps
    their previous source cohort boundaries, so a local split cannot regroup
    every later request. Only genuinely affected cohorts lose native reuse.
    """
    from .story_structure_pass import infer_story_structure
    from .dialogue_relations import infer_dialogue_relations, attach_dialogue_result
    changed_ids = set(changed_ids)
    allowed = recovery_scope(events,previous_analysis,changed_ids)
    bindings = _context_bindings(events,previous_analysis,changed_ids)
    previous_story = {**((previous_analysis or {}).get('story_structure') or {}),'context_bindings':bindings}
    previous_dialogue = {**((previous_analysis or {}).get('dialogue_relations') or {}),'context_bindings':bindings}
    report('quality_gate',.68,f'Уточняем связи только зависимых исходных фрагментов: {len(allowed)}')
    structure = infer_story_structure(events,transcript,job_dir,vision,cancelled,
        previous=previous_story,dispatch_refs=allowed)
    dialogue = infer_dialogue_relations(structure['events'],transcript,job_dir,vision,cancelled,
        relations=structure,previous=previous_dialogue,dispatch_refs=allowed)
    result_events = attach_dialogue_result(structure['events'],dialogue)
    structure['events'] = result_events
    return {'events':result_events,'story_structure':structure,'dialogue_relations':dialogue,
            'recovery_scope':[{'event':e,'unit':u} for e,u in sorted(allowed)]}
