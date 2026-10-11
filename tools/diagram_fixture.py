"""Owned loopback Kroki fixture for return-contract tests; no external rendering.

The fixture records only request paths and status codes. It never logs headers
or request bodies. Binding an occupied port fails before any test is launched.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import base64

SVG=b'<svg xmlns="http://www.w3.org/2000/svg"><text>fixture-diagram</text></svg>'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZQAAAABJRU5ErkJggg==')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>1024*1024:
            self.send_error(413);return
        body=self.rfile.read(length)
        if b'fixture-error' in body:
            status,payload,mime=503,b'fixture-failure','text/plain; charset=utf-8'
        elif self.path=='/mermaid/svg':
            status,payload,mime=200,SVG,'image/svg+xml; charset=utf-8'
        elif self.path=='/mermaid/png':
            status,payload,mime=200,PNG,'image/png'
        else:
            status,payload,mime=404,b'unexpected fixture endpoint','text/plain'
        self.server.events.append({'path':self.path,'status':status})
        self.send_response(status);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)

@contextmanager
def local_diagram_fixture():
    server=ThreadingHTTPServer(('127.0.0.1',8872),Handler)
    server.events=[];thread=Thread(target=server.serve_forever,name='owned-local-diagram-fixture',daemon=True)
    thread.start()
    try:yield server.events
    finally:
        server.shutdown();server.server_close();thread.join(timeout=10)
        if thread.is_alive():raise RuntimeError('Local fixture did not stop normally')
