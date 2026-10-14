"""Provider-independent wire encoding; native questions and validators stay local.

Domain modules own target/evidence selection. This layer removes representation
duplication only; it never truncates source facts or silently drops unknown fields.
"""
from __future__ import annotations

import json


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def compact_prompt(prompt):
    from .deepseek import _selection_wire_prompt
    from .selection_adjudication import ADJUDICATION_PROMPT
    prefix = ADJUDICATION_PROMPT + '\n'
    candidate = _selection_wire_prompt(prompt)
    if candidate != prompt:
        return candidate
    # A rejected answer adds a bounded question, not permission to restore a
    # larger packet. Compact the same source packet on source-validation retry.
    if prompt.startswith(prefix):
        try:
            _, end = json.JSONDecoder().raw_decode(prompt[len(prefix):])
            tail = prompt[len(prefix)+end:]
            if tail.startswith('\nThe previous response failed source validation:'):
                return _selection_wire_prompt(prompt[:len(prefix)+end]) + tail
        except (ValueError, TypeError):
            pass
    # Independent Antigravity tasks retain their individual contracts. Sharing
    # instructions cannot hide an expanded child packet from wire compaction.
    if prompt.startswith('Process each independent task below '):
        try:
            instruction, text = prompt.split('\n', 1)
            value = json.loads(text)
            tasks = value['tasks'] if isinstance(value, dict) else value
            shared = value.get('shared_instructions', '') if isinstance(value, dict) else ''
            changed = [{**task, 'prompt': compact_prompt(shared+task['prompt'])} for task in tasks]
            payload = {k:v for k,v in value.items() if k not in ('shared_instructions','tasks')} if isinstance(value,dict) else {}
            payload['tasks'] = changed
            instruction = instruction.replace(' For EACH task, its exact original prompt is shared_instructions followed by its prompt. Apply the shared instructions independently to every task.', '')
            candidate = instruction+'\n'+_encode(payload)
            if len(candidate) < len(prompt):
                return candidate
        except (ValueError, KeyError, TypeError):
            pass
    # Whitespace in a JSON data suffix has no evidence meaning. Preserve its
    # decoded values and every byte of surrounding instructions/source prose.
    starts = [i+1 for i,c in enumerate(prompt) if c == '\n' and prompt[i+1:i+2] in ('{','[')]
    if 'Events: ' in prompt:
        starts.append(prompt.index('Events: ')+len('Events: '))
    for start in starts:
        try:
            value, end = json.JSONDecoder().raw_decode(prompt[start:])
            candidate = prompt[:start]+_encode(value)+prompt[start+end:]
            if len(candidate) < len(prompt):
                return candidate
        except (ValueError, TypeError):
            continue
    return prompt


def record_payload(directory, provider, canonical, wire, pages):
    """Record sizes, never prompts, paths, speech or estimated token charges."""
    if directory is None:
        return
    from .pipeline_diagnostics import Diagnostics
    from .model_perf import _PURPOSE
    Diagnostics(directory).event('request_payload', 'prepared', provider=provider,
        purpose=_PURPOSE.get(), canonical_bytes=len(canonical.encode('utf-8')),
        wire_bytes=len(wire.encode('utf-8')), image_pages=pages)
