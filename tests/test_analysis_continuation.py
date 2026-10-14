"""Neutral stages, exact replies, provenance, corruption and partial failures."""
import hashlib
from unittest.mock import Mock, patch

import pytest

from app.analysis_continuation import (StageJournal, attach_replies, enable_continuation,
                                       ContinuationMiss)
from app.antigravity_exchange import ManualVision, import_result
from app.json_store import atomic_json, read_json
from app.pipeline_diagnostics import Diagnostics

SCHEMA = {'type': 'object', 'properties': {'value': {'type': 'integer', 'enum': [1, 2]}},
          'required': ['value'], 'additionalProperties': False}


@pytest.fixture
def job(tmp_path):
    source = hashlib.sha256(b'source').hexdigest()
    atomic_json(tmp_path / 'analysis.meta.json', {'source': source, 'version': 16})
    atomic_json(tmp_path / 'probe.json', {'duration': 10})
    atomic_json(tmp_path / 'transcript.json', {'words': [], 'segments': []})
    return tmp_path


def journal(job, transcript=None):
    return StageJournal(job, read_json(job / 'analysis.meta.json')['source'],
                        transcript or {'words': [], 'segments': []}, [], {}, Diagnostics(job),
                        lambda *args: None, lambda: False)


def legacy_reply(job, prompt='accepted', image=None):
    vision = ManualVision(job, lambda: False)
    directory, identifier, _ = vision._prepare_request(prompt, image, schema=SCHEMA)
    import_result(job, identifier, b'{"status":"SUCCESS","structured_output":{"value":1}}')
    return directory


class Vision:
    supports_image_pages = True
    def __init__(self):
        self.calls = []
    def query(self, prompt, image=None, max_tokens=1200, schema=None):
        self.calls.append(prompt)
        return {'value': 2}
    def query_many(self, tasks):
        self.calls.extend(task['prompt'] for task in tasks)
        return [{'value': 2} for task in tasks]


def test_completed_stage_reuses_original_producer_after_switch(job):
    stage = journal(job)
    original = [{'id': 'event', 'start': 0, 'end': 10}]
    run = Mock(return_value=[{**original[0], 'summary': 'accepted'}])
    first = stage.run('titles', original, run, 'antigravity_manual')
    second = stage.run('titles', original, lambda: pytest.fail('Must not repeat completed pass'), 'deepseek_plan')
    assert second == first and run.call_count == 1
    assert read_json(job / 'continuation/stages/titles.json')['producer'] == 'antigravity_manual'


def test_partial_failure_does_not_save_a_completed_stage(job):
    stage = journal(job)
    def fail():
        raise ContinuationMiss('unfinished')
    with pytest.raises(ContinuationMiss):
        stage.run('selection_adjudication', [], fail, 'antigravity_manual')
    assert not (job / 'continuation/stages/selection_adjudication.json').exists()
    assert stage.run('selection_adjudication', [], lambda: ['remaining'], 'deepseek_plan') == ['remaining']


def test_changed_inputs_transcript_code_or_output_cannot_reuse_stage(job):
    stage = journal(job)
    stage.save('titles', ['input'], ['accepted'], 'antigravity_manual')
    assert stage.load('titles', ['changed']) is None
    assert journal(job, {'words': [{'text': 'new'}], 'segments': []}).load('titles', ['input']) is None
    stage.context['story_code'] = 'changed-code'
    assert stage.load('titles', ['input']) is None
    path = job / 'continuation/stages/titles.json'
    row = read_json(path); row['output'] = ['tampered']; atomic_json(path, row)
    assert journal(job).load('titles', ['input']) is None


def test_exact_legacy_reply_skips_model_and_preserves_adapter_type(job):
    legacy_reply(job)
    enable_continuation(job, 'antigravity_manual', 'deepseek_plan')
    vision = attach_replies(Vision(), job, 'deepseek_plan', lambda: False)
    assert type(vision) is Vision and vision.supports_image_pages
    assert vision.query('accepted', schema=SCHEMA) == {'value': 1}
    assert vision.calls == []
    assert vision.query('new', schema=SCHEMA) == {'value': 2}
    assert vision.calls == ['new']
    # A following Antigravity session reuses the real DeepSeek reply as well.
    back = attach_replies(Vision(), job, 'antigravity_manual', lambda: False)
    assert back.query('new', schema=SCHEMA) == {'value': 2} and not back.calls


