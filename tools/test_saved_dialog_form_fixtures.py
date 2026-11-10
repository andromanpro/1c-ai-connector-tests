import unittest

from saved_dialog_form_fixtures import validate_actor, MaterialFixtures


class FixtureScope(unittest.TestCase):
    def setUp(self):
        self.config = {'connection': 'Srvr="localhost";Ref="iikona_perf_20261011";'}
        self.actor = {'name': 'K09_bsp_example_forms', 'ib_uid': 'owned-user', 'roles': ['КИИ_БазовыеПрава']}
        self.baseline = {'ib_users': {'existing': {'uid': 'existing-user'}}}

    def test_accepts_its_disposable_limited_actor(self):
        validate_actor(self.config, self.actor, self.baseline)

    def test_refuses_wrong_stand(self):
        with self.assertRaises(RuntimeError):
            validate_actor({'connection': 'Srvr="localhost";Ref="another";'}, self.actor, self.baseline)

    def test_refuses_existing_identity_or_name(self):
        for field, value in [('ib_uid', 'existing-user'), ('name', 'existing')]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                validate_actor(self.config, dict(self.actor, **{field: value}), self.baseline)

    def test_refuses_broad_roles_or_unowned_names(self):
        for change in [{'roles': ['ПолныеПрава']}, {'roles': ['КИИ_ПолныеПрава']},
                       {'roles': ['АдминистраторСистемы']}, {'name': 'other_forms'}]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_actor(self.config, dict(self.actor, **change), self.baseline)

    def test_refuses_unknown_transition_before_accessing_a_connection(self):
        fixture = MaterialFixtures(self.config, self.actor, self.baseline, None)
        with self.assertRaises(RuntimeError):
            fixture.change_pending_state({'dialogue': 'foreign', 'request': 'foreign'}, 'Выполняется')
        with self.assertRaises(RuntimeError):
            fixture.change_pending_state({'dialogue': 'foreign', 'request': 'foreign'}, 'Завершен')

    def test_failed_entry_releases_the_connector(self):
        from unittest.mock import MagicMock, patch
        fixture = MaterialFixtures(self.config, self.actor, self.baseline, None)
        connector = MagicMock()
        connector.Connect.side_effect = RuntimeError('Synthetic connection failure')
        with patch('win32com.client.Dispatch', return_value=connector):
            with self.assertRaises(RuntimeError):
                fixture.__enter__()
        self.assertIsNone(fixture.connector)
        self.assertIsNone(fixture.base)


if __name__ == '__main__':
    unittest.main()
