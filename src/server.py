from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import os
os.chdir(os.path.expanduser('~/.cache/cast-control'))
class H(SimpleHTTPRequestHandler):
 def end_headers(self):
  self.send_header('Access-Control-Allow-Origin','*')
  self.send_header('Cache-Control','no-cache')
  super().end_headers()
ThreadingHTTPServer(('0.0.0.0',8767),H).serve_forever()
