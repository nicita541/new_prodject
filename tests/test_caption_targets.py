"""Authored publication fixtures; no media decoding or inference is claimed."""
import copy

import pytest
from fastapi.testclient import TestClient

from app.artifact_publication import publish_revision
from app.caption_state import caption_path, caption_record, target_id
from app.finishing import FinishProfile
from app.json_store import atomic_json, read_json
from app.media import EXPORT_VALIDATION_VERSION
from app.server import create_app
from app.studio_render import _effective_part
from tests.test_committed_plan_finishing import published
from tests.test_finishing import authored_finishing


@pytest.fixture
def bound_job(published):
    manager, job, directory, original = published
    plan = copy.deepcopy(original)
    first = plan['parts'][0]
    first['candidate_id'] = 'story-a'
    second = {**copy.deepcopy(first), 'index': 2, 'candidate_id': 'story-b',
              'cuts': [{'start': 5, 'end': 8}],
              'subtitles': [{'start': .1, 'end': 1, 'text': 'Story B'}]}
    plan['parts'].append(second)

    def commit(value):
        artifacts = []
        for part in value['parts']:
            video = directory / 'output' / ('part_%03d.mp4' % part['index'])
            subtitles = video.with_suffix('.srt')
            video.write_bytes(('Authored ' + part['candidate_id']).encode())
            subtitles.write_text(part['subtitles'][0]['text'], 'utf-8')
            artifacts.append({'candidate_id': part['candidate_id'], 'video': video,
                'subtitles': subtitles, 'full_decode_version': EXPORT_VALIDATION_VERSION})
        publish_revision(directory, value, artifacts, producer_id=job['id'], attempt_id='authored')

    commit(plan)
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        project = client.post('/api/projects', json={'title': 'Caption targets'}).json()
        episode = client.post('/api/projects/' + project['id'] + '/episodes', json={'number': 1}).json()
        atomic_json(directory / 'job.json', {**job, 'episode_id': episode['id']})
        yield manager, job['id'], directory, plan, commit, client, episode['id']


def path(job_id, index=1):
    return f'/api/jobs/{job_id}/parts/{index}/captions'


def test_edits_follow_candidate_and_stale_rank_saves_fail_without_writes(bound_job):
    manager, job_id, directory, plan, commit, client, _ = bound_job
    loaded = client.get(path(job_id)).json()
    body = {key: loaded[key] for key in ('part_index', 'revision', 'target_id', 'cues')}
    body['cues'][0]['text'] = 'Edited story A'
    assert client.put(path(job_id), json=body).status_code == 200
    old_path = caption_path(directory, plan, plan['parts'][0])
    old_bytes = old_path.read_bytes()
    swapped = copy.deepcopy(plan)
    swapped['parts'] = list(reversed(swapped['parts']))
    for i, part in enumerate(swapped['parts'], 1):
        part['index'] = i
    commit(swapped)
    first = client.get(path(job_id)).json()
    second = client.get(path(job_id, 2)).json()
    assert first['cues'][0]['text'] == 'Story B'
    assert second['cues'][0]['text'] == 'Edited story A'
    assert second['part_index'] == 2 and second['revision'] == 1
    assert second['target_id'] == loaded['target_id']
    body['revision'] = 0  # Same revision as the newly ranked B: target still blocks it.
    assert client.put(path(job_id), json=body).status_code == 409
    assert old_path.read_bytes() == old_bytes
    assert not caption_path(directory, swapped, swapped['parts'][0]).exists()
    effective = _effective_part(manager, job_id, swapped['parts'][1], FinishProfile().model_dump())
    assert effective['subtitles'][0]['text'] == 'Edited story A'


def test_changed_source_geometry_resets_edits_preserving_old_record(bound_job):
    _, job_id, directory, plan, commit, client, _ = bound_job
    body = client.get(path(job_id)).json()
    body.pop('job_id')
    body['cues'][0]['text'] = 'Old cut edit'
    assert client.put(path(job_id), json=body).status_code == 200
    old_path = caption_path(directory, plan, plan['parts'][0])
    old_bytes = old_path.read_bytes()
    changed = copy.deepcopy(plan)
    changed['parts'][0]['cuts'] = [{'start': 2, 'end': 5}]
    commit(changed)
    fresh = client.get(path(job_id)).json()
    assert fresh['revision'] == 0 and fresh['target_id'] != body['target_id']
    assert fresh['cues'][0]['text'] == 'Published text'
    assert client.put(path(job_id), json=body).status_code == 409
    assert old_path.read_bytes() == old_bytes


