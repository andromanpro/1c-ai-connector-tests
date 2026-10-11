"""Loopback-only synthetic responses; never forwards requests to real models."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json

@contextmanager
def local_model_fixture():
    events=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            scenario=self.path.strip('/').split('/')[0]
            events.append({'scenario':scenario,'body':payload,'synthetic_header':self.headers.get('X-Iikona-Test',''),'authorization_present':'Authorization' in self.headers})
            count=sum(e['scenario']==scenario for e in events)
            code=200
            result={'id':'synthetic-request','object':'chat.completion','model':'legacy-fixture',
                    'choices':[{'message':{'role':'assistant','content':'Совместимость подтверждена'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10,'cost':0.001}}
            if scenario=='anthropic':result={'id':'synthetic-request','model':'legacy-fixture','content':[{'type':'text','text':'Совместимость подтверждена'}],'stop_reason':'end_turn','usage':{'input_tokens':7,'output_tokens':3}}
            if scenario=='google':result={'candidates':[{'content':{'parts':[{'text':'Совместимость подтверждена'}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':3,'totalTokenCount':10}}
            if scenario=='yandex':result={'result':{'alternatives':[{'message':{'role':'assistant','text':'Совместимость подтверждена'},'status':'ALTERNATIVE_STATUS_FINAL'}],'usage':{'inputTextTokens':'7','completionTokens':'3','totalTokens':'10'},'modelVersion':'legacy-fixture'}}
            if scenario=='error400':code=400;result={'error':{'code':'invalid_request','message':'Synthetic request rejected'}}
            if scenario=='retry429' and count<3:code=429;result={'error':{'code':'rate_limit_exceeded','message':'Synthetic retry'}}
            if scenario=='html502':code=502;result='<html>Bad Gateway</html>'
            if scenario=='badjson':result='{broken-json'
            if scenario=='echo':result['choices'][0]['message']['content']=payload['messages'][-1]['content']
            raw=(result if isinstance(result,str) else json.dumps(result,ensure_ascii=False)).encode('utf-8')
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',8873),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield events
    finally:server.shutdown();server.server_close();thread.join(5)
