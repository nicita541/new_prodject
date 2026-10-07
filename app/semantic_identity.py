"""Fixed, import-free semantic cache identities from code, prompts and policy.

Reading only these component modules avoids executing model/provider imports.
Runtime allowlists deliberately exclude configuration, credentials and paths.
Embedded prompt literals are covered by complete normalized source hashes.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
import sys


SEMANTIC_IDENTITY_VERSION = 1
_ROOT = Path(__file__).resolve().parent
_COMPONENTS = {
    'shot_detector': ('media_probe',),
    'scene_detector': ('scene_detection', 'semantic_boundary', 'media_evidence', 'episode_profile', 'media_probe'),
    'scene_grouping': ('scene_detection', 'semantic_boundary'),
    'visual_features': ('scene_detection', 'media_evidence', 'media_probe'),
    'storyboard': ('vision', 'story_review', 'media_probe'),
    'local_prompt': ('scene_analysis', 'scene_understanding', 'scene_detection', 'story_review', 'source_roles', 'editorial', 'vision', 'deepseek', 'selection_adjudication', 'selection_gate'),
    'recovery': ('scene_understanding', 'story_review', 'vision', 'deepseek', 'selection_adjudication', 'selection_gate'),
    'global_story': ('global_verification', 'scene_understanding', 'story_review', 'source_roles', 'editorial', 'vision', 'deepseek', 'selection_adjudication', 'selection_gate'),
    'episode_profile': ('episode_profile',),
    'story': ('story', 'scene_refinement', 'story_review', 'editorial', 'source_roles', 'production', 'vision', 'deepseek', 'selection_adjudication', 'selection_gate'),
    'pacing': ('pacing', 'editorial', 'source_roles', 'speech_context', 'titles', 'planner', 'vision', 'deepseek'),
    'planner': ('planner', 'dramatic_planner', 'episode_profile', 'story_structure', 'planner_audit', 'endings', 'pacing', 'source_roles', 'titles', 'subtitles', 'media_probe', 'selection_adjudication', 'selection_gate'),
    'ending': ('endings', 'planner', 'dramatic_planner', 'episode_profile', 'story_structure', 'source_roles', 'titles', 'subtitles', 'vision', 'deepseek')}
_OPTIONAL = {'story_structure', 'planner_audit'}
_CONSTANTS = {
    'media_probe': ('SHOT_DETECTOR_VERSION', 'BASE_SCENE_THRESHOLD'),
    'scene_detection': ('SCENE_DETECTOR_VERSION', 'SCENE_GROUPING_VERSION', 'VISUAL_FEATURE_VERSION', 'DEFAULT_SETTINGS'),
    'scene_analysis': ('SCENE_PROMPT',),
    'semantic_boundary': ('SEMANTIC_BOUNDARY_VERSION', 'BOUNDARY_PROMPT', 'BOUNDARY_RECOVERY_PROMPT', 'FLAGS', 'TRANSITIONS'),
    'media_evidence': ('VERSION', 'POLICY'),
    'selection_adjudication': ('VERSION', 'POLICY', 'ADJUDICATION_PROMPT', 'KINDS'),
    'selection_gate': ('VERSION',),
    'scene_understanding': ('SCENE_UNDERSTANDING_VERSION', 'RECOVERY_PROMPT', 'CONFIDENCE_FIELDS', 'UNCERTAINTY_REASONS', 'KINDS'),
    'global_verification': ('GLOBAL_VERIFICATION_VERSION', 'GLOBAL_VISUAL_PROMPT'),
    'episode_profile': ('EPISODE_PROFILE_VERSION', 'EPISODE_PROFILE_POLICY'),
    'story': ('STORY_VERSION', 'EDGE_VERSION', 'OMISSION_REASONS'),
    'scene_refinement': ('SCENE_REFINEMENT_VERSION',),
    'story_review': ('VALID_OMIT_REASONS',),
    'editorial': ('POLICY_ID', 'DRAMATIC_POLICY_ID', 'DEFAULT_PROFILE', 'DRAMATIC_PROFILE'),
    'pacing': ('PACING_VERSION', 'REMOVABLE'),
    'planner': ('PLANNER_VERSION', 'SCHEMA_VERSION', 'MAX_DURATION', 'TARGET_DURATION', 'SPEECH_LEAD', 'SPEECH_TAIL'),
    'dramatic_planner': ('TARGET_SHORT_MIN', 'TARGET_SHORT_OPTIMAL', 'TARGET_SHORT_MAX', 'MAX_SHORT_DURATION', 'MIN_PARTS', 'MAX_PARTS'),
    'endings': ('VERSION', 'RECOVERY_VERSION', 'KINDS'),
    'story_structure': ('STORY_STRUCTURE_VERSION', 'CONTINUITY_VERSION'),
    'planner_audit': ('PLANNER_AUDIT_VERSION',),
    'deepseek': ('SYSTEM', 'PROFILE'),
    'source_roles': ('VERSION', 'ROLES', 'EXCLUSION_KEYS'),
    'speech_context': ('PREFIX_WORDS',),
    'titles': ('TITLES_VERSION',),
    'subtitles': ('TEXT_WIDTH',),
    'vision': (), 'production': ()}


def _canonical(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    raise ValueError('Неподдерживаемое значение политики semantic identity')


def _hash(value):
    return hashlib.sha256(json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _text_hash(text):
    return hashlib.sha256(text.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')).hexdigest()


def _literal(node, earlier):
    """Evaluate only literal data and earlier literal names, never calls/imports."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in earlier:
        return earlier[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_literal(item, earlier) for item in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else set(values) if isinstance(node, ast.Set) else values
    if isinstance(node, ast.Dict):
        values = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                spread = _literal(value, earlier)
                if not isinstance(spread, dict):
                    raise ValueError('Распаковка политики должна быть словарём')
                values.update(spread)
            else:
                values[_literal(key, earlier)] = _literal(value, earlier)
        return values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal(node.left, earlier) + _literal(node.right, earlier)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _literal(node.operand, earlier)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError('Не литеральная константа')


def _static_constants(tree):
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        try:
            value = _literal(node.value, values)
        except (ValueError, TypeError):
            continue
        values.update({name: value for name in names})
    return values


def component_identity(name):
    if name not in _COMPONENTS:
        raise ValueError(f'Неизвестный semantic компонент: {name}')
    sources, literals, runtime, prompts, versions = {}, {}, {}, {}, {}
    for filename in _COMPONENTS[name]:
        path = _ROOT / (filename+'.py')
        key = 'app/'+filename+'.py'
        if filename in _OPTIONAL and not path.is_file():
            sources[key] = 'component_not_present'
            continue
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=key)
        sources[key] = _text_hash(source)
        literals[key] = _hash([node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)])
        constants = _static_constants(tree)
        module = sys.modules.get('app.'+filename)
        for constant in _CONSTANTS.get(filename, ()):
            # getattr only for the fixed allowlist; no credential/config scan.
            value = getattr(module, constant) if module is not None and hasattr(module, constant) else constants.get(constant)
            if constant not in constants and (module is None or not hasattr(module, constant)):
                continue
            qualified = 'app.'+filename+'.'+constant
            runtime[qualified] = _hash(value)
            if 'PROMPT' in constant or constant == 'SYSTEM':
                prompts[qualified] = _text_hash(value) if isinstance(value, str) else _hash(value)
            if 'VERSION' in constant and type(value) in (int, str):
                versions[qualified] = value
    result = {'component': name, 'identity_version': SEMANTIC_IDENTITY_VERSION,
              'sources': sources, 'literal_text_hashes': literals, 'runtime_hashes': runtime,
              'prompt_hashes': prompts, 'versions': versions,
              'identity_policy_hash': _text_hash(Path(__file__).read_text(encoding='utf-8'))}
    return {**result, 'digest': _hash(result)}


def semantic_identity():
    result = {'version': SEMANTIC_IDENTITY_VERSION,
              'components': {name: component_identity(name) for name in _COMPONENTS}}
    return {**result, 'digest': _hash(result)}
