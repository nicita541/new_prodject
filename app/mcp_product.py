"""Product MCP adapter. Studio's HTTP service remains the only mutation owner."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from app.finishing import FinishProfile, Cue, PreviewSubmission, ExportSubmission
from app.mcp_contract import ID, OP, LIMIT, OFFSET, TEXT, MCPError, Registry, ReplayJournal, digest, page, resolve_under
from app.studio_identity import backend_fingerprint

PROVIDER = Literal['local', 'deepseek', 'hybrid', 'deepseek_plan', 'local_flash_story',
                   'local_fast_story', 'local_flash_story_budgeted', 'antigravity_manual']
EPISODE = {'project_id': (ID, ...), 'episode_id': (ID, ...)}
JOB = {**EPISODE, 'job_id': (ID, ...)}
PAGING = {'offset': (OFFSET, 0), 'limit': (LIMIT, 30)}
PART = Annotated[int, Field(ge=1, le=100)]


class Product:
    def __init__(self, root: Path, backend='http://127.0.0.1:8765', *, transport=None, expected_backend=None):
        parsed = urlsplit(backend)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1', 'localhost'}
                or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise ValueError('MCP разрешает только loopback HTTP backend')
        self.root, self.backend = root.resolve(), backend.rstrip('/')
        self.expected_workspace = hashlib.sha256(str(self.root).casefold().encode()).hexdigest()[:20]
        self.expected_backend = expected_backend or backend_fingerprint()
        self.client = httpx.AsyncClient(base_url=self.backend, transport=transport,
            timeout=httpx.Timeout(30, connect=3), follow_redirects=False, trust_env=False,
            headers={'Origin': self.backend})
        self.journal = ReplayJournal(self.root / 'data/mcp/operations', root=self.root)
        self.registry = Registry('kadr_', self.journal)
        self._register()

    async def close(self):
        await self.journal.drain()
        await self.client.aclose()

    async def request(self, method, path, **kwargs):
        try:
            async with self.client.stream(method, path, **kwargs) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 32 * 1024 * 1024:
                        raise MCPError('backend_invalid_response', 'Ответ backend превышает 32 МБ')
                try:
                    data = json.loads(content) if content else None
                except (ValueError, UnicodeError):
                    raise MCPError('backend_invalid_response', 'Backend вернул не JSON') from None
                if response.status_code >= 400:
                    raise MCPError('backend_failure' if response.status_code >= 500 else 'backend_rejected',
                        str(data.get('detail', 'Запрос отклонён') if isinstance(data, dict) else 'Запрос отклонён'),
                        details={'http_status': response.status_code})
                if response.status_code >= 300:
                    raise MCPError('backend_invalid_response', 'Перенаправления backend запрещены')
                return data
        except httpx.HTTPError:
            raise MCPError('backend_unavailable', 'Сервер Studio недоступен. Запустите КАДР; повторный запуск монтажа автоматически не выполняется') from None

    async def identity(self, *, mutation=False):
        identity = await self.request('GET', '/api/studio/identity')
        if not isinstance(identity, dict):
            raise MCPError('backend_invalid_response', 'Identity backend должен быть объектом JSON')
        if identity.get('application') != 'kadr-studio' or identity.get('workspace') != self.expected_workspace:
            raise MCPError('wrong_backend', 'По этому адресу запущен другой проект/сервер')
        if mutation and identity.get('backend') != self.expected_backend:
            raise MCPError('stale_backend', 'Backend работает со старым кодом. Перезапустите Studio после завершения активных задач')
        return identity

    async def library(self):
        await self.identity()
        value = await self.request('GET', '/api/library', params={'read_only': 'true'})
        if (not isinstance(value, dict) or any(not isinstance(value.get(key), list) or
                any(not isinstance(item, dict) for item in value[key]) for key in ('projects', 'episodes'))):
            raise MCPError('backend_invalid_response', 'Backend вернул несовместимый каталог проектов/серий')
        return value

    async def target(self, project_id, episode_id=None, job_id=None):
        library = await self.library()
        project = next((p for p in library['projects'] if p['id'] == project_id), None)
        if project is None:
            raise MCPError('not_found', 'Проект не найден')
        result = {'project_id': project_id, 'project_title': project['title']}
        if episode_id:
            episode = next((e for e in library['episodes'] if e['id'] == episode_id), None)
            if episode is None or episode['project_id'] != project_id:
                raise MCPError('ownership_mismatch', 'Серия не принадлежит указанному проекту')
            result.update(episode_id=episode_id, episode_number=episode['number'], episode=episode)
            if job_id:
                if not any(j['id'] == job_id for j in episode.get('jobs', [])):
                    raise MCPError('ownership_mismatch', 'Задание не принадлежит указанной серии')
                result.update(job_id=job_id)
        return result

    async def mutate(self, method, path, **kwargs):
        await self.identity(mutation=True)
        return await self.request(method, path, **kwargs)

    def _register(self):
        add = self.registry.add
        add('get_operation', 'Inspect replay journal without executing or relaunching the command.', {'operation_id': (OP, ...)}, self.journal.inspect)
        add('get_app_status', 'Read readiness/identity; never launches processing.', {}, self.app_status)
        add('list_projects', 'List actual projects including optional archives.', {**PAGING, 'include_archived': (bool, False)}, self.projects)
        add('list_episodes', 'List episodes of the exact project.', {'project_id': (ID, ...), **PAGING, 'include_archived': (bool, False)}, self.episodes)
        add('get_episode', 'Get exact episode and linked jobs.', EPISODE, self.target)
        add('create_project', 'Create a project once for this operation ID.', {'title': (TEXT, ...)}, self.create_project, mutating=True)
        add('create_episode', 'Create episode within the exact project.', {'project_id': (ID, ...), 'number': (Annotated[int, Field(ge=1, le=9999)] | None, None)}, self.create_episode, mutating=True)
        add('list_sources', 'List registered video sources.', PAGING, self.sources)
        add('import_video', 'Upload MP4/MKV placed by the user in data/mcp/inbox. No disk-wide file access.', {'filename': (TEXT, ...)}, self.import_video, mutating=True)
        add('get_settings', 'Read episode settings and concurrency revision.', EPISODE, self.settings)
        add('update_settings', 'Save validated settings only if the supplied revision still matches Studio.',
            {**EPISODE, 'revision': (Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')], ...), 'source_id': (ID, ...),
             'analysis_provider': (PROVIDER, ...), 'layout': (Literal['portrait', 'cinema'], ...),
             'caption_style': (Literal['classic', 'accent'], ...)}, self.update_settings, mutating=True)
        for name, endpoint, fields in [('start_job', 'jobs', EPISODE), ('resume_job', 'retry', JOB), ('cancel_job', 'cancel', JOB), ('prepare_analysis', 'antigravity/prepare', JOB)]:
            async def action(endpoint=endpoint, **ids):
                target = await self.target(**ids)
                path = f"/api/jobs/{ids['job_id']}/{endpoint}" if 'job_id' in ids else f"/api/episodes/{ids['episode_id']}/{endpoint}"
                return {'target': target, 'result': await self.mutate('POST', path)}
            add(name, 'Explicit target; returns accepted job state, uses existing worker and cache.', fields, action, mutating=True)
        add('get_job_status', 'Read every stage counter, progress, status and concrete error.', JOB, self.job_status)
        add('wait_job_update', 'Wait at most 30s for status revision; timeout never stops the product job.',
            {**JOB, 'revision': (str, ...), 'wait_seconds': (Annotated[float, Field(ge=0, le=30)], 15.0)}, self.wait_update)
        for name, endpoint in [('get_plan', 'plan'), ('get_quality_summary', 'plan'), ('list_analysis_packets', 'antigravity')]:
            async def read(endpoint=endpoint, name=name, offset=0, limit=30, **ids):
                target = await self.target(**ids)
                value = await self.request('GET', f"/api/jobs/{ids['job_id']}/{endpoint}")
                if name == 'get_quality_summary': value = {k: v for k, v in value.items() if k in {'quality_summary', 'quality', 'warnings'}}
                elif name == 'get_plan':
                    value = {**{k: v for k, v in value.items() if k != 'parts'}, 'parts': page(value.get('parts', []), offset, limit)}
                    value.pop('debug_timeline', None)
                    value.pop('events', None)
                elif isinstance(value.get('packets'), list): value['packets'] = page(value['packets'], offset, limit)
                return {'target': target, 'result': value}
            add(name, 'Read persisted validated state with bounded pages.', {**JOB, **PAGING}, read)
        add('get_outputs', 'List registered output files and API URLs; no rendering.', {**JOB, **PAGING}, self.outputs)
        add('get_finishing', 'Read versioned episode styling.', EPISODE, self.get_finishing)
        add('update_finishing', 'Save shared styling with existing backend revision guard.',
            {**EPISODE, 'profile': (FinishProfile, ...), 'revision': (OFFSET, ...)}, self.update_finishing, mutating=True)
        add('get_captions', 'Read existing captions for a part.', {**JOB, 'part_index': (PART, ...)}, self.get_captions)
        add('update_captions', 'Save captions using the existing timing/order/revision validator.',
            {**JOB, 'part_index': (PART, ...), 'cues': (Annotated[list[Cue], Field(max_length=150)], ...), 'revision': (OFFSET, ...)}, self.update_captions, mutating=True)
        for name, endpoint, model in [('create_preview', 'previews', PreviewSubmission), ('start_export', 'exports', ExportSubmission)]:
            async def submit(endpoint=endpoint, settings=None, **ids):
                target = await self.target(**ids)
                # Pydantic dump uses from_seconds; HTTP preview input accepts alias "from".
                if endpoint == 'previews' and 'from_seconds' in settings: settings['from'] = settings.pop('from_seconds')
                return {'target': target, 'result': await self.mutate('POST', f"/api/jobs/{ids['job_id']}/{endpoint}", json=settings)}
            add(name, 'Submit asynchronous render; returns task ID immediately.', {**JOB, 'settings': (model, ...)}, submit, mutating=True)
        add('get_preview', 'Read preview task for the exact source job.', {**JOB, 'preview_id': (Annotated[str, Field(pattern=r'^pv_[0-9a-f]{32}$')], ...)}, self.get_preview)
        add('get_export', 'Read export only after verifying its source job.', {**JOB, 'export_id': (Annotated[str, Field(pattern=r'^ex_[0-9a-f]{32}$')], ...)}, self.get_export)
        add('save_outputs', 'Save completed MP4s to an existing folder inside this workspace.',
            {**JOB, 'destination': (TEXT, ...), 'filename': (TEXT | None, None), 'all': (bool, False)}, self.save_outputs, mutating=True)
        add('import_analysis_result', 'Validate a supplied JSON object via existing manual packet importer; never runs agy.',
            {**JOB, 'packet_id': (Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')], ...), 'result': (dict, ...)}, self.import_analysis, mutating=True)
        for kind in ('project', 'episode'):
            for action in ('archive', 'restore'):
                async def change(kind=kind, action=action, **ids):
                    target = await self.target(**ids)
                    identifier = ids[kind + '_id']
                    return {'target': target, 'result': await self.mutate('DELETE' if action == 'archive' else 'POST',
                        f'/api/{kind}s/{identifier}' + ('/restore' if action == 'restore' else ''))}
                add(action + '_' + kind, 'Reversible archive/restore with backend active-job checks.',
                    {'project_id': (ID, ...)} if kind == 'project' else EPISODE, change, mutating=True)

    async def app_status(self):
        identity = await self.identity()
        return {'identity': identity, 'backend_matches': identity['backend'] == self.expected_backend,
                'health': await self.request('GET', '/api/health')}

    async def projects(self, offset=0, limit=30, include_archived=False):
        return page([p for p in (await self.library())['projects'] if include_archived or not p.get('archived_at')], offset, limit)

    async def episodes(self, project_id, offset=0, limit=30, include_archived=False):
        await self.target(project_id)
        return page([e for e in (await self.library())['episodes'] if e['project_id'] == project_id and (include_archived or not e.get('archived_at'))], offset, limit)

    async def create_project(self, title):
        return await self.mutate('POST', '/api/projects', json={'title': title})

    async def create_episode(self, project_id, number=None):
        target = await self.target(project_id)
        return {'target': target, 'result': await self.mutate('POST', f'/api/projects/{project_id}/episodes', json={'number': number})}

    async def sources(self, offset=0, limit=30):
        await self.identity()
        return page(await self.request('GET', '/api/sources', params={'read_only': 'true'}), offset, limit)

    async def import_video(self, filename):
        if Path(filename).name != filename or ':' in filename or '\\' in filename or Path(filename).suffix.lower() not in {'.mp4', '.mkv'}:
            raise MCPError('path_denied', 'Укажите обычное имя MP4/MKV из data/mcp/inbox')
        inbox = resolve_under(self.root, 'data/mcp/inbox')
        path = resolve_under(inbox, filename)
        if not path.is_file(): raise MCPError('not_found', 'Файл в папке inbox не найден')
        await self.identity(mutation=True)
        with path.open('rb') as video:
            return await self.request('POST', '/api/import', files={'file': (filename, video, 'video/mp4')}, timeout=600)

    async def settings(self, **ids):
        target = await self.target(**ids)
        episode = target['episode']
        values = {'source_id': episode['source_id'], 'settings': episode['settings']}
        return {'target': target, **values, 'revision': digest(values)}

    async def update_settings(self, project_id, episode_id, revision, **values):
        target = await self.target(project_id, episode_id)
        result = await self.mutate('PUT', f'/api/episodes/{episode_id}/settings', json=values, headers={'If-Match': revision})
        return {'target': target, 'result': result, 'revision': digest({'source_id': result['source_id'], 'settings': result['settings']})}

    async def job_status(self, **ids):
        target = await self.target(**ids)
        job = await self.request('GET', f"/api/jobs/{ids['job_id']}")
        return {'target': target, 'job': job, 'revision': digest(job)}

    async def wait_update(self, revision, wait_seconds=15.0, **ids):
        deadline = asyncio.get_running_loop().time() + wait_seconds
        value = await self.job_status(**ids)
        while True:
            if value['revision'] != revision or asyncio.get_running_loop().time() >= deadline:
                return {**value, 'changed': value['revision'] != revision}
            await asyncio.sleep(min(1, max(0, deadline - asyncio.get_running_loop().time())))
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0: return {**value, 'changed': False}
            try:
                value = await asyncio.wait_for(self.job_status(**ids), timeout=remaining)
            except asyncio.TimeoutError:
                return {**value, 'changed': False, 'wait_expired': True}

    async def outputs(self, offset=0, limit=30, **ids):
        value = await self.job_status(**ids)
        return {'target': value['target'], **page(value['job'].get('files', []), offset, limit)}

    async def get_finishing(self, **ids):
        return {'target': await self.target(**ids), 'result': await self.request('GET', f"/api/episodes/{ids['episode_id']}/finishing")}

    async def update_finishing(self, profile, revision, **ids):
        return {'target': await self.target(**ids), 'result': await self.mutate('PUT', f"/api/episodes/{ids['episode_id']}/finishing", json={**profile, 'revision': revision})}

    async def get_captions(self, part_index, **ids):
        return {'target': await self.target(**ids), 'result': await self.request('GET', f"/api/jobs/{ids['job_id']}/parts/{part_index}/captions")}

    async def update_captions(self, part_index, cues, revision, **ids):
        return {'target': await self.target(**ids), 'result': await self.mutate('PUT', f"/api/jobs/{ids['job_id']}/parts/{part_index}/captions", json={'part_index': part_index, 'cues': cues, 'revision': revision})}

    async def get_preview(self, preview_id, **ids):
        return {'target': await self.target(**ids), 'result': await self.request('GET', f"/api/jobs/{ids['job_id']}/previews/{preview_id}")}

    async def get_export(self, export_id, **ids):
        target = await self.target(**ids)
        value = await self.request('GET', f'/api/exports/{export_id}')
        if value.get('source_job_id') != ids['job_id']: raise MCPError('ownership_mismatch', 'Экспорт относится к другому заданию')
        return {'target': target, 'result': value}

    async def save_outputs(self, destination, filename=None, all=False, **ids):
        target = await self.target(**ids)
        path = resolve_under(self.root, destination)
        if not path.is_dir(): raise MCPError('not_found', 'Папка назначения должна существовать')
        return {'target': target, 'result': await self.mutate('POST', f"/api/jobs/{ids['job_id']}/save-videos", json={'destination': str(path), 'filename': filename, 'all': all})}

    async def import_analysis(self, packet_id, result, **ids):
        if len(json.dumps(result).encode()) > 8 * 1024 * 1024: raise MCPError('input_too_large', 'Результат пакета превышает 8 МБ')
        return {'target': await self.target(**ids), 'result': await self.mutate('POST', f"/api/jobs/{ids['job_id']}/antigravity/{packet_id}/import", json=result)}
