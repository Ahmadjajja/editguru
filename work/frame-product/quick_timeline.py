"""Versioned non-destructive edits over existing uploads and FFmpeg renderer."""
import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from editor import probe, render_timeline, detect_silence, trim_pauses

LOCK = threading.RLock()
ID = r'[a-f0-9]{32}'
OPERATIONS = ['get_project', 'get_timeline', 'split_clip', 'trim_clip', 'delete_segment',
              'move_segment', 'position_clip', 'log_activity', 'undo', 'redo', 'export_video', 'tighten_pacing', 'set_studio','generate_studio_captions']
OPERATIONS += ['record_edit_feedback','get_creative_memory','forget_edit_feedback']
OPERATIONS += ['sync_editor_state']
HANDOFF_OPERATIONS = {'begin_revision_handoff', 'finish_revision_handoff', 'get_revision_handoff', 'acknowledge_revision_handoff'}
OPERATIONS += sorted(HANDOFF_OPERATIONS)

MAX_SEGMENTS = 240  # pause cutting on talking-head footage easily exceeds 48

class Conflict(ValueError):
    pass

def write(path, data):
    if path.name == 'timeline.json':
        # Keep each changed video state, including edits made between exports.
        # Notes, activity and in-progress exports do not create video revisions.
        import quick_sections
        if data.get('checkpoints'):
            quick_sections.save_video_revision(data)
        data['saved_at'] = time.time()
        data['source_reference'] = '/media/'+data['project_id']+'/input.mp4'
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump({k:v for k,v in data.items() if k not in ('activity','revision_handoffs')} if path.name=='timeline.json' else data, f, allow_nan=False, indent=2)
        f.flush()
        import os
        os.fsync(f.fileno())
    temp.replace(path)
    import os
    fd = os.open(str(path.parent), os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def clip(a, b):
    return {'id': uuid.uuid4().hex, 'start': a, 'end': b}

def number(v):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
        raise ValueError('Use a finite number for time and position.')
    return float(v)

def load(app, pid):
    data = app.project(pid)  # validates identifier and source existence
    path = app.WORK / pid / 'timeline.json'
    if path.exists():
        doc = json.loads(path.read_text())
        if 'revision_id' not in doc:
            doc.update(revision_id=uuid.uuid4().hex, pins=[], accepted_edits=[], proposals=[], rendered=None)
            write(path, doc)
        import quick_sections
        if quick_sections.initialize(doc): write(path,doc)
        journal=app.WORK/pid/'activity.json'
        doc['activity']=json.loads(journal.read_text()) if journal.exists() else []
        handoffs=app.WORK/pid/'revision-handoffs.json'
        doc['revision_handoffs']=[{k:v for k,v in row.items() if k not in ('receipt_token','prompt')}
                                  for row in json.loads(handoffs.read_text())] if handoffs.exists() else []
        return doc
    info = probe(app.WORK / pid / 'input.mp4')
    segments = data.get('current_segments') or [[0, info['duration']]]
    doc = {'project_id': pid, 'name': data['name'], 'version': 1, 'source_duration': info['duration'],
           'revision_id': uuid.uuid4().hex, 'pins': [], 'accepted_edits': [], 'proposals': [], 'rendered': None,
           'audio': info['audio'], 'clips': [clip(round(a*30)/30, min(round(b*30),math.floor(info['duration']*30+1e-6))/30) for a,b in segments], 'undo': [], 'redo': [], 'exports': [], 'revision_handoffs': [], 'activity': []}
    import quick_sections
    quick_sections.initialize(doc)
    write(path, doc)
    return doc

def public(doc):
    return {k: copy.deepcopy(v) for k,v in doc.items() if k not in ('undo','redo')} | {
        'duration': sum(c['end']-c['start'] for c in doc['clips']),
        'studio': copy.deepcopy(doc.get('studio', {})),
        'can_undo': bool(doc['undo']), 'can_redo': bool(doc['redo']),
        'source_url': '/media/'+doc['project_id']+'/input.mp4'}

def completed_export(doc, export_id):
    """Resolve manual exports and accepted renders saved by older checkpoints."""
    exported = next((e for e in doc.get('exports', []) if e.get('id') == export_id and e.get('status') == 'done'), None)
    if exported is not None:
        return exported
    if not any(p.get('id') == export_id and p.get('status') == 'accepted' for p in doc.get('proposals', [])):
        return None
    renders = [doc.get('rendered')] + [c.get('rendered') for c in doc.get('checkpoints', [])]
    rendered = next((r for r in renders if r and r.get('proposal_id') == export_id), None)
    if rendered is None:
        return None
    return {'id': export_id, 'status': 'done', 'timeline_version': rendered.get('timeline_version'),
            'duration': rendered.get('duration'), 'url': rendered.get('url')}

def validate(doc):
    if len(doc['clips']) > MAX_SEGMENTS:
        raise ValueError('Maximum %d segments per project.' % MAX_SEGMENTS)
    for c in doc['clips']:
        for axis in ('x','y'):
            value=number(c.get(axis,0))
            if abs(value)>.5:raise ValueError('Keep asset position within 50% of the frame.')
        a,b=number(c['start']),number(c['end'])
        if a < 0 or b > doc['source_duration']+.00001:
            raise ValueError('Trim times must stay inside the source.')
        a,b=round(a*30)/30,min(round(b*30),math.floor(doc['source_duration']*30+1e-6))/30
        c.update(start=a,end=b)
        if a<0 or b>doc['source_duration']+.00001 or b-a<1/30-1e-7:
            raise ValueError('Keep at least one 30 fps frame, inside the original source.')

def activity(app, pid, command, message, status='running', identifier=None):
    with LOCK:
        doc=load(app,pid)
        journal=app.WORK/pid/'activity.json'
        rows=json.loads(journal.read_text()) if journal.exists() else []
        row=next((e for e in rows if e['id']==identifier),None) if identifier else None
        if row is None:
            if command=='agent':
                for prior in rows:
                    if prior.get('command')=='agent' and prior.get('status')=='running':prior.update(status='done',updated_at=time.time())
            row={'id':identifier or uuid.uuid4().hex,'command':str(command)[:80],'created_at':time.time()};rows.append(row)
        row.update(message=str(message)[:2000],status=status,updated_at=time.time())
        write(journal,rows[-300:])
        return row['id']

def tracked(app,pid,command,fn):
    identifier=activity(app,pid,command,command.replace('_',' '),'running')
    try:
        result=fn()
    except Exception as exc:
        activity(app,pid,command,str(exc),'failed',identifier)
        raise
    activity(app,pid,command,'Command accepted; rendering continues below.' if command in ('export_video','apply_notes','approve_proposal') else 'Completed','done',identifier)
    with LOCK:return public(load(app,pid))

def execute(app,pid,op,args):
    if op=='generate_studio_captions':
        import quick_studio
        return quick_studio.queue_captions(app,pid,args)
    import quick_learning
    if op in quick_learning.TOOLS:return quick_learning.execute(app,pid,op,args)
    if op in HANDOFF_OPERATIONS:
        return revision_handoff(app, pid, op, args)
    if op in ('get_project','get_timeline'):return _execute(app,pid,op,args)
    if op=='log_activity':
        message=args.get('message');status=args.get('status','running')
        if not isinstance(message,str) or not message.strip() or len(message)>2000:raise ValueError('Provide a progress message of 1–2000 characters.')
        if status not in ('running','done','failed'):raise ValueError('Use running, done or failed.')
        activity(app,pid,'agent',message,status)
        with LOCK:return public(load(app,pid))
    return tracked(app,pid,str(op),lambda:_execute(app,pid,op,args))

def revision_handoff(app, pid, op, args):
    """Delivery journal is independent of timeline versions and undo history.

    A host acknowledgment is only submission. Only the receiving model, holding
    the token embedded in the message, can acknowledge receipt. Never auto-retry
    an ambiguous send: the host bridge has no idempotency-key contract.
    """
    with LOCK:
        doc = load(app, pid)
        path = app.WORK / pid / 'revision-handoffs.json'
        rows = json.loads(path.read_text()) if path.exists() else []
        may_send = False
        if op == 'begin_revision_handoff':
            expected = args.get('expected_version')
            if type(expected) is not int or expected != doc['version']:
                raise Conflict('Timeline changed. Rebuild the implementation prompt before sending.')
            text = args.get('prompt')
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > 128000:
                raise ValueError('Provide an implementation prompt of 1–128000 bytes.')
            digest = hashlib.sha256(text.encode()).hexdigest()
            row = next((r for r in reversed(rows) if r['digest'] == digest), None)
            if row is None:
                if len(rows)>=200:
                    raise ValueError('This project has 200 saved handoffs. Its history is preserved; start a new project for additional handoffs.')
                prior = next((c for c in doc['checkpoints'] if c.get('prompt_digest')==digest and c.get('timeline_version')==expected), None)
                identifier, token = prior['id'] if prior else uuid.uuid4().hex, uuid.uuid4().hex
                row = {'id': identifier, 'project_id': pid, 'version': expected,
                       'digest': digest, 'receipt_token': token, 'created_at': time.time(),
                       'attempt': 0, 'status': 'not_sent',
                       'prompt': text + '\n\n## Confirm receipt before editing\n'
                       + 'After receiving this message in the chat, call acknowledge_revision_handoff '
                       + 'with project_id="' + pid + '", handoff_id="' + identifier
                       + '", receipt_token="' + token + '". This records receipt only; '
                       + 'it does not mark the requested edits or render as completed. '
                       + 'If that tool is unavailable, report the handoff ID in your reply and continue the requests; do not claim a recorded receipt.'}
                # Persist the exact review state before releasing a prompt to the host.
                # Retry uses this ID, so a lost journal write cannot duplicate versions.
                import quick_sections
                rendered = doc.get('rendered')
                source = next(c for c in doc['checkpoints'] if c['id']=='source')
                if rendered and rendered.get('clips') == doc['clips']:
                    output = app.WORK/pid/'versions'/rendered['proposal_id']/'edited.mp4'
                    if not output.is_file() or output.stat().st_size == 0:
                        raise ValueError('The saved video is unavailable. Export before sending revisions.')
                elif doc['clips'] != source['clips']:
                    raise ValueError('Export the current timeline before sending revisions.')
                else:
                    rendered = None  # The unchanged original is already a saved video.
                output = app.WORK/pid/'versions'/rendered['proposal_id']/'edited.mp4' if rendered else app.WORK/pid/'input.mp4'
                if not output.is_file() or output.stat().st_size == 0:
                    raise ValueError('The saved video is unavailable. Import or export before sending revisions.')
                with output.open('rb') as stream:
                    digest_video = hashlib.sha256()
                    for chunk in iter(lambda:stream.read(1048576), b''): digest_video.update(chunk)
                    video_sha256 = digest_video.hexdigest()
                if not prior: quick_sections.checkpoint(doc, 'Before revision prompt', identifier)
                saved = prior or doc['checkpoints'][-1]
                comments_file=app.WORK/pid/'frame-comments.json'
                frame_comments=json.loads(comments_file.read_text()) if comments_file.exists() else []
                saved.update(kind='prompt', frame_comments=frame_comments, rendered=copy.deepcopy(rendered), handoff_id=identifier,
                             prompt=text, prompt_digest=digest, video_sha256=video_sha256, video_bytes=output.stat().st_size, saved_video_id=rendered['proposal_id'] if rendered else 'source')
                row['checkpoint_id'] = identifier
                write(app.WORK/pid/'timeline.json', doc)
                rows.append(row)
            if row['status'] == 'not_sent':
                row.update(status='sending', attempt=row['attempt'] + 1, updated_at=time.time(), error='')
                may_send = True
        else:
            identifier = args.get('handoff_id')
            row = next((r for r in rows if r['id'] == identifier), None)
            if row is None:
                raise ValueError('Handoff does not exist in this project.')
            if op == 'acknowledge_revision_handoff':
                import hmac
                token = args.get('receipt_token')
                if not isinstance(token, str) or not hmac.compare_digest(token, row['receipt_token']):
                    raise ValueError('Receipt token does not match the delivered prompt.')
                row.update(status='received', received_at=row.get('received_at', time.time()), updated_at=time.time())
            elif op == 'finish_revision_handoff':
                status = args.get('status')
                if status not in ('submitted', 'not_sent', 'uncertain'):
                    raise ValueError('Use submitted, not_sent, or uncertain for the transport result.')
                if type(args.get('attempt')) is not int or args['attempt'] != row['attempt']:
                    raise Conflict('This send attempt is no longer current.')
                # Receipt may arrive while the original host call is still waiting.
                if row['status'] == 'sending':
                    row.update(status=status, updated_at=time.time(), error=str(args.get('error', ''))[:1000])
            elif op != 'get_revision_handoff':
                raise ValueError('Unknown handoff action.')
        if op != 'get_revision_handoff':
            write(path, rows)
        result = {k: copy.deepcopy(v) for k, v in row.items() if k not in ('receipt_token', 'prompt')}
        if op == 'begin_revision_handoff':
            result.update(prompt=row['prompt'], may_send=may_send)
        return result

def _execute(app, pid, op, args):
    regions = []
    if op == 'tighten_pacing' and args.get('remove_pauses', True):
        with LOCK:
            initial = load(app, pid)
            if args.get('expected_version') != initial['version']:
                raise Conflict('Timeline changed. Reload before measuring pauses.')
        # Audio analysis must not block other projects or timeline reads.
        if initial['audio']:
            regions = detect_silence(app.WORK / pid / 'input.mp4')
    with LOCK:
        doc=load(app,pid)
        if op in ('get_project','get_timeline'):
            result=public(doc)
            import quick_learning
            result['creative_memory']=quick_learning.memory(app,doc)
            return result
        expected=args.get('expected_version')
        if isinstance(expected,bool) or not isinstance(expected,int) or expected != doc['version']:
            raise Conflict('Timeline changed. Reload and retry with its current expected_version.')
        if op=='export_video':
            if not doc['clips']: raise ValueError('Add a segment before exporting.')
            if sum(e['status']=='working' for e in doc['exports']) >= 2:
                raise ValueError('Two exports are already queued; wait for one to finish.')
            section_id=args.get('section_id')
            snapshot=copy.deepcopy(doc)
            if section_id is not None:
                import quick_sections
                pin=quick_sections.section(doc,section_id)
                a,b=pin['start'],pin['end']
                # Section download is the original source interval, independent of timeline cuts.
                snapshot['clips']=[clip(a,b)]
                snapshot['studio']={}
                validate(snapshot)
            eid=uuid.uuid4().hex
            exp={'id':eid,'timeline_version':doc['version'],'status':'working','created':time.time(),
                 'duration':sum(c['end']-c['start'] for c in snapshot['clips']),
                 **({'section_id':section_id,'source_start':a,'source_end':b} if section_id is not None else {}),
                 'url':'/media/'+pid+'/versions/'+eid+'/edited.mp4'}
            doc['exports'].append(exp)
            write(app.WORK/pid/'timeline.json',doc)
            threading.Thread(target=export_worker,args=(app,pid,snapshot,eid),daemon=True).start()
            return public(doc)
        import quick_studio
        before=quick_studio.snapshot(doc)
        if op in ('undo','redo'):
            source,target=('undo','redo') if op=='undo' else ('redo','undo')
            if not doc[source]: raise ValueError('Nothing to '+op+'.')
            doc[target].append(before)
            quick_studio.restore(doc, doc[source].pop())
        else:
            if op=='set_studio':
                doc['studio']=quick_studio.validate(app,pid,doc,args.get('studio'))
            elif op in ('split_clip','trim_clip','delete_segment','move_segment','position_clip'):
                idx=next((i for i,c in enumerate(doc['clips']) if c['id']==args.get('clip_id')),None)
                if idx is None: raise ValueError('Select a current segment.')
                c=doc['clips'][idx]
                if op=='split_clip':
                    at=number(args.get('source_time'))
                    if not c['start']+.04 <= at <= c['end']-.04: raise ValueError('Split inside the selected clip, away from its edges.')
                    doc['clips'][idx:idx+1]=[dict(c,end=at,origin_id=c.get('origin_id',c['id'])),dict(c,id=uuid.uuid4().hex,start=at,origin_id=c.get('origin_id',c['id']))]
                elif op=='trim_clip':
                    a,b=number(args.get('start')),number(args.get('end'))
                    doc['clips'][idx]=dict(c,start=a,end=b)
                elif op=='position_clip':
                    doc['clips'][idx]=dict(c,x=number(args.get('x')),y=number(args.get('y')))
                elif op=='delete_segment':
                    doc['clips'].pop(idx)
                else:
                    pos=args.get('position')
                    if isinstance(pos,bool) or not isinstance(pos,int) or not 0<=pos<len(doc['clips']): raise ValueError('Invalid destination index.')
                    doc['clips'].insert(pos,doc['clips'].pop(idx))
            elif op=='tighten_pacing':
                # Explicit deterministic preset; energy-based silence, not language interpretation.
                cut=number(args.get('cut_first_seconds',0))
                if cut<0: raise ValueError('Opening cut must be nonnegative.')
                keep=[]
                for c in doc['clips']:
                    length=c['end']-c['start']
                    if cut>=length: cut-=length; continue
                    ranges=[[c['start']+cut,c['end']]];cut=0
                    if args.get('remove_pauses',True):ranges=trim_pauses(ranges,regions)
                    for i,(a,b) in enumerate(ranges):
                        keep.append(dict(c,id=c['id'] if i==0 else uuid.uuid4().hex,start=a,end=b))
                if not keep: raise ValueError('Opening cut would remove the entire timeline.')
                doc['clips']=keep
            elif op=='sync_editor_state':
                editor_changed=sync_editor_state(app,pid,doc,args)
            else: raise ValueError('Unknown operation.')
            validate(doc)
            if before==quick_studio.snapshot(doc):
                if op=='sync_editor_state' and editor_changed:
                    # Editor-only detail (grade wheels, caption style, media pool) is saved without a new video version.
                    write(app.WORK/pid/'timeline.json',doc)
                return public(doc)
            doc['undo']=(doc['undo']+[before])[-100:]
            doc['redo']=[]
        doc['version']+=1
        logged={k:v for k,v in args.items() if k!='expected_version'}
        if op=='sync_editor_state':
            logged={'clips':len(doc['clips']),'captions':len(doc.get('studio',{}).get('captions',[])),'provider':str(args.get('provider','editor'))[:80]}
        doc.setdefault('accepted_edits',[]).append({'id':uuid.uuid4().hex,'provider':str(args.get('provider','manual'))[:80] if op=='sync_editor_state' else 'manual','operation':op,'arguments':logged,'timeline_version':doc['version'],'accepted_at':time.time()})
        doc['accepted_edits']=doc['accepted_edits'][-2000:]
        validate(doc)
        write(app.WORK/pid/'timeline.json',doc)
        return public(doc)

EDITOR_STATE_LIMIT=400000

def sync_editor_state(app,pid,doc,args):
    """Replace the cut and finishing settings from the Swarmcut editor in one undoable revision.

    clips are original-source ranges in playback order. studio is validated by quick_studio.
    editor_state is the editor's own project (tracks, grade wheels, caption style) kept so a
    reload restores exactly what the creator saw; None clears it after a headless edit.
    """
    rows=args.get('clips')
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_SEGMENTS:raise ValueError('Keep between 1 and %d sections.' % MAX_SEGMENTS)
    known={c['id'] for c in doc['clips']}
    clips=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Each section needs a start and end.')
        cid=row.get('id') if isinstance(row.get('id'),str) and re.fullmatch(ID,row['id']) and row['id'] not in seen else uuid.uuid4().hex
        seen.add(cid)
        item={'id':cid,'start':number(row.get('start')),'end':number(row.get('end'))}
        prior=next((c for c in doc['clips'] if c['id']==cid),None) if cid in known else None
        if prior and 'origin_id' in prior:item['origin_id']=prior['origin_id']
        clips.append(item)
    doc['clips']=clips
    if 'studio' in args:
        import quick_studio
        doc['studio']=quick_studio.validate(app,pid,doc,args['studio'])
    if 'editor_state' not in args:return False
    state=args['editor_state']
    if state is None:
        return doc.pop('editor_state',None) is not None
    if not isinstance(state,dict):raise ValueError('Editor state must be an object.')
    encoded=json.dumps(state,allow_nan=False,separators=(',',':'))
    if len(encoded.encode())>EDITOR_STATE_LIMIT:raise ValueError('Editor state is too large to save.')
    changed=doc.get('editor_state')!=state
    doc['editor_state']=json.loads(encoded)
    return changed

def export_worker(app,pid,snapshot,eid):
    folder=app.WORK/pid/'versions'/eid
    try:
        folder.mkdir(parents=True)
        with app.WORKERS:
            duration=render_timeline(app.WORK/pid/'input.mp4',folder,[(c['start'],c['end']) for c in snapshot['clips']],snapshot['audio'],lambda _:None,positions=[(c.get('x',0),c.get('y',0)) for c in snapshot['clips']])
            import quick_studio
            if snapshot.get('studio'): quick_studio.render(app,pid,snapshot,folder)
        result={'status':'done','measured_duration':duration}
        if snapshot.get('recipe_runs'):
            import quick_recipe_apply
            manifest = {'timeline_version': snapshot['version'], 'export_id': eid,
                        'video_sha256': quick_recipe_apply.source_sha(folder/'edited.mp4'),
                        'video_state': quick_studio.snapshot(snapshot),
                        'runs': copy.deepcopy(snapshot['recipe_runs'])}
            write(folder/'recipe-provenance.json', manifest)
            result['recipe_provenance'] = manifest
        import quick_asset_capture
        result.update(quick_asset_capture.capture_render(
            app,pid,eid,folder/'edited.mp4',
            snapshot.get('name','Frame')+' render '+eid[:8],snapshot['version']))
    except Exception as exc:
        result={'status':'failed','error':str(exc)[-1200:]}
    with LOCK:
        doc=load(app,pid)
        exported=next(e for e in doc['exports'] if e['id']==eid);exported.update(result)
        if result['status']=='done' and not exported.get('section_id'):
            rendered={'url':exported['url'],'duration':duration,'timeline_version':snapshot['version'],'proposal_id':eid,'clips':copy.deepcopy(snapshot['clips']),'studio':copy.deepcopy(snapshot.get('studio',{}))}
            import quick_sections
            if doc['version']==snapshot['version']:
                doc['rendered']=rendered
                quick_sections.checkpoint(doc,'Manual edit export',eid)
            else:
                # A completed export remains a selectable revision even if editing
                # continued while FFmpeg was running. Do not replace the live head.
                snapshot['rendered']=rendered
                quick_sections.checkpoint(snapshot,'Saved export',eid)
                doc['checkpoints'].append(copy.deepcopy(snapshot['checkpoints'][-1]))
        write(app.WORK/pid/'timeline.json',doc)

def recover(app):
    for path in app.WORK.glob('*/timeline.json'):
        with LOCK:
            doc=json.loads(path.read_text());changed=False
            if doc.get('caption_job',{}).get('status')=='working':doc['caption_job'].update(status='failed',error='Frame restarted. Generate captions again.');changed=True
            for exp in doc['exports']:
                if exp['status']=='working':
                    exp.update(status='failed',error='Server restarted; export again. Your timeline is saved.');changed=True
            if changed: write(path,doc)

def route(handler, app, method):
    from urllib.parse import urlparse
    path=urlparse(handler.path).path
    if method=='GET' and path=='/api/quick/tools':
        handler.json(200,{'operations':OPERATIONS,'command_endpoint':'/api/quick/projects/{project_id}/commands',
                          'versioning':'Timeline mutations and handoff reservation require integer expected_version. Delivery receipts do not change the timeline. Conflicts return 409.',
                          'timebase':'clip start/end/source_time use original-source seconds; move position is zero based.'})
        return True
    match=re.fullmatch('/api/quick/projects/('+ID+')(?:/(timeline|commands))?',path)
    if not match:return False
    try:
        if method=='GET' and match[2] in (None,'timeline'):
            result=execute(app,match[1],'get_project',{})
        elif method=='POST' and match[2]=='commands':
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=600000: raise ValueError('Command is too large.')
            handler.connection.settimeout(20)
            body=json.loads(handler.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('Expected a JSON command object.')
            if length>16000 and body.get('operation') not in ('begin_revision_handoff','set_studio','sync_editor_state'):
                raise ValueError('Command must be 1–16000 bytes.')
            result=execute(app,match[1],body.get('operation'),body)
        else: raise ValueError('Unsupported request.')
        handler.json(200,result)
    except Conflict as exc:handler.json(409,{'error':str(exc)})
    except (ValueError,FileNotFoundError,TypeError,KeyError) as exc:handler.json(400,{'error':str(exc)})
    return True
