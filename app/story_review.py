"""Candidate story units, event validation, global omission checks, and LLM story review."""
from __future__ import annotations

import copy
import json
import math
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.vision import LocalVision


def analysis_context_limit(vision) -> int:
    from .deepseek import DeepSeekVision
    return vision.text_budget - 4000 if isinstance(vision, DeepSeekVision) else 5300


def validated_event(raw: dict, event_id: str, start: float, end: float, timestamps: list[float], earlier: set[str]) -> dict:
    kind = raw.get('kind', 'story')
    if kind not in ('story', 'opening', 'ending', 'recap', 'filler'):
        kind = 'story'
    importance = raw.get('importance', 4)
    if isinstance(importance, bool) or not isinstance(importance, (int, float)) or not math.isfinite(importance):
        importance = 4
    importance = min(5, max(1, int(importance)))
    focus = []
    for entry in raw.get('focus', []) if isinstance(raw.get('focus'), list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            frame_index = int(entry.get('frame', 0)) - 1
            if not 0 <= frame_index < len(timestamps):
                continue
            x, y = float(entry['x']), float(entry.get('y', 0.5))
            confidence = float(entry.get('confidence', 0.5))
            if not all(math.isfinite(v) for v in (x, y, confidence)) or not 0 <= x <= 1 or not 0 <= y <= 1:
                continue
            focus.append({'time': timestamps[frame_index], 'x': x, 'y': y, 'confidence': min(1, max(0, confidence))})
        except (ValueError, TypeError, KeyError):
            continue
    if not focus:
        focus = [{'time': start, 'x': 0.5, 'y': 0.5, 'confidence': 0.0}]
    return {'id': event_id, 'start': start, 'end': end, 'summary': str(raw.get('summary', 'События серии'))[:1500],
            'kind': kind, 'importance': importance,
            'requires': [x for x in raw.get('requires', []) if isinstance(x, str) and x in earlier] if isinstance(raw.get('requires'), list) else [],
            'focus': sorted(focus, key=lambda f: f['time']), 'boundary_times': [],
            'uncertain': bool(raw.get('uncertain', False))}


def candidate_units(start: float, end: float, transcript: dict, shots: list[dict] | None = None,
                    *, visual_during_speech=True, annotated=False) -> list[dict]:
    """Separate visible beats even during speech; never cut an ASR word."""
    words = transcript.get('words', [])
    segments = transcript.get('segments', [])
    boundaries = {start: ['interval_start'], end: ['interval_end']}

    def add(value, reason):
        if start < value < end and not any(w['start'] < value < w['end'] for w in words):
            nearest = min(boundaries, key=lambda b: abs(b-value))
            if abs(nearest-value) < .08:
                boundaries[nearest].append(reason)
            else:
                boundaries.setdefault(value, []).append(reason)

    for segment in segments:
        add(float(segment['end']), 'speech_boundary')
    for shot in shots or []:
        value = float(shot['start'])
        if not start < value < end:
            continue
        if not visual_during_speech and any(s['start']-.25 < value < s['end']+.3 for s in segments):
            continue
        # Prefer the nearest real word edge around a camera cut. Overlapping
        # ASR words may leave no safe edge; preserve that ambiguity explicitly.
        if any(w['start'] < value < w['end'] for w in words):
            edges = [float(w[key]) for w in words for key in ('start', 'end')
                     if abs(float(w[key])-value) <= .75
                     and not any(other['start'] < float(w[key]) < other['end'] for other in words)]
            if not edges:
                continue
            value = min(edges, key=lambda t: (abs(t-value), t))
        add(value, 'shot_transition')
    ordered = sorted(boundaries)
    return [{'id': f'u{i:03d}', 'start': a, 'end': b,
             **({'boundary_reason': sorted(set(boundaries[a]))} if annotated else {}),
             'text': ' '.join(w['text'] for w in (words or segments)
                              if w['start'] < b and w['end'] > a)}
            for i, (a, b) in enumerate(zip(ordered, ordered[1:])) if b > a]


def apply_unit_selection(event: dict, raw: dict, units: list[dict]) -> None:
    selection = raw.get('keep_units')
    known = {u['id'] for u in units}
    if selection is None:
        event.update(selected_ranges=[], uncertain=True, selection_uncertain=True, analysis_unresolved=True)
        return
    if not isinstance(selection, list) or any(not isinstance(u, str) or u not in known for u in selection):
        raise ValueError('Модель выбрала неизвестный исходный фрагмент')
    if not selection:
        event.update(selection_uncertain=True, analysis_unresolved=True)
    event['selected_ranges'] = [{'start': u['start'], 'end': u['end']} for u in units if u['id'] in selection]


VALID_OMIT_REASONS = {'redundant_exchange', 'repeated_information', 'nonstory', 'low_stakes_filler', 'exposition_without_action'}


def validate_global_omissions(decisions, known):
    omissions = decisions.get('omit')
    if not isinstance(omissions, list):
        raise ValueError('Некорректный список исключённых событий')
    ids = []
    for item in omissions:
        if (not isinstance(item, dict) or item.get('event') not in known
                or item.get('reason') not in VALID_OMIT_REASONS
                or not isinstance(item.get('evidence'), str) or not item['evidence'].strip()
                or ('reaction_or_humor' in item and type(item['reaction_or_humor']) is not bool)
                or isinstance(item.get('confidence'), bool) or not isinstance(item.get('confidence'), (float,int))
                or not math.isfinite(item['confidence']) or not 0 <= item['confidence'] <= 1):
            raise ValueError('Нет подтверждения исключения события')
        ids.append(item['event'])
    selected = set(decisions['keep'])
    if len(ids) != len(set(ids)) or set(ids) & selected or set(ids) | selected != known:
        raise ValueError('Общий отбор должен покрывать все события без пересечений')


def apply_global_selection(events, decisions, editorial_profile=None):
    """Only explicit validated omissions may overrule local importance."""
    from .editorial import DEFAULT_PROFILE
    profile=editorial_profile or DEFAULT_PROFILE
    from .source_roles import verified_story_ranges
    if 'omit' in decisions:
        validate_global_omissions(decisions, {e['id'] for e in events})
    omissions = {item['event']:item for item in decisions.get('omit', [])}
    for event in events:
        event.pop('global_excluded', None)
        event.pop('global_omission', None)
        omission = omissions.get(event['id'])
        if (omission and omission['confidence'] >= .85 and not event.get('uncertain')
                and not event.get('selection_uncertain')
                and not event.get('narrative_bridge')
                and not (omission.get('reaction_or_humor') and not profile.get('dramatic_condensation'))
                and not (verified_story_ranges(event) and event.get('selection_status') != 'accepted')
                and not (omission['reason'] in ('redundant_exchange','repeated_information')
                         and not profile['remove_exact_repetition'])
                and not (omission['reason'] in ('nonstory','low_stakes_filler','exposition_without_action') and not profile['remove_empty_holds'])
                and event['id'] not in decisions.get('incomplete_event_ids',[])):
            event['global_excluded'] = True
            event['global_omission'] = omission
        elif omission and (event.get('uncertain') or event.get('selection_uncertain')
                          or omission['confidence'] < .85):
            event['selection_uncertain'] = True


def global_story_review(vision: LocalVision, events: list[dict], editorial_profile=None) -> dict:
    from .deepseek import DeepSeekVision
    if isinstance(vision, DeepSeekVision):
        # A complete episode description is only tens of KB. The scene-sized
        # 20KB bound truncated every summary, making safe global omissions
        # impossible. Keep cache-only/cancellation/reasoning settings intact.
        vision = copy.copy(vision)
        vision.text_budget = 64000
    from .editorial import instruction as policy_instruction, DEFAULT_PROFILE
    profile = editorial_profile or DEFAULT_PROFILE
    dramatic = profile.get('dramatic_condensation', False)
    if dramatic:
        mode_instruction = (
            'DRAMATIC CONDENSATION MODE: Condense the episode into 5-8 focused, high-impact dramatic shorts. '
            'Focus strictly on the main dramatic conflicts, major revelations, emotional turning points, and decisive character actions. '
            'Omit low-stakes filler scenes, prolonged routine conversations with no plot development, and repetitive exchanges. '
            'Mark omissions with reason in redundant_exchange, repeated_information, nonstory, low_stakes_filler, exposition_without_action. '
            'Mark reaction_or_humor=true if the scene is primarily light comedy or banter without plot consequences. '
            'CRITICAL: NEVER omit a narrative bridge: an event or non-verbal transition connecting State A to State B '
            '(e.g. capture, departure, sudden accident, transport, handover) where omitting it would cause '
            'an unexplained jump or broken causal continuity between surrounding events. Put such events into "narrative_bridges". '
        )
    else:
        mode_instruction = (
            'Edit a concise chronological episode, not an almost complete episode merely split into clips. '
            'Keep setup/payoff, causes/results, new information, significant relationship changes and consequential silent action. '
            'Only when the applied editorial profile permits repetition removal, remove whole exact redundant exchanges '
            'or repeated information when all necessary facts are conveyed by kept events. '
            'Preserve nearly all short reactions, jokes, banter and atmospheric exchanges even without plot progress. '
            'A whole repeated exchange can be removed only when it adds no distinct reaction, humor or emotional beat. '
            'Never drop an unresolved cause or needed context. '
            'Never omit a narrative bridge: an event or non-verbal transition connecting State A to State B '
            '(e.g. capture, departure, sudden accident, transport, handover) where omitting it would cause '
            'an unexplained jump or broken causal continuity between surrounding events. '
        )
    instruction = (policy_instruction(profile)+' '+mode_instruction+
        'For each removed event supply a concrete explanation of redundancy/nonstory evidence and confidence; '
        'Uncertainty and summary_complete=false require targeted verification, never keep-all. '
        'Use only resolved source-grounded choices; do not turn missing facts into a retention reason. '
        'Return JSON {"keep":[event ids],"omit":[{"event":id,"reason":"redundant_exchange|repeated_information|nonstory|low_stakes_filler|exposition_without_action",'
        '"evidence":"concrete explanation","confidence":0..1,"reaction_or_humor":boolean}],'
        '"narrative_bridges":[event ids connecting state changes or transitions],'
        '"dependencies":[{"event":id,"requires":[earlier ids]}],"summary":"Russian episode storyline"}. '
        'Events: ')
    # Measure actual model tokens and leave room for template and output. Keep
    # every event ID in this global view instead of truncating the episode tail.
    length = max((len(e['summary']) for e in events), default=1500)
    while True:
        summary = [{'id': e['id'], 'summary': e['summary'] if len(e['summary'])<=length else (
                    e['summary'][:length//2]+' [middle omitted] '+e['summary'][-length//2:]),
                    'summary_complete':len(e['summary'])<=length,
                    'kind': e['kind'], 'importance': e['importance']} for e in events]
        prompt = instruction + json.dumps(summary, ensure_ascii=False)
        if vision.token_count(prompt) <= analysis_context_limit(vision):
            break
        length //= 2
        if length < 40:
            raise ValueError('Серия слишком длинная для общего анализа: уменьшите размер входного видео')
    known = {e['id'] for e in events}
    id_list = {'type': 'array', 'items': {'type': 'string', 'enum': sorted(known)}}
    schema = {'type': 'object', 'properties': {'keep': id_list,
        'narrative_bridges': id_list,
        'dependencies': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'event': {'type': 'string', 'enum': sorted(known)}, 'requires': id_list},
            'required': ['event', 'requires'], 'additionalProperties': False}}, 'summary': {'type': 'string'}},
        'required': ['keep', 'omit', 'dependencies', 'summary'], 'additionalProperties': False}
    schema['properties']['omit'] = {'type':'array', 'items':{'type':'object', 'properties':{
        'event': {'type':'string', 'enum':sorted(known)},
        'reason': {'type':'string', 'enum':sorted(VALID_OMIT_REASONS)},
        'evidence': {'type':'string'}, 'confidence':{'type':'number'},'reaction_or_humor':{'type':'boolean'}},
        'required':['event','reason','evidence','confidence','reaction_or_humor'], 'additionalProperties':False}}
    last_error = None
    def validate_decisions(decisions):
        keep = decisions.get('keep')
        dependencies = decisions.get('dependencies', [])
        if not isinstance(keep, list) or not keep or any(not isinstance(e, str) or e not in known for e in keep):
            raise ValueError('Модель вернула некорректные ссылки на события серии')
        if dependencies is None:
            dependencies = []
        if not isinstance(dependencies, list) or any(not isinstance(item, dict) for item in dependencies):
            raise ValueError('Модель вернула некорректные связи событий')
        bridges = decisions.get('narrative_bridges')
        if bridges is not None:
            if not isinstance(bridges, list) or any(not isinstance(e, str) or e not in known for e in bridges):
                raise ValueError('Модель вернула некорректные связи narrative_bridges')
        decisions['dependencies'] = dependencies
        if 'omit' in decisions:
            validate_global_omissions(decisions, known)
    for _ in range(3):
        try:
            from .deepseek import DeepSeekVision
            from .hybrid import query_checked
            decisions = query_checked(vision, prompt,
                max_tokens=1800 if isinstance(vision, DeepSeekVision) else 2200, schema=schema,
                validator=validate_decisions, validation_profile='global-existing-events-v2')
            decisions['incomplete_event_ids']=[s['id'] for s in summary if not s['summary_complete']]
            for event in events:
                if event['id'] in decisions.get('narrative_bridges', []):
                    event['narrative_bridge'] = True
            return decisions
        except (ValueError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
    raise ValueError(f'Общий анализ истории не завершён: {last_error}')
