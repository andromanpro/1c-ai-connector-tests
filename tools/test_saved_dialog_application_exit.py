import unittest

from check_saved_dialog_forms import exercise_application_exit


class Evidence:
    def __init__(self):
        self.records = {}

    def record(self, name, value):
        self.records[name] = value


class Client:
    def __init__(self, stopped, form='Обработка.КИИ_ТестИИ.Форма.Форма'):
        self.stopped = stopped
        self.form = form
        self.timeouts = []

    def get_context(self, **kwargs):
        return {'form': {'form_name': self.form}}

    def stop_client(self, *, graceful_timeout):
        self.timeouts.append(graceful_timeout)
        return self.stopped


class ApplicationExitTests(unittest.TestCase):
    def test_graceful_exit_is_recorded(self):
        client = Client({'ok': True, 'shutdown': 'graceful'})
        evidence = Evidence()
        result = exercise_application_exit(client, evidence)
        self.assertTrue(result['dialogue_open_on_exit'])
        self.assertEqual(client.timeouts, [30])
        self.assertEqual(evidence.records['application-exit-result'], client.stopped)

    def test_forced_exit_is_never_a_success(self):
        client = Client({'ok': True, 'shutdown': 'forced', 'shutdown_reason': 'close_request_failed'})
        evidence = Evidence()
        with self.assertRaisesRegex(AssertionError, 'did not close gracefully'):
            exercise_application_exit(client, evidence)
        self.assertEqual(evidence.records['application-exit-result']['shutdown'], 'forced')

    def test_already_exited_does_not_prove_the_open_dialogue_path(self):
        with self.assertRaisesRegex(AssertionError, 'did not close gracefully'):
            exercise_application_exit(Client({'ok': True, 'shutdown': 'already_exited'}), Evidence())

    def test_failed_shutdown_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'did not close gracefully'):
            exercise_application_exit(Client({'ok': False, 'shutdown': 'graceful'}), Evidence())

    def test_wrong_form_is_rejected_before_closing(self):
        client = Client({'ok': True, 'shutdown': 'graceful'}, form='ДругаяФорма')
        with self.assertRaisesRegex(AssertionError, 'must remain open'):
            exercise_application_exit(client, Evidence())
        self.assertEqual(client.timeouts, [])


if __name__ == '__main__':
    unittest.main()
