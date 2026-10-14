import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from app import launcher
from app.studio_identity import server_identity


class LauncherTests(unittest.TestCase):
    def setUp(self):
        probe = patch.object(launcher, 'instance_released', return_value=True)
        self.instance_released = probe.start()
        self.addCleanup(probe.stop)

    def test_start_refuses_a_closed_listener_with_a_held_instance_lock(self):
        self.instance_released.return_value = False
        with patch.object(launcher, 'studio_status', return_value='missing'), \
                patch('app.server.main') as server:
            with self.assertRaises(SystemExit) as error:
                launcher.main()
        self.assertEqual(error.exception.code, 2)
        server.assert_not_called()

    def test_stop_waits_for_lock_release_after_listener_closes(self):
        self.instance_released.side_effect = [False, True]
        with patch.object(launcher, 'studio_status', side_effect=['current', 'missing', 'missing']), \
                patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher.time, 'sleep') as sleep:
            factory.return_value.open.return_value.__enter__.return_value.status = 202
            self.assertEqual(launcher.stop_studio(), 0)
        sleep.assert_called_once_with(0.25)

    def test_missing_listener_with_held_lock_is_not_reported_as_stopped(self):
        self.instance_released.return_value = False
        with patch.object(launcher, 'studio_status', return_value='missing'):
            self.assertEqual(launcher.stop_studio(), 2)

    def test_missing_server_starts_server_and_schedules_browser_after_readiness(self):
        with patch.object(launcher, 'studio_status', return_value='missing'), \
                patch.object(launcher.threading, 'Thread') as thread, \
                patch('app.server.main') as server, \
                patch.object(launcher.webbrowser, 'open') as browser:
            launcher.main()
        thread.assert_called_once_with(target=launcher.open_when_ready, daemon=True)
        thread.return_value.start.assert_called_once_with()
        server.assert_called_once_with()
        browser.assert_not_called()

    def test_existing_current_studio_is_reused(self):
        with patch.object(launcher, 'studio_status', return_value='current'), \
                patch.object(launcher.webbrowser, 'open') as browser, \
                patch('app.server.main') as server:
            launcher.main()
        browser.assert_called_once_with(launcher.studio_url())
        server.assert_not_called()

    def test_outdated_studio_must_not_open_or_start_competing_server(self):
        with patch.object(launcher, 'studio_status', return_value='occupied'), \
                patch.object(launcher.webbrowser, 'open') as browser, \
                patch('app.server.main') as server:
            with self.assertRaises(SystemExit) as error:
                launcher.main()
        self.assertEqual(error.exception.code, 2)
        server.assert_not_called()
        browser.assert_not_called()

    def test_browser_waits_for_verified_studio(self):
        with patch.object(launcher, 'studio_available', side_effect=[False, False, True]), \
                patch.object(launcher.time, 'sleep') as sleep, \
                patch.object(launcher.webbrowser, 'open') as browser:
            launcher.open_when_ready()
        self.assertEqual(sleep.call_count, 2)
        browser.assert_called_once_with(launcher.studio_url())

    def test_readiness_timeout_counts_time_spent_in_http_requests(self):
        clock = [0.0]

        def slow_probe():
            clock[0] += 12
            return False

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(launcher, 'studio_available', side_effect=slow_probe) as probe, \
                patch.object(launcher.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(launcher.time, 'sleep', side_effect=sleep), \
                patch.object(launcher.webbrowser, 'open') as browser:
            launcher.open_when_ready()
        self.assertEqual(probe.call_count, 3)
        browser.assert_not_called()

    def test_server_startup_exception_is_written_to_session_logs(self):
        with patch.object(launcher, 'studio_status', return_value='missing'), \
                patch.object(launcher.threading, 'Thread'), \
                patch('app.server.main', side_effect=RuntimeError('startup-test-error')), \
                patch('logging.Logger.exception') as logged:
            with self.assertRaisesRegex(RuntimeError, 'startup-test-error'):
                launcher.main()
        logged.assert_called_once()

    def test_uvicorn_startup_exit_is_written_to_session_logs(self):
        with patch.object(launcher, 'studio_status', return_value='missing'), \
                patch.object(launcher.threading, 'Thread'), \
                patch('app.server.main', side_effect=SystemExit(1)), \
                patch('logging.Logger.exception') as logged:
            with self.assertRaises(SystemExit):
                launcher.main()
        logged.assert_called_once()

    def test_stop_of_missing_or_unrelated_server_never_sends_shutdown(self):
        for status, result in [('missing', 0), ('occupied', 2)]:
            with self.subTest(status=status), \
                    patch.object(launcher, 'studio_status', return_value=status), \
                    patch.object(launcher.urllib.request, 'build_opener') as opener:
                self.assertEqual(launcher.stop_studio(), result)
                opener.assert_not_called()

    def test_stop_sends_exact_identity_and_waits_until_server_disappears(self):
        with patch.object(launcher, 'studio_status', side_effect=['current', 'current', 'missing']), \
                patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher.time, 'sleep') as sleep:
            factory.return_value.open.return_value.__enter__.return_value.status = 202
            self.assertEqual(launcher.stop_studio(), 0)
        request = factory.return_value.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.full_url, launcher.URL + '/api/studio/shutdown')
        self.assertEqual(json.loads(request.data), {'identity': server_identity()})
        sleep.assert_called_once_with(0.25)

    def test_stop_of_busy_server_preserves_work(self):
        error = urllib.error.HTTPError(launcher.URL, 409, 'Busy', None,
            io.BytesIO(b'{"detail":"Processing is active"}'))
        with patch.object(launcher, 'studio_status', return_value='current'), \
                patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher.time, 'sleep') as sleep:
            factory.return_value.open.side_effect = error
            self.assertEqual(launcher.stop_studio(), 2)
        sleep.assert_not_called()

    def test_stop_reports_timeout_without_killing_processes(self):
        with patch.object(launcher, 'studio_status', return_value='current'), \
                patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher.time, 'monotonic', side_effect=[0, 0, 15]), \
                patch.object(launcher.time, 'sleep'):
            factory.return_value.open.return_value.__enter__.return_value.status = 202
            self.assertEqual(launcher.stop_studio(), 2)

    def test_http_identity_matching_current_workspace_is_accepted(self):
        payload = server_identity()
        self.assertIsNotNone(payload['backend'])
        with patch.object(launcher.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value = io.BytesIO(
                json.dumps(payload).encode('utf-8'))
            with patch.object(launcher, 'port_occupied') as port:
                actual = launcher.studio_status()
        self.assertEqual(actual, 'current' if payload['ui'] is not None else 'occupied')
        port.assert_not_called()

    def test_same_health_but_old_identity_is_not_accepted(self):
        payload = server_identity()
        payload['backend'] = 'stale-code-version'
        with patch.object(launcher.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value = io.BytesIO(
                json.dumps(payload).encode('utf-8'))
            self.assertEqual(launcher.studio_status(), 'occupied')

    def test_legacy_health_endpoint_does_not_bypass_identity_validation(self):
        legacy_error = urllib.error.HTTPError(
            launcher.IDENTITY_URL, 404, 'No route', None, None)
        with patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher, 'port_occupied', return_value=True):
            factory.return_value.open.side_effect = legacy_error
            self.assertEqual(launcher.studio_status(), 'occupied')

    def test_no_server_or_listener_means_missing(self):
        with patch.object(launcher.urllib.request, 'build_opener') as factory, \
                patch.object(launcher, 'port_occupied', return_value=False):
            factory.return_value.open.side_effect = ConnectionRefusedError()
            self.assertEqual(launcher.studio_status(), 'missing')

    def test_browser_uses_versioned_studio_url_not_legacy_root(self):
        self.assertTrue(launcher.studio_url().startswith(
            'http://127.0.0.1:8765/studio-edition.html?v='))
