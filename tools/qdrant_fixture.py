"""Disposable loopback Qdrant fixture; never records authorization headers."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,sys,threading
sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
state={'fixture':{},'puts':0,'deletes':0,'scrolls':0,'requests':[]}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.handle_request()
    def do_POST(self):self.handle_request()
    def do_PUT(self):self.handle_request()
    def handle_request(self):
        data=self.rfile.read(int(self.headers.get('Content-Length',0)))
        value=json.loads(data) if data else {}
        code=200;response={'result':{'status':'completed'},'status':'ok'}
        if self.path=='/__fixture':
            state.update(fixture=value,puts=0,deletes=0,scrolls=0,requests=[])
        elif self.path=='/__stats':response={k:v for k,v in state.items() if k!='fixture'}
        elif self.path=='/__stop':threading.Thread(target=self.server.shutdown,daemon=True).start()
        else:
            state['requests'].append({'method':self.command,'path':self.path,'body':value})
            if self.path.endswith('/points/scroll'):
                state['scrolls']+=1;response={'result':{'points':state['fixture'].get('points',[]),'next_page_offset':None},'status':'ok'}
            elif '/points/delete' in self.path:state['deletes']+=1
            elif self.command=='PUT' and '/points' in self.path:
                state['puts']+=1
                if any(p.get('payload',{}).get('фрагмент')==state['fixture'].get('fail_uuid') for p in value.get('points',[])):
                    code=500;response={'status':'error','result':'fixture failure'}
        raw=json.dumps(response,ensure_ascii=False).encode('utf-8')
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

from contextlib import contextmanager
@contextmanager
def local_fixture():
    """Own a short-lived loopback Qdrant fixture; fail closed if its port is occupied.

    The YAxUnit cases override the target address inside their own transactions.
    No authorization headers are recorded. No production service is contacted.
    """
    server=ThreadingHTTPServer(('127.0.0.1',8871),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:yield
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
