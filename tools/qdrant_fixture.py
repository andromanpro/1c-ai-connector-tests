"""Disposable loopback Qdrant fixture; never records authorization headers."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,sys,threading,time,copy
sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
lock=threading.RLock()
state={'fixture':{},'puts':0,'deletes':0,'scrolls':0,'requests':[],
       'batch_requests':0,'max_operations':0,'conditional_operations':0,
       'accepted':0,'skipped':0,'active':0,'peak_active':0,'stored_points':{}}
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
            with lock:
                assert state['active']==0,'Do not reset an active fixture'
                points=state['stored_points'] if value.get('preserve_points') else {}
                state.update(fixture=value,puts=0,deletes=0,scrolls=0,requests=[],
                    batch_requests=0,max_operations=0,conditional_operations=0,
                    accepted=0,skipped=0,active=0,peak_active=0,stored_points=points)
        elif self.path=='/__stats':
            with lock:
                response=copy.deepcopy({k:v for k,v in state.items() if k not in ['fixture','stored_points']})
                # JSON -> Structure requires identifier-like property names in 1C.
                response['stored_points']=list(copy.deepcopy(state['stored_points']).values())
        elif self.path=='/__stop':threading.Thread(target=self.server.shutdown,daemon=True).start()
        else:
            with lock:
                state['requests'].append({'method':self.command,'path':self.path,'body':value})
                fixture=copy.deepcopy(state['fixture'])
            if self.path=='/':response={'version':fixture.get('version','1.18.2')}
            elif fixture.get('create_conflict') and self.path.startswith('/collections/') and '/points' not in self.path and '/index' not in self.path:
                if self.command=='PUT':code=int(fixture.get('create_failure_code',409));response={'status':{'error':'collection creation rejected'}}
                else:
                    with lock:
                        reads=state['fixture'].setdefault('_collection_reads',{})
                        count=reads.get(self.path,0);reads[self.path]=count+1
                    if count==0:code=404;response={'status':{'error':'collection not found'}}
                    elif count<=int(fixture.get('readback_failures',0)):code=int(fixture.get('readback_failure_code',500));response={'status':{'error':'collection not ready'}}
                    else:response={'status':'ok','result':{'config':{'params':{'vectors':{'size':int(fixture.get('collection_size',3)),'distance':fixture.get('collection_distance','Dot')}}}}}
            elif '/points/batch?' in self.path:
                with lock:
                    state['batch_requests']+=1
                    operations=value.get('operations',[])
                    state['max_operations']=max(state['max_operations'],len(operations))
                    state['active']+=1;state['peak_active']=max(state['peak_active'],state['active'])
                try:
                    time.sleep(float(fixture.get('delay_seconds',0)))
                    failed=False;results=[]
                    for op in operations:
                        upsert=op.get('upsert',{})
                        points=upsert.get('points',[])
                        for point in points:
                            deleted=point.get('payload',{}).get('_kii_deleted',False)
                            with lock:
                                state['deletes' if deleted else 'puts']+=1
                            if fixture.get('fail_all') or (fixture.get('fail_uuid') and point.get('payload',{}).get('фрагмент')==fixture['fail_uuid']):
                                failed=True;break
                            filters=upsert.get('update_filter',{}).get('must_not',[])
                            assert len(filters)==1 and filters[0]['key']=='_kii_revision'
                            threshold=filters[0]['range']['gte']
                            key=self.path.split('/points/')[0]+'/'+str(point['id'])
                            with lock:
                                state['conditional_operations']+=1
                                old=state['stored_points'].get(key)
                                if old and old.get('payload',{}).get('_kii_revision',-1)>=threshold:
                                    state['skipped']+=1
                                else:state['stored_points'][key]=copy.deepcopy(point);state['accepted']+=1
                        if failed:break
                        results.append({'operation_id':len(results)+1,'status':'completed'})
                    if failed:code=500;response={'status':'error','result':'fixture partial acceptance then failure'}
                    else:response={'result':[] if fixture.get('malformed_result') else results,'status':'ok'}
                finally:
                    with lock:state['active']-=1
            elif self.path.endswith('/points/scroll'):
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

    HTTP tests restore the target address and delete their committed owned data.
    No authorization headers are recorded. No production service is contacted.
    """
    server=ThreadingHTTPServer(('127.0.0.1',8871),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:yield
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
