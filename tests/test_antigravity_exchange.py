"""Manual transport boundaries: no cloud calls, preserved inputs, strict imports."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.antigravity_exchange import (AnalysisPending, ManualVision, PROVIDER,
    import_result, packet_dir, preserve_provider_checkpoints, snapshot)
from app.config import STORY_MODEL
from app.jobs import JobManager, atomic_json, read_json
from app.server import create_app
from tests.test_jobs import FakeWorker


SCHEMA = {'type': 'object', 'properties': {'keep_units': {
    'type': 'array', 'items': {'type': 'string', 'enum': ['u1', 'u2']}, 'uniqueItems': True}},
    'required': ['keep_units'], 'additionalProperties': False}


def session(directory, **options):
    directory.mkdir(exist_ok=True)
    atomic_json(directory / 'analysis.meta.json', {'source': 'source-sha', 'version': 16})
    atomic_json(directory / 'probe.json', {'duration': 120})
    (directory / 'evidence.jpg').write_bytes(b'original-page')
    return ManualVision(directory, lambda: False, **options)


def prepare(vision, prompt='CURRENT u1 u2; PREVIOUS and NEXT are context only'):
    with pytest.raises(AnalysisPending):
        vision.query(prompt, vision.job_dir / 'evidence.jpg', schema=SCHEMA)
    return snapshot(vision.job_dir)['packets'][-1]['id']


def envelope(answer):
    return json.dumps({'status': 'SUCCESS', 'structured_output': answer,
        'duration_seconds': 2.5, 'usage': {'input_tokens': 12, 'output_tokens': 4, 'total_tokens': 16}}).encode()


def test_official_stream_final_import_preserves_strict_json_and_usage(tmp_path):
    vision = session(tmp_path)
    identifier = prepare(vision)
    wrapped = b'{"event":"result","result":' + envelope({'keep_units':['u1']}) + b'}'
    accepted = import_result(tmp_path, identifier, wrapped)
    assert accepted['usage']['total_tokens'] == 16
    original = (packet_dir(tmp_path, identifier)/'result.json').read_bytes()
    for invalid in (
        b'{"event":"result","result":{"status":"SUCCESS","structured_output":{"keep_units":["u1"],"keep_units":["u2"]}}}',
        b'{"event":"result","result":{"status":"SUCCESS","structured_output":{"keep_units":["u1"]},"usage":{"total_tokens":NaN}}}',
        b'{"event":"result","result":null}',
        b'{"event":"result","result":{"status":"ERROR"}}',
    ):
        with pytest.raises(ValueError):
            import_result(tmp_path, identifier, invalid)
        assert (packet_dir(tmp_path, identifier)/'result.json').read_bytes()==original


def batch_receiver(vision, calls, answer=None):
    def receive(directory, identifier, **unused):
        request = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
        members = json.loads((directory / 'batch.json').read_text(encoding='utf-8'))['members'] if (directory / 'batch.json').exists() else []
        calls.append((request, members))
        result = {('q_' + member): {'request_id': member, 'answer': answer(member) if answer else {'keep_units': ['u1']}}
                  for member in members} if members else {'keep_units': ['u1']}
        try:
            import_result(vision.job_dir, identifier, envelope(result))
        except ValueError as error:
            raise AnalysisPending('успешные ответы сохранены') from error
    return receive


def test_batch_preserves_individual_identities_ownership_and_warm_cache(tmp_path):
    vision = session(tmp_path)
    tasks = [{'prompt': f'Independent scene {i}', 'image': tmp_path / 'evidence.jpg', 'schema': SCHEMA} for i in range(4)]
    originals = [vision._prepare_request(**task)[1] for task in tasks]
    calls = []
    with patch.object(vision, '_receive', side_effect=batch_receiver(vision, calls)):
        assert vision.query_many(tasks) == [{'keep_units': ['u1']}] * 4
        assert vision.query_many(tasks) == [{'keep_units': ['u1']}] * 4
        assert vision.query(**tasks[0]) == {'keep_units': ['u1']}
    assert len(calls) == 1 and set(calls[0][1]) == set(originals)
    contracts = json.loads(calls[0][0]['prompt'].split('\n', 1)[1])
    assert [item['image_pages'] for item in contracts] == [[f'page_{i:03}.jpg'] for i in range(4)]
    for identifier in originals:
        assert json.loads((packet_dir(tmp_path, identifier) / 'result.json').read_text())['usage'] == {}


def test_batch_reuses_cached_child_and_splits_large_contracts(tmp_path):
    vision = session(tmp_path)
    tasks = [{'prompt': f'{i}' + 'x' * 17000, 'schema': SCHEMA} for i in range(4)]
    item = vision._prepare_request(**tasks[0])
    import_result(tmp_path, item[1], envelope({'keep_units': ['u2']}))
    calls = []
    with patch.object(vision, '_receive', side_effect=batch_receiver(vision, calls)):
        assert vision.query_many(tasks)[0] == {'keep_units': ['u2']}
    assert len(calls) == 3 and all(not members for _, members in calls)


def test_independent_queue_exports_all_groups_and_restores_result_order(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    tasks = [{'prompt': str(i) + 'x' * 17000, 'schema': SCHEMA} for i in range(4)]
    ids = [vision._prepare_request(**task)[1] for task in tasks]
    queues = []
    def publish(_):
        exchange = read_json(tmp_path / 'antigravity/exchange.json')
        queues.append(exchange['packets'])
        assert exchange['packet'] == exchange['packets'][0]
        # Simulate out-of-order external completions. KADR starts no processes.
        for key in reversed(exchange['packets']):
            packet_dir(tmp_path, key).joinpath('agy-result.json').write_bytes(
                envelope({'keep_units': ['u1'] if key == ids[0] else ['u2']}))
    with patch('app.antigravity_exchange.time.sleep', side_effect=publish), \
            patch('subprocess.Popen', side_effect=AssertionError('no embedded CLI')):
        assert vision.query_many(tasks) == [{'keep_units': ['u1']}] + [{'keep_units': ['u2']}] * 3
    assert len(queues) == 1 and set(queues[0]) == set(ids)
    assert read_json(tmp_path / 'antigravity/exchange.json')['packets'] == []
    with patch.object(vision, '_receive', side_effect=AssertionError('warm cache')):
        assert len(vision.query_many(tasks)) == 4


def test_non_head_queue_failure_preserves_published_sibling(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    tasks = [{'prompt': str(i) + 'x' * 17000, 'schema': SCHEMA} for i in range(3)]
    ids = sorted(vision._prepare_request(**task)[1] for task in tasks)
    def failure(_):
        exchange = read_json(tmp_path / 'antigravity/exchange.json')
        assert exchange['packet'] == ids[0]
        packet_dir(tmp_path, ids[-1]).joinpath('agy-result.json').write_bytes(envelope({'keep_units': ['u2']}))
        atomic_json(tmp_path / 'antigravity/runner.json', {'status': 'error', 'packet': ids[1]})
    with patch('app.antigravity_exchange.time.sleep', side_effect=failure):
        with pytest.raises(AnalysisPending, match='успешные ответы сохранены'):
            vision.query_many(tasks)
    assert (packet_dir(tmp_path, ids[-1]) / 'result.json').exists()
    assert not (packet_dir(tmp_path, ids[0]) / 'result.json').exists()
    assert read_json(tmp_path / 'antigravity/exchange.json')['status'] == 'error'


def test_cloud_global_review_keeps_every_complete_middle_fact_and_native_schema(tmp_path):
    vision = session(tmp_path)
    events = [{'id': f'event_{i:04d}', 'summary': ('Начало. ' * 45 + f'UNIQUE_MIDDLE_{i} ' + 'Конец. ' * 45),
        'kind': 'story', 'importance': 4} for i in range(129)]
    expected = {'keep':[e['id'] for e in events], 'omit':[], 'dependencies':[], 'summary':'История'}
    with patch.object(vision, 'query', return_value=expected) as query, \
            patch('subprocess.Popen', side_effect=AssertionError('no embedded CLI')):
        result = vision.review_global_story(events)
    assert result['incomplete_event_ids'] == []
    prompt = query.call_args.args[0]
    assert len(prompt.encode('utf-8')) > 5300 and len(prompt) > 32767
    assert all(e['summary'] in prompt for e in events)
    assert '[middle omitted]' not in prompt
    assert query.call_args.kwargs['schema']['properties']['keep']['items']['enum'] == sorted(expected['keep'])
    assert query.call_args.kwargs['max_tokens'] == 2200


def test_cloud_global_review_oversize_and_cancel_never_trim_or_call(tmp_path):
    vision = session(tmp_path)
    events = [{'id':'event_0000','summary':'x' * 240001,'kind':'story','importance':4}]
    with patch.object(vision, 'query', side_effect=AssertionError('must not launch')):
        with pytest.raises(AnalysisPending, match='без потери контекста'):
            vision.review_global_story(events)
        vision.cancelled = lambda: True
        with pytest.raises(InterruptedError):
            vision.review_global_story(events)


@pytest.mark.parametrize('mode', ['success', 'malformed', 'cancel'])
def test_packet_stream_stdin_unicode_final_envelope_and_native_cancel(tmp_path, mode):
    import os
    import subprocess
    import time
    if os.name != 'nt':
        pytest.skip('executes Windows PowerShell packet wrapper')
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    packet = tmp_path / 'packet'
    packet.mkdir()
    marker = 'Проверка полного русского контекста'
    prompt = marker + ' контекст ' * 5000
    atomic_json(packet / 'request.json', {'images':[], 'schema':{'type':'object'}})
    atomic_json(packet / 'schema.json', {'type':'object'})
    (packet / 'prompt.txt').write_text(prompt, encoding='utf-8')
    fake_cli = tmp_path / 'fake-cli.py'
    fake_cli.write_text('''import json,sys,time,os
from pathlib import Path
payload=json.loads(sys.stdin.buffer.readline().decode('utf-8'))
assert payload['event']=='user' and payload['message']['role']=='user'
text=payload['message']['content'][0]['text']
assert text.startswith('Проверка полного русского контекста') and text.count('контекст')>=5000
Path('child-started').write_text(str(os.getpid()))
mode=''' + repr(mode) + '''
if mode=='cancel':
    time.sleep(60)
elif mode=='malformed':
    print('not JSON',flush=True)
else:
    print(json.dumps({'event':'init'}))
    print(json.dumps({'event':'result','result':{'status':'SUCCESS','structured_output':{'ok':True},'usage':{'input_tokens':7,'output_tokens':2,'total_tokens':9}}}),flush=True)
''', encoding='utf-8')
    wrapper = (root / 'scripts/run_antigravity_packet.ps1').read_text('utf-8')
    # Substitute only the native paid executable's arguments AFTER the real
    # Windows-limit/stream branches; exercise actual stdin, parsing and kill.
    wrapper = wrapper.replace('$startInfo.WorkingDirectory = $packet',
        "$startInfo.Arguments = '" + str(fake_cli) + "'\n$startInfo.WorkingDirectory = $packet")
    script = scripts / 'run_antigravity_packet.ps1'
    script.write_text(wrapper, encoding='utf-8-sig')
    stop = tmp_path / '.cancel'
    command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
        '-PacketDirectory',str(packet),'-AgyExe',str(root/'tools/python/python.exe'),
        '-DefaultAgent','-StopFile',str(stop),'-TimeLimitSeconds','15']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if mode == 'cancel':
            deadline = time.monotonic() + 10
            while not (packet/'child-started').exists() and process.poll() is None and time.monotonic()<deadline:
                time.sleep(.05)
            assert (packet/'child-started').exists()
            stop.touch()
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == (0 if mode=='success' else 1), stderr.decode(errors='replace')
        records = list((packet/'cli-attempts').glob('*/cli-run.json'))
        assert len(records)==1
        telemetry=json.loads(records[0].read_text(encoding='utf-8-sig'))
        assert telemetry['input_format']=='stream-json' and telemetry['command_line_chars']<32767
        assert (packet/'agy-result.json').exists() == (mode=='success')
        assert (records[0].parent/'agy.stream.jsonl').exists()
        if mode=='success':
            assert json.loads((packet/'agy-result.json').read_text(encoding='utf-8-sig'))['result']['structured_output']=={'ok':True}
            assert telemetry['usage']['total_tokens']==9
        elif mode=='malformed':
            assert telemetry['stream_error'] and not telemetry['usage_reported']
        else:
            assert telemetry['abort_reason']
            child_id=int((packet/'child-started').read_text())
            import ctypes
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x1000,False,child_id)
            if handle:
                exit_code=ctypes.c_ulong()
                assert kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(exit_code))
                kernel.CloseHandle(ctypes.c_void_p(handle))
                assert exit_code.value != 259, 'owned native child must exit'
    finally:
        if process.poll() is None:
            stop.touch()
            process.communicate(timeout=10)


def test_batch_keeps_valid_children_when_native_coverage_fails(tmp_path):
    vision = session(tmp_path)
    units = {'type': 'array', 'items': {'type': 'string', 'enum': ['u1', 'u2']}}
    schema = {'type': 'object', 'properties': {'keep_units': units, 'preserve_silent_units': units,
              'omit_units': {'type': 'array', 'items': {'type': 'object'}}}}
    tasks = [{'prompt': str(i), 'schema': schema} for i in range(3)]
    identifiers = [vision._prepare_request(**task)[1] for task in tasks]
    bad = identifiers[1]
    def answer(identifier):
        return {'keep_units': ['u1'] if identifier == bad else ['u1', 'u2'],
                'preserve_silent_units': [], 'omit_units': []}
    with patch.object(vision, '_receive', side_effect=batch_receiver(vision, [], answer)):
        with pytest.raises(AnalysisPending, match='успешные'):
            vision.query_many(tasks)
    assert not (packet_dir(tmp_path, bad) / 'result.json').exists()
    assert all((packet_dir(tmp_path, identifier) / 'result.json').exists() for identifier in identifiers if identifier != bad)


def test_batch_cancellation_exports_nothing(tmp_path):
    vision = session(tmp_path)
    vision.cancelled = lambda: True
    with pytest.raises(InterruptedError):
        vision.query_many([{'prompt': 'one', 'schema': SCHEMA}])
    assert snapshot(tmp_path)['packets'] == []


def test_batch_strict_numeric_enum_failure_still_saves_valid_siblings(tmp_path):
    vision = session(tmp_path)
    schema = {'type': 'object', 'properties': {'confidence': {'type': 'number', 'enum': [.95, 1.0]}},
              'required': ['confidence'], 'additionalProperties': False}
    tasks = [{'prompt': str(i), 'schema': schema} for i in range(4)]
    ids = [vision._prepare_request(**task)[1] for task in tasks]
    calls = []
    with patch.object(vision, '_receive', side_effect=batch_receiver(vision, calls,
            lambda identifier: {'confidence': .98 if identifier == ids[1] else .95})):
        with pytest.raises(AnalysisPending):
            vision.query_many(tasks)
    assert not (packet_dir(tmp_path, ids[1]) / 'result.json').exists()
    assert all((packet_dir(tmp_path, identifier) / 'result.json').exists() for identifier in ids if identifier != ids[1])
    contracts = json.loads(calls[0][0]['prompt'].split('\n', 1)[1])
    assert all(item['schema'] == schema for item in contracts)


def test_batch_bounds_windows_quoting_without_truncating_child_prompt(tmp_path):
    import subprocess
    vision = session(tmp_path)
    tasks = [{'prompt': str(i) + ('quote " and slash \\ ' * 400), 'schema': SCHEMA} for i in range(4)]
    calls = []
    with patch.object(vision, '_receive', side_effect=batch_receiver(vision, calls)):
        assert len(vision.query_many(tasks)) == 4
    assert len(calls) > 1
    observed = []
    for request, members in calls:
        if members:
            assert len(subprocess.list2cmdline([request['prompt']])) < 28000
            observed.extend(item['prompt'] for item in json.loads(request['prompt'].split('\n', 1)[1]))
        else:
            observed.append(request['prompt'])
    assert sorted(observed) == sorted(task['prompt'] for task in tasks)


def test_batch_factors_identical_instruction_lines_to_fit_large_requests(tmp_path):
    import subprocess
    vision=session(tmp_path)
    shared='Original independent CURRENT instructions. '*75+'\n'
    tasks=[{'prompt':shared+str(i)+'x'*10000,'schema':SCHEMA} for i in range(4)]
    originals=[vision._prepare_request(**task)[1] for task in tasks]
    calls=[]
    with patch.object(vision,'_receive',side_effect=batch_receiver(vision,calls)):
        vision.query_many(tasks)
    assert len(calls)==2 and all(len(members)==2 for _,members in calls)
    restored={}
    for request,members in calls:
        assert len(subprocess.list2cmdline([request['prompt']]))<28000
        payload=json.loads(request['prompt'].split('\n',1)[1])
        for contract in payload['tasks']:
            restored[contract['request_id']]=payload['shared_instructions']+contract['prompt']
            assert contract['schema']==SCHEMA
    assert restored==dict(zip(originals,[task['prompt'] for task in tasks],strict=True))


def test_batch_windows_bound_counts_utf16_units(tmp_path):
    vision=session(tmp_path)
    tasks=[{'prompt':str(i)+'\U0001f600'*7500,'schema':SCHEMA} for i in range(2)]
    calls=[]
    with patch.object(vision,'_receive',side_effect=batch_receiver(vision,calls)):
        vision.query_many(tasks)
    assert len(calls)==2 and all(not members for _,members in calls)
    assert sorted(request['prompt'] for request,_ in calls)==sorted(task['prompt'] for task in tasks)


def test_export_import_resume_uses_same_packet_and_native_contract(tmp_path):
    vision = session(tmp_path)
    identifier = prepare(vision)
    request = json.loads((packet_dir(tmp_path, identifier) / 'request.json').read_text())
    assert request['prompt'].startswith('CURRENT')
    assert request['schema'] == SCHEMA
    assert request['source']['source'] == 'source-sha'
    assert request['source_duration'] == 120
    assert (packet_dir(tmp_path, identifier) / request['images'][0]).read_bytes() == b'original-page'
    result = import_result(tmp_path, identifier, envelope({'keep_units': ['u1']}))
    assert result['usage']['total_tokens'] == 16
    with patch('subprocess.Popen', side_effect=AssertionError('must never start CLI/model')):
        for _ in range(2):
            assert vision.query(request['prompt'], tmp_path / 'evidence.jpg', schema=SCHEMA) == {'keep_units': ['u1']}
    assert len(snapshot(tmp_path)['packets']) == 1


@pytest.mark.parametrize('answer', [{'keep_units': ['invented']}, {'keep_units': ['u1', 'u1']},
    {'keep_units': 'u1'}, {'keep_units': ['u1'], 'unexpected': True}])
def test_schema_rejects_unknown_ids_duplicates_types_and_extras(tmp_path, answer):
    identifier = prepare(session(tmp_path))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, envelope(answer))
    assert snapshot(tmp_path)['packets'][0]['status'] == 'error'


@pytest.mark.parametrize('raw', [b'{broken', b'{"status":"ERROR"}',
    b'{"status":"SUCCESS","structured_output":{"keep_units":[],"keep_units":[]}}',
    b'{"status":"SUCCESS","structured_output":{"keep_units":[]},"duration_seconds":NaN}'])
def test_strict_json_and_failed_envelopes_are_never_answers(tmp_path, raw):
    identifier = prepare(session(tmp_path))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, raw)


def test_bad_replacement_keeps_accepted_cache(tmp_path):
    identifier = prepare(session(tmp_path))
    import_result(tmp_path, identifier, envelope({'keep_units': ['u1']}))
    with pytest.raises(ValueError):
        import_result(tmp_path, identifier, b'{}')
    assert snapshot(tmp_path)['packets'][0]['status'] == 'ready'


def test_request_identity_changes_with_context_and_images(tmp_path):
    vision = session(tmp_path)
    first = prepare(vision)
    prepare(vision, 'Different neighboring context')
    (tmp_path / 'evidence.jpg').write_bytes(b'changed-page')
    prepare(vision)
    assert len(snapshot(tmp_path)['packets']) == 3
    (packet_dir(tmp_path, first) / 'page_000.jpg').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Изображения'):
        import_result(tmp_path, first, envelope({'keep_units': ['u1']}))


def test_rejects_outside_images_and_packet_paths(tmp_path):
    vision = session(tmp_path / 'job')
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(b'outside')
    with pytest.raises(ValueError):
        vision.query('prompt', outside, schema=SCHEMA)
    with pytest.raises(ValueError):
        packet_dir(vision.job_dir, '../../outside')


def test_import_rejects_stale_source_and_out_of_bounds_times(tmp_path):
    vision = session(tmp_path)
    schema = {'type': 'object', 'properties': {'start': {'type': 'number'},
              'end': {'type': 'number'}}, 'required': ['start', 'end'], 'additionalProperties': False}
    with pytest.raises(AnalysisPending):
        vision.query('Existing ranges only', schema=schema)
    identifier = snapshot(tmp_path)['packets'][0]['id']
    for answer in ({'start': -1, 'end': 1}, {'start': 2, 'end': 1}, {'start': 1, 'end': 121}):
        with pytest.raises(ValueError):
            import_result(tmp_path, identifier, envelope(answer))
    atomic_json(tmp_path / 'analysis.meta.json', {'source': 'another-source'})
    with pytest.raises(ValueError, match='Исходник'):
        import_result(tmp_path, identifier, envelope({'start': 0, 'end': 1}))


def test_cli_generation_schema_preserves_strict_backend_contract():
    from app.antigravity_exchange import cli_schema
    schema = {'type': 'object', 'properties': {'number': {'type': 'number', 'enum': [0, .5, 1]},
        'flag': {'type': 'boolean', 'enum': [True]}, 'id': {'type': 'string', 'enum': ['u1']}}}
    converted = cli_schema(schema)
    assert 'enum' not in converted['properties']['number']
    assert 'enum' not in converted['properties']['flag']
    assert converted['properties']['id']['enum'] == ['u1']
    assert schema['properties']['flag']['enum'] == [True]


def test_cancel_does_not_export_packet(tmp_path):
    vision = session(tmp_path)
    vision.cancelled = lambda: True
    with pytest.raises(InterruptedError) as caught:
        vision.query('prompt')
    assert not isinstance(caught.value, AnalysisPending)
    assert not snapshot(tmp_path)['packets']


def test_import_rejects_contradictory_and_incomplete_native_story_selection(tmp_path):
    vision = session(tmp_path)
    units = {'type': 'array', 'items': {'type': 'string', 'enum': ['u1', 'u2']}}
    schema = {'type': 'object', 'properties': {'keep_units': units, 'preserve_silent_units': units,
        'omit_units': {'type': 'array', 'items': {'type': 'object'}}}}
    with pytest.raises(AnalysisPending):
        vision.query('native selection', schema=schema)
    identifier = snapshot(tmp_path)['packets'][0]['id']
    omission = {'unit': 'u1', 'reason': 'waiting', 'reaction_or_humor': False}
    for answer in ({'keep_units': ['u1'], 'preserve_silent_units': [], 'omit_units': [omission]},
                   {'keep_units': ['u1'], 'preserve_silent_units': [], 'omit_units': []}):
        with pytest.raises(ValueError):
            import_result(tmp_path, identifier, envelope(answer))
    answer = {'keep_units': ['u2'], 'preserve_silent_units': [], 'omit_units': [omission]}
    assert import_result(tmp_path, identifier, envelope(answer))['status'] == 'ready'


def test_switch_restores_qwen_checkpoints_and_keeps_factual_data(tmp_path):
    for name in ('transcript.json', 'scenes.json', 'story-events.json'):
        atomic_json(tmp_path / name, {'original': name})
    (tmp_path / 'visual').mkdir()
    (tmp_path / 'visual/evidence.jpg').write_bytes(b'perception')
    preserve_provider_checkpoints(tmp_path, 'local', PROVIDER)
    atomic_json(tmp_path / 'story-events.json', {'manual': True})
    preserve_provider_checkpoints(tmp_path, PROVIDER, 'local')
    assert json.loads((tmp_path / 'story-events.json').read_text()) == {'original': 'story-events.json'}
    assert json.loads((tmp_path / 'transcript.json').read_text()) == {'original': 'transcript.json'}
    assert (tmp_path / 'visual/evidence.jpg').read_bytes() == b'perception'


def test_only_manual_9b_routed_and_other_providers_unchanged(tmp_path):
    from app.analysis import vision_session, provider_identity
    with patch('app.analysis._native_vision_session', return_value='native') as native:
        assert vision_session(tmp_path, lambda: False, PROVIDER) == 'native'
        assert native.call_args.args[2] == 'local'
        assert isinstance(vision_session(tmp_path, lambda: False, PROVIDER, model=STORY_MODEL), ManualVision)
        for provider in ('local', 'deepseek', 'deepseek_plan', 'hybrid'):
            assert vision_session(tmp_path, lambda: False, provider) == 'native'
            assert native.call_args.args[2] == provider
    assert provider_identity('local') == {'provider': 'local'}


def test_existing_control_failure_recognizes_pending_without_degrading():
    from app.scene_understanding import _control_failure
    assert _control_failure(AnalysisPending('waiting'))


def test_worker_persists_waiting_state_without_marking_cancelled(tmp_path):
    from app import config
    from app.worker import main
    import uuid
    identifier = str(uuid.uuid4())
    directory = tmp_path / identifier
    directory.mkdir()
    (directory / '.start').touch()
    atomic_json(directory / 'job.json', {'id': identifier, 'status': 'running', 'outputs': []})
    with patch.object(config, 'JOBS', tmp_path), patch('sys.argv', ['worker', '--job', identifier]), \
            patch('app.pipeline.run_job', side_effect=AnalysisPending('waiting for packet')):
        assert main() == 0
    job = json.loads((directory / 'job.json').read_text())
    assert job['status'] == job['stage'] == 'waiting_analysis'
    assert job['cancel_requested'] is False
    assert job['error'] is None


def test_automatic_pause_keeps_current_stage_for_checkmarks(tmp_path):
    from app import config
    from app.worker import main
    import uuid
    identifier = str(uuid.uuid4())
    directory = tmp_path / identifier
    directory.mkdir()
    (directory / '.start').touch()
    atomic_json(directory / 'job.json', {'id': identifier, 'status': 'running', 'stage':'condense', 'outputs': []})
    atomic_json(directory / 'antigravity/automation.json', {'enabled':True})
    with patch.object(config, 'JOBS', tmp_path), patch('sys.argv', ['worker', '--job', identifier]), \
            patch('app.pipeline.run_job', side_effect=AnalysisPending('waiting for packet')):
        assert main() == 0
    job = json.loads((directory / 'job.json').read_text())
    assert job['status'] == 'waiting_analysis'
    assert job['stage'] == 'condense'


def test_api_manual_import_mode_retry_and_busy_guards(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'media')
    manager = JobManager(tmp_path, worker_factory=FakeWorker)
    with TestClient(create_app(manager), base_url='http://127.0.0.1:8765') as client:
        imported = manager.list_sources()[0]
        job = manager.create(imported['id'])
        identifier = job['id']
        prefix = '/api/jobs/' + identifier
        assert client.post(prefix + '/analysis-provider', json={'provider': PROVIDER}).status_code == 409
        manager.cancel(identifier)
        assert client.post(prefix + '/analysis-provider', json={'provider': PROVIDER}).status_code == 200
        assert client.post(prefix + '/antigravity/automation?enabled=true').json()['automation']['enabled']
        assert not client.post(prefix + '/antigravity/automation?enabled=false').json()['automation']['enabled']
        directory = manager.job_dir(identifier)
        packet = prepare(session(directory))
        accepted = client.post(prefix + '/antigravity/' + packet + '/import',
            content=envelope({'keep_units': ['u2']}), headers={'content-type': 'application/json'})
        assert accepted.status_code == 200, accepted.text
        assert client.get(prefix + '/antigravity').json()['packets'][0]['status'] == 'ready'
        assert client.post(prefix + '/antigravity/prepare').status_code == 200
        assert client.post(prefix + '/antigravity/automation?enabled=false').status_code == 409
        assert client.post(prefix + '/antigravity/' + packet + '/import', content=b'{}').status_code == 409
        manager.cancel(identifier)
        assert client.post(prefix + '/analysis-provider', json={'provider': 'local'}).status_code == 200
        assert manager.get(identifier)['analysis_provider'] == 'local'


def test_automatic_file_exchange_multiple_queries_no_process_and_cache(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    def publish(_):
        exchange = json.loads((tmp_path / 'antigravity/exchange.json').read_text())
        packet_dir(tmp_path, exchange['packet']).joinpath('agy-result.json').write_bytes(envelope({'keep_units': ['u2']}))
    with patch('app.antigravity_exchange.time.sleep', side_effect=publish), \
            patch('subprocess.Popen', side_effect=AssertionError('KADR must never start CLI')):
        for prompt in ('first scene', 'second scene'):
            assert vision.query(prompt, tmp_path / 'evidence.jpg', schema=SCHEMA) == {'keep_units': ['u2']}
    with patch('app.antigravity_exchange.time.sleep', side_effect=AssertionError('cached answer must not wait')):
        assert vision.query('first scene', tmp_path / 'evidence.jpg', schema=SCHEMA) == {'keep_units': ['u2']}
    assert [packet['status'] for packet in snapshot(tmp_path)['packets']] == ['ready', 'ready']


def test_automatic_cancel_and_timeout_never_degrade(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    with patch('app.antigravity_exchange.time.sleep', side_effect=lambda _: setattr(vision, 'cancelled', lambda: True)):
        with pytest.raises(InterruptedError) as caught:
            vision.query('cancelled query', schema=SCHEMA)
        assert not isinstance(caught.value, AnalysisPending)
    vision.cancelled = lambda: False
    with patch('app.antigravity_exchange.time.monotonic', side_effect=[0, 601]):
        with pytest.raises(AnalysisPending, match='10 минут'):
            vision.query('timed out query', schema=SCHEMA)
    assert len(snapshot(tmp_path)['packets']) == 2


def test_automatic_invalid_file_pauses_and_preserves_request(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    def invalid(_):
        exchange = json.loads((tmp_path / 'antigravity/exchange.json').read_text())
        packet_dir(tmp_path, exchange['packet']).joinpath('agy-result.json').write_bytes(envelope({'keep_units': ['invented']}))
    with patch('app.antigravity_exchange.time.sleep', side_effect=invalid):
        with pytest.raises(AnalysisPending, match='отклонён'):
            vision.query('invalid query', schema=SCHEMA)
    assert snapshot(tmp_path)['exchange']['status'] == 'error'
    assert snapshot(tmp_path)['packets'][0]['status'] == 'error'


def test_external_runner_failure_pauses_same_packet(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    def failure(_):
        exchange = json.loads((tmp_path / 'antigravity/exchange.json').read_text())
        atomic_json(tmp_path / 'antigravity/runner.json', {'status': 'error', 'packet': exchange['packet']})
    with patch('app.antigravity_exchange.time.sleep', side_effect=failure):
        with pytest.raises(AnalysisPending, match='с ошибкой'):
            vision.query('failed CLI query', schema=SCHEMA)


def test_external_runner_budget_pause_retains_packet_and_cached_results(tmp_path):
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    def publish(_):
        exchange = read_json(tmp_path / 'antigravity/exchange.json')
        packet_dir(tmp_path, exchange['packet']).joinpath('agy-result.json').write_bytes(envelope({'keep_units': ['u2']}))
    with patch('app.antigravity_exchange.time.sleep', side_effect=publish):
        assert vision.query('accepted before budget', schema=SCHEMA) == {'keep_units': ['u2']}
    def stop(_):
        # May expire while waiting for a different packet; the whole runner stopped.
        atomic_json(tmp_path / 'antigravity/runner.json', {'status': 'budget_exhausted', 'packet': 'previous'})
    with patch('app.antigravity_exchange.time.sleep', side_effect=stop):
        with pytest.raises(AnalysisPending, match='Лимит времени'):
            vision.query('pending after budget', schema=SCHEMA)
    with patch('app.antigravity_exchange.time.sleep', side_effect=AssertionError('must reuse accepted cache')):
        assert vision.query('accepted before budget', schema=SCHEMA) == {'keep_units': ['u2']}
    assert read_json(tmp_path / 'antigravity/exchange.json')['status'] == 'waiting'
    assert sorted(item['status'] for item in snapshot(tmp_path)['packets']) == ['ready', 'waiting']


@pytest.mark.parametrize('limited', [False, True])
def test_standalone_production_unlimited_and_test_budget_pause(tmp_path, limited):
    import os
    import subprocess
    if os.name != 'nt':
        pytest.skip('executes the actual Windows PowerShell runner')
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    runner = (root / 'scripts/run_antigravity_job.ps1').read_text('utf-8')
    # Freeze only elapsed time, leaving the actual launch and budget branches intact.
    seconds = 59 if limited else 999999
    runner = runner.replace('$timer = [Diagnostics.Stopwatch]::StartNew()',
        '$timer = [PSCustomObject]@{Elapsed=[TimeSpan]::FromSeconds(' + str(seconds) + ')}')
    (scripts / 'run_antigravity_job.ps1').write_text(runner, encoding='utf-8-sig')
    (scripts / 'run_antigravity_packet.ps1').write_text("throw 'must not launch CLI'", encoding='utf-8')
    job = tmp_path / 'job'
    job.mkdir()
    atomic_json(job / 'job.json', {'analysis_provider': PROVIDER, 'status': 'running' if limited else 'completed'})
    exchange = job / 'antigravity'
    exchange.mkdir()
    atomic_json(exchange / 'automation.json', {'enabled': True})
    atomic_json(exchange / 'exchange.json', {'status': 'waiting', 'packet': 'a' * 64})
    (exchange / 'packets' / ('a' * 64)).mkdir(parents=True)
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        str(scripts / 'run_antigravity_job.ps1'), '-JobDirectory', str(job)]
    if limited:
        command += ['-MaxMinutes', '1']
    result = subprocess.run(command, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert read_json(exchange / 'runner.json')['status'] == ('budget_exhausted' if limited else 'completed')


@pytest.mark.parametrize('mode', ['parallel', 'serial', 'cancel', 'failure', 'invalid'])
def test_actual_standalone_workers_overlap_stop_and_do_not_retry(tmp_path, mode):
    import os
    import shutil
    import subprocess
    import time
    if os.name != 'nt':
        pytest.skip('executes the actual Windows PowerShell coordinator')
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(root / 'scripts/run_antigravity_job.ps1', scripts / 'run_antigravity_job.ps1')
    # Replace only the external paid-call boundary, leaving native queue,
    # Start-Job, completion, locking, cancellation and error handling intact.
    stub = r'''param($PacketDirectory, $AgyExe, $Model, [switch]$DefaultAgent, $StopFile, $RunnerStopFile, $TimeLimitSeconds)
    $ErrorActionPreference='Stop'
    $stamp=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    [IO.File]::WriteAllText((Join-Path $PacketDirectory 'started.json'), "$stamp")
    try {
        for($i=0;$i -lt 35;$i++) {
            if ((Test-Path -LiteralPath $StopFile) -or (Test-Path -LiteralPath $RunnerStopFile)) {
                [IO.File]::WriteAllText((Join-Path $PacketDirectory 'observed-stop'), 'yes')
                throw 'cancelled owned worker'
            }
            if ((Test-Path -LiteralPath (Join-Path $PacketDirectory 'fail')) -and $i -eq 10) { throw 'simulated CLI failure' }
            Start-Sleep -Milliseconds 100
        }
        [IO.File]::WriteAllText((Join-Path $PacketDirectory 'agy-result.json'), '{}')
    } finally {
        [IO.File]::WriteAllText((Join-Path $PacketDirectory 'ended.json'), "$( [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() )")
    }
    '''
    (scripts / 'run_antigravity_packet.ps1').write_text(stub, encoding='utf-8-sig')
    job = tmp_path / 'job'
    job.mkdir()
    atomic_json(job / 'job.json', {'analysis_provider': PROVIDER, 'status': 'running'})
    exchange = job / 'antigravity'
    exchange.mkdir()
    atomic_json(exchange / 'automation.json', {'enabled': True})
    ids = ['a' * 64, 'b' * 64]
    packets = [exchange / 'packets' / key for key in ids]
    for directory in packets:
        directory.mkdir(parents=True)
    if mode == 'failure':
        (packets[1] / 'fail').touch()
    atomic_json(exchange / 'exchange.json', {'status': 'waiting', 'packet': ids[0],
        'packets': [ids[0], '../outside'] if mode == 'invalid' else ids})
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        str(scripts / 'run_antigravity_job.ps1'), '-JobDirectory', str(job),
        '-MaxConcurrent', '1' if mode == 'serial' else '2']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and process.poll() is None:
            if mode == 'cancel' and all((path / 'started.json').exists() for path in packets):
                (job / '.cancel').touch()
            elif mode in ('parallel', 'serial') and all((path / 'agy-result.json').exists() for path in packets):
                atomic_json(job / 'job.json', {'analysis_provider': PROVIDER, 'status': 'completed'})
            time.sleep(.05)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == (1 if mode in ('failure', 'invalid') else 0), stderr.decode(errors='replace')
        state = read_json(exchange / 'runner.json')
        assert state['status'] == {'cancel': 'stopped', 'failure': 'error', 'invalid': 'error'}.get(mode, 'completed')
        if mode == 'invalid':
            assert not any((path / 'started.json').exists() for path in packets)
            return
        assert all((path / 'ended.json').exists() for path in packets)
        if mode in ('parallel', 'serial'):
            starts = [json.loads((path / 'started.json').read_text()) for path in packets]
            ends = [json.loads((path / 'ended.json').read_text()) for path in packets]
            assert (max(starts) < min(ends)) == (mode == 'parallel')
            assert 'Attempt already finished' not in stderr.decode(errors='replace')
        else:
            assert (packets[0] / 'observed-stop').exists()
            assert not (packets[0] / 'agy-result.json').exists()
        assert not list(exchange.glob('.runner-stop-*'))
    finally:
        if process.poll() is None:
            (job / '.cancel').touch()
            process.communicate(timeout=10)


def test_locked_runner_hint_does_not_abort_receipt_or_ui_snapshot(tmp_path):
    import app.antigravity_exchange as exchange_module
    vision = session(tmp_path)
    atomic_json(tmp_path / 'antigravity/automation.json', {'enabled': True})
    original_read = exchange_module.read_json
    def locked_hint(path, *args):
        if Path(path).name == 'runner.json':
            raise PermissionError('Windows status sharing race')
        return original_read(path, *args)
    def publish(_):
        exchange = original_read(tmp_path / 'antigravity/exchange.json')
        packet_dir(tmp_path, exchange['packet']).joinpath('agy-result.json').write_bytes(envelope({'keep_units': ['u2']}))
    with patch('app.antigravity_exchange.read_json', side_effect=locked_hint), \
            patch('app.antigravity_exchange.time.sleep', side_effect=publish):
        assert vision.query('sharing race', schema=SCHEMA) == {'keep_units': ['u2']}
        state = snapshot(tmp_path)
        assert state['runner'] == {}
        assert state['packets'][0]['status'] == 'ready'
