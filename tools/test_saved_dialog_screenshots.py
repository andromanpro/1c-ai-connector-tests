import unittest
from unittest.mock import Mock, patch
from check_saved_dialog_forms import capture_screenshot, ActionError


def changed():
    return ActionError('get_screenshot', {'ok': False, 'code': 'screenshot_window_changed'})


class ScreenshotTests(unittest.TestCase):
    @patch('time.sleep')
    def test_window_transition_retries_only_capture(self, sleep):
        client = Mock()
        expected = object()
        client.get_screenshot.side_effect = [changed(), expected]
        self.assertIs(capture_screenshot(client), expected)
        self.assertEqual(client.get_screenshot.call_count, 2)
        self.assertEqual(client.method_calls, [unittest.mock.call.get_screenshot(), unittest.mock.call.get_screenshot()])

    @patch('time.sleep')
    def test_permanent_failure_is_not_retried(self, sleep):
        client = Mock()
        client.get_screenshot.side_effect = ActionError('get_screenshot', {'ok': False, 'code': 'connection_lost'})
        with self.assertRaises(ActionError):
            capture_screenshot(client)
        self.assertEqual(client.get_screenshot.call_count, 1)

    @patch('time.sleep')
    def test_unstable_window_has_bounded_attempts(self, sleep):
        client = Mock()
        client.get_screenshot.side_effect = changed()
        with self.assertRaises(ActionError):
            capture_screenshot(client)
        self.assertEqual(client.get_screenshot.call_count, 4)


if __name__ == '__main__':
    unittest.main()
