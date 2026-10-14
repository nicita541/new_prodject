"""Clock-driven quota waits: no early dispatch, no accepted-result loss."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from app.antigravity_exchange import packet_failure, ManualVision, AnalysisPending, snapshot
from app.antigravity_quota import (reset_fields, seed_cooldown, wait_for_quota,
                                  cooldown_state, QuotaRecoveryBlocked)
from app.json_store import atomic_json, read_json


BASE=datetime(2026,10,13,15,48,14,949329,tzinfo=timezone.utc)
ID='a'*64


def fixture(tmp_path, delay=2, count=0):
    root=tmp_path/'antigravity';packet=root/'packets'/ID
    packet.mkdir(parents=True)
    atomic_json(tmp_path/'job.json',{'id':'job','status':'running','stage':'analyze',
        'message':'Проверка конкретного выбора · обработано событий: 50 из 129','progress':.5})
    atomic_json(root/'automation.json',{'enabled':True,'managed':True})
    atomic_json(root/'runner.json',{'status':'processing','packet':ID})
    atomic_json(packet/'request.json',{'id':ID})
    fields=reset_fields(f'Individual quota reached. Resets in {delay}s.',BASE.isoformat())
    failure={'packet':ID,'code':'quota','attempt':'first','response_mode':'structured',**fields}
    atomic_json(packet/'failure.json',failure)
    if count:atomic_json(packet/'quota-retry.json',{'count':count})
    seed_cooldown(tmp_path,failure)
    return root,packet,failure


def test_exact_historical_reset_is_never_extended_on_reread():
    fields=reset_fields('Individual quota reached. Please upgrade. Resets in 2h29m4s.',BASE.isoformat())
    assert fields['quota_delay_seconds']==8944
    assert fields['quota_reset_at']=='2026-10-13T18:17:18.949329+00:00'
    assert fields['quota_retry_at']=='2026-10-13T18:17:48.949329+00:00'
    assert reset_fields('Individual quota reached. Resets in 2h29m4s.',BASE.isoformat())==fields


@pytest.mark.parametrize('error,stamp',[
    ('Quota exceeded.',BASE.isoformat()),('Resets in 0s.',BASE.isoformat()),
    ('Resets in 25h.',BASE.isoformat()),('Resets in 1h2h.',BASE.isoformat()),
    ('Resets in 2m1h.',BASE.isoformat()),('Resets in 1h unexpected text',BASE.isoformat()),
    ('Resets in 1s.','2026-10-13T15:48:14'),('Resets in 999999999999999999h.',BASE.isoformat())])
def test_unconfirmed_reset_never_schedules_a_retry(error,stamp):
    assert reset_fields(error,stamp)=={}


def test_legacy_quota_enrichment_uses_recorded_cli_finish_and_keeps_error_unaccepted(tmp_path):
    root,packet,_=fixture(tmp_path)
    old={'packet':ID,'code':'quota','attempt':'first','response_mode':'structured'}
    atomic_json(packet/'failure.json',old)
    attempt=packet/'cli-attempts'/'first';attempt.mkdir(parents=True)
    atomic_json(attempt/'agy-result.json',{'event':'result','result':{'status':'ERROR',
        'error':'Individual quota reached. Resets in 2h29m4s.','structured_output':{'fake':'success'}}})
    (attempt/'cli-run.json').write_text(json.dumps({'official_cli':True,'finished_at':BASE.isoformat()}),'utf-8-sig')
    before=(packet/'failure.json').read_bytes()
    failure=packet_failure(packet,ID,persist=False)
    assert failure['quota_retry_at']=='2026-10-13T18:17:48.949329+00:00'
    assert (packet/'failure.json').read_bytes()==before
    assert packet_failure(packet,ID)==failure
    assert read_json(packet/'failure.json')==failure
    assert not (packet/'result.json').exists()


def test_wait_preserves_stage_counter_then_rearms_one_failed_marker_only(tmp_path):
    root,packet,failure=fixture(tmp_path)
    original=(packet/'request.json').read_bytes()
    seen=[]
    class Clock(datetime):
        current=BASE
        @classmethod
        def now(cls,tz):return cls.current
    def advance(seconds):
        job=read_json(tmp_path/'job.json')
        seen.append(job)
        assert (packet/'failure.json').exists()
        assert not (packet/'quota-retry.json').exists()
        Clock.current+=timedelta(seconds=16)
    with patch('app.antigravity_quota.datetime',Clock),patch('app.antigravity_quota.time.sleep',side_effect=advance):
        wait_for_quota(tmp_path,lambda:False)
    assert seen and seen[0]['provider_wait']['reason']=='quota'
    assert all(j['stage']=='analyze' and j['progress']==.5 for j in seen)
    assert read_json(tmp_path/'job.json')['message'].endswith('50 из 129')
    assert 'provider_wait' not in read_json(tmp_path/'job.json')
    assert not (root/'quota-cooldown.json').exists()
    assert not (packet/'failure.json').exists()
    assert read_json(packet/'quota-retry.json')['count']==1
    assert json.loads(next((packet/'quota-history').glob('*.json')).read_text('utf-8'))==failure
    assert (packet/'request.json').read_bytes()==original


def test_cancel_during_cooldown_keeps_original_failure_and_no_retry_ticket(tmp_path):
    root,packet,failure=fixture(tmp_path)
    count=[0]
    def cancel():count[0]+=1;return count[0]>1
    with patch('app.antigravity_quota.datetime',wraps=datetime) as clock,patch('app.antigravity_quota.time.sleep'):
        clock.now.return_value=BASE
        with pytest.raises(InterruptedError):wait_for_quota(tmp_path,cancel)
    assert read_json(packet/'failure.json')==failure
    assert not (packet/'quota-retry.json').exists()
    assert cooldown_state(root)
    assert 'provider_wait' not in read_json(tmp_path/'job.json')


def test_retry_cap_and_unknown_quota_are_not_automatic_model_loops(tmp_path):
    root,packet,failure=fixture(tmp_path,count=2)
    with pytest.raises(QuotaRecoveryBlocked,match='двух'):
        wait_for_quota(tmp_path,lambda:False)
    assert read_json(packet/'failure.json')==failure
    assert not (packet/'quota-history').exists()
    (root/'quota-cooldown.json').unlink()
    assert seed_cooldown(tmp_path,{'packet':ID,'code':'quota'}) is None


def test_accepted_reply_and_external_mode_are_never_rearmed(tmp_path):
    root,packet,failure=fixture(tmp_path,count=2)
    atomic_json(packet/'result.json',{'native':'accepted'})
    accepted=(packet/'result.json').read_bytes()
    with patch('app.antigravity_quota.datetime',wraps=datetime) as clock:
        clock.now.return_value=BASE+timedelta(seconds=60)
        wait_for_quota(tmp_path,lambda:False)
    assert (packet/'result.json').read_bytes()==accepted
    assert read_json(packet/'failure.json')==failure
    assert not (packet/'quota-history').exists()
    atomic_json(root/'automation.json',{'enabled':True})
    assert seed_cooldown(tmp_path,failure) is None


def test_receive_wait_preserves_response_deadline_and_snapshot_is_read_only(tmp_path):
    vision=ManualVision(tmp_path,lambda:False)
    root=tmp_path/'antigravity'
    atomic_json(root/'automation.json',{'enabled':True,'managed':True})
    atomic_json(tmp_path/'job.json',{'status':'running','stage':'analyze','message':'Actual stage'})
    directory,identifier,request=vision._prepare_request('Actual native prompt',schema={'type':'object'})
    failure={'packet':identifier,'code':'quota','attempt':'first',**reset_fields('Resets in 2s.',BASE.isoformat())}
    atomic_json(directory/'failure.json',failure)
    seed_cooldown(tmp_path,failure)
    atomic_json(root/'runner.json',{'status':'waiting_quota','packet':identifier})
    # Simulate a long quota wait, then the SAME native request gets a valid reply.
    times=[0,0,0,7200,7200,7201,7201,7202]
    def recovered(job,cancelled):
        (directory/'failure.json').unlink(missing_ok=True)
        (root/'quota-cooldown.json').unlink(missing_ok=True)
        atomic_json(directory/'agy-result.json',{'status':'SUCCESS','structured_output':{'ok':True}})
    with patch('app.antigravity_quota.wait_for_quota',side_effect=recovered), \
         patch('app.antigravity_exchange.time.monotonic',side_effect=lambda:times.pop(0) if times else 7202):
        assert vision.query('Actual native prompt',schema={'type':'object'})=={'ok':True}
    assert read_json(directory/'result.json')['id']==identifier


def test_actual_owned_coordinator_waits_then_retries_same_packet_once(tmp_path):
    import os
    import shutil
    import subprocess
    import time
    import uuid
    from pathlib import Path
    if os.name!='nt':pytest.skip('native Windows coordinator')
    source_root=Path(__file__).resolve().parents[1]
    scripts=tmp_path/'scripts';scripts.mkdir()
    shutil.copy2(source_root/'scripts/run_antigravity_job.ps1',scripts/'run_antigravity_job.ps1')
    stub=r'''param($PacketDirectory,$AgyExe,$Model,[switch]$DefaultAgent,$StopFile,$RunnerStopFile,$TimeLimitSeconds,[switch]$AllowQuotaWait)
    $ErrorActionPreference='Stop'
    $counter=Join-Path $PacketDirectory 'calls'
    $count=if(Test-Path -LiteralPath $counter){[int][IO.File]::ReadAllText($counter)+1}else{1}
    [IO.File]::WriteAllText($counter,"$count")
    [IO.File]::WriteAllText((Join-Path $PacketDirectory "started-$count"),[DateTimeOffset]::UtcNow.ToString('o'))
    $id=Split-Path $PacketDirectory -Leaf
    if($count -eq 1){
        $finished=[DateTimeOffset]::UtcNow
        $failure=@{packet=$id;code='quota';attempt='first';quota_finished_at=$finished.ToString('o');quota_delay_seconds=1;
            quota_reset_at=$finished.AddSeconds(1).ToString('o');quota_retry_at=$finished.AddSeconds(31).ToString('o')}
        $text=$failure|ConvertTo-Json -Compress
        [IO.File]::WriteAllText((Join-Path $PacketDirectory 'failure.json'),$text)
        [IO.File]::WriteAllText((Join-Path (Split-Path (Split-Path $PacketDirectory -Parent) -Parent) 'quota-cooldown.json'),$text)
        return
    }
    [IO.File]::WriteAllText((Join-Path $PacketDirectory 'agy-result.json'),' {"status":"SUCCESS","structured_output":{"ok":true}} ')
    '''
    (scripts/'run_antigravity_packet.ps1').write_text(stub,'utf-8-sig')
    job=tmp_path/'job';job.mkdir()
    atomic_json(job/'job.json',{'status':'running','analysis_provider':'antigravity_manual',
        'stage':'analyze','progress':.5,'message':'Проверка конкретного выбора · обработано событий: 50 из 129'})
    atomic_json(job/'antigravity/automation.json',{'enabled':True,'managed':True})
    vision=ManualVision(job,lambda:False)
    packet,identifier,_=vision._prepare_request('Exact native request',schema={'type':'object'})
    stop=job/'antigravity'/('.managed-stop-'+uuid.uuid4().hex)
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/'run_antigravity_job.ps1'),
        '-JobDirectory',str(job),'-AgyExe',str(source_root/'tools/python/python.exe'),'-ManagedStopFile',str(stop),'-MaxMinutes','1']
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    observed=[];original_sleep=time.sleep
    def observe(seconds):
        state=read_json(job/'job.json')
        if state.get('provider_wait'):observed.append(state)
        original_sleep(seconds)
    try:
        with patch('app.antigravity_quota.time.sleep',side_effect=observe):
            assert vision.query('Exact native request',schema={'type':'object'})=={'ok':True}
        assert observed and all(j['stage']=='analyze' and j['progress']==.5 for j in observed)
        assert (packet/'calls').read_text()=='2'
        history=read_json(next((packet/'quota-history').glob('*.json')))
        second=datetime.fromisoformat((packet/'started-2').read_text().replace('Z','+00:00'))
        assert second>=datetime.fromisoformat(history['quota_retry_at'].replace('Z','+00:00'))
        assert read_json(packet/'quota-retry.json')['count']==1
        assert read_json(packet/'result.json')['id']==identifier
        atomic_json(job/'job.json',{'analysis_provider':'antigravity_manual','status':'completed'})
        out,err=process.communicate(timeout=10)
        assert process.returncode==0,err.decode(errors='replace')
    finally:
        if process.poll() is None:
            stop.touch();process.communicate(timeout=10)
