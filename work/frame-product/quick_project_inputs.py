"""Add footage/context to a stable project family and branch from a new take."""
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import types
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlparse, quote
import quick_import
import quick_timeline as timeline


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(timeline.ID,value):
        raise ValueError('Choose the current Frame project explicitly.')
    return value


def request(base,path,body=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        try:message=json.loads(error.read(16000)).get('error','Project update failed.')
        except Exception:message='Project update failed.'
        raise ValueError(message) from None


def add_asset(base,args):
    pid=identifier(args.get('project_id'));doc=request(base,'/api/quick/projects/'+pid)
    kinds=[key for key in ('file','source_path') if args.get(key) is not None]
    if len(kinds)!=1:raise ValueError('Supply one actual chat attachment or absolute host file path.')
    with tempfile.TemporaryFile() as stream:
        if kinds[0]=='file':
            file=args['file']
            if not isinstance(file,dict) or not file.get('file_id') or not isinstance(file.get('download_url'),str):raise ValueError('Use the actual host attachment and fresh download URL.')
            quick_import.download(file['download_url'],stream,max_bytes=quick_import.MAX_BYTES,limit_label='700 MB',timeout=300)
            name=file.get('file_name') or 'Project file'
        else:
            source=Path(args['source_path']) if isinstance(args['source_path'],str) else Path('')
            if not source.is_absolute() or not source.is_file():raise ValueError('Use an existing absolute file path supplied by this conversation host.')
            if not 0<source.stat().st_size<=quick_import.MAX_BYTES:raise ValueError('Project files must be between 1 byte and 700 MB.')
            with source.open('rb') as original:
                for chunk in iter(lambda:original.read(1024*1024),b''):
                    stream.write(chunk)
                    if stream.tell()>quick_import.MAX_BYTES:raise ValueError('Project file exceeds 700 MB.')
            name=source.name
        stream.seek(0);digest=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        doc=request(base,'/api/quick/projects/'+pid)
        existing=next((a for a in doc.get('assets',[]) if a.get('sha256')==digest.hexdigest()),None)
        if existing:return {'project_id':pid,'project':doc,'asset':existing,'reused':True,'open_project_files':True}
        stream.seek(0,2);size=stream.tell();stream.seek(0);endpoint=urlparse(base);connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port,timeout=300)
        try:
            connection.request('POST','/api/quick/projects/'+pid+'/assets',body=stream,headers={'Content-Type':'application/octet-stream','Content-Length':str(size),'X-Filename':quote(Path(name).name)})
            response=connection.getresponse();updated=json.loads(response.read())
            if response.status!=200:raise ValueError(updated.get('error','Project file could not be saved.'))
        finally:connection.close()
        asset=next(a for a in reversed(updated.get('assets',[])) if a.get('sha256')==digest.hexdigest())
        return {'project_id':pid,'project':updated,'asset':asset,'reused':False,'open_project_files':True,'next_step':'File saved inside this project. Keep the current cut. Use start_project_revision only when the user chooses a re-recording as the next cut.'}


def family_docs(app,doc):
    # Explicit family/lineage only. Similar filenames never merge projects.
    docs={doc['project_id']:doc}
    for folder in app.WORK.iterdir():
        path=folder/'timeline.json'
        if not re.fullmatch(timeline.ID,folder.name) or not path.is_file():continue
        try:docs[folder.name]=json.loads(path.read_text())
        except (OSError,ValueError):continue
    members={doc['project_id']};changed=True
    while changed:
        changed=False
        groups={(docs[pid].get('work_project') or {}).get('id') for pid in members}-{None}
        for pid,value in docs.items():
            links={(value.get('revision_parent') or {}).get('project_id'),(value.get('revision_parent') or {}).get('result_project_id'),(value.get('next_revision') or {}).get('project_id')}
            linked=bool(links&members) or any(pid in {(docs[known].get('revision_parent') or {}).get('project_id'),(docs[known].get('next_revision') or {}).get('project_id')} for known in members)
            if pid not in members and ((value.get('work_project') or {}).get('id') in groups or linked):members.add(pid);changed=True
    return [docs[pid] for pid in members]


