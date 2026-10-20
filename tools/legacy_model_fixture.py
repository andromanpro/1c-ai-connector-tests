"""Loopback-only synthetic responses; never forwards requests to real models."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
import uuid
import re
import socket

@contextmanager
def local_model_fixture():
    events=[]
    sessions={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            scenario=self.path.strip('/').split('/')[0]
            events.append({'scenario':scenario,'body':payload,'synthetic_header':self.headers.get('X-Iikona-Test',''),'authorization_present':'Authorization' in self.headers})
            if scenario.startswith('emb-'):
                mode=scenario[4:]
                texts=payload.get('input')
                texts=texts if isinstance(texts,list) else [texts]
                data=[]
                for i,value in enumerate(texts):
                    match=re.search(r'k07-vector:(\d+)',value or '')
                    number=int(match.group(1)) if match else i+1
                    data.append({'object':'embedding','index':i,'embedding':[number,1,0]})
                if mode=='reverse': data.reverse()
                if mode=='duplicate' and len(data)>1: data[-1]['index']=0
                if mode=='missing': data=data[:-1]
                if mode=='extra': data.append({'index':len(data),'embedding':[1,1,0]})
                if mode=='no-index': data[-1].pop('index')
                if mode=='fractional': data[-1]['index']=0.5
                if mode=='negative': data[-1]['index']=-1
                if mode=='out-of-range': data[-1]['index']=len(texts)
                if mode=='bool-index': data[-1]['index']=True
                if mode=='bad-coordinate': data[-1]['embedding']=[1,'x',0]
                if mode=='bool-coordinate': data[-1]['embedding']=[1,True,0]
                if mode=='empty-vector': data[-1]['embedding']=[]
                if mode=='mixed-size': data[-1]['embedding']=[1,1]
                if mode=='zero-vector': data[-1]['embedding']=[0,0,0]
                if mode=='not-array': data={'index':0,'embedding':[1,1,0]}
                if mode=='disconnect':
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close();self.close_connection=True;return
                code=500 if mode=='http500' else 200
                result={'data':data,'usage':{'prompt_tokens':len(texts),'total_tokens':len(texts)}}
                if code==500: result={'error':{'message':'synthetic upstream failure'}}
                raw=json.dumps(result,ensure_ascii=False).encode('utf-8')
                self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            if scenario.startswith('mcp'):
                method=payload.get('method');sid=self.headers.get('Mcp-Session-Id')
                code=200;headers={};result=None
                if self.headers.get('Authorization')!='Bearer synthetic-mcp-token' or scenario=='mcp-denied':
                    code=401;result={'error':'fixture unauthorized'}
                elif method=='initialize':
                    assert payload['params']['protocolVersion']=='2025-06-18'
                    assert payload['params']['clientInfo']['name']=='iikona'
                    sid=uuid.uuid4().hex;sessions[sid]=False;headers['Mcp-Session-Id']=sid
                    result={'jsonrpc':'2.0','id':payload['id'],'result':{'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'synthetic MCP','version':'1'}}}
                elif sid not in sessions or self.headers.get('MCP-Protocol-Version')!='2025-06-18':
                    code=400;result={'error':'fixture session or protocol missing'}
                elif method=='notifications/initialized':
                    assert 'id' not in payload;sessions[sid]=True;code=202
                elif method=='tools/call' and sessions[sid]:
                    args=payload['params']['arguments'];name=payload['params']['name']
                    if name=='get_diagnostics':
                        expected='ИИКона_разработки.ИИКона/src/CommonModules/КИИ_МониторингОшибокРегистры/Module.bsl'
                        assert set(args)=={'project_name','scope','path'} and args['project_name']=='ИИКона_разработки.ИИКона' and args['scope']=='file' and args['path']==expected
                        value={'content':[{'type':'text','text':expected}]}
                    elif name=='edt_get_module_structure':
                        assert set(args)=={'projectName','moduleFqn'} and args['projectName']=='ИИКона_разработки.ИИКона' and args['moduleFqn']=='CommonModules/КИИ_МониторингОшибокРегистры/Module.bsl'
                        value={'tool':name,'methods':[]}
                    else:raise AssertionError('Unexpected MCP tool '+str(name))
                    if scenario=='mcp-tool-error':value={'isError':True,'content':[{'type':'text','text':'Синтетический отказ инструмента'}]}
                    result={'jsonrpc':'2.0','id':payload['id'],'result':value}
                else:
                    code=400;result={'error':'fixture uninitialized or unknown method'}
                raw=b'' if result is None else json.dumps(result,ensure_ascii=False).encode('utf-8')
                content_type='application/json; charset=utf-8'
                if scenario=='mcp-sse' and method=='tools/call' and code==200:
                    progress=json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{}},ensure_ascii=False)
                    serialized=json.dumps(result,ensure_ascii=False,indent=2)
                    raw=('event: message\ndata: '+progress+'\n\nevent: message\n'+''.join('data: '+line+'\n' for line in serialized.splitlines())+'\n').encode('utf-8');content_type='text/event-stream'
                self.send_response(code);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
                for k,v in headers.items():self.send_header(k,v)
                self.end_headers();self.wfile.write(raw);return
            count=sum(e['scenario']==scenario for e in events)
            if scenario in ('transport-unknown','transport-retry') and count==1:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                self.close_connection=True
                return
            code=200
            result={'id':'synthetic-request','object':'chat.completion','model':'legacy-fixture',
                    'choices':[{'message':{'role':'assistant','content':'Совместимость подтверждена'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10,'cost':0.001}}
            if scenario.startswith('exam-'):
                def identifiers(value):
                    if isinstance(value,dict):
                        for child in value.values():yield from identifiers(child)
                    elif isinstance(value,list):
                        for child in value:yield from identifiers(child)
                    elif isinstance(value,str):
                        try:decoded=json.loads(value)
                        except (ValueError,TypeError):return
                        if isinstance(decoded,dict) and isinstance(decoded.get('requestId'),str):
                            yield decoded['requestId']
                found=list(identifiers(payload))
                if len(found)!=1 or scenario not in {'exam-openai','exam-anthropic','exam-google','exam-yandex'}:
                    code=400;result={'error':{'message':'Synthetic assessment requestId missing or ambiguous'}}
                else:
                    answer=json.dumps({'requestId':found[0],'verdict':'верно','score':1,'feedback':'По критериям.'},ensure_ascii=False)
                    result['choices'][0]['message']['content']=answer
                    if scenario=='exam-anthropic':result={'id':'synthetic-request','model':'legacy-fixture','content':[{'type':'text','text':answer}],'stop_reason':'end_turn','usage':{'input_tokens':7,'output_tokens':3}}
                    if scenario=='exam-google':result={'candidates':[{'content':{'parts':[{'text':answer}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':3,'totalTokenCount':10}}
                    if scenario=='exam-yandex':result={'result':{'alternatives':[{'message':{'role':'assistant','text':answer},'status':'ALTERNATIVE_STATUS_FINAL'}],'usage':{'inputTextTokens':'7','completionTokens':'3','totalTokens':'10'},'modelVersion':'legacy-fixture'}}
            if scenario=='anthropic':result={'id':'synthetic-request','model':'legacy-fixture','content':[{'type':'text','text':'Совместимость подтверждена'}],'stop_reason':'end_turn','usage':{'input_tokens':7,'output_tokens':3}}
            if scenario=='google':result={'candidates':[{'content':{'parts':[{'text':'Совместимость подтверждена'}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':3,'totalTokenCount':10}}
            if scenario=='yandex':result={'result':{'alternatives':[{'message':{'role':'assistant','text':'Совместимость подтверждена'},'status':'ALTERNATIVE_STATUS_FINAL'}],'usage':{'inputTextTokens':'7','completionTokens':'3','totalTokens':'10'},'modelVersion':'legacy-fixture'}}
            if scenario=='error400':code=400;result={'error':{'code':'invalid_request','message':'Synthetic request rejected'}}
            if scenario=='retry429' and count<3:code=429;result={'error':{'code':'rate_limit_exceeded','message':'Synthetic retry'}}
            if scenario in ('html502','upstream-unknown'):code=502;result='<html>Bad Gateway</html>'
            if scenario=='badjson':result='{broken-json'
            if scenario=='echo':result['choices'][0]['message']['content']=payload['messages'][-1]['content']
            raw=(result if isinstance(result,str) else json.dumps(result,ensure_ascii=False)).encode('utf-8')
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_DELETE(self):
            sid=self.headers.get('Mcp-Session-Id');sessions.pop(sid,None)
            self.send_response(204);self.send_header('Content-Length','0');self.end_headers()
        def do_GET(self):
            marker=self.path.removeprefix('/embedding-events/')
            relevant=[e for e in events if marker in e['body'].get('model','')]
            groups=[e['body']['input'] if isinstance(e['body'].get('input'),list) else [e['body'].get('input','')] for e in relevant]
            result={'requests':len(relevant),'sizes':[len(group) for group in groups],
                    'array_inputs':[isinstance(e['body'].get('input'),list) for e in relevant],
                    'text_lengths':[len(value) for group in groups for value in group],
                    'total_lengths':[sum(len(value) for value in group) for group in groups]}
            raw=json.dumps(result).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',8873),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield events
    finally:server.shutdown();server.server_close();thread.join(5)
