"""Serve the real production bundle with a loopback same-origin test API proxy."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import http.client
ROOT=Path(__file__).resolve().parents[1]/'dist/knowledge-ai/browser'
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def proxy(self):
        conn=http.client.HTTPConnection('127.0.0.1',9635,timeout=180)
        data=self.rfile.read(int(self.headers.get('Content-Length','0')))
        headers=dict(self.headers);headers.pop('Connection',None)
        conn.request(self.command,self.path,body=data,headers=headers);res=conn.getresponse()
        self.send_response(res.status)
        for k,v in res.getheaders():
            if k.lower() not in ('transfer-encoding','connection','server','date'):self.send_header(k,v)
        self.end_headers();self.wfile.write(res.read());conn.close()
    def do_GET(self):
        if self.path.startswith('/api/'):return self.proxy()
        if not (ROOT/self.path.split('?')[0].lstrip('/')).is_file():self.path='/index.html'
        super().do_GET()
    do_POST=proxy
    do_PATCH=proxy
    do_PUT=proxy
    do_DELETE=proxy
ThreadingHTTPServer(('127.0.0.1',9636),Handler).serve_forever()
