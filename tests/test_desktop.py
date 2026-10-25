"""App-window lifecycle tests without opening native windows in CI."""
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_app


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, function):
        self.handlers.append(function)
        return self


class DesktopTests(unittest.TestCase):
    def fixture(self):
        window = SimpleNamespace(events=SimpleNamespace(closing=Event()), create_confirmation_dialog=Mock())
        webview = SimpleNamespace(settings={}, create_window=Mock(return_value=window), start=Mock())
        server = Mock(server_port=5049)
        return window, webview, server

    def test_window_uses_local_server_and_closes_server_on_exit(self):
        window, webview, server = self.fixture()
        with patch.object(desktop_app, 'make_server', return_value=server):
            self.assertEqual(desktop_app.main(webview), 0)
        self.assertEqual(webview.create_window.call_args.args[1], 'http://127.0.0.1:5049')
        self.assertTrue(webview.create_window.call_args.kwargs['confirm_close'])
        webview.start.assert_called_once()
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()

    def test_failed_renderer_does_not_leave_server_running(self):
        _, webview, server = self.fixture()
        webview.start.side_effect = RuntimeError('renderer unavailable')
        with patch.object(desktop_app, 'make_server', return_value=server), \
             patch.object(desktop_app, 'report_startup_error'):
            self.assertEqual(desktop_app.main(webview), 1)
        server.shutdown.assert_called_once()

    def test_active_calculation_prevents_window_close(self):
        window, webview, server = self.fixture()
        def attempt_close(**kwargs):
            self.assertFalse(window.events.closing.handlers[0]())
        webview.start.side_effect = attempt_close
        with patch.object(desktop_app, 'make_server', return_value=server), \
             patch.dict(desktop_app.SERVER_STATE, {'active_calculations': 1}):
            self.assertEqual(desktop_app.main(webview), 0)
        window.create_confirmation_dialog.assert_called_once()


if __name__ == '__main__':
    unittest.main()
