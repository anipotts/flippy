"""No real signals or native input: assert graceful shutdown routing."""
import signal
import unittest
from unittest.mock import Mock, patch

from flippy.runtime import install_shutdown_handlers


class TestShutdown(unittest.TestCase):
    def test_signals_schedule_one_main_thread_shutdown(self):
        installed = {}
        queued = []
        quit_app = Mock()
        with patch('flippy.runtime.signal.signal', side_effect=lambda sig, fn: installed.update({sig:fn})), \
                patch('flippy.runtime.signal.getsignal', return_value='previous'):
            restore = install_shutdown_handlers(quit_app, queued.append)
            installed[signal.SIGTERM](signal.SIGTERM, None)
            installed[signal.SIGHUP](signal.SIGHUP, None)
            installed[signal.SIGINT](signal.SIGINT, None)
            quit_app.assert_not_called()
            self.assertEqual(len(queued), 1)
            self.assertFalse(queued[0]())
            quit_app.assert_called_once()
            restore()
            self.assertEqual(set(installed.values()), {'previous'})