def test_only_unfinished_batch_members_are_sent_to_selected_provider(job):
    legacy_reply(job)
    enable_continuation(job, 'antigravity_manual', 'deepseek_plan')
    vision = attach_replies(Vision(), job, 'deepseek_plan', lambda: False)
    tasks = [{'prompt': prompt, 'schema': SCHEMA} for prompt in ('accepted', 'unfinished')]
    assert vision.query_many(tasks) == [{'value': 1}, {'value': 2}]
    assert vision.calls == ['unfinished']


def test_offline_miss_never_invokes_model(job):
    atomic_json(job / 'continuation/control.json', {'enabled': True, 'cache_only': True})
    vision = attach_replies(Vision(), job, 'deepseek_plan', lambda: False)
    with pytest.raises(ContinuationMiss):
        vision.query('not accepted', schema=SCHEMA)
    with pytest.raises(ContinuationMiss):
        vision.query_many([{'prompt': 'not accepted', 'schema': SCHEMA}])
    assert not vision.calls


def test_changed_schema_source_or_image_and_corrupt_reply_are_not_transferred(job):
    image = job / 'frame.jpg'; image.write_bytes(b'original pixels')
    directory = legacy_reply(job, image=image)
    enable_continuation(job, 'antigravity_manual', 'deepseek_plan')
    vision = attach_replies(Vision(), job, 'deepseek_plan', lambda: False)
    schema = {**SCHEMA, 'properties': {'value': {'type': 'integer', 'enum': [2]}}}
    assert vision.query('accepted', image, schema=schema) == {'value': 2}
    image.write_bytes(b'changed pixels')
    assert vision.query('accepted', image, schema=SCHEMA) == {'value': 2}
    assert len(vision.calls) == 2
    image.write_bytes(b'original pixels')
    result = read_json(directory / 'result.json'); result['answer'] = {'value': 2}; atomic_json(directory / 'result.json', result)
    assert vision.query('accepted', image, schema=SCHEMA) == {'value': 2}
    assert len(vision.calls) == 3
    atomic_json(job / 'analysis.meta.json', {'source': '1'*64, 'version': 16})
    changed = attach_replies(Vision(), job, 'deepseek_plan', lambda: False)
    assert changed.query('accepted', image, schema=SCHEMA) == {'value': 2} and changed.calls


def test_cancelled_reply_reuse_still_raises(job):
    vision = attach_replies(Vision(), job, 'deepseek_plan', lambda: True)
    with pytest.raises(InterruptedError):
        vision.query('any', schema=SCHEMA)


def test_legacy_perception_requires_verified_current_images_and_asr_and_adopts_once(job):
    from app.scene_detection import SCENE_DETECTOR_VERSION, SCENE_GROUPING_VERSION
    visual = job / 'visual'; visual.mkdir()
    image = visual / 'event_0000.jpg'; image.write_bytes(b'current evidence')
    sha = read_json(job / 'analysis.meta.json')['source']
    event = {'id': 'event_0000', 'scene_id': 'scene_0000', 'start': 0, 'end': 10,
             'units': [{'id': 'u0', 'start': 0, 'end': 10, 'text': ''}],
             'scene_evidence': {'detector_version': SCENE_DETECTOR_VERSION,
                                'grouping_version': SCENE_GROUPING_VERSION}}
    boards = [{'image': str(image), 'role': 'current', 'source': {'sha256': sha}},
              {'image': str(image), 'role': 'legacy_overview'}]
    atomic_json(visual / 'event_0000.json', {'event': event, 'storyboards': boards,
                'image_hashes': {'event_0000.jpg': hashlib.sha256(image.read_bytes()).hexdigest()}})
    enable_continuation(job, 'antigravity_manual', 'deepseek_plan')
    stage = journal(job)
    imported = stage.perception({}, allow_legacy=True)
    assert imported['events'] == [event]
    assert read_json(job / 'continuation/control.json')['legacy_visual_events'] == 1
    stage.context['perception_code'] = 'changed-code'
    assert stage.perception({}, allow_legacy=True) is None, 'A code change cannot silently readopt old records'


def test_stage_hashing_large_records_does_not_resolve_paths_for_every_string(job, monkeypatch):
    from pathlib import Path
    stage = journal(job)
    original = Path.resolve
    calls = []
    def resolve(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    records = [{'id': str(n), 'summary': 'source dialogue', 'path': str(job / 'frame.jpg')} for n in range(2000)]
    stage.save('titles', records, records, 'antigravity_manual')
    assert stage.load('titles', records) == records
    assert len(calls) < 10
