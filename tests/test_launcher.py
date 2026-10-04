import unittest
from unittest.mock import patch

from app import launcher


class LauncherTests(unittest.TestCase):
    def test_missing_server_starts_server_and_schedules_browser_after_readiness(self):
        with patch.object(launcher, 'studio_available', return_value=False), \
                patch.object(launcher.threading, 'Thread') as thread, \
                patch('app.server.main') as server, \
                patch.object(launcher.webbrowser, 'open') as browser:
            launcher.main()
        thread.assert_called_once_with(target=launcher.open_when_ready, daemon=True)
        thread.return_value.start.assert_called_once_with()
        server.assert_called_once_with()
        browser.assert_not_called()

    def test_existing_studio_is_opened_without_launching_another_server(self):
        with patch.object(launcher, 'studio_available', return_value=True), \
                patch.object(launcher.webbrowser, 'open') as browser, \
                patch('app.server.main') as server:
            launcher.main()
        browser.assert_called_once_with(launcher.URL)
        server.assert_not_called()

    def test_browser_waits_until_studio_responds(self):
        with patch.object(launcher, 'studio_available', side_effect=[False, False, True]), \
                patch.object(launcher.time, 'sleep') as sleep, \
                patch.object(launcher.webbrowser, 'open') as browser:
            launcher.open_when_ready()
        self.assertEqual(sleep.call_count, 2)
        browser.assert_called_once_with(launcher.URL)
