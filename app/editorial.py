"""Persisted editorial intent, separate from rendering and provider settings."""
from __future__ import annotations

import json
from pathlib import Path
from app.viewer_interest import INTEREST_INSTRUCTION

POLICY_ID = 'balanced-atmosphere-v1'
DRAMATIC_POLICY_ID = 'dramatic-shorts-v1'
DEFAULT_PROFILE = {'version':1,'policy':POLICY_ID,'preserve_reactions':True,
                   'preserve_humor':True,'remove_empty_holds':True,'remove_exact_repetition':True,
                   'dramatic_condensation':False}
DRAMATIC_PROFILE = {'version':1,'policy':DRAMATIC_POLICY_ID,'preserve_reactions':False,
                    'preserve_humor':True,'remove_empty_holds':True,'remove_exact_repetition':True,
                    'dramatic_condensation':True}


def load_profile(job_dir: Path, *, persist=False):
    path=job_dir/'editorial-settings.json'
    value=json.loads(path.read_text('utf-8')) if path.is_file() else dict(DEFAULT_PROFILE)
    if not isinstance(value, dict):
        raise ValueError('Некорректный редакторский профиль')
    value.setdefault('dramatic_condensation', value.get('policy') == DRAMATIC_POLICY_ID)
    if (set(value)!=set(DEFAULT_PROFILE)
            or type(value['version']) is not int or value['version']!=1 or value['policy'] not in (POLICY_ID, DRAMATIC_POLICY_ID)
            or any(type(value[k]) is not bool for k in DEFAULT_PROFILE if k not in ('version','policy'))):
        raise ValueError('Некорректный редакторский профиль')
    if persist and not path.is_file():
        from app.json_store import atomic_json
        atomic_json(path,value)
    return value


def instruction(profile):
    if profile.get('dramatic_condensation'):
        parts = [
            'Dramatic Shorts condensation: build focused, engaging Shorts with a soft part-count preference.',
            'Preserve the core dramatic arc: decisive character choices, escalating conflict, key twists, and climaxes.',
            'Omit low-stakes filler, slow background exposition, repetitive talk, and uneventful walking.',
            'Never omit a narrative bridge (causal physical transition connecting State A to State B) or an unresolved prerequisite.',
        ]
        if profile.get('preserve_humor'):
            parts.append('Preserve sharp punchlines, comedic climaxes, and decisive character reactions.')
        return ' '.join(parts) + ' ' + INTEREST_INSTRUCTION
    parts=['Balanced chronological condensation with no duration or removal quota.']
    parts.append('An unchanged pose, generic walking between places, repeated camera views, empty holds, and scenery alone are not reactions or atmosphere.')
    if profile.get('preserve_reactions'):
        parts.append('Preserve almost all specific character reactions and emotional pauses that are visibly carried by a character: a changed expression, gesture, interaction, or a clearly staged response. Silence can carry emotion. Do not protect neutral views only because they are quiet, slow, or plot-neutral.')
        if profile.get('remove_empty_holds'):
            parts.append('For neutral travel or holds, keep only the briefest establishing arrival/context and remove redundant views when neighboring frames prove no unique action or response is lost.')
    if profile.get('preserve_humor'):
        parts.append('Preserve almost all jokes, banter, comic timing and their setup/payoff even without new plot facts.')
    if not profile.get('remove_empty_holds'):
        parts.append('Do not shorten empty holds or neutral scenery.')
    if not profile.get('remove_exact_repetition'):
        parts.append('Do not remove repetitions.')
    return ' '.join(parts) + ' ' + INTEREST_INSTRUCTION
