"""Editorial preference for typed reactions; source evidence stays caller-owned."""
from __future__ import annotations

import math

REACTION_KINDS = ('character_reaction', 'emotional_pause', 'comedic_payoff')


def preserve_reaction(profile, record):
    """A combined legacy flag cannot distinguish comedy from a plain reaction."""
    kind = record.get('reaction_kind', record.get('kind'))
    if kind in ('character_reaction', 'emotional_pause'):
        return profile['preserve_reactions']
    if kind == 'comedic_payoff':
        return profile['preserve_humor']
    return (record.get('reaction_or_humor') is True
            and (profile['preserve_reactions'] or profile['preserve_humor']))


def unit_reaction_kind(event, ident):
    """Only independently accepted concrete unit evidence can type a legacy flag."""
    kinds = set()
    for row in event.get('unit_evidence', []) if event.get('selection_status') == 'accepted' else []:
        confidence = row.get('confidence')
        if (row.get('unit') == ident and row.get('decision') == 'keep'
                and row.get('kind') in REACTION_KINDS
                and type(confidence) in (int, float) and math.isfinite(confidence) and confidence >= .9
                and isinstance(row.get('evidence'), str) and row['evidence'].strip()
                and (row.get('frame_indices') or row.get('frame_times'))):
            kinds.add(row['kind'])
    for row in event.get('story_omission_review', {}).get('decision', {}).get('decisions', []):
        confidence = row.get('confidence')
        if (row.get('unit') == ident and row.get('current_episode_story') is True
                and row.get('reaction_or_humor') is True and row.get('reaction_kind') in REACTION_KINDS
                and type(confidence) in (int, float) and math.isfinite(confidence) and confidence >= .9
                and isinstance(row.get('evidence'), str) and row['evidence'].strip() and row.get('frame_indices')):
            kinds.add(row['reaction_kind'])
    # Mixed evidence containing an actual comic payoff still has humor value.
    if 'comedic_payoff' in kinds:
        return 'comedic_payoff'
    return next(iter(kinds)) if len(kinds) == 1 else None


def preserve_unit_reaction(profile, event, ident, *, flagged):
    if not flagged:
        return False
    return preserve_reaction(profile, {'reaction_or_humor': True,
        'reaction_kind': unit_reaction_kind(event, ident)})


def reaction_instruction(profile, *, typed=True):
    parts = []
    if profile['preserve_reactions']:
        parts.append('Preserve specific visible character reactions and emotional pauses even without plot progress.')
    else:
        parts.append('A non-comedic character reaction or emotional pause is not by itself a retention reason; '
                     'keep actual consequences, decisive responses, emotional turning points and needed setup/payoff.')
    if profile['preserve_humor']:
        parts.append('Preserve jokes, comic timing and comedic setup/payoff.')
    else:
        parts.append('Humor alone is not a retention reason; causal and source-evidence safeguards still apply.')
    if typed:
        parts.append('When reporting reaction_or_humor=true, distinguish reaction_kind=character_reaction, '
                     'emotional_pause or comedic_payoff; do not call an ordinary reaction comedy.')
    return ' '.join(parts)+' '
