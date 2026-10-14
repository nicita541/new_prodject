"""Restore repaired scene ownership for exact derived events; never raw perception."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .content_identity import digest
from .json_store import atomic_json,read_json


def _identity(job_dir,events,transcript,shots):
    source=read_json(Path(job_dir)/'analysis.meta.json',{}).get('source')
    if not isinstance(source,str) or len(source)!=64:
        return None
    names=('scoped_boundary_recovery','scoped_owner_refresh','scoped_relations',
           'quality_recovery','semantic_boundary','scene_detection','scoped_recovery_state')
    code={name:hashlib.sha256(Path(__file__).with_name(name+'.py').read_bytes()).hexdigest() for name in names}
    return {'version':1,'source_sha256':source,'events':digest(events),
            'transcript':digest(transcript),'shots':digest(shots),'repair_code':code}


def persist_repaired_scenes(job_dir,events,scenes,transcript,shots):
    identity=_identity(job_dir,events,transcript,shots)
    if identity is None or not scenes:
        return
    atomic_json(Path(job_dir)/'boundary-recovery'/'derived-ownership.json',
        {'identity':identity,'scenes':scenes,'scenes_hash':digest(scenes)})


def repaired_scenes(job_dir,events,transcript,shots,default):
    path=Path(job_dir)/'boundary-recovery'/'derived-ownership.json'
    if not path.is_file():
        return default
    try:
        row=read_json(path)
        identity=_identity(job_dir,events,transcript,shots)
        scenes=row['scenes']
        if (identity is None or row.get('identity')!=identity or row.get('scenes_hash')!=digest(scenes)
                or not isinstance(scenes,list) or not scenes):
            return default
        owners={s['id']:s for s in scenes}
        if len(owners)!=len(scenes) or any(e.get('scene_id') not in owners or
                not owners[e['scene_id']]['start']<=e['start']<e['end']<=owners[e['scene_id']]['end']
                for e in events):
            return default
        return scenes
    except (OSError,ValueError,KeyError,TypeError,UnicodeError):
        return default