def test_published_saves_require_target_and_never_adopt_unbound_rank_cues(bound_job):
    _, job_id, directory, plan, _, client, _ = bound_job
    legacy = directory / 'finishing/captions_001.json'
    atomic_json(legacy, {'revision': 7, 'cues': [{'start': 0, 'end': 1, 'text': 'Wrong old rank'}]})
    loaded = client.get(path(job_id)).json()
    assert loaded['revision'] == 0 and loaded['cues'][0]['text'] == 'Published text'
    assert client.put(path(job_id), json={'part_index': 1, 'revision': 0, 'cues': []}).status_code == 409
    assert read_json(legacy)['revision'] == 7
    assert not caption_path(directory, plan, plan['parts'][0]).exists()


def test_batch_target_conflict_preflights_before_caption_or_profile_changes(bound_job):
    _, job_id, directory, plan, _, client, episode_id = bound_job
    profile = client.get(f'/api/episodes/{episode_id}/finishing').json()
    profile.pop('episode_id')
    captions = [client.get(path(job_id, index)).json() for index in (1, 2)]
    for row in captions:
        row.pop('job_id')
        row['cues'] = [{'start': 0, 'end': 1, 'text': 'Should not write'}]
    captions[1]['target_id'] = 'f' * 64
    response = client.put(f'/api/jobs/{job_id}/finishing/state', json={'profile': profile, 'captions': captions})
    assert response.status_code == 409
    assert client.get(f'/api/episodes/{episode_id}/finishing').json()['revision'] == profile['revision']
    assert all(not caption_path(directory, plan, part).exists() for part in plan['parts'])


def test_target_tracks_source_words_and_geometry_but_not_rank_or_focus(bound_job):
    _, _, directory, plan, _, _, _ = bound_job
    part = plan['parts'][0]
    identity = target_id(directory, plan, part)
    changed = copy.deepcopy(part)
    changed.update(index=77, layout='portrait', caption_style='accent')
    changed['cuts'][0]['focus'] = [{'time': 1, 'x': .9}]
    assert target_id(directory, plan, changed) == identity
    changed['subtitles'][0]['text'] = 'Different source words'
    assert target_id(directory, plan, changed) != identity


def test_bound_record_with_wrong_owner_is_not_applied(bound_job):
    _, _, directory, plan, _, _, _ = bound_job
    part = plan['parts'][0]
    atomic_json(caption_path(directory, plan, part), {'target_id': 'a' * 64,
        'revision': 1, 'cues': []})
    with pytest.raises(ValueError, match='ownership'):
        caption_record(directory, plan, part)


def test_published_editor_batch_saves_each_owned_candidate(bound_job):
    _, job_id, directory, plan, _, client, episode_id = bound_job
    profile = client.get(f'/api/episodes/{episode_id}/finishing').json()
    profile.pop('episode_id')
    captions = [client.get(path(job_id, index)).json() for index in (1, 2)]
    for row in captions:
        row.pop('job_id')
        row['cues'][0]['text'] = 'Edited ' + str(row['part_index'])
    response = client.put(f'/api/jobs/{job_id}/finishing/state', json={'profile': profile, 'captions': captions})
    assert response.status_code == 200, response.text
    assert [row['target_id'] for row in response.json()['captions']] == [row['target_id'] for row in captions]
    assert [caption_record(directory, plan, part)['revision'] for part in plan['parts']] == [1, 1]
    assert [row['cues'][0]['text'] for row in response.json()['captions']] == ['Edited 1', 'Edited 2']


def test_queued_export_snapshots_bound_corrections(bound_job):
    import threading
    from app.studio_render import submit_render
    manager, job_id, _, _, _, client, _ = bound_job
    body = client.get(path(job_id)).json()
    body.pop('job_id')
    body['cues'][0]['text'] = 'Bound queued correction'
    assert client.put(path(job_id), json=body).status_code == 200
    entered, captured = threading.Event(), []
    def execute(source, part, probe, output, work, encoder, cancelled, **kwargs):
        captured.append(copy.deepcopy(part))
        entered.set()
        output.mkdir(parents=True, exist_ok=True)
        video = output/f"part_{part['index']:03}.mp4"
        video.write_bytes(b'Authored bound caption fixture, not media')
        return video
    with authored_finishing(manager, execute):
        submit_render(manager, job_id, [1], FinishProfile().model_dump())
        assert entered.wait(2)
    assert captured[0]['subtitles'][0]['text'] == 'Bound queued correction'
