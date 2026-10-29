"""Two deterministic MCP databases and negative publication modes, no paid models."""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

PORT = 8874
ID_A = '11111111-1111-1111-1111-111111111111'
ID_B = '22222222-2222-2222-2222-222222222222'


def requires_database_fixture(selection):
    modules = ('Тесты_КИИ_УдаленныеБазыMCP.', 'Тесты_КИИ_ПодключенияКБазам.',
               'Тесты_КИИ_ПраваПодключенийКБазам.', 'Тесты_КИИ_АгентАнализа.Базы_')
    return any(test.startswith(modules) for test in selection)


@contextmanager
def local_database_fixture(enabled=True, port=PORT):
    events = []
    if not enabled:
        yield events
        return

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body=None, headers=None):
            data = b'' if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            scenario = self.path.strip('/').split('/')[0]
            raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            event = {'scenario': scenario, 'path': self.path,
                     'authorization_present': bool(self.headers.get('Authorization'))}
            events.append(event)
            try:
                request = json.loads(raw)
                method = request.get('method')
                params = request.get('params', {})
                event['method'] = method
                event['tool'] = params.get('name')
                event['id_present'] = 'id' in request
                user = 'reader-b' if scenario == 'source-b' else 'reader-a'
                expected = 'Basic ' + base64.b64encode((user + ':123456').encode()).decode()
                accepted = self.headers.get('Authorization') == expected
                event['authorization_accepted'] = accepted
                if scenario != 'fixed' and not accepted:
                    self.reply(401, headers={'WWW-Authenticate': 'Basic realm="test-1c"'})
                    return
                if scenario == 'redirect':
                    self.reply(307, headers={'Location': f'http://127.0.0.1:{self.server.server_port}/redirect-destination'})
                    return
                if scenario == 'forbidden':
                    self.reply(403)
                    return
                if scenario == 'redirect-destination':
                    raise AssertionError('Client followed a credential-bearing redirect')
                if request.get('jsonrpc') != '2.0':
                    raise AssertionError('Client did not send JSON-RPC 2.0')
                if method == 'notifications/initialized':
                    if 'id' in request:
                        raise AssertionError('Initialized notification has an id')
                    self.reply(202)
                    return
                if 'id' not in request:
                    raise AssertionError('Request has no correlation id')
                if method == 'initialize':
                    if params.get('protocolVersion') != '2025-11-25':
                        raise AssertionError('Client requested an unexpected MCP version')
                    result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'database-fixture', 'version': '1'}}
                elif method == 'tools/call':
                    tool = params['name']
                    if tool == 'get_configuration_info':
                        data = {'session_user': 'other-user' if scenario == 'wrong-user' else user,
                                'database_id': ID_B if scenario in ('source-b', 'wrong-id') else ID_A,
                                'connection_protocol': 1, 'configuration_name': scenario,
                                'configuration_version': '1'}
                    elif tool == 'get_object_structure':
                        arguments = params['arguments']
                        event['structure_arguments'] = arguments
                        if scenario not in ('source-a', 'source-b') or arguments.get('name') != 'RemoteOnly':
                            raise AssertionError('Unexpected remote structure request')
                        offset = arguments.get('offset', 0)
                        limit = arguments.get('limit', 20)
                        all_items = [{'name': name, 'synonym': name, 'type': 'Number', 'required': False,
                                      'section': 'attributes', 'path': 'attributes.' + name}
                                     for name in ('RemoteA', 'RemoteB', 'RemoteC')]
                        items = all_items[offset:offset+limit]
                        following = offset + len(items)
                        data = {'canonical_ref': 'Catalog.RemoteOnly', 'type': 'Catalog', 'name': 'RemoteOnly',
                                'synonym': 'Remote only object', 'paged': True, 'section': 'all', 'items': items,
                                'offset': offset, 'limit': limit, 'total_count': len(all_items),
                                'returned_count': len(items), 'next_offset': following, 'has_more': following < len(all_items)}
                    elif tool == 'execute_query':
                        if scenario == 'query-error':
                            diagnostic = {'code': 'query_failed', 'message': 'Поле НетТакогоПоля не найдено',
                                          'correlation_id': '18918918-9189-4189-8189-189189189189'}
                            data = {'error': diagnostic}
                            self.reply(200, {'jsonrpc': '2.0', 'id': request['id'], 'result': {
                                'ok': False, 'tool': tool, 'isError': True, 'structuredContent': data,
                                'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}]}})
                            return
                        if scenario == 'tool-error':
                            self.reply(200, {'jsonrpc': '2.0', 'id': request['id'],
                                             'error': {'code': -32602, 'message': 'sensitive-password'}})
                            return
                        if scenario not in ('source-a', 'source-b'):
                            raise AssertionError('Execution reached a rejected source')
                        event['query_id'] = params['arguments']['query_id']
                        event['query_text'] = params['arguments']['query_text']
                        data = {'columns': [{'name': 'Value', 'type': 'Number'}],
                                'rows': [[22 if scenario == 'source-b' else 11]], 'total': 1, 'truncated': False}
                    else:
                        raise AssertionError('Unexpected tool')
                    result = {'ok': True, 'tool': tool, 'isError': False,
                              'content': [{'type': 'text', 'text': json.dumps(data)}], 'structuredContent': data}
                else:
                    raise AssertionError('Unexpected method')
                self.reply(200, {'jsonrpc': '2.0', 'id': request['id'], 'result': result})
            except Exception as exc:
                event['fixture_error'] = str(exc)
                self.reply(500, {'fixture_error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, name='mcp-database-fixture', daemon=True)
    thread.start()
    try:
        yield events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError('MCP database fixture did not stop normally')


def require_clean_events(events):
    failures = [event for event in events if event.get('fixture_error')
                or event['scenario'] == 'redirect-destination']
    if failures:
        raise RuntimeError('MCP database fixture rejected client protocol: ' + json.dumps(failures))
