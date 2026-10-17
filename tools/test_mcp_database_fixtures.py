import base64
import json
import unittest
import urllib.request
import urllib.error

from mcp_database_fixtures import local_database_fixture, require_clean_events, ID_A, ID_B


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class FixtureTests(unittest.TestCase):
    def request(self, scenario='source-a', user=None, password='123456', method='initialize',
                parameters=None, notification=False):
        payload = {'jsonrpc': '2.0', 'method': method, 'params': parameters or {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'self-test', 'version': '1'}}}
        if not notification:
            payload['id'] = 'own-request'
        headers = {'Content-Type': 'application/json'}
        if user:
            headers['Authorization'] = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        request = urllib.request.Request(
            f'http://127.0.0.1:18874/{scenario}/hs/iikona-mcp/connection',
            data=json.dumps(payload).encode(), headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, dict(response.headers)

    def test_anonymous_and_incorrect_password_are_rejected(self):
        with local_database_fixture(port=18874) as events:
            self.assertEqual(self.request()[0], 401)
            self.assertEqual(self.request(user='reader-a', password='wrong')[0], 401)
        self.assertEqual(len(events), 2)
        require_clean_events(events)

    def test_two_sources_return_different_data_and_stable_ids(self):
        with local_database_fixture(port=18874) as events:
            for source, user, expected, identifier in [('source-a', 'reader-a', 11, ID_A),
                                                      ('source-b', 'reader-b', 22, ID_B)]:
                status, body, _ = self.request(source, user, method='tools/call', parameters={
                    'name': 'get_configuration_info', 'arguments': {}})
                self.assertEqual(status, 200)
                self.assertEqual(body['id'], 'own-request')
                self.assertEqual(body['result']['structuredContent']['database_id'], identifier)
                status, body, _ = self.request(source, user, method='tools/call', parameters={
                    'name': 'execute_query', 'arguments': {'query_id': 'same', 'query_text': 'ВЫБРАТЬ 1'}})
                self.assertEqual(body['result']['structuredContent']['rows'], [[expected]])
        require_clean_events(events)

    def test_notification_has_202_and_no_body(self):
        with local_database_fixture(port=18874) as events:
            status, body, _ = self.request(user='reader-a', method='notifications/initialized', notification=True)
            self.assertEqual((status, body), (202, None))
        require_clean_events(events)

    def test_publication_failure_modes_are_distinct(self):
        with local_database_fixture(port=18874) as events:
            self.assertEqual(self.request('fixed')[0], 200)
            self.assertEqual(self.request('redirect', 'reader-a')[0], 307)
            self.assertEqual(self.request('forbidden', 'reader-a')[0], 403)
        require_clean_events(events)

    def test_events_do_not_capture_credentials(self):
        with local_database_fixture(port=18874) as events:
            self.request(user='reader-a')
        text = json.dumps(events)
        self.assertNotIn('123456', text)
        self.assertNotIn(base64.b64encode(b'reader-a:123456').decode(), text)
        self.assertTrue(events[0]['authorization_accepted'])

    def test_protocol_violations_fail_the_fixture_gate(self):
        with local_database_fixture(port=18874) as events:
            self.assertEqual(self.request(user='reader-a', method='notifications/initialized')[0], 500)
        with self.assertRaisesRegex(RuntimeError, 'correlation|notification'):
            require_clean_events(events)


if __name__ == '__main__':
    unittest.main()
