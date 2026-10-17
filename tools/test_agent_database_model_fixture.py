import copy
import json
import unittest

from agent_database_model_fixture import PREFIX, database_reply


def check(value, label):
    if not value:
        raise AssertionError(label)


def payload(ids=('local',)):
    catalog = [{'database_id': key, 'database_name': name} for key, name in
               zip(ids, ['Текущая база'] if ids == ('local',) else ['ROUTING_A', 'ROUTING_B'])]
    schema = {'properties': {'database_id': {'enum': list(ids)}}, 'required': ['database_id']}
    return {'messages': [{'role': 'system', 'content': PREFIX + json.dumps(catalog) + '\n\ninstruction'}],
            'tools': [{'function': {'parameters': copy.deepcopy(schema)}} for _ in range(4)]}


class ContractTests(unittest.TestCase):
    def test_valid_local_and_result(self):
        body = payload()
        reply = database_reply(body, 'database-local', check)
        self.assertEqual(reply['choices'][0]['message']['tool_calls'][0]['function']['name'],
                         'get_configuration_info')
        body['messages'].append({'role': 'tool', 'tool_call_id': 'db_local', 'content': json.dumps({
            'database_id': 'local', 'database_name': 'Current', 'data': {'configuration_name': 'Test'}})})
        self.assertEqual(database_reply(body, 'database-local', check)['choices'][0]['message']['content'],
                         'DATABASE_LOCAL_OK')

    def test_missing_catalog_is_red(self):
        body = payload(); body['messages'] = []
        with self.assertRaisesRegex(AssertionError, 'one_current_database_catalog'):
            database_reply(body, 'database-local', check)

    def test_missing_required_id_is_red(self):
        body = payload(); body['tools'][0]['function']['parameters']['required'] = []
        with self.assertRaisesRegex(AssertionError, 'explicit_database_required'):
            database_reply(body, 'database-local', check)

    def test_extra_database_in_schema_is_red(self):
        body = payload(); body['tools'][0]['function']['parameters']['properties']['database_id']['enum'].append('extra')
        with self.assertRaisesRegex(AssertionError, 'schema_database_allowlist'):
            database_reply(body, 'database-local', check)

    def test_empty_selection_has_no_tools(self):
        body = payload(())
        with self.assertRaisesRegex(AssertionError, 'empty_selection_has_no_database_tools'):
            database_reply(body, 'database-empty', check)
        body['tools'] = []
        self.assertEqual(database_reply(body, 'database-empty', check)['choices'][0]['message']['content'],
                         'DATABASE_EMPTY_OK')

    def test_credentials_and_session_identity_are_red(self):
        body = payload(); body['messages'].append({'role': 'user', 'content': 'reader-a'})
        with self.assertRaisesRegex(AssertionError, 'no_connection_credentials_or_addresses'):
            database_reply(body, 'database-local', check)
        body['messages'][-1] = {'role': 'tool', 'tool_call_id': 'db_local', 'content': json.dumps({
            'database_id': 'local', 'database_name': 'Current', 'data': {'session_user': 'test-runner'}})}
        with self.assertRaisesRegex(AssertionError, 'session_identity_not_sent_to_model'):
            database_reply(body, 'database-local', check)

    def test_pair_rejects_swapped_source_values(self):
        body = payload(('a', 'b'))
        reply = database_reply(body, 'database-pair', check)
        self.assertEqual(len(reply['choices'][0]['message']['tool_calls']), 3)
        for n, (key, value) in enumerate([('a', 11), ('b', 22), ('a', 11)]):
            body['messages'].append({'role': 'tool', 'tool_call_id': 'db_pair_' + str(n),
                'content': json.dumps({'database_id': key, 'success': True, 'data': {'rows': [[value]]}})})
        self.assertEqual(database_reply(body, 'database-pair', check)['choices'][0]['message']['content'],
                         'DATABASE_PAIR_OK')
        body['messages'][-1]['content'] = json.dumps({'database_id': 'a', 'success': True, 'data': {'rows': [[22]]}})
        with self.assertRaisesRegex(AssertionError, 'pair_source_value'):
            database_reply(body, 'database-pair', check)


if __name__ == '__main__':
    unittest.main()
