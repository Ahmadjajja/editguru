"""Explicit new-footage uploads that resume only their originating Frame panel."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import types
from urllib.parse import unquote
import quick_timeline as timeline

MAX_BYTES=700*1024*1024

def upload(handler,app,session):
    allowed={'http://127.0.0.1:'+str(handler.server.server_port),'http://localhost:'+str(handler.server.server_port)}
    if handler.headers.get('Origin') not in allowed:
        handler.close_connection=True;return handler.json(403,{'error':'Open the upload page from Frame.'})
    try:
        if not re.fullmatch('[a-f0-9]{32}',session):raise ValueError('Invalid upload session. Open a new upload from Frame.')
        length=int(handler.headers.get('Content-Length','0'))
        if not 0<length<=MAX_BYTES:raise ValueError('Choose a video between 1 byte and 700 MB.')
        name=Path(unquote(handler.headers.get('X-Filename','New footage.mp4')).replace('\\','/')).name[:180] or 'New footage.mp4'
        # The same upload action has one destination, even if its confirmation is lost.
        pid=hashlib.sha256(('frame-new-upload:'+session).encode()).hexdigest()[:32]
        target=app.WORK/pid;incoming=app.WORK/'.incoming';incoming.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='new-',dir=incoming) as temporary:
            stage=Path(temporary);folder=stage/pid;folder.mkdir();hasher=hashlib.sha256()
            handler.connection.settimeout(300)
            with (folder/'input.mp4').open('wb') as output:
                remaining=length
                while remaining:
                    chunk=handler.rfile.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('Upload interrupted. Select the same video to retry.')
                    output.write(chunk);hasher.update(chunk);remaining-=len(chunk)
                output.flush();os.fsync(output.fileno())
            sha=hasher.hexdigest()
            app.probe(folder/'input.mp4')
            with timeline.LOCK:
                if target.exists():
                    data=json.loads((target/'project.json').read_text())
                    if data.get('upload_session_id')!=session or data.get('source_sha256')!=sha:raise ValueError('This upload already contains another video. Start a new upload from Frame.')
                else:
                    data={'id':pid,'name':name,'created':time.time(),'versions':[],'history':[],'current_segments':None,'current_version':None,'upload_session_id':session,'source_sha256':sha}
                    timeline.write(folder/'project.json',data)
                    isolated=types.SimpleNamespace(WORK=stage,project=lambda _:data)
                    doc=timeline.load(isolated,pid)
                    doc['work_project']={'id':pid,'title':Path(name).stem,'role':'cut','upload_session_id':session}
                    timeline.write(folder/'timeline.json',doc)
                    folder.rename(target)
                    fd=os.open(str(app.WORK),os.O_RDONLY)
                    try:os.fsync(fd)
                    finally:os.close(fd)
        return handler.json(200,{'project_id':pid,'name':data['name'],'upload_session_id':session,'editor_url':'/frame?project='+pid})
    except (ValueError,OSError,KeyError) as exc:
        handler.close_connection=True
        return handler.json(400,{'error':str(exc)[-500:]})
