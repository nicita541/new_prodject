"""Idle-only shutdown uses identity and lifespan, never OS process killing."""
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import config
from app.jobs import BusyError, JobManager
from app.server import create_app
from app.studio_identity import server_identity
from app.studio_render import submit_render


class StudioShutdownTests(unittest.TestCase):
    def setUp(self):
        self.root = config.TEMP / ("shutdown-api-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.manager = JobManager(self.root)
        self.app = create_app(self.manager)
        self.callback = Mock()
        self.app.state.shutdown_callback = self.callback
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8765")
        self.client.__enter__()

    def tearDown(self):
        self.manager.active = None
        self.manager.finishing_tasks.clear()
        self.client.__exit__(None, None, None)
        if self.root.resolve().is_relative_to(config.TEMP.resolve()):
            shutil.rmtree(self.root, ignore_errors=True)

    def stop(self, **kwargs):
        return self.client.post("/api/studio/shutdown", json={"identity": server_identity()}, **kwargs)

    def test_idle_shutdown_sets_flag_but_preserves_lock_until_lifespan_exit(self):
        response = self.stop()
        self.assertEqual(response.status_code, 202, response.text)
        self.callback.assert_called_once_with()
        self.assertTrue(self.manager.shutdown_requested)
        self.assertFalse(self.manager.closed)
        self.assertFalse(self.manager.lock.stream.closed)
        with self.assertRaises(BusyError):
            JobManager(self.root)
        self.client.__exit__(None, None, None)
        self.assertTrue(self.manager.closed)
        replacement = JobManager(self.root)
        replacement.close()

    def test_wrong_workspace_backend_or_ui_cannot_stop_server(self):
        for key in ("workspace", "backend", "ui", "application", "interface"):
            with self.subTest(key=key):
                identity = {**server_identity(), key: "other"}
                response = self.client.post("/api/studio/shutdown", json={"identity": identity})
                self.assertEqual(response.status_code, 409)
        self.callback.assert_not_called()
        self.assertFalse(self.manager.shutdown_requested)

    def test_identity_schema_is_strict(self):
        for body in ({}, {"identity": {}, "force": True}, {"identity": {"workspace": 12}}):
            with self.subTest(body=body):
                response = self.client.post("/api/studio/shutdown", json=body)
                self.assertEqual(response.status_code, 422)
        self.callback.assert_not_called()

    def test_missing_uvicorn_callback_refuses_shutdown(self):
        self.app.state.shutdown_callback = None
        self.assertEqual(self.stop().status_code, 409)
        self.assertFalse(self.manager.shutdown_requested)

    def test_active_analysis_refuses_shutdown_without_touching_worker(self):
        worker = Mock()
        self.manager.active = ("test-job", worker)
        self.assertEqual(self.stop().status_code, 409)
        self.callback.assert_not_called()
        worker.terminate_tree.assert_not_called()
        self.assertFalse(self.manager.shutdown_requested)

    def test_active_finishing_refuses_shutdown(self):
        self.manager.finishing_tasks["test-job"] = 1
        self.assertEqual(self.stop().status_code, 409)
        self.callback.assert_not_called()
        self.assertFalse(self.manager.shutdown_requested)

    def test_cross_origin_and_cross_site_cannot_stop_server(self):
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Host": "evil.example:8765"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.stop(headers=headers).status_code, 403)
        self.callback.assert_not_called()

    def test_failed_callback_restores_task_admission(self):
        self.callback.side_effect = RuntimeError("test callback failed")
        self.assertEqual(self.stop().status_code, 500)
        self.assertFalse(self.manager.shutdown_requested)
        self.manager._assert_available()

    def test_stop_blocks_new_mutations_analysis_and_export_but_allows_read_only(self):
        self.assertEqual(self.stop().status_code, 202)
        self.assertEqual(self.client.post("/api/projects", json={"title": "too late"}).status_code, 409)
        self.assertEqual(self.stop().status_code, 409)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        with self.assertRaises(BusyError):
            self.manager._assert_available()
        with self.assertRaisesRegex(RuntimeError, "завершает работу"), \
                patch("app.studio_render.atomic_json") as write:
            submit_render(self.manager, "test-job", [1], {})
        write.assert_not_called()

    def test_uvicorn_main_registers_shutdown_callback_on_the_served_app(self):
        from app import server as server_module
        with patch('uvicorn.Server') as server, patch('uvicorn.Config') as configuration:
            instance = server.return_value
            instance.should_exit = False
            instance.run.side_effect = lambda: server_module.app.state.shutdown_callback()
            server_module.main()
            configuration.assert_called_once_with(server_module.app, host='127.0.0.1',
                                                  port=8765, access_log=False)
            self.assertTrue(instance.should_exit)
            self.assertIsNone(server_module.app.state.shutdown_callback)
