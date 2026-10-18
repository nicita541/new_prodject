"""Caption corrections follow source candidates rather than public ranks."""
from __future__ import annotations

import copy
from pathlib import Path

from .content_identity import digest
from .json_store import read_json


def requires_target(job_dir: Path, part: dict) -> bool:
    return (Path(job_dir) / 'publication.json').exists() or bool(part.get('candidate_id'))


def target_id(job_dir: Path, plan: dict, part: dict) -> str:
    """Keep rank/style changes independent of source geometry and words."""
    return digest({'version': 1, 'job_id': Path(job_dir).resolve().name,
        'source': plan.get('source'), 'candidate_id': part.get('candidate_id'),
        'duration': part.get('duration'), 'subtitles': part.get('subtitles'),
        'cuts': [{key: cut.get(key) for key in ('start', 'end')}
                 for cut in part.get('cuts', [])]})


def caption_path(job_dir: Path, plan: dict, part: dict) -> Path:
    root = Path(job_dir).resolve()
    path = (root / 'finishing' / 'captions' / (target_id(root, plan, part) + '.json')
            if requires_target(root, part) else
            root / 'finishing' / ('captions_%03d.json' % part['index']))
    if not path.resolve().is_relative_to(root):
        raise ValueError('Caption state escapes job')
    return path


def caption_record(job_dir: Path, plan: dict, part: dict) -> dict:
    target = target_id(job_dir, plan, part)
    stored = read_json(caption_path(job_dir, plan, part))
    if stored is not None:
        if (not isinstance(stored, dict)
                or stored.get('job_id', Path(job_dir).name) != Path(job_dir).name
                or type(stored.get('revision')) is not int or stored['revision'] < 0
                or not isinstance(stored.get('cues'), list)
                or (requires_target(job_dir, part) and stored.get('target_id') != target)):
            raise ValueError('Invalid caption ownership')
        return {**copy.deepcopy(stored), 'job_id': Path(job_dir).name,
                'part_index': part['index'], 'target_id': target}
    return {'job_id': Path(job_dir).name, 'part_index': part['index'],
            'target_id': target, 'revision': 0,
            'cues': copy.deepcopy(part.get('subtitles', []) or [])}
