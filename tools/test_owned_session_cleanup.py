"""Ownership and fail-closed checks for delayed removal of a normally closed client."""
import unittest
from unittest.mock import Mock, patch

import verified_yaxunit as runner
from verification_receipt import VerificationError


class OwnedSessionCleanupTests(unittest.TestCase):
    def test_does_not_accept_a_live_client(self):
        with patch.object(runner, "idle") as idle:
            with self.assertRaises(VerificationError):
                runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=None)), False)
            idle.assert_not_called()

    def test_does_not_accept_abnormal_exit(self):
        with patch.object(runner, "idle") as idle:
            with self.assertRaises(VerificationError):
                runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=1)), False)
            idle.assert_not_called()

    def test_does_not_accept_requested_close(self):
        with patch.object(runner, "idle") as idle:
            with self.assertRaises(VerificationError):
                runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=0)), True)
            idle.assert_not_called()

    def test_rechecks_sessions_instead_of_ignoring_them(self):
        expected = {"connected_sessions": 0}
        with patch.object(runner, "idle", side_effect=[VerificationError("Target has an unknown session"), expected]) as idle:
            with patch.object(runner.time, "sleep") as sleep:
                self.assertEqual(runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=0)), False), expected)
                self.assertEqual(idle.call_count, 2)
                sleep.assert_called_once_with(2)

    def test_keeps_unknown_sessions_a_failure_after_timeout(self):
        with patch.object(runner, "idle", side_effect=VerificationError("Target has an unknown session")):
            with patch.object(runner.time, "monotonic", side_effect=[0, 100]):
                with self.assertRaisesRegex(VerificationError, "unknown session"):
                    runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=0)), False)

    def test_does_not_retry_an_unrelated_failure(self):
        with patch.object(runner, "idle", side_effect=VerificationError("Cannot verify target sessions")) as idle:
            with self.assertRaisesRegex(VerificationError, "Cannot verify"):
                runner.wait_for_owned_client_cleanup({}, Mock(poll=Mock(return_value=0)), False)
            idle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
