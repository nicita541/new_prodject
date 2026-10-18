"""Versioned editorial objective; absent settings preserve legacy jobs."""
from __future__ import annotations

from pathlib import Path

from .json_store import read_json

LEGACY = 'episode_condensation'
STANDALONE = 'standalone_shorts'


def validate_objective(value=None):
    if value is None:
        return {'version': 1, 'objective': LEGACY}
    if (not isinstance(value, dict) or set(value)-{'version', 'objective', 'settings'}
            or type(value.get('version', 1)) is not int or value.get('version', 1) != 1
            or value.get('objective') not in (LEGACY, STANDALONE)):
        raise ValueError('Неизвестная цель монтажа или версия настроек')
    if value['objective'] == LEGACY:
        if value.get('settings'):
            raise ValueError('Параметры отдельных историй не применяются к сокращению серии')
        return {'version': 1, 'objective': LEGACY}
    from .standalone_planner import _settings
    return {'version': 1, 'objective': STANDALONE, 'settings': _settings(value.get('settings'))}


def load_objective(job_dir: Path):
    path = job_dir/'story-objective.json'
    return validate_objective(read_json(path)) if path.is_file() else validate_objective()
