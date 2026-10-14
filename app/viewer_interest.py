"""Rank optional source material by story value and evidenced viewer interest.

This module does not classify media or authorize cuts. Categories are inherited
from the bounded story-structure pass; legacy emotional/comedic proof kinds can
supply a limited fallback. Speech quantity and generic closure have no bonus.
"""
from __future__ import annotations

import math

from app.content_identity import digest, stable_semantics
from app.selection_gate import positive_ranges, source_selection_problems
from app.source_roles import confirmed_exclusions
from app.source_ranges import intersect_ranges, subtract_ranges
from app.source_text import source_text, quote_in

VERSION = 1
INTEREST_WEIGHTS = {'conflict': 10, 'escalation': 14, 'reversal': 16,
                    'revelation': 14, 'humor': 14, 'emotional_payoff': 16,
                    'anticipation': 12, 'character_choice': 14, 'skill_payoff': 14}
INTEREST_KINDS = ('conflict', 'escalation', 'reversal', 'revelation', 'humor',
                  'emotional_payoff', 'anticipation', 'character_choice', 'skill_payoff')
MAX_INTEREST_BONUS = 32
PROOF_INTEREST = {'character_reaction': ('emotional_payoff', 8),
                  'emotional_pause': ('emotional_payoff', 16),
                  'comedic_payoff': ('humor', 14)}
INTEREST_INSTRUCTION = (
    'Assess viewer interest separately from plot necessity. Preserve concrete conflict, '
    'escalation, reversals, revelations, humorous setup/payoff, emotional payoff, '
    'anticipation, meaningful character choices and demonstrations of ability with stakes. '
    'A quiet response can deliver a stronger payoff than explanatory dialogue. '
    'Retain the supported setup and immediate reaction needed to experience that payoff. '
    'Speech density, movement, silence, a generic question/answer, or mere scene closure '
    'do not by themselves establish viewer interest. Remove redundant explanation and '
    'empty holds only when no distinct dramatic or emotional function is lost. '
    'Part count is a soft preference; never erase a needed buildup or payoff to meet it.'
)


def _confident(value):
    return type(value) in (int, float) and math.isfinite(value) and .9 <= value <= 1


def _signals(event, transcript):
    if (event.get('global_excluded') or event.get('pacing_excluded')
            or event.get('credit_montage') or event.get('kind') != 'story'):
        return []
    # ASR, not an old unit description, owns spoken evidence.
    source = {**event, 'units': [{**u, 'text': source_text(transcript, u['start'], u['end'])}
                               for u in event.get('units', [])]}
    if source_selection_problems(source):
        return []
    selected = subtract_ranges(event.get('selected_ranges', []), confirmed_exclusions(event))
    proofs, rows = {}, []
    for record in event.get('unit_evidence', []):
        if not isinstance(record, dict) or record.get('decision') != 'keep':
            continue
        pieces = intersect_ranges(positive_ranges({**source, 'unit_evidence': [record]}), selected)
        if not pieces:
            continue
        ref = {'event': event['id'], 'unit': record['unit']}
        ident = 'proof_' + digest({'ref': ref, 'record': stable_semantics(record)})[:24]
        proofs[ident] = (record, pieces)
        fallback = PROOF_INTEREST.get(record['kind'])
        if fallback:
            rows.append({'kind': fallback[0], 'weight': fallback[1], 'ref': ref,
                         'proof': ident, 'evidence': record['evidence'], 'ranges': pieces,
                         'origin': 'source_kind'})
    structure = event.get('story_structure', {})
    if (not isinstance(structure, dict) or structure.get('status') != 'accepted'
            or type(structure.get('version')) is not int or structure['version'] < 8):
        return rows
    units = structure.get('units', [])
    if not isinstance(units, list):
        return rows
    for unit in units:
        if not isinstance(unit, dict):
            continue
        kinds = unit.get('viewer_interest', [])
        ref = unit.get('ref')
        if (unit.get('status') != 'accepted' or not _confident(unit.get('confidence'))
                or not isinstance(kinds, list) or len(kinds) > 3
                or any(not isinstance(k, str) or k not in INTEREST_WEIGHTS for k in kinds)
                or len(kinds) != len(set(kinds)) or not isinstance(ref, dict)
                or ref.get('event') != event['id']
                or not isinstance(unit.get('evidence'), str) or len(unit['evidence'].strip()) < 12):
            continue
        support = unit.get('support', [])
        if not isinstance(support, list):
            continue
        owned = [r for r in support if isinstance(r, dict) and r.get('ref') == ref]
        if not owned or any(not isinstance(r.get('proof'), str) or r['proof'] not in proofs or
                proofs[r['proof']][0]['unit'] != ref.get('unit') or
                not isinstance(r.get('quote'), str) for r in owned):
            continue
        valid = True
        for citation in owned:
            record, pieces = proofs[citation['proof']]
            if citation['quote'].strip() and not any(quote_in(citation['quote'],
                    source_text(transcript, r['start'], r['end'])) for r in pieces):
                valid = False
        if not valid:
            continue
        for kind in kinds:
            for citation in owned:
                rows.append({'kind': kind, 'weight': INTEREST_WEIGHTS[kind], 'ref': ref,
                             'proof': citation['proof'], 'evidence': unit['evidence'],
                             'ranges': proofs[citation['proof']][1], 'origin': 'story_structure'})
    return rows