def start_revision(app,pid,body):
    pid=identifier(pid);owner=identifier(body.get('asset_project_id') or pid);aid=identifier(body.get('asset_id'))
    token=body.get('request_id');brief=body.get('brief','')
    if not isinstance(brief,str):raise ValueError('Write the new direction as text.')
    brief=brief.strip()
    if not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}',token):raise ValueError('Supply a stable request_id before starting a new cut.')
    if not isinstance(brief,str) or len(brief)>2000:raise ValueError('Use a new-direction brief up to 2000 characters.')
    with timeline.LOCK:
        parent=timeline.load(app,pid)
        previous=next((r for r in parent.get('revision_branches',[]) if r.get('request_id')==token),None)
        if previous:
            if previous['asset_id']!=aid or previous['asset_project_id']!=owner or previous.get('brief','')!=brief:raise ValueError('That request_id belongs to a different new cut.')
            child=timeline.public(timeline.load(app,previous['project_id']));return {'project_id':child['project_id'],'project':child,'parent_project_id':pid,'reused':True}
        if type(body.get('expected_version')) is not int or body['expected_version']!=parent['version']:raise timeline.Conflict('Project changed. Refresh before starting the new cut; the uploaded file is already saved.')
        family=family_docs(app,parent)
        source_doc=next((d for d in family if d['project_id']==owner),None)
        if not source_doc:raise ValueError('Choose footage already saved inside this project family.')
        asset=next((a for a in source_doc.get('assets',[]) if a['id']==aid),None)
        if not asset:raise ValueError('Project file not found. Upload it to this project first.')
        source=(app.WORK/owner/asset['path']).resolve();folder=(app.WORK/owner).resolve()
        if folder not in source.parents or not source.is_file():raise ValueError('Project footage is unavailable.')
        info=timeline.probe(source)
        if not info.get('duration') or not info.get('width') or not info.get('height'):raise ValueError('Choose video footage to start a new cut. Other files remain available as context.')
        digest=hashlib.sha256()
        with source.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        checksum=digest.hexdigest()
        if checksum!=asset.get('sha256'):raise ValueError('The saved footage changed. Upload the new take again before using it.')
        child_id=uuid.uuid5(uuid.NAMESPACE_URL,'frame:direction:'+pid+':'+token).hex;target=app.WORK/child_id
        receipt={'request_id':token,'parent_project_id':pid,'asset_project_id':owner,'asset_id':aid,'sha256':checksum,'brief':brief}
        if target.is_symlink():raise ValueError('The new-cut destination could not be verified. Previous cuts are unchanged.')
        if target.exists():
            saved=target/'timeline.json'
            if saved.is_symlink() or not saved.is_file() or json.loads(saved.read_text()).get('direction_creation')!=receipt:
                raise ValueError('The new-cut destination belongs to another or incomplete request. Previous cuts are unchanged.')
            child=timeline.load(app,child_id)
            # The child commit succeeded before the parent record failed. Reuse it
            # without resetting any notes, references, or edits saved since then.
        else:
            # Keep incomplete initialization out of the visible project store.
            # Publishing the finished directory is one same-filesystem rename.
            with tempfile.TemporaryDirectory(prefix='.new-direction-',dir=app.WORK) as pending:
                pending_root=Path(pending);staged=pending_root/child_id;staged.mkdir()
                media=staged/'input.mp4';shutil.copyfile(source,media)
                copied=hashlib.sha256()
                with media.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):copied.update(chunk)
                if copied.hexdigest()!=checksum:
                    raise ValueError('The footage changed while copying. The previous cut is unchanged; retry with the saved file.')
                timeline.write(staged/'project.json',{'id':child_id,'name':asset['name'],'created':time.time(),'versions':[],'history':[],'current_segments':None,'current_version':None})
                staging_app=types.SimpleNamespace(**vars(app));staging_app.WORK=pending_root
                staging_app.project=lambda identifier:json.loads((pending_root/identifier/'project.json').read_text())
                child=timeline.load(staging_app,child_id)
                work=copy.deepcopy(parent.get('work_project') or {'id':pid,'title':Path(parent['name']).stem})
                child['work_project']={**work,'role':'cut','label':'New take · '+Path(asset['name']).stem}
                child['revision_parent']={'project_id':pid,'source_version':parent['version'],'kind':'new_direction','asset_project_id':owner,'asset_id':aid,'sha256':checksum}
                child['project_context']={'parent_project_id':pid,'brief':brief,'previous_general_notes':copy.deepcopy([n for n in parent.get('notes',[]) if n.get('scope')=='general']),'assets':[{'project_id':d['project_id'],**copy.deepcopy(a)} for d in family for a in d.get('assets',[])]}
                child['video_references']=copy.deepcopy(parent.get('video_references',[]))
                timeline.write(staged/'timeline.json',child)
                if brief:
                    import quick_revision
                    quick_revision.act(staging_app,child_id,{'action':'add_general_note','expected_version':child['version'],'instruction':brief});child=timeline.load(staging_app,child_id)
                child['direction_creation']=receipt;timeline.write(staged/'timeline.json',child)
                staged.rename(target)
                directory=os.open(str(app.WORK),os.O_RDONLY)
                try:os.fsync(directory)
                finally:os.close(directory)
        record={'request_id':token,'project_id':child_id,'asset_id':aid,'asset_project_id':owner,'brief':brief,'created_at':time.time()}
        parent.setdefault('revision_branches',[]).append(record);parent['next_direction']={'project_id':child_id,'asset_name':asset['name'],'created_at':record['created_at']};parent['version']+=1;timeline.write(app.WORK/pid/'timeline.json',parent)
        return {'project_id':child_id,'project':timeline.public(child),'parent_project_id':pid,'reused':False,'next_step':'New cut created inside the same project folder. Previous cuts, notes and files are preserved. Use project_context for the earlier brief and files.'}


def route(handler,app,method):
    path=urlparse(handler.path).path;match=re.fullmatch('/api/quick/projects/('+timeline.ID+')/new-cut',path)
    if method!='POST' or not match:return False
    try:
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=16000:raise ValueError('Invalid new-cut request.')
        body=json.loads(handler.rfile.read(size));handler.json(200,start_revision(app,match[1],body))
    except (ValueError,OSError,KeyError,TypeError) as error:handler.json(409 if isinstance(error,timeline.Conflict) else 400,{'error':str(error)})
    return True
