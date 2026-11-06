import unittest
from owned_forms_cleanup import candidate
from runtime_session_guard import ZERO
from runtime_session_guard import ACTIVITY
from owned_forms_cleanup import review_candidate
from datetime import datetime


class OwnedFormsCleanup(unittest.TestCase):
    def setUp(self):
        self.actor = {'name': 'K09_bsp_synthetic_forms', 'ib_uid': 'new-owner'}
        self.launched = {'pid': 12345}
        self.baseline = {'ib_users': {'existing': {'uid': 'existing-owner'}}}
        self.row = {'session': 'own-session', 'user-name': self.actor['name'], 'infobase': 'expected-base',
                    'host': 'testhost', 'app-id': '1CV8C', 'connection': ZERO, 'process': ZERO, 'hibernate': 'yes',
                    'current-service-name': '', **dict.fromkeys(['duration-current', 'duration-current-dbms',
                    'memory-current', 'read-current', 'write-current', 'cpu-time-current'], '0')}

    def check(self, rows=None, alive=False):
        return candidate([self.row] if rows is None else rows, self.actor, self.launched,
                         self.baseline, 'expected-base', 'testhost', alive)

    def test_accepts_exact_disconnected_disposable_session(self):
        self.assertEqual(self.check(), self.row)

    def test_does_not_select_other_users(self):
        self.assertIsNone(self.check([{**self.row, 'user-name': 'existing'}]))

    def test_refuses_live_client(self):
        with self.assertRaises(RuntimeError):
            self.check(alive=True)

    def test_refuses_preexisting_actor(self):
        self.actor['ib_uid'] = 'existing-owner'
        with self.assertRaises(RuntimeError):
            self.check()

    def test_refuses_connected_active_wrong_or_ambiguous_session(self):
        for patch in [{'connection': 'live'}, {'process': 'live'}, {'hibernate': 'no'},
                      {'cpu-time-current': '1'}, {'infobase': 'other-base'}, {'host': 'other-host'},
                      {'app-id': 'Designer'}]:
            with self.subTest(patch=patch), self.assertRaises(RuntimeError):
                self.check([{**self.row, **patch}])
        with self.assertRaises(RuntimeError):
            self.check([self.row, self.row])


class ClosedReviewCleanup(unittest.TestCase):
    def setUp(self):
        self.launched = {'pid': 12345}
        self.handoff = {'ready': True, 'automation_disconnected': True, 'pid': 12345}
        self.recorded = datetime(2026, 11, 1, 13, 21, 54)
        self.row = {'session': 'owned-review', 'user-name': 'review-owner', 'infobase': 'expected-base',
                    'host': 'testhost', 'app-id': '1CV8C', 'started-at': '2026-11-01T13:21:50',
                    'connection': ZERO, 'process': ZERO, 'hibernate': 'yes',
                    'current-service-name': '', **dict.fromkeys(ACTIVITY, '0')}

    def check(self, rows=None, alive=False, closed=True):
        return review_candidate([self.row] if rows is None else rows, self.launched, self.handoff,
            'review-owner', 'expected-base', 'testhost', alive, self.recorded, closed)

    def test_accepts_the_stopped_handed_off_preview(self):
        self.assertEqual(self.check(), self.row)

    def test_requires_explicit_closure_and_absent_process(self):
        for kwargs in [{'alive': True}, {'closed': False}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                self.check(**kwargs)

    def test_requires_matching_disconnected_handoff(self):
        for field, value in [('ready', False), ('automation_disconnected', False), ('pid', 1)]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                review_candidate([self.row], self.launched,
                    {**self.handoff, field: value}, 'review-owner', 'expected-base', 'testhost',
                    False, self.recorded, True)

    def test_never_selects_another_user_or_launch_time(self):
        for patch in [{'user-name': 'another'}, {'app-id': 'Designer'},
                      {'started-at': '2026-11-01T12:21:50'}, {'started-at': '2026-11-01T13:22:00'}]:
            with self.subTest(patch=patch):
                self.assertIsNone(self.check([{**self.row, **patch}]))

    def test_refuses_wrong_target_connected_active_or_ambiguous(self):
        patches = [{'infobase': 'another'}, {'host': 'another'}, {'connection': 'connected'},
                   {'process': 'running'}, {'hibernate': 'no'}, {'current-service-name': 'operation'}]
        patches.extend({key: '1'} for key in ACTIVITY)
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(RuntimeError):
                self.check([{**self.row, **patch}])
        with self.assertRaises(RuntimeError):
            self.check([self.row, self.row])


class FailedLaunchOwnership(unittest.TestCase):
    def test_failed_launch_keeps_its_isolated_process(self):
        from owned_forms_cleanup import failed_launch_result
        value = {'ok': False, 'pid': 123, 'desktop': 'isolated', 'client_stopped': True}
        self.assertEqual(failed_launch_result('launch_client', value), value)

    def test_other_actions_or_missing_process_do_not_create_ownership(self):
        from owned_forms_cleanup import failed_launch_result
        for action, value in [('other', {'ok': False, 'pid': 123}),
                              ('launch_client', {'ok': False}),
                              ('launch_client', {'ok': False, 'pid': True}),
                              ('launch_client', {'ok': False, 'pid': -1})]:
            with self.subTest(action=action, value=value):
                self.assertIsNone(failed_launch_result(action, value))

    def test_saved_timeout_can_recover_without_successful_launch_file(self):
        from owned_forms_cleanup import saved_launch
        from pathlib import Path
        import tempfile, json
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            value = {'ok': False, 'pid': 123, 'desktop': 'isolated', 'client_stopped': True}
            (run/'result.json').write_text(json.dumps({'error_type': 'ActionError',
                'error': 'launch_client: Test-client startup deadline expired.'}), encoding='utf-8')
            (run/'action-error.json').write_text(json.dumps(value), encoding='utf-8')
            self.assertEqual(saved_launch(run), value)
            (run/'result.json').write_text(json.dumps({'error_type': 'ActionError',
                'error': 'other_action: failed'}), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                saved_launch(run)

    def test_visible_desktop_is_not_accepted_for_failed_launch_cleanup(self):
        from owned_forms_cleanup import failed_launch_result
        with self.assertRaises(RuntimeError):
            failed_launch_result('launch_client', {'ok': False, 'pid': 123, 'desktop': 'default'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
