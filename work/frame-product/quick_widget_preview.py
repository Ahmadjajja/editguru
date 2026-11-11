"""Loopback preview of the MCP widget using the same editor tools and project data."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import quick_mcp

ROOT = Path(__file__).resolve().parent
PORT = 18966
PROJECT = '32289b5aaee14fcfaaedfee16396a035'
ADAPTER = '''const applyDocumentTheme=()=>{},applyHostStyleVariables=()=>{};
class App {
 async connect(){this.ontoolresult({structuredContent:{project_id:PROJECT}})}
 getHostContext(){return {theme:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
 async updateModelContext(){}
 async requestDisplayMode(){await document.documentElement.requestFullscreen()}
 async sendMessage(){throw Error('Use the chat to read saved notes.')}
 async callServerTool(request){return await(await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)})).json()}
}'''.replace('PROJECT',json.dumps(PROJECT))

class Handler(BaseHTTPRequestHandler):
 def allowed(self):
  return self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
 def reply(self,code,body,kind='application/json'):
  self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if not self.allowed():return self.reply(403,b'{}')
  if self.path in ('/markup.js','/section-timeline.js'):return self.reply(200,(ROOT/'widget'/self.path[1:]).read_bytes(),'text/javascript')
  if self.path not in ('/','/index.html'):return self.reply(404,b'{}')
  source=(ROOT/'widget/editor.js').read_text().split('\n',1)[1]
  html=(ROOT/'widget/editor.html').read_text().replace('/* FRAME_WIDGET_SCRIPT */',ADAPTER+source)
  self.reply(200,html.encode(),'text/html; charset=utf-8')
 def do_POST(self):
  origin=self.headers.get('Origin')
  if not self.allowed() or origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
   return self.reply(403,b'{}')
  if self.path!='/rpc':return self.reply(404,b'{}')
  try:
   size=int(self.headers.get('Content-Length',0))
   if not 0<size<=16000 or self.headers.get('Content-Type')!='application/json':raise ValueError('Invalid request.')
   request=json.loads(self.rfile.read(size))
   if request.get('name') not in quick_mcp.SPECS:raise ValueError('Unknown editor tool.')
   result=quick_mcp.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/call','params':request})['result']
   self.reply(200,json.dumps(result).encode())
  except (ValueError,TypeError,KeyError) as exc:self.reply(400,json.dumps({'isError':True,'content':[{'type':'text','text':str(exc)}]}).encode())
 def log_message(self,*args):pass

if __name__=='__main__':
 ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
