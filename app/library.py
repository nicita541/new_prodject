"""Anime/episode ownership, additive to the existing source and job storage."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .jobs import atomic_json, contained, now, read_json, validate_id

DEFAULT_SETTINGS = {'analysis_provider': 'deepseek_plan', 'layout': 'cinema', 'caption_style': 'accent'}


def title(value):
    value = value.strip()
    if not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('Введите название от 1 до 200 символов')
    return value


class Library:
    def __init__(self, manager):
        self.manager = manager
        self.path = contained(manager.data / 'library.json', manager.root)
        with manager.mutex:
            self.data = read_json(self.path, {'version': 1, 'projects': {}, 'episodes': {}, 'legacy_jobs': {}})
            if self.data.get('version') != 1:
                raise ValueError('Неизвестная версия библиотеки проектов')
            self._migrate()

    def _save(self):
        try:
            atomic_json(self.path, self.data)
        except OSError:
            self.data = read_json(self.path, {'version': 1, 'projects': {}, 'episodes': {}, 'legacy_jobs': {}})
            raise

    def _project(self, identifier, archived=False):
        project = self.data['projects'][validate_id(identifier)]
        if project.get('archived_at') and not archived:
            raise KeyError(identifier)
        return project

    def _episode(self, identifier, archived=False):
        episode = self.data['episodes'][validate_id(identifier)]
        if not archived and not self.alive(episode):
            raise KeyError(identifier)
        return episode

    def alive(self, episode):
        return not episode.get('archived_at') and not self.data['projects'][episode['project_id']].get('archived_at')

    def _new_project(self, name):
        identifier = str(uuid.uuid4())
        result = {'id': identifier, 'title': title(name), 'created_at': now()}
        self.data['projects'][identifier] = result
        return result

    def _new_episode(self, project_id, number, source_id=None, settings=None):
        self._project(project_id)
        identifier = str(uuid.uuid4())
        result = {'id': identifier, 'project_id': project_id, 'number': number,
                  'title': f'Серия {number}', 'source_id': source_id,
                  'settings': dict(settings or DEFAULT_SETTINGS), 'created_at': now()}
        self.data['episodes'][identifier] = result
        return result

    def _migrate(self):
        jobs = self.manager.list_jobs()
        pending = [j for j in jobs if not j.get('episode_id') and j['id'] not in self.data['legacy_jobs']]
        if not pending:
            return
        self.manager.list_sources()
        changed = False
        # Oldest first: one registered source becomes one episode, not one job.
        for job in reversed(pending):
            record = read_json(self.manager.job_dir(job['id']) / 'source.json', {})
            source_id = next((i for i, s in self.manager.sources.items() if s['path'] == record.get('path')), None)
            if not source_id:
                continue
            episode = next((e for e in self.data['episodes'].values() if e['source_id'] == source_id), None)
            if not episode:
                name = job['source_name']
                match = re.search(r'[«「]([^»」]+)[»」]', name)
                anime = title(match.group(1) if match else Path(name).stem[:200])
                project = next((p for p in self.data['projects'].values() if not p.get('archived_at') and p['title'].casefold() == anime.casefold()), None)
                project = project or self._new_project(anime)
                number_match = re.search(r'(\d+)\s*сер', name, re.I)
                used = {e['number'] for e in self.data['episodes'].values() if e['project_id'] == project['id']}
                number = int(number_match.group(1)) if number_match else 1
                while number in used or number < 1:
                    number = max(used, default=0) + 1
                episode = self._new_episode(project['id'], number, source_id)
            episode['settings'] = {key: job.get(key, default) for key, default in DEFAULT_SETTINGS.items()}
            self.data['legacy_jobs'][job['id']] = episode['id']
            changed = True
        if changed:
            self._save()

    def snapshot(self):
        with self.manager.mutex:
            self._migrate()
            jobs = self.manager.list_jobs()
            episodes = []
            for episode in self.data['episodes'].values():
                attempts = [j for j in jobs if j.get('episode_id', self.data['legacy_jobs'].get(j['id'])) == episode['id']]
                episodes.append({**episode, 'jobs': [{'id': j['id'], 'status': j['status'],
                                                   'created_at': j['created_at']} for j in attempts]})
            return {'projects': list(self.data['projects'].values()), 'episodes': episodes}

    def create_project(self, name):
        with self.manager.mutex:
            name = title(name)
            if any(not p.get('archived_at') and p['title'].casefold() == name.casefold() for p in self.data['projects'].values()):
                raise ValueError('Проект с таким названием уже существует')
            project = self._new_project(name)
            self._save()
            return dict(project)

    def create_episode(self, project_id, number):
        with self.manager.mutex:
            self._project(project_id)
            used = {e['number'] for e in self.data['episodes'].values() if e['project_id'] == project_id and self.alive(e)}
            if number is None:
                number = max(used, default=0) + 1
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 9999:
                raise ValueError('Номер серии должен быть от 1 до 9999')
            if number in used:
                raise ValueError('Такая серия уже существует в этом проекте')
            result = self._new_episode(project_id, number)
            self._save()
            return dict(result)

    def save_episode(self, identifier, source_id, settings):
        with self.manager.mutex:
            episode = self._episode(identifier)
            if self.manager.busy():
                active = self.manager.get(self.manager.active[0])
                owner = active.get('episode_id') or self.data['legacy_jobs'].get(active['id'])
                if owner == identifier:
                    raise ValueError('Дождитесь окончания монтажа этой серии')
            self.manager.source(source_id)
            if episode['source_id'] and episode['source_id'] != source_id:
                raise ValueError('Этот подпроект уже связан с одним видео. Для другой серии создайте новый подпроект.')
            if any(e['id'] != identifier and self.alive(e) and e['source_id'] == source_id for e in self.data['episodes'].values()):
                raise ValueError('Это видео уже принадлежит другой серии')
            from .editing import validate_options
            options = validate_options(settings['layout'], settings['caption_style'])
            if settings['analysis_provider'] not in {'local', 'hybrid', 'deepseek', 'deepseek_plan', 'local_flash_story', 'local_fast_story', 'local_flash_story_budgeted'}:
                raise ValueError('Неизвестный способ анализа')
            episode.update(source_id=source_id, settings={**options, 'analysis_provider': settings['analysis_provider']})
            self._save()
            return dict(episode)

    def launch(self, identifier):
        with self.manager.mutex:
            episode = self._episode(identifier)
            if not episode['source_id']:
                raise ValueError('Сначала выберите и сохраните видео серии')
            return self.manager.create(episode['source_id'], **episode['settings'], episode_id=identifier)

    def archive(self, kind, identifier):
        with self.manager.mutex:
            item = self._project(identifier) if kind == 'project' else self._episode(identifier)
            if self.manager.busy():
                job = self.manager.get(self.manager.active[0])
                episode_id = job.get('episode_id') or self.data['legacy_jobs'].get(job['id'])
                active = self.data['episodes'].get(episode_id)
                if active and (active['project_id'] == identifier if kind == 'project' else episode_id == identifier):
                    from .jobs import BusyError
                    raise BusyError('Сначала завершите или отмените монтаж этой серии')
            item['archived_at'] = now()
            self._save()
            return {'id': identifier, 'archived': True}

    def restore(self, kind, identifier):
        with self.manager.mutex:
            item = self._project(identifier, True) if kind == 'project' else self._episode(identifier, True)
            if not item.get('archived_at'):
                return {'id': identifier, 'archived': False}
            if kind == 'project':
                if any(p['id'] != identifier and not p.get('archived_at') and p['title'].casefold() == item['title'].casefold() for p in self.data['projects'].values()):
                    raise ValueError('Сначала удалите другой активный проект с таким названием')
                targets = [e for e in self.data['episodes'].values() if e['project_id'] == identifier and not e.get('archived_at')]
            else:
                self._project(item['project_id'])
                if any(e['id'] != identifier and self.alive(e) and e['project_id'] == item['project_id'] and e['number'] == item['number'] for e in self.data['episodes'].values()):
                    raise ValueError('В проекте уже есть активная серия с таким номером')
                targets = [item]
            if any(t['source_id'] and e['source_id'] == t['source_id'] and e['id'] != t['id'] and self.alive(e) for t in targets for e in self.data['episodes'].values()):
                raise ValueError('Видео уже используется другой активной серией')
            item.pop('archived_at', None)
            self._save()
            return {'id': identifier, 'archived': False}