def interest_index(events, transcript):
    """Validate source interest once before enumerating allocation/boundary choices."""
    return {event['id']: _signals(event, transcript) for event in events}


def score_source(events, candidate_ranges, transcript, *, index=None):
    """Score only this candidate's real units; repeated labels do not inflate it."""
    story_value, ending_value, signals = 0.0, 0.0, []
    for event in events:
        ranges = candidate_ranges.get(event['id'], [])
        if not ranges:
            continue
        importance = event.get('importance', 3)
        if type(importance) in (int, float) and math.isfinite(importance):
            story_value = max(story_value, 4 * min(5, max(1, importance)))
        for signal in index[event['id']] if index is not None else _signals(event, transcript):
            pieces = intersect_ranges(signal['ranges'], ranges)
            if pieces:
                signals.append({**signal, 'ranges': pieces})
        for ending in event.get('part_endings', []):
            verification = ending.get('verification') or {}
            if (ending.get('kind') == 'cliffhanger' and verification.get('supported') is True
                    and _confident(verification.get('confidence')) and _confident(ending.get('confidence'))
                    and any(r['start'] < ending['time'] <= r['end'] + .002 for r in ranges)):
                ending_value = max(ending_value, 12 * ending['confidence'])
    strongest = {}
    for signal in signals:
        if signal['kind'] not in strongest or signal['weight'] > strongest[signal['kind']]['weight']:
            strongest[signal['kind']] = signal
    interest_value = min(MAX_INTEREST_BONUS, sum(s['weight'] for s in strongest.values()))
    return {'version': VERSION, 'story_value': story_value, 'viewer_interest_value': interest_value,
            'ending_value': ending_value, 'total': story_value + interest_value + ending_value,
            'signals': list(strongest.values()), 'speech_density_bonus': 0}


def score_event(event, transcript):
    return score_source([event], {event['id']: event.get('selected_ranges', [event])}, transcript)


def ending_cost(ending, interest):
    """Distinguish a dramatic exit from a structurally complete microdialogue."""
    verification = ending.get('verification') or {}
    verified = (ending.get('verified') is True or verification.get('supported') is True
                and _confident(verification.get('confidence')))
    if not verified or not _confident(ending.get('confidence')):
        return 6.0
    if ending.get('kind') == 'cliffhanger':
        return 0.0
    if ending.get('kind') == 'closure':
        return 1.0 if interest['viewer_interest_value'] > 0 else 6.0
    return 4.0
