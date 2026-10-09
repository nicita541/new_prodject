import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from app import launcher
from app.studio_identity import server_identity


class LauncherTests(unittest.TestCase):
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
