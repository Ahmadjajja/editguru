"""Import one host-provided attachment into an explicitly selected project's references.

The active project comes from conversation/app context, never global recency.
No assumption that this service can enumerate a host's private attachments.
"""
import hashlib
import json
import re
import tempfile
import urllib.request
import urllib.error
import quick_import


def request(base, path, body=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        try:message=json.loads(exc.read(16000)).get('error','Reference could not be saved.')
        except Exception:message='Reference could not be saved.'
        raise ValueError(message) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise ValueError('Frame connection was interrupted. Check the saved project before retrying.') from None


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):
        raise ValueError('Choose the target Frame project from this conversation before adding a reference.')
    return value


def result(base, doc, ref, reused=False):
    return {'project_id':doc['project_id'],'project':doc,'reference_project_id':ref['project_id'],
            'reference_name':ref['name'],'status':'reference_added','reused':reused,'open_references':True,
            'editor_url':base+'/frame?project='+doc['project_id']+'&tab=references&reference='+ref['project_id'],
            'next_step':'Reference saved to this project. Open References to inspect a moment and specify the aspect to implement. The edit timeline has not changed.'}


def link(base, target, source, sha256=None):
    identifier(target);identifier(source)
    if target==source:raise ValueError('The edit video cannot be its own reference.')
    # Linking is commutative and idempotent. Reconcile only this addition after CAS conflicts.
    for _ in range(3):
        doc=request(base,'/api/quick/projects/'+target)
        existing=next((r for r in doc.get('video_references',[]) if r['project_id']==source or (sha256 and r.get('sha256')==sha256)),None)
        if existing:return result(base,doc,existing,True)
        try:
            updated=request(base,'/api/quick/projects/'+target+'/revision',{
                'action':'add_video_reference','expected_version':doc['version'],'reference_project_id':source})
            ref=next((r for r in updated.get('video_references',[]) if r['project_id']==updated.get('linked_reference_project_id',source) or (sha256 and r.get('sha256')==sha256)),None)
            if not ref:raise ValueError('Server needs the current References update. Imported video remains saved as project '+source+'.')
            return result(base,updated,ref)
        except ValueError as exc:
            if not any(s in str(exc).lower() for s in ('revision changed','conflict')):raise
    raise ValueError('Project kept changing. Reference video is saved as project '+source+'; retry using reference_project_id to link it without another upload.')


def import_reference(base, args):
    target=identifier(args.get('project_id'))
    sources=[k for k in ('file','source_path','reference_project_id') if args.get(k) is not None]
    if len(sources)!=1:raise ValueError('Supply exactly one host attachment file, host local source_path, or saved reference_project_id.')
    doc=request(base,'/api/quick/projects/'+target) # Validate target before transferring any bytes.
    if len(doc.get('video_references',[]))>=20 and sources[0]!='reference_project_id':
        raise ValueError('Maximum 20 reference videos per project. Remove one before importing another.')
    kind=sources[0]
    if kind=='reference_project_id':return link(base,target,identifier(args[kind]))
    with tempfile.TemporaryFile() as stream:
        if kind=='file':
            file=args['file']
            if not isinstance(file,dict) or not file.get('file_id') or not isinstance(file.get('download_url'),str):
                raise ValueError('Use the actual conversation attachment and its fresh host-provided download URL.')
            if file.get('mime_type') and not (file['mime_type'].startswith('video/') or file['mime_type']=='application/octet-stream'):
                raise ValueError('Choose a video attachment.')
            try:quick_import.download(file['download_url'],stream,max_bytes=quick_import.MAX_REFERENCE_BYTES,limit_label='1 GiB',timeout=300)
            except Exception:raise ValueError('Attachment download failed. Request a fresh host file handoff; do not invent a URL.') from None
            name=file.get('file_name') or 'Chat reference.mp4'
        else:
            from pathlib import Path
            path=Path(args['source_path']) if isinstance(args['source_path'],str) else Path('')
            if not path.is_absolute() or not path.is_file():raise ValueError('Use the actual absolute video path supplied by this conversation host.')
            if not 0<path.stat().st_size<=quick_import.MAX_REFERENCE_BYTES:raise ValueError('Reference video must be between 1 byte and 1 GiB.')
            with path.open('rb') as source:
                while True:
                    chunk=source.read(1024*1024)
                    if not chunk:break
                    stream.write(chunk)
                    if stream.tell()>quick_import.MAX_REFERENCE_BYTES:raise ValueError('Reference exceeds 1 GiB.')
            name=path.name
        stream.seek(0);digest=hashlib.sha256()
        while True:
            chunk=stream.read(1024*1024)
            if not chunk:break
            digest.update(chunk)
        # Reload before dedup so parallel imports and fresh app links are visible.
        doc=request(base,'/api/quick/projects/'+target)
        existing=next((r for r in doc.get('video_references',[]) if r.get('sha256')==digest.hexdigest()),None)
        if existing:return result(base,doc,existing,True)
        imported=quick_import.upload(base,stream,name,endpoint='/upload-reference',max_bytes=quick_import.MAX_REFERENCE_BYTES,limit_label='1 GiB',media_label='Reference video')
    try:return link(base,target,imported['project_id'],digest.hexdigest())
    except ValueError as exc:
        raise ValueError(str(exc)+' Imported reference is retained as project '+imported['project_id']+'. Retry with reference_project_id; no re-upload is needed.') from None
