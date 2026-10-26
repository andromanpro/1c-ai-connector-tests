"""1C can briefly hold its log with Windows sharing disabled."""
from pathlib import Path
import tempfile
import unittest
import win32con
import win32file

import verified_yaxunit as runner


class BusyLogTests(unittest.TestCase):
    def test_busy_log_is_retried_while_client_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            log = folder / 'yaxunit-debug.log'
            log.write_text('Зацикливание обработки глобальной ошибки, дальнейшая работа YAxUnit прервана',
                           encoding='utf-8')
            handle = win32file.CreateFile(str(log), win32con.GENERIC_WRITE, 0, None,
                                          win32con.OPEN_EXISTING, 0, None)
            try:
                self.assertIsNone(runner.fatal_client_log(folder))
            finally:
                handle.Close()
            # Reading resumes after the writer releases the file; the error is retained.
            self.assertEqual(runner.fatal_client_log(folder, include_debug=True)['kind'], 'global-error-loop')

    def test_running_monitor_does_not_open_the_active_yaxunit_log(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'yaxunit-debug.log').write_text('diagnostic', encoding='utf-8')
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Active YAxUnit log must not be opened')):
                self.assertIsNone(runner.fatal_client_log(folder))

    def test_unreadable_log_after_client_exit_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            log = folder / 'platform.log'
            log.write_text('diagnostic', encoding='utf-8')
            handle = win32file.CreateFile(str(log), win32con.GENERIC_WRITE, 0, None,
                                          win32con.OPEN_EXISTING, 0, None)
            try:
                with self.assertRaises(PermissionError):
                    runner.fatal_client_log(folder, allow_busy=False)
            finally:
                handle.Close()


if __name__ == '__main__':
    unittest.main()
