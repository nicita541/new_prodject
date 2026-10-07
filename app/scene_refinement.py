"""Bounded story refinement whose technical children retain one scene owner."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .source_roles import merge_ranges, verified_story_ranges

SCENE_REFINEMENT_VERSION = 1

_LARGE_FIELDS = ('analysis_chunks', 'chunk_analyses', 'chunk_refinements', 'scene_evidence', 'units')
_PROOF_FIELDS = ('story_omission_review', 'verified_current_story_ranges', 'omitted_story_units',
                 'protected_atmosphere_units', 'protected_atmosphere_ranges', 'unit_selection_version')
_AUTHORITY_FIELDS = ('excluded_title_units', 'excluded_credit_ranges', 'excluded_closing_ranges',
                     'excluded_review_ranges', 'confirmed_opening_ranges', 'confirmed_opening_proofs',
                     'confirmed_nonstory_ending_ranges', 'confirmed_nonstory_ending_proofs',
                     'source_role_excluded', 'global_excluded', 'pacing_excluded')


def _bounded(ranges, start, end):
    result = []
    for interval in ranges:
        a, b = float(interval['start']), float(interval['end'])
        if not math.isfinite(a) or not math.isfinite(b) or a >= b:
            raise ValueError('Некорректный интервал сокращения смысловой сцены')
        a, b = max(start, a), min(end, b)
        if a < b:
            result.append({'start': a, 'end': b})
    return merge_ranges(result)


def _unique(values):
    result, seen = [], set()
    for value in values:
        identity = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if identity not in seen:
            seen.add(identity)
            result.append(copy.deepcopy(value))
    return result


def _child(parent, chunk, number):
    start, end = float(chunk['start']), float(chunk['end'])
    child = copy.deepcopy(parent)
    for key in (*_LARGE_FIELDS, *_PROOF_FIELDS, *_AUTHORITY_FIELDS,
                'speech_context_protections', 'question_pair_protections', 'speech_context_warnings'):
        child.pop(key, None)
    initial = parent.get('chunk_analyses', [])
    if number < len(initial):
        for key in ('summary', 'kind', 'importance', 'uncertain'):
            if key in initial[number]:
                child[key] = copy.deepcopy(initial[number][key])
    child.update(id=f'{parent["id"]}_chunk_{number:03d}', parent_event_id=parent['id'],
                 start=start, end=end, technical_chunk=True)
    child['selected_ranges'] = _bounded(parent.get('selected_ranges', [parent]), start, end) or [{'start': start, 'end': end}]
    child['focus'] = [f for f in parent.get('focus', []) if start <= f['time'] < end]
    child['boundary_times'] = [t for t in parent.get('boundary_times', []) if start < t < end]
    return child


def _prefix_review(review, prefix):
    result = copy.deepcopy(review)
    for decision in result['decision']['decisions']:
        decision['unit'] = prefix + decision['unit']
        if decision['retained_witness'] != 'none':
            decision['retained_witness'] = prefix + decision['retained_witness']
    result['restored_units'] = [prefix + unit for unit in result['restored_units']]
    for unit in result['verified_units']:
        unit['id'] = prefix + unit['id']
    return result


def _merge_parent(parent, children, profile):
    from .story import _valid_cache, STORY_VERSION
    result = copy.deepcopy(parent)
    # New selections supersede tentative earlier omission decisions. Existing
    # independently verified protections remain separately authoritative.
    for key in _PROOF_FIELDS:
        result.pop(key, None)
    selected, verified, atmosphere, omitted, reviews, history = [], [], [], [], [], []
    warnings = list(parent.get('story_warnings', []))
    speech = list(parent.get('speech_context_protections', []))
    questions = list(parent.get('question_pair_protections', []))
    speech_warnings = list(parent.get('speech_context_warnings', []))
    atmosphere.extend(parent.get('protected_atmosphere_ranges', []))
    verified.extend(verified_story_ranges(parent))
    if parent.get('story_omission_review'):
        saved = {'version': STORY_VERSION, 'signature': 'parent-proof', 'event': parent}
        if _valid_cache(saved, 'parent-proof', parent, profile):
            reviews.append(_prefix_review(parent['story_omission_review'], 'parent_'))
    validated = True
    atmosphere_ids = []
    summaries = []
    for number, supplied in enumerate(children):
        child = copy.deepcopy(supplied)
        start, end = child['start'], child['end']
        prefix = f'c{number:03d}_'
        proof_rejected = False
        if child.get('story_omission_review') or child.get('verified_current_story_ranges'):
            saved = {'version': STORY_VERSION, 'signature': 'child-proof', 'event': child}
            if not _valid_cache(saved, 'child-proof', child, profile):
                proof_rejected = True
                for key in ('story_omission_review', 'verified_current_story_ranges',
                            'omitted_story_units', 'unit_selection_version'):
                    child.pop(key, None)
                child.update(selection_uncertain=True, selected_ranges=[{'start': start, 'end': end}])
                warnings.append(f'Доказательства сокращения {child["id"]} не подтверждены; фрагмент сохранён')
        intervals = child.get('selected_ranges', [child])
        if any(float(r['start']) < start or float(r['end']) > end for r in intervals):
            raise ValueError('Сокращение технического фрагмента вышло за его исходные границы')
        selected.extend(_bounded(intervals, start, end))
        verified.extend(verified_story_ranges(child))
        atmosphere.extend(_bounded(child.get('protected_atmosphere_ranges', []), start, end))
        atmosphere_ids.extend(prefix + unit for unit in child.get('protected_atmosphere_units', []))
        for unit in child.get('omitted_story_units', []):
            omitted.append({**copy.deepcopy(unit), 'id': prefix + unit['id']})
        if child.get('story_omission_review'):
            reviews.append(_prefix_review(child['story_omission_review'], prefix))
        speech.extend(child.get('speech_context_protections', []))
        questions.extend(child.get('question_pair_protections', []))
        speech_warnings.extend(child.get('speech_context_warnings', []))
        warnings.extend(child.get('story_warnings', []))
        validated &= ((type(child.get('unit_selection_version')) is int and child['unit_selection_version'] == 1)
                      or child.get('credit_montage') is True) and not proof_rejected
        summaries.append(str(child.get('summary', '')))
        history.append({'child_event_id': child['id'], 'start': start, 'end': end,
                        'unit_prefix': prefix, 'proof_rejected': proof_rejected,
                        **{key: copy.deepcopy(child[key]) for key in
                           ('summary', 'kind', 'importance', 'uncertain', 'selection_uncertain', 'selected_ranges',
                            'unit_selection_version', 'contains_credits', 'credit_montage',
                            'story_omission_review', 'omitted_story_units', 'story_warnings') if key in child}})
    verified = _bounded(verified, parent['start'], parent['end'])
    atmosphere = _bounded(atmosphere, parent['start'], parent['end'])
    # Speech protections are evidence about actual source words; preserve their
    # core intervals even when a child proposed a different unit partition.
    speech_ranges = _bounded([p for p in [*speech, *questions] if 'start' in p and 'end' in p],
                             parent['start'], parent['end'])
    result['selected_ranges'] = merge_ranges([*selected, *verified, *atmosphere, *speech_ranges])
    kinds = {c.get('kind', 'story') for c in children}
    all_credits = all(c.get('credit_montage') is True for c in children) and not verified
    result['kind'] = next(iter(kinds)) if len(kinds) == 1 else 'story'
    if all_credits and result['kind'] == 'story':
        result['kind'] = children[0].get('credits_kind', 'opening')
    result['credit_montage'] = all_credits
    result['contains_credits'] = bool(parent.get('contains_credits')) or any(c.get('contains_credits') or c.get('credit_montage') for c in children)
    result['importance'] = max(int(c.get('importance', 4)) for c in children)
    if verified:
        result.update(kind='story', importance=max(4, result['importance']))
    if all_credits:
        result.update(importance=1, requires=[])
    result['uncertain'] = bool(parent.get('uncertain')) or any(c.get('uncertain') for c in children)
    result['selection_uncertain'] = any(c.get('selection_uncertain') for c in children) or any(h['proof_rejected'] for h in history)
    # Share the bounded summary budget across children so a late payoff is not
    # erased by taking the first 1500 characters of a long concatenation.
    allowance = max(1, (1500 - len(summaries) + 1) // max(1, len(summaries)))
    result['summary'] = '\n'.join(s[:allowance] for s in summaries)
    result.update(chunk_refinements=history, scene_refinement_version=SCENE_REFINEMENT_VERSION,
                  story_warnings=_unique(warnings))
    if validated:
        result['unit_selection_version'] = 1
    if reviews:
        result['story_omission_review'] = {'version': 2,
            'decision': {'decisions': [d for review in reviews for d in review['decision']['decisions']]},
            'restored_units': _unique([unit for review in reviews for unit in review['restored_units']]),
            'verified_units': [unit for review in reviews for unit in review['verified_units']]}
    if verified:
        result['verified_current_story_ranges'] = verified
    if atmosphere:
        result['protected_atmosphere_ranges'] = atmosphere
        result['protected_atmosphere_units'] = _unique([*parent.get('protected_atmosphere_units', []), *atmosphere_ids])
    if omitted:
        result['omitted_story_units'] = omitted
    for key, values in (('speech_context_protections', speech), ('question_pair_protections', questions),
                        ('speech_context_warnings', speech_warnings)):
        if values:
            result[key] = _unique(values)
    return result


def refine_scene_story(events, transcript, shots, job_dir, vision, report, cancelled):
    """Refine existing child collages and return one event per semantic parent.

    Flatten all children in one call so the existing refiner still sees the
    actual episode duration when deciding whether footage is near an OP/ED.
    Child credit classifications never manufacture whole-sequence exclusions.
    """
    from .editorial import load_profile
    from .story import refine_story
    parents = copy.deepcopy(events)
    children, owners = [], []
    for parent in parents:
        if cancelled():
            raise InterruptedError('Обработка отменена')
        chunks = parent.get('analysis_chunks')
        if not chunks:
            owners.append((len(children), len(children) + 1, False))
            children.append(copy.deepcopy(parent))
            continue
        start = parent['start']
        first = len(children)
        for number, chunk in enumerate(chunks):
            if (not math.isfinite(float(chunk['start'])) or not math.isfinite(float(chunk['end']))
                    or abs(float(chunk['start']) - start) > .000001 or chunk['end'] <= chunk['start']
                    or chunk.get('parent_scene_id') != parent.get('scene_id', parent.get('parent_scene_id'))):
                raise ValueError('Технические фрагменты не покрывают смысловую сцену последовательно')
            children.append(_child(parent, chunk, number))
            start = chunk['end']
        if abs(float(start) - parent['end']) > .000001:
            raise ValueError('Технические фрагменты не покрывают конец смысловой сцены')
        owners.append((first, len(children), True))
    refined = refine_story(children, transcript, shots, Path(job_dir), vision, report, cancelled)
    if len(refined) != len(children) or any((a['id'], a['start'], a['end']) != (b['id'], b['start'], b['end'])
                                          for a, b in zip(children, refined)):
        raise ValueError('Сокращение изменило владельца или границы исходного фрагмента')
    profile = load_profile(Path(job_dir))
    result = []
    for parent, (first, stop, chunked) in zip(parents, owners):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        result.append(_merge_parent(parent, refined[first:stop], profile) if chunked else refined[first])
    return result
