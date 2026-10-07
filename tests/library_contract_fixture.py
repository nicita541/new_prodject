"""Deterministic real Library/JobManager data for the React wire contract."""
from unittest.mock import patch
from types import SimpleNamespace
import uuid

from app.jobs import JobManager, atomic_json
from app.library import Library


def identifier(number):
    return str(uuid.UUID(int=number))


def build_library(root):
    manager = JobManager(root)
    library = Library(manager)
    ids = iter(uuid.UUID(int=n) for n in range(1, 11))
    with patch('app.library.uuid', SimpleNamespace(uuid4=lambda: next(ids))), \
            patch('app.library.now', return_value='2026-01-01T12:00:00+00:00'):
        p1 = library.create_project('Project 1')
        p2 = library.create_project('Project 2')
        p3 = library.create_project('Archived Project')
        e1 = library.create_episode(p1['id'], 1)
        library.create_episode(p1['id'], 2)
        library.create_episode(p2['id'], 1)
        library.create_episode(p2['id'], 2)
        e5 = library.create_episode(p1['id'], 3)
        library.create_episode(p3['id'], 1)
        e7 = library.create_episode(p3['id'], 2)
        library.archive('episode', e5['id'])
        library.archive('episode', e7['id'])
        library.archive('project', p3['id'])
    for index, (episode, status) in enumerate([(e1['id'],'completed'), (e1['id'],'failed'),
            (identifier(5),'running'), (identifier(6),'failed'),
            (identifier(7),'cancelled'), (identifier(7),'interrupted')], 1):
        job = {'id':identifier(100+index),'episode_id':episode,'source_id':identifier(200),
               'source_name':'source.mp4','status':status,'created_at':f'2026-01-0{index}T12:00:00+00:00',
               'analysis_provider':'local','layout':'cinema','caption_style':'accent',
               'progress':1 if status=='completed' else 0,'stage':'completed' if status=='completed' else 'prepare',
               'message':'','outputs':[]}
        directory = manager.job_dir(job['id'])
        directory.mkdir(parents=True)
        atomic_json(directory/'job.json',job)
    manager.active=(identifier(103),SimpleNamespace(terminate_tree=lambda:None,close=lambda:None))
    return manager, library
