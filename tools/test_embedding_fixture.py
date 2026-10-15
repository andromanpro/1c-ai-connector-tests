import json
import unittest
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError, URLError
from http.client import RemoteDisconnected
from legacy_model_fixture import local_model_fixture


class EmbeddingFixtureTests(unittest.TestCase):
    def test_packet_order_and_telemetry(self):
        opener=build_opener(ProxyHandler({}))
        with local_model_fixture() as events:
            payload={'model':'fixture-local-unique','input':['k07-vector:8','k07-vector:3']}
            req=Request('http://127.0.0.1:8873/emb-reverse',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with opener.open(req,timeout=3) as r: response=json.load(r)
            self.assertEqual([(x['index'],x['embedding']) for x in response['data']],[(1,[3,1,0]),(0,[8,1,0])])
            with opener.open('http://127.0.0.1:8873/embedding-events/fixture-local-unique',timeout=3) as r: stats=json.load(r)
            self.assertEqual(stats,{'requests':1,'sizes':[2],'array_inputs':[True],
                                    'text_lengths':[12,12],'total_lengths':[24]})
            self.assertEqual(len(events),1)

    def test_malformed_packets_are_actually_malformed(self):
        opener=build_opener(ProxyHandler({}))
        with local_model_fixture():
            results={}
            for mode in ['duplicate','missing','extra','no-index','fractional','negative','out-of-range','bool-index','bad-coordinate','bool-coordinate','empty-vector','mixed-size','zero-vector','not-array']:
                req=Request('http://127.0.0.1:8873/emb-'+mode,data=b'{"model":"fixture-errors","input":["a","b"]}',headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=3) as r: results[mode]=json.load(r)['data']
            self.assertEqual([x['index'] for x in results['duplicate']],[0,0])
            self.assertEqual(len(results['missing']),1)
            self.assertEqual(len(results['extra']),3)
            self.assertNotIn('index',results['no-index'][-1])
            self.assertEqual(results['fractional'][-1]['index'],0.5)
            self.assertEqual(results['negative'][-1]['index'],-1)
            self.assertEqual(results['out-of-range'][-1]['index'],2)
            self.assertIs(type(results['bool-index'][-1]['index']),bool)
            self.assertIs(type(results['bad-coordinate'][-1]['embedding'][1]),str)
            self.assertIs(type(results['bool-coordinate'][-1]['embedding'][1]),bool)
            self.assertEqual(results['empty-vector'][-1]['embedding'],[])
            self.assertEqual(len(results['mixed-size'][-1]['embedding']),2)
            self.assertEqual(results['zero-vector'][-1]['embedding'],[0,0,0])
            self.assertIsInstance(results['not-array'],dict)

    def test_unknown_outcomes_do_not_generate_fixture_retries(self):
        opener=build_opener(ProxyHandler({}))
        with local_model_fixture() as events:
            for mode in ['http500','disconnect']:
                req=Request('http://127.0.0.1:8873/emb-'+mode,data=b'{"model":"fixture-unknown","input":["a","b"]}',headers={'Content-Type':'application/json'})
                try:
                    response=opener.open(req,timeout=3)
                except HTTPError as error:
                    self.assertEqual(error.code,500)
                    error.close()
                except (URLError,RemoteDisconnected):
                    self.assertEqual(mode,'disconnect')
                else:
                    response.close()
                    self.fail('Expected an error for '+mode)
            self.assertEqual(len(events),2)


if __name__=='__main__': unittest.main()
