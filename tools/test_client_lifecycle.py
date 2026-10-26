"""Fatal start and a failed normal close must have a bounded terminal outcome."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import verified_yaxunit as runner


class LifecycleTests(unittest.TestCase):
    def test_normal_exit_does_not_request_close(self):
        process = Mock(poll=Mock(return_value=0), returncode=0, pid=321)
        close = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = runner.wait_for_client(process, Path(directory), 10, close)
        self.assertEqual(result['state'], 'exited')
        self.assertFalse(result['normal_close_requested'])
        close.assert_not_called()

    def test_real_global_error_requests_close_and_returns_attention_if_stuck(self):
        process = Mock(poll=Mock(return_value=None), pid=321)
        close = Mock(return_value=0)
        ticks = iter([0, 0, 1, 2, 3])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'platform.log').write_text(
                'Зацикливание обработки глобальной ошибки, дальнейшая работа YAxUnit прервана',
                encoding='utf-8')
            result = runner.wait_for_client(process, folder, 10, close, close_grace_s=2,
                                            clock=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(result['initialization_error']['kind'], 'global-error-loop')
        self.assertEqual(result['close_windows'], 0)
        close.assert_called_once_with(321)
        process.wait.assert_not_called()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_timeout_stays_a_failure_even_if_normal_close_succeeds(self):
        process = Mock(poll=Mock(side_effect=[None, None, 0]), returncode=0, pid=321)
        close = Mock(return_value=1)
        ticks = iter([0, 11, 12, 13])
        with tempfile.TemporaryDirectory() as directory:
            result = runner.wait_for_client(process, Path(directory), 10, close,
                                            clock=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(result['state'], 'exited')
        self.assertTrue(result['normal_close_requested'])
        self.assertEqual(result['failure_reason'], 'timeout')
        close.assert_called_once_with(321)


if __name__ == '__main__':
    unittest.main()
