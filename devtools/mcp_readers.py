"""Bounded allowlisted repository/diagnostic readers. No inference or repair."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from app.mcp_contract import MCPError, page, resolve_under, redact
from app.run_logging import scrub

MAX_JSON = 32 * 1024 * 1024
ARTIFACTS = {'job.json', 'source.json', 'probe.json', 'transcript.json', 'shots.json',
    'scenes.json', 'events.json', 'analysis.json', 'analysis-final.json', 'analysis-meta.json',
    'plan.json', 'timings.json', 'semantic_identity.json', 'feature-map.json', 'checkpoint.json'}
ARTIFACTS |= {'analysis.meta.json', 'events.meta.json', 'scenes.meta.json', 'scene-features.json',
    'scene-features.meta.json', 'media-evidence.json', 'media-evidence.meta.json', 'story-events.json',
    'story.json', 'episode_profile.json', 'story_structure-result.json', 'dialogue_relations-result.json',
    'final_quality_gate.json', 'analysis-settings.json', 'render-settings.json', 'editorial-settings.json',
    'planning-preferences.json'}
DIAGNOSTICS = {'run.json', 'summary.json', 'warnings.json', 'timeline.jsonl', 'decisions.jsonl',
    'scene_analysis.jsonl', 'scene_recovery.jsonl', 'planner.json', 'global_story.json',
    'episode_profile.json', 'story_structure.json', 'dialogue_relations.json',
    'proof-selection-gate.json', 'selection.json', 'shots.json', 'scenes.json', 'storyboard.json'}


class Readers:
    def __init__(self, root): self.root = Path(root).resolve()

    def source_files(self, docs=False):
        roots = ['docs'] if docs else ['app', 'devtools', 'tests', 'scripts', 'frontend/public', 'frontend/scripts']
        suffixes = {'.md'} if docs else {'.py', '.js', '.mjs', '.html', '.css', '.ps1', '.cmd', '.bat'}
        result = []
        for name in roots:
            for path in (self.root / name).rglob('*'):
                if path.suffix.lower() in suffixes and path.is_file():
                    resolved = resolve_under(self.root / name, path)
                    if resolved.stat().st_size <= 3 * 1024 * 1024:
                        result.append(path)
        if docs and (self.root / 'app/README.md').is_file():
            result.append(resolve_under(self.root, 'app/README.md'))
        return sorted(result)[:3000]

    def document(self, name, offset=0, limit=30):
        allowed = {'app/README.md', 'docs/ai/architecture.md', 'docs/audit/storage-and-modules.md'}
        if name not in allowed and not re.fullmatch(r'docs/ai/decisions/[A-Za-z0-9_.-]+\.md', name):
            raise MCPError('path_denied', 'Документ не входит в разрешённый список')
        return self.text(resolve_under(self.root, name), offset, limit)

    def text(self, path, offset=0, limit=100):
        if not path.is_file(): return {'available': False, 'path': path.relative_to(self.root).as_posix()}
        if path.stat().st_size > MAX_JSON: raise MCPError('artifact_too_large', 'Файл превышает 32 МБ; используйте журнал с курсором')
        text = path.read_text('utf-8-sig', errors='replace')
        lines = scrub(text, limit=len(text)).splitlines()
        return {'available': True, 'path': path.relative_to(self.root).as_posix(),
                **page([{'line': i + 1, 'text': row[:2000], 'truncated': len(row) > 2000} for i, row in enumerate(lines)], offset, limit)}

    def search(self, query, docs=False, offset=0, limit=30):
        items, total, truncated = [], 0, False
        for path in self.source_files(docs):
            for line, text in enumerate(path.read_text('utf-8-sig', errors='replace').splitlines(), 1):
                if query.casefold() in text.casefold():
                    total += 1
                    if offset < total <= offset + limit:
                        items.append({'path': path.relative_to(self.root).as_posix(), 'line': line, 'text': text[:2000]})
                    if total >= 10000: truncated = True; break
            if truncated: break
        return {'items': items, 'total': total, 'truncated': truncated,
                'next_offset': offset + limit if total > offset + limit else None}

    def symbols(self, symbol, callers=False, offset=0, limit=30):
        result = []
        for path in self.source_files():
            if path.suffix != '.py': continue
            try: tree = ast.parse(path.read_text('utf-8-sig'))
            except SyntaxError: continue
            for node in ast.walk(tree):
                if callers:
                    if not isinstance(node, ast.Call): continue
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                else:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
                    name = node.name
                if name == symbol:
                    result.append({'path': path.relative_to(self.root).as_posix(), 'line': node.lineno,
                        'end_line': node.end_lineno, 'kind': type(node).__name__, 'name': name})
        return {**page(result, offset, limit), 'coverage': 'Python AST; callers match syntactic names, dynamic/aliased calls may be absent or ambiguous'}

    def job(self, job_id):
        base = resolve_under(self.root, 'data/jobs')
        directory = resolve_under(base, job_id)
        if not (directory / 'job.json').is_file(): raise MCPError('not_found', 'Задание не найдено')
        return directory

    def json(self, path):
        resolve_under(self.root, path)
        if not path.is_file(): return None
        if path.stat().st_size > MAX_JSON: raise MCPError('artifact_too_large', 'JSON превышает 32 МБ')
        try: return json.loads(path.read_text('utf-8-sig'))
        except (ValueError, UnicodeError):
            raise MCPError('corrupt_json', 'Повреждённый JSON: ' + path.relative_to(self.root).as_posix()) from None

    def artifact(self, job_id, artifact):
        directory = self.job(job_id)
        if artifact in ARTIFACTS: return self.json(resolve_under(directory, artifact))
        if artifact.startswith('diagnostics/pipeline/') and artifact.removeprefix('diagnostics/pipeline/') in DIAGNOSTICS:
            return self.json(resolve_under(directory, artifact))
        if re.fullmatch(r'(render|runs|visual|focus|story-structure|dialogue-relations)/[A-Za-z0-9_.-]+\.json', artifact):
            return self.json(resolve_under(directory, artifact))
        raise MCPError('path_denied', 'Этот артефакт не доступен для MCP')

    def jsonl(self, path, cursor=0, limit=30, stage=None):
        resolve_under(self.root, path)
        if not path.is_file(): return {'available': False, 'items': [], 'next_cursor': None}
        # Byte cursor avoids reading multi-hour logs from the beginning.
        items, scanned, invalid = [], 0, 0
        with path.open('rb') as stream:
            if cursor > path.stat().st_size: raise MCPError('stale_cursor', 'Журнал был обрезан; начните с курсора 0')
            stream.seek(cursor)
            while len(items) < limit and scanned < 2 * 1024 * 1024:
                start = stream.tell()
                line = stream.readline(256 * 1024 + 1)
                if not line: break
                if not line.endswith(b'\n'):
                    if len(line) > 256 * 1024: raise MCPError('record_too_large', 'Строка журнала превышает 256 КБ')
                    stream.seek(start); break  # writer has not completed this row yet
                scanned += len(line)
                try: row = json.loads(line)
                except (ValueError, UnicodeError): invalid += 1; continue
                if stage and (not isinstance(row, dict) or row.get('stage') != stage): continue
                items.append({'cursor': start, 'record': row})
            next_cursor = stream.tell()
        return {'available': True, 'items': items, 'next_cursor': next_cursor,
                'invalid_records': invalid, 'path': path.relative_to(self.root).as_posix()}

    def packets(self, job_id):
        directory = self.job(job_id) / 'antigravity/packets'
        result = []
        for path in sorted(directory.glob('*/request.json'))[:10000]:
            path = resolve_under(self.job(job_id), path)
            request = self.json(path)
            if isinstance(request, dict):
                result.append({'request_id': path.parent.name, 'purpose': request.get('purpose'),
                    'result_available': (path.parent / 'result.json').is_file(), 'bytes': path.stat().st_size})
        return result

    def packet(self, job_id, request_id, artifact, offset=0, limit=30):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id): raise MCPError('path_denied', 'Некорректный ID пакета')
        if artifact not in {'request.json', 'result.json', 'schema.json', 'failure.json', 'reception.json'}:
            raise MCPError('path_denied', 'Файл пакета не доступен')
        path = resolve_under(self.job(job_id), f'antigravity/packets/{request_id}/{artifact}')
        value = self.json(path)
        if value is None: return {'available': False, 'artifact': artifact}
        lines = json.dumps(redact(value), ensure_ascii=False, indent=2).splitlines()
        return {'available': True, 'artifact': artifact,
                **page([{'line': i + 1, 'text': line[:2000], 'truncated': len(line) > 2000} for i, line in enumerate(lines)], offset, limit)}

    def trace(self, job_id, unit_id, offset=0, limit=30):
        matches = []
        for name in ('analysis.json', 'analysis-final.json', 'plan.json', 'events.json', 'story-events.json',
                     'story_structure-result.json', 'dialogue_relations-result.json',
                     'diagnostics/pipeline/selection.json', 'diagnostics/pipeline/story_structure.json'):
            value = self.artifact(job_id, name)
            stack = [('', value)]
            while stack:
                pointer, item = stack.pop()
                if isinstance(item, dict):
                    if (any(str(v) == unit_id for k, v in item.items() if k in {'id', 'unit_id', 'event_id', 'source_unit_id'})
                            or any(unit_id in [str(x) for x in v] for k, v in item.items()
                                if k in {'unit_ids', 'source_unit_ids', 'event_ids', 'requires'} and isinstance(v, list))):
                        matches.append({'artifact': name, 'pointer': pointer, 'record': item})
                    stack.extend((pointer + '/' + str(k), v) for k, v in item.items() if isinstance(v, (dict, list)))
                elif isinstance(item, list): stack.extend((pointer + '/' + str(i), v) for i, v in enumerate(item))
        return {**page(matches, offset, limit), 'coverage': 'Exact persisted IDs; no invented links or inference', 'available': bool(matches)}

    def checkpoints(self, job_id, offset=0, limit=30):
        directory = self.job(job_id)
        candidates = [p for p in directory.glob('*.json') if p.name in ARTIFACTS]
        for name in ('render', 'runs', 'visual', 'focus', 'story-structure', 'dialogue-relations'):
            candidates.extend(p for p in (directory / name).glob('*.json') if re.fullmatch(r'[A-Za-z0-9_.-]+\.json', p.name))
        candidates = sorted(candidates)[:10000]
        result = []
        for path in candidates[offset:offset + limit]:
            value = self.json(resolve_under(directory, path))
            result.append({'artifact': path.relative_to(directory).as_posix(), 'bytes': path.stat().st_size,
                'identity_fields': {k: v for k, v in value.items() if k in {'signature', 'fingerprint', 'identity', 'source', 'version', 'run_id'}} if isinstance(value, dict) else None})
        return {'items': result, 'total': len(candidates), 'next_offset': offset + limit if offset + limit < len(candidates) else None,
                'note': 'Persisted signatures only; cache compatibility is not guessed without current expected inputs'}
