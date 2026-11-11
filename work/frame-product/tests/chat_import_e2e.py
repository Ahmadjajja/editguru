"""Manual live-local-service test; run from repo root with FRAME_FOOTAGE (>=8s).

Remote host transport is deliberately simulated. This does not test a ChatGPT account.
"""
import json, os, subprocess, time, sys, threading, http.client
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,'work/frame-product')
import quick_mcp,quick_import
source=Path(os.environ['FRAME_FOOTAGE']).resolve()
Path('output/playwright').mkdir(parents=True,exist_ok=True)
class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  data=source.read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
# Simulate a host-issued signed URL with a local fixture transport; production public-HTTPS validation remains unchanged.
with patch.object(quick_import,'public_target',return_value=(quick_import.urlsplit('https://fixture.example/attachment?signature=fixture'),'8.8.8.8')),patch.object(quick_import,'PinnedHTTPS',side_effect=lambda *a,**kw:http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)):
 attachment=quick_mcp.dispatch({'id':1,'method':'tools/call','params':{'name':'import_video','arguments':{'file':{'file_id':'file-fixture','download_url':'https://fixture.example/attachment?signature=fixture','file_name':'Conversation footage.mp4','mime_type':'video/mp4'}}}})
assert not attachment['result']['isError'],attachment
server.shutdown();server.server_close()
proc=subprocess.Popen([sys.executable,'work/frame-product/quick_mcp.py'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
seq=0

def request(method,params=None):
 global seq
 seq+=1;proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params or {}})+'\n');proc.stdin.flush();return json.loads(proc.stdout.readline())['result']
def tool(name,args):
 r=request('tools/call',{'name':name,'arguments':args});assert not r.get('isError'),r;return r['structuredContent']
try:
 init=request('initialize',{'protocolVersion':'2025-03-26','clientInfo':{'name':'frame-attachment-acceptance','version':'1'}})
 discovery=request('tools/list');assert {'import_video','import_local_video','position_clip','get_frame_comments','get_frame_comment'} <= {t['name'] for t in discovery['tools']}
 imported=tool('import_local_video',{'source_path':str(source)})
 pid=imported['project_id'];t=tool('get_timeline',{'project_id':pid});cid=t['clips'][0]['id']
 t=tool('trim_clip',{'project_id':pid,'clip_id':cid,'start':3,'end':8,'expected_version':t['version']});assert t['duration']==5
 t=tool('split_clip',{'project_id':pid,'clip_id':cid,'source_time':5,'expected_version':t['version']});assert len(t['clips'])==2
 t=tool('undo',{'project_id':pid,'expected_version':t['version']});assert len(t['clips'])==1
 t=tool('export_video',{'project_id':pid,'expected_version':t['version']})
 for _ in range(100):
  t=tool('get_project',{'project_id':pid})
  if t['exports'][-1]['status'] in ('done','failed'):break
  time.sleep(.3)
 assert t['exports'][-1]['status']=='done',t
 original=Path('work/frame-product/jobs')/pid/'input.mp4';assert original.read_bytes()==source.read_bytes()
 attached=attachment['result']['structuredContent'];assert (Path('work/frame-product/jobs')/attached['project_id']/'input.mp4').read_bytes()==source.read_bytes()
 evidence={'initialized':True,'tool_count':len(discovery['tools']),'attachment_fixture_transport':'simulated HTTPS URL delivered over actual loopback HTTP fixture, no ChatGPT account','attachment_import':attached,'local_import':imported,'project':t,'native_chatgpt_connection':'unverified','source_bytes_preserved':True}
 Path('output/playwright/chat-first-mcp-results.json').write_text(json.dumps(evidence,indent=2))
 print(json.dumps({'editor_url':imported['editor_url'],'duration':t['duration'],'export':t['exports'][-1]['status'],'tools':len(discovery['tools']),'attachment_pipeline':'PASS (fixture transport)'}))
finally:proc.stdin.close();proc.wait(timeout=5)
