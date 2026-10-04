from __future__ import annotations

import unittest
import asyncio
import shutil
import subprocess
import uuid
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from starlette import formparsers

from fastapi.testclient import TestClient

from app import config
from app.jobs import JobManager, atomic_json
from app.server import create_app, validate_media
from tests.test_jobs import FakeWorker, deepseek_stub


class ApiTests(unittest.TestCase):
    def test_balance_refresh_is_free_scoped_throttled_and_keeps_private_errors_out(self):
        state={'source':'deepseek_user_balance','scope':'account','balance_usd':'1.78','window':None}
        with patch('app.provider_balance.refresh',return_value=state) as refresh, patch('app.provider_balance.status',return_value=state):
            self.assertEqual(self.client.get('/api/deepseek/balance').json(),state)
            denied=self.client.post('/api/deepseek/balance',headers={'Origin':'https://other.example'})
            self.assertEqual(denied.status_code,403)
            refresh.assert_not_called()
            self.assertEqual(self.client.post('/api/deepseek/balance').json(),state)
            refresh.assert_called_once_with(None,None,False)
            self.assertEqual(self.client.post('/api/deepseek/balance?job_id=missing').status_code,404)
        with patch('app.provider_balance.refresh',side_effect=RuntimeError('secret-private-field')):
            error=self.client.post('/api/deepseek/balance')
            self.assertEqual(error.status_code,503)
            self.assertNotIn('secret',error.text)

    def test_trash_preserves_outputs_across_reload_and_parent_restore(self):
        job=self.start_job(); self.client.post(f"/api/jobs/{job['id']}/cancel")
        library=self.client.get('/api/library').json()
        project=library['projects'][0]; episode=library['episodes'][0]
        other=self.client.post(f"/api/projects/{project['id']}/episodes",json={}).json()
        output=self.manager.job_dir(job['id'])/'output'; output.mkdir(exist_ok=True)
        (output/'part_001.mp4').write_bytes(b'export preserved')
        self.assertEqual(self.client.delete(f"/api/episodes/{other['id']}").status_code,200)
        path=f"/api/projects/{project['id']}"
        self.assertEqual(self.client.delete(path,headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.delete(path).status_code,200)
        self.assertEqual(self.client.post(f"/api/episodes/{episode['id']}/jobs").status_code,404)
        self.assertEqual(self.client.post(path+'/episodes',json={}).status_code,404)
        from app.library import Library
        reloaded=Library(self.manager).snapshot()
        self.assertTrue(reloaded['projects'][0]['archived_at'])
        self.assertEqual(len(reloaded['projects']),1)  # Legacy migration does not resurrect it.
        self.assertEqual(self.client.post(path+'/restore').status_code,200)
        current=self.client.get('/api/library').json()
        self.assertNotIn('archived_at',current['projects'][0])
        self.assertTrue(next(e for e in current['episodes'] if e['id']==other['id'])['archived_at'])
        self.assertEqual(next(e for e in current['episodes'] if e['id']==episode['id'])['jobs'][0]['id'],job['id'])
        self.assertEqual((output/'part_001.mp4').read_bytes(),b'export preserved')
        self.assertEqual((self.root/'Русская серия 01.mp4').read_bytes(),b'source untouched')
        self.assertEqual(len(self.manager.list_jobs()),1)

    def test_trash_rejects_active_new_and_legacy_attempts(self):
        job=self.start_job()
        current=self.client.get('/api/library').json()
        episode=current['episodes'][0]; project=current['projects'][0]
        for kind,item in [('episodes',episode),('projects',project)]:
            self.assertEqual(self.client.delete(f"/api/{kind}/{item['id']}").status_code,409)
        self.client.post(f"/api/jobs/{job['id']}/cancel")
        started=self.client.post(f"/api/episodes/{episode['id']}/jobs").json()
        self.assertEqual(started['episode_id'],episode['id'])
        for kind,item in [('episodes',episode),('projects',project)]:
            self.assertEqual(self.client.delete(f"/api/{kind}/{item['id']}").status_code,409)
        self.client.post(f"/api/jobs/{started['id']}/cancel")
        self.assertEqual(self.client.delete(f"/api/episodes/{episode['id']}").status_code,200)

    def test_restore_checks_episode_number_source_and_project_title_conflicts(self):
        project=self.client.post('/api/projects',json={'title':'Аниме'}).json()
        base=f"/api/projects/{project['id']}"
        episode=self.client.post(base+'/episodes',json={'number':1}).json()
        source=self.client.get('/api/sources').json()[0]
        settings={'source_id':source['id'],'analysis_provider':'local','layout':'cinema','caption_style':'accent'}
        self.client.put(f"/api/episodes/{episode['id']}/settings",json=settings)
        ep_path=f"/api/episodes/{episode['id']}"
        self.assertEqual(self.client.delete(ep_path).status_code,200)
        replacement=self.client.post(base+'/episodes',json={'number':1}).json()
        self.assertEqual(self.client.post(ep_path+'/restore').status_code,400)
        self.client.delete(f"/api/episodes/{replacement['id']}")
        another=self.client.post(base+'/episodes',json={'number':2}).json()
        self.assertEqual(self.client.put(f"/api/episodes/{another['id']}/settings",json=settings).status_code,200)
        self.assertEqual(self.client.post(ep_path+'/restore').status_code,400)
        self.client.delete(f"/api/episodes/{another['id']}")
        self.assertEqual(self.client.post(ep_path+'/restore').status_code,200)
        self.client.delete(base)
        duplicate=self.client.post('/api/projects',json={'title':'аниме'}).json()
        self.assertEqual(self.client.post(base+'/restore').status_code,400)
        self.client.delete(f"/api/projects/{duplicate['id']}")
        self.assertEqual(self.client.post(base+'/restore').status_code,200)

    def test_project_episode_settings_persist_and_scope_worker_identity(self):
        (self.root/'Другая серия.mp4').write_bytes(b'other source')
        project = self.client.post('/api/projects', json={'title':'Тестовое аниме'}).json()
        episode = self.client.post(f"/api/projects/{project['id']}/episodes", json={'number':1}).json()
        second = self.client.post(f"/api/projects/{project['id']}/episodes", json={}).json()
        self.assertEqual(second['number'], 2)
        source = self.client.get('/api/sources').json()[0]
        settings = {'source_id':source['id'], 'analysis_provider':'local', 'layout':'cinema', 'caption_style':'accent'}
        saved = self.client.put(f"/api/episodes/{episode['id']}/settings", json=settings)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.put(f"/api/episodes/{second['id']}/settings", json=settings).status_code, 400)
        other_source = self.client.get('/api/sources').json()[1]
        self.assertEqual(self.client.put(f"/api/episodes/{episode['id']}/settings", json={**settings,'source_id':other_source['id']}).status_code, 400)
        from app.library import Library
        restored = Library(self.manager).snapshot()
        self.assertEqual(restored['episodes'][0]['source_id'], source['id'])
        started = self.client.post(f"/api/episodes/{episode['id']}/jobs")
        self.assertEqual(started.status_code, 201, started.text)
        job = started.json()
        self.assertEqual(job['episode_id'], episode['id'])
        self.assertEqual(job['layout'], 'cinema')
        from app.jobs import read_json
        self.assertEqual(read_json(self.manager.job_dir(job['id'])/'job.json')['episode_id'],episode['id'])
        self.assertEqual(self.client.put(f"/api/episodes/{episode['id']}/settings", json=settings).status_code, 400)
        snapshot = self.client.get('/api/library').json()
        self.assertEqual(snapshot['episodes'][0]['jobs'][0]['id'],job['id'])
        self.assertEqual(snapshot['episodes'][1]['jobs'],[])

    def test_project_inputs_missing_source_and_origin_are_guarded(self):
        self.assertEqual(self.client.post('/api/projects',json={'title':'   '}).status_code,400)
        self.assertEqual(self.client.post('/api/projects',json={'title':'Аниме'},headers={'Origin':'https://external.example'}).status_code,403)
        project=self.client.post('/api/projects',json={'title':'Аниме'}).json()
        self.assertEqual(self.client.post('/api/projects',json={'title':'аниме'}).status_code,400)
        base=f"/api/projects/{project['id']}/episodes"
        for number in [0,True,1.5,'2']:
            self.assertEqual(self.client.post(base,json={'number':number}).status_code,422)
        episode=self.client.post(base,json={'number':1}).json()
        self.assertEqual(self.client.post(base,json={'number':1}).status_code,400)
        self.assertEqual(self.client.post(f"/api/episodes/{episode['id']}/jobs").status_code,400)
        self.assertEqual(self.manager.list_jobs(),[])
        self.assertEqual(self.client.post('/api/projects/not-a-uuid/episodes',json={}).status_code,404)

    def test_legacy_migration_merges_same_source_and_retains_outputs(self):
        source=self.client.get('/api/sources').json()[0]
        jobs=[]
        for index in range(2):
            identifier=str(uuid.uuid4()); directory=self.manager.job_dir(identifier); directory.mkdir()
            job={'id':identifier,'status':'completed','source_name':'1 серия «Аниме» .mp4',
                 'created_at':f'2026-10-02T00:00:0{index}+00:00','outputs':['part_001.mp4'],
                 'analysis_provider':'local','layout':'cinema','caption_style':'accent'}
            atomic_json(directory/'job.json',job)
            atomic_json(directory/'source.json',self.manager.source(source['id']))
            (directory/'output').mkdir(); (directory/'output/part_001.mp4').write_bytes(b'unchanged')
            jobs.append(identifier)
        first=self.client.get('/api/library').json()
        second=self.client.get('/api/library').json()
        self.assertEqual(first,second)
        self.assertEqual(len(first['projects']),1)
        self.assertEqual(len(first['episodes']),1)
        self.assertEqual(len(first['episodes'][0]['jobs']),2)
        for identifier in jobs:
            self.assertEqual((self.manager.job_dir(identifier)/'output/part_001.mp4').read_bytes(),b'unchanged')

    def test_timeline_original_stream_uses_stored_source_and_supports_range(self):
        job = self.start_job()
        path = f"/api/jobs/{job['id']}/source"
        response = self.client.get(path, headers={'Range':'bytes=2-7'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(response.content,b'urce u')
        self.assertEqual(response.headers['Content-Range'],'bytes 2-7/16')
        self.assertEqual(self.client.head(path).status_code,200)
        self.assertEqual(self.client.get(path+'?path=C:/private').content,b'source untouched')
        atomic_json(self.manager.job_dir(job['id'])/'source.json',{'path':str(config.ROOT/'README.md')})
        self.assertEqual(self.client.get(path).status_code,400)

    def test_attempt_reset_requires_idle_job_and_same_origin(self):
        source = self.client.get('/api/sources').json()[0]
        job = self.client.post('/api/jobs', json={'source_id': source['id']}).json()
        path = f"/api/jobs/{job['id']}/reset-budget"
        with patch('app.deepseek.begin_attempt', return_value={'attempt':2, 'charged_ceiling_usd':'0'}) as reset:
            self.assertEqual(self.client.post(path, json={}).status_code, 409)
            reset.assert_not_called()
            self.client.post(f"/api/jobs/{job['id']}/cancel")
            self.assertEqual(self.client.post(path, json={}, headers={'Origin':'https://other.example'}).status_code, 403)
            reset.assert_not_called()
            accepted = self.client.post(path, json={})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(accepted.json()['charged_ceiling_usd'], '0')
            reset.assert_called_once_with(self.manager.job_dir(job['id']))

    def test_recovery_requires_explicit_body_and_same_origin(self):
        with patch('app.deepseek.acknowledge_reserved_requests', return_value={'resumed':True}) as recover:
            self.assertEqual(self.client.post('/api/deepseek/recovery', json={}).status_code, 422)
            self.assertEqual(self.client.post('/api/deepseek/recovery', json={'accept_reserved_costs':False}).status_code, 422)
            self.assertEqual(self.client.post('/api/deepseek/recovery', json={'accept_reserved_costs':True},
                                             headers={'Origin':'https://other.example'}).status_code, 403)
            recover.assert_not_called()
            accepted = self.client.post('/api/deepseek/recovery', json={'accept_reserved_costs':True})
            self.assertEqual(accepted.status_code, 200)
            recover.assert_called_once_with()

    def test_editing_presets_are_validated_persisted_and_retained_on_retry(self):
        source = self.client.get('/api/sources').json()[0]
        for field in ('layout', 'caption_style'):
            invalid = self.client.post('/api/jobs', json={'source_id': source['id'], field: 'arbitrary-filter'})
            self.assertEqual(invalid.status_code, 422)
        created = self.client.post('/api/jobs', json={'source_id': source['id'], 'layout': 'cinema', 'caption_style': 'accent'})
        self.assertEqual(created.status_code, 201, created.text)
        job = created.json()
        from app.editing import load_options
        self.assertEqual(load_options(self.manager.job_dir(job['id'])), {'layout': 'cinema', 'caption_style': 'accent'})
        self.client.post(f"/api/jobs/{job['id']}/cancel")
        retried = self.client.post(f"/api/jobs/{job['id']}/retry").json()
        self.assertEqual((retried['layout'], retried['caption_style']), ('cinema', 'accent'))

    def test_deepseek_status_and_free_check_exclude_private_fields(self):
        client = deepseek_stub()
        client.public_status.return_value["api_key"] = "hidden-test-value"
        client.check_connection.return_value["api_key"] = "hidden-test-value"
        client.check_connection.return_value["balance_infos"][0]["private"] = "hidden-test-value"
        with patch.dict(sys.modules, {"app.deepseek": client}):
            response = self.client.get("/api/deepseek")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {"configured", "budget_usd", "charged_ceiling_usd", "remaining_usd", "model"})
            self.assertIsNone(response.json()["budget_usd"])
            client.check_connection.assert_not_called()
            self.assertNotIn("hidden-test-value", response.text)
            denied = self.client.post("/api/deepseek/check", headers={"Origin": "https://other.example"})
            self.assertEqual(denied.status_code, 403)
            client.check_connection.assert_not_called()
            checked = self.client.post("/api/deepseek/check")
            self.assertEqual(checked.status_code, 200)
            self.assertEqual(checked.json()["balance_infos"], [{"currency": "USD", "total_balance": "0.06"}])
            self.assertNotIn("hidden-test-value", checked.text)
            client.check_connection.assert_called_once_with()

    def test_deepseek_errors_never_echo_client_exception_text(self):
        client = deepseek_stub()
        client.public_status.side_effect = RuntimeError("hidden-test-value")
        client.check_connection.side_effect = RuntimeError("hidden-test-value")
        with patch.dict(sys.modules, {"app.deepseek": client}):
            for method, path in ((self.client.get, "/api/deepseek"), (self.client.post, "/api/deepseek/check")):
                response = method(path)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("hidden-test-value", response.text)

    def test_job_analysis_provider_is_explicit_local_default_and_balance_checked(self):
        client = deepseek_stub()
        source = self.client.get("/api/sources").json()[0]
        with patch.dict(sys.modules, {"app.deepseek": client}):
            local = self.start_job()
            self.assertEqual(local["analysis_provider"], "local")
            client.public_status.assert_not_called()
            self.client.post(f"/api/jobs/{local['id']}/cancel")
            selected = self.client.post("/api/jobs", json={"source_id": source["id"], "analysis_provider": "deepseek"})
            self.assertEqual(selected.status_code, 201, selected.text)
            self.assertEqual(selected.json()["analysis_provider"], "deepseek")
            directory = self.manager.job_dir(selected.json()["id"])
            self.assertEqual((directory / "analysis-settings.json").read_text(encoding="utf-8").count("deepseek"), 1)
            client.check_connection.assert_not_called()
            self.client.post(f"/api/jobs/{selected.json()['id']}/cancel")
            client.public_status.return_value["remaining_usd"] = "0"
            count = len(list(self.manager.jobs.iterdir()))
            denied = self.client.post("/api/jobs", json={"source_id": source["id"], "analysis_provider": "deepseek"})
            self.assertEqual(denied.status_code, 400)
            self.assertIn("Баланс не подтверждён", denied.json()["detail"])
            self.assertNotIn("лимит", denied.json()["detail"].lower())
            self.assertEqual(len(list(self.manager.jobs.iterdir())), count)
            invalid = self.client.post("/api/jobs", json={"source_id": source["id"], "analysis_provider": "other"})
            self.assertEqual(invalid.status_code, 422)

    def test_hybrid_api_persists_and_retries_without_confirmed_remote_balance(self):
        source = self.client.get("/api/sources").json()[0]
        for status in ({"configured": False, "remaining_usd": "0"},
                       {"configured": True, "remaining_usd": "0"}):
            with self.subTest(status=status):
                client = deepseek_stub(status)
                with patch.dict(sys.modules, {"app.deepseek": client}):
                    response = self.client.post("/api/jobs", json={"source_id": source["id"], "analysis_provider": "hybrid"})
                    self.assertEqual(response.status_code, 201, response.text)
                    job = response.json()
                    self.assertEqual(job["analysis_provider"], "hybrid")
                    directory = self.manager.job_dir(job["id"])
                    self.assertEqual((directory / "analysis-settings.json").read_text(encoding="utf-8").count("hybrid"), 1)
                    self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").json()["analysis_provider"], "hybrid")
                    self.client.post(f"/api/jobs/{job['id']}/cancel")
                    retried = self.client.post(f"/api/jobs/{job['id']}/retry")
                    self.assertEqual(retried.status_code, 200, retried.text)
                    self.assertEqual(retried.json()["analysis_provider"], "hybrid")
                    self.assertEqual(retried.json()["status"], "running")
                    self.client.post(f"/api/jobs/{job['id']}/cancel")
                client.public_status.assert_not_called()
                client.check_connection.assert_not_called()

    def test_deepseek_plan_api_requires_balance_and_preserves_provider_on_retry(self):
        source = self.client.get("/api/sources").json()[0]
        client = deepseek_stub({"configured": False, "remaining_usd": "0.04"})
        body = {"source_id": source["id"], "analysis_provider": "deepseek_plan"}
        with patch.dict(sys.modules, {"app.deepseek": client}):
            denied = self.client.post("/api/jobs", json=body)
            self.assertEqual(denied.status_code, 400)
            self.assertEqual(list(self.manager.jobs.iterdir()), [])
            client.public_status.return_value["configured"] = True
            accepted = self.client.post("/api/jobs", json=body)
            self.assertEqual(accepted.status_code, 201, accepted.text)
            job = accepted.json()
            self.assertEqual(job["analysis_provider"], "deepseek_plan")
            self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").json()["analysis_provider"], "deepseek_plan")
            self.client.post(f"/api/jobs/{job['id']}/cancel")
            client.public_status.return_value["remaining_usd"] = "0"
            self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/retry").status_code, 400)
            self.assertFalse(self.manager.busy())
            client.public_status.return_value["remaining_usd"] = "0.03"
            retried = self.client.post(f"/api/jobs/{job['id']}/retry")
            self.assertEqual(retried.status_code, 200, retried.text)
            self.assertEqual(retried.json()["analysis_provider"], "deepseek_plan")
        client.check_connection.assert_not_called()

    def test_file_over_limit_inside_envelope_budget_is_not_copied(self):
        with patch("app.server.MAX_UPLOAD", 1024), \
                patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock) as read:
            response = self.client.post("/api/import", files={"file": ("too-big.mp4", b"x" * 2000, "video/mp4")})
        self.assertEqual(response.status_code, 413)
        read.assert_not_called()
        self.assertEqual(list(self.manager.imports.iterdir()), [])

    def test_oversized_known_length_rejected_before_multipart_parser(self):
        with patch("app.server.MAX_UPLOAD", 1024), \
                patch("starlette.formparsers.SpooledTemporaryFile") as spool:
            response = self.client.post("/api/import", files={"file": ("too-big.mp4", b"x" * 70000, "video/mp4")})
        self.assertEqual(response.status_code, 413)
        spool.assert_not_called()
        self.assertEqual(list(self.manager.imports.iterdir()), [])

    def test_chunked_upload_limit_closes_already_spooled_partial_file(self):
        opened = []
        written = []
        original = formparsers.SpooledTemporaryFile
        def spool(*args, **kwargs):
            value = original(*args, **kwargs)
            opened.append(value)
            index = len(written)
            written.append(0)
            original_write = value.write
            def counted_write(data):
                written[index] += len(data)
                return original_write(data)
            value.write = counted_write
            return value
        boundary = b"audit-boundary"
        header = (b"--" + boundary + b'\r\nContent-Disposition: form-data; name="file"; filename="too-big.mp4"\r\n'
                  b"Content-Type: video/mp4\r\n\r\n")
        messages = [{"type": "http.request", "body": header + b"x" * (1100 * 1024), "more_body": True},
                    {"type": "http.request", "body": b"x" * (1100 * 1024) + b"\r\n--" + boundary + b"--\r\n", "more_body": False}]
        sent = []
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                 "scheme": "http", "path": "/api/import", "raw_path": b"/api/import", "root_path": "", "query_string": b"",
                 "headers": [(b"host", b"127.0.0.1:8765"), (b"content-type", b"multipart/form-data; boundary=" + boundary)],
                 "client": ("127.0.0.1", 1000), "server": ("127.0.0.1", 8765)}
        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}
        async def send(message):
            sent.append(message)
        with patch("app.server.MAX_UPLOAD", 2 * 1024 * 1024), \
                patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool):
            asyncio.run(self.client.app(scope, receive, send))
        self.assertEqual(next(m["status"] for m in sent if m["type"] == "http.response.start"), 413)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0]._rolled)
        self.assertTrue(opened[0].closed)
        self.assertLessEqual(sum(written), 2 * 1024 * 1024)
        self.assertEqual(list(self.manager.imports.iterdir()), [])

    def setUp(self):
        self.root = config.TEMP / ("api_" + uuid.uuid4().hex)
        self.root.mkdir()
        (self.root / "Русская серия 01.mp4").write_bytes(b"source untouched")
        self.manager = JobManager(self.root, FakeWorker)
        self.ready = patch("app.server.config.readiness", return_value={"ready": True, "missing": []})
        self.ready.start()
        self.client = TestClient(create_app(self.manager), base_url="http://127.0.0.1:8765")
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.ready.stop()
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root)
    def start_job(self):
        source = self.client.get("/api/sources").json()[0]
        response = self.client.post("/api/jobs", json={"source_id": source["id"]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_flow_sources_single_job_cancel_retry_and_plan(self):
        sources = self.client.get("/api/sources").json()
        self.assertEqual(set(sources[0]), {"id", "name", "size"})
        self.assertEqual(sources[0]["name"], "Русская серия 01.mp4")
        job = self.start_job()
        self.assertTrue(self.client.get("/api/health").json()["busy"])
        self.assertEqual(self.client.post("/api/jobs", json={"source_id": sources[0]["id"]}).status_code, 409)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/plan").status_code, 404)
        checkpoint = self.manager.job_dir(job["id"]) / "transcript.json"
        atomic_json(checkpoint, {"words": ["saved"]})
        atomic_json(checkpoint.parent / "plan.json", {"parts": [{"number": 1}]})
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/plan").json()["parts"][0]["number"], 1)
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel").json()["status"], "cancelled")
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/retry").json()["status"], "running")
        self.assertTrue(checkpoint.is_file())
        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)

    def test_dns_rebinding_and_cross_origin_mutations_blocked(self):
        for host in ["evil.example", "127.0.0.1.evil.example", "localhost:8765@evil.example"]:
            self.assertEqual(self.client.get("/api/sources", headers={"Host": host}).status_code, 403)
        source = self.client.get("/api/sources").json()[0]
        for origin in ["https://evil.example", "null", "http://127.0.0.1:9999", "http://localhost:8765"]:
            response = self.client.post("/api/jobs", json={"source_id": source["id"]}, headers={"Origin": origin})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/jobs", json={"source_id": source["id"]},
                                         headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/jobs", json={"source_id": source["id"]},
                                         headers={"Origin": "http://127.0.0.1:8765"}).status_code, 201)

    def test_path_injection_and_extra_fields_rejected(self):
        self.assertEqual(self.client.post("/api/jobs", json={"source_id": str(self.root / "Русская серия 01.mp4")}).status_code, 404)
        self.assertEqual(self.client.post("/api/jobs", json={"source_id": "no", "path": "C:\\private"}).status_code, 422)
        self.assertEqual(self.client.get("/api/jobs/not-a-uuid").status_code, 404)

    def test_import_real_validation_boundary_and_long_name(self):
        original = "Длинная русская серия с пробелами " * 8 + ".mkv"
        with patch("app.server.validate_media") as probe:
            response = self.client.post("/api/import", files={"file": (original, b"valid_media", "video/x-matroska")})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertTrue(probe.called)
        registered = response.json()
        self.assertEqual(registered["name"], original)
        imported = Path(self.manager.source(registered["id"])["path"])
        self.assertTrue(imported.is_relative_to(self.root / "data" / "imports"))
        self.assertLess(len(imported.name), 110)
        self.assertEqual(imported.read_bytes(), b"valid_media")
        with patch("app.server.validate_media", side_effect=ValueError("Файл повреждён")):
            self.assertEqual(self.client.post("/api/import", files={"file": ("broken.mp4", b"junk")}).status_code, 400)
        self.assertFalse(list(self.manager.imports.glob("*/.upload")))
        for filename in ["../evil.mp4", "C:\\evil.mp4", "video.exe", "empty.mp4"]:
            self.assertEqual(self.client.post("/api/import", files={"file": (filename, b"")}).status_code, 400)

    def test_range_serves_only_completed_registered_outputs(self):
        job = self.start_job()
        self.manager.cancel(job["id"])
        directory = self.manager.job_dir(job["id"])
        (directory / "output").mkdir()
        (directory / "output" / "part_001.mp4").write_bytes(b"0123456789")
        (directory / "output" / "part_001.srt").write_bytes(b"subtitle")
        (directory / "output" / "private.mp4").write_bytes(b"secret")
        job.update(status="completed", outputs=["part_001.mp4", "part_001.srt"])
        atomic_json(directory / "plan.json", {"parts": [{"index": 1, "duration": 75.25}]})
        atomic_json(directory / "job.json", job)
        base = f"/api/jobs/{job['id']}/files/"
        response = self.client.get(base + "part_001.mp4", headers={"Range": "bytes=2-5"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"2345")
        self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
        self.assertEqual(self.client.get(base + "part_001.mp4", headers={"Range": "bytes=-3"}).content, b"789")
        self.assertEqual(self.client.get(base + "part_001.mp4", headers={"Range": "bytes=5-"}).content, b"56789")
        self.assertEqual(self.client.get(base + "part_001.mp4", headers={"Range": "bytes=200-"}).status_code, 416)
        self.assertEqual(self.client.get(base + "part_001.mp4", headers={"Range": "bytes=0-1,4-5"}).status_code, 416)
        self.assertEqual(self.client.head(base + "part_001.mp4").content, b"")
        self.assertEqual(self.client.get(base + "part_001.srt").content, b"subtitle")
        self.assertEqual(self.client.get(base + "private.mp4").status_code, 404)
        self.assertEqual(self.client.get(base + "..%5Csource.json").status_code, 404)
        public = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(len(public["files"]), 1)
        self.assertEqual(public["files"][0]["duration"], 75.25)
        self.assertTrue(public["files"][0]["subtitle_url"].endswith("part_001.srt"))
        job["status"] = "running"
        atomic_json(directory / "job.json", job)
        self.assertEqual(self.client.get(base + "part_001.mp4").status_code, 404)

    def test_unready_job_has_no_side_effect_and_missing_components_shown(self):
        with patch("app.server.config.readiness", return_value={"ready": False, "missing": ["FFmpeg"]}):
            source = self.client.get("/api/sources").json()[0]
            self.assertEqual(self.client.post("/api/jobs", json={"source_id": source["id"]}).status_code, 503)
            self.assertEqual(self.manager.list_jobs(), [])

    def test_ffprobe_rejects_missing_audio_video_invalid_duration_and_corruption(self):
        import json
        cases = [
            {"streams": [{"codec_type": "video"}], "format": {"duration": "10"}},
            {"streams": [{"codec_type": "audio"}], "format": {"duration": "10"}},
            {"streams": [{"codec_type": "audio"}, {"codec_type": "video"}], "format": {"duration": "NaN"}},
        ]
        with patch("app.server.config.FFPROBE", self.root / "Русская серия 01.mp4"):
            for case in cases:
                with patch("app.server.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(case).encode(), b"")):
                    with self.assertRaises(ValueError):
                        validate_media(self.root / "Русская серия 01.mp4")
            with patch("app.server.subprocess.run", side_effect=subprocess.CalledProcessError(1, [])):
                with self.assertRaises(ValueError):
                    validate_media(self.root / "Русская серия 01.mp4")


if __name__ == "__main__":
    unittest.main()
