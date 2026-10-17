"""Validate the model-facing database contract independently of the BSL router."""
import json

PREFIX = 'Доступные базы для инструментов:\n'


def database_reply(payload, scenario, check):
    messages = payload.get('messages', [])
    tools = payload.get('tools', [])
    catalogs = [m['content'][len(PREFIX):].split('\n\n', 1)[0]
                for m in messages if m.get('role') == 'system'
                and isinstance(m.get('content'), str) and m['content'].startswith(PREFIX)]
    check(len(catalogs) == 1, 'one_current_database_catalog')
    catalog = json.loads(catalogs[0])
    check(isinstance(catalog, list), 'database_catalog_array')
    raw = json.dumps(payload, ensure_ascii=False)
    check(not any(value in raw for value in ['reader-a', 'reader-b', '123456', '127.0.0.1:8874']),
          'no_connection_credentials_or_addresses')
    results = [m for m in messages if m.get('role') == 'tool']
    if scenario == 'database-empty':
        check(catalog == [] and not tools, 'empty_selection_has_no_database_tools')
        return completion('DATABASE_EMPTY_OK')
    identifiers = [item['database_id'] for item in catalog]
    pair = scenario in ('database-pair', 'database-pair-masked')
    if pair:
        check(len(identifiers) == 2 and 'local' not in identifiers and len(set(identifiers)) == 2,
              'exactly_two_remote_sources')
        if scenario.endswith('masked'):
            check('database.person@example.org' not in raw, 'database_context_personal_data_masked')
    else:
        check(identifiers == ['local'], 'only_selected_local_database')
    if scenario == 'database-limit' and results:
        check(not tools, 'budget_finalization_has_no_tools')
        result = json.loads(results[-1]['content'])
        check(result['database_id'] == 'local' and result['success'] is False,
              'budget_error_preserves_requested_source')
        return completion('DATABASE_LIMIT_OK')
    check(len(tools) == 4, 'four_database_tools')
    for tool in tools:
        schema = tool['function']['parameters']
        check('database_id' in schema.get('required', []), 'explicit_database_required')
        check(schema['properties']['database_id']['enum'] == identifiers, 'schema_database_allowlist')
    if pair:
        by_name = {item['database_name']: item['database_id'] for item in catalog}
        check(set(by_name) == {'ROUTING_A', 'ROUTING_B'}, 'source_labels')
        ids = [by_name['ROUTING_A'], by_name['ROUTING_B'], by_name['ROUTING_A']]
        if not results:
            calls = []
            for n, identifier in enumerate(ids):
                args = {'database_id': identifier, 'query_id': 'routing-probe',
                        'query_text': 'ВЫБРАТЬ 1 КАК Value', 'limit': 10, 'params': {}}
                calls.append({'id': 'db_pair_' + str(n), 'type': 'function', 'function': {
                    'name': 'execute_query', 'arguments': json.dumps(args, ensure_ascii=False)}})
            reply = completion(None)
            reply['choices'][0]['message']['tool_calls'] = calls
            reply['choices'][0]['finish_reason'] = 'tool_calls'
            return reply
        check(len(results) == 3, 'three_results_for_a_b_a')
        for n, message in enumerate(results):
            result = json.loads(message['content'])
            check(message['tool_call_id'] == 'db_pair_' + str(n), 'pair_call_id')
            check(result['database_id'] == ids[n] and result['success'], 'pair_result_source')
            check(result['data']['rows'][0][0] == [11, 22, 11][n], 'pair_source_value')
        return completion('DATABASE_PAIR_OK')
    if not results:
        return {'id': 'db-local-round-1', 'object': 'chat.completion', 'model': 'fixture-expert-tools',
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': None,
                    'tool_calls': [{'id': 'db_local', 'type': 'function', 'function': {
                        'name': 'get_configuration_info', 'arguments': '{"database_id":"local"}'}}]},
                    'finish_reason': 'tool_calls'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
    result = json.loads(results[-1]['content'])
    check(results[-1]['tool_call_id'] == 'db_local', 'correct_tool_call_id')
    check(result['database_id'] == 'local' and bool(result['database_name']), 'source_attached_to_result')
    check('session_user' not in result['data'], 'session_identity_not_sent_to_model')
    return completion('DATABASE_LOCAL_OK')


def completion(text):
    return {'id': 'db-final', 'object': 'chat.completion', 'model': 'fixture-expert-tools',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 7, 'total_tokens': 27}}
