"""Ordered source-anchored review notes over the existing revision transaction."""
import copy
import re
import threading
import time
import uuid
import quick_timeline as timeline
import quick_revision as revision

ACTIONS={'attach_reference_clip','remove_reference_clip','add_video_reference','remove_video_reference','add_reference_moment','add_reference','remove_reference','add_note','add_general_note','add_annotation','edit_note','remove_note','keep_note','apply_notes','restore_checkpoint','manual_range_edit'}


def initialize(doc):
    changed=False
    for key,value in {'notes':[],'active_revision_set_id':uuid.uuid4().hex,'checkpoints':[]}.items():
        if key not in doc:doc[key]=value;changed=True
    if not doc['checkpoints']:
        root=doc['clips'][0].get('origin_id',doc['clips'][0]['id']) if doc['clips'] else uuid.uuid4().hex
        doc['checkpoints'].append({'id':'source','parent_id':None,'label':'Original upload','created_at':doc.get('saved_at',time.time()),
            'clips':[{'id':root,'start':0,'end':int(doc['source_duration']*30+1e-6)/30}],
            'rendered':None,'accepted_edits':[]})
        if doc.get('rendered'):
            checkpoint(doc,'Existing saved result')
        else:doc['current_checkpoint_id']='source'
        changed=True
    current=next((c for c in doc['checkpoints'] if c['id']==doc.get('current_checkpoint_id')),None)
    if current is None or not same_video(current,doc):
        save_video_revision(doc);changed=True
    return changed


def checkpoint(doc,label,identifier=None):
    cid=identifier or uuid.uuid4().hex
    doc['checkpoints'].append({'id':cid,'parent_id':doc.get('current_checkpoint_id','source'),
        'label':label,'created_at':time.time(),'timeline_version':doc['version'],'clips':copy.deepcopy(doc['clips']),
        'rendered':copy.deepcopy(doc['rendered']),'accepted_edits':copy.deepcopy(doc['accepted_edits']),
        'studio':copy.deepcopy(doc.get('studio',{})),
        'notes':copy.deepcopy(doc.get('notes',[])), 'pins':copy.deepcopy(doc.get('pins',[])),
        'kind':'video' if doc.get('rendered') and doc['rendered'].get('clips')==doc['clips'] and doc['rendered'].get('studio',{})==doc.get('studio',{}) else 'edit'})
    doc['current_checkpoint_id']=cid
    return cid


def same_video(a,b):
    return a.get('clips')==b.get('clips') and a.get('rendered')==b.get('rendered') and a.get('studio',{})==b.get('studio',{})


def save_video_revision(doc):
    current=next((c for c in doc['checkpoints'] if c['id']==doc.get('current_checkpoint_id')),None)
    if current is None or not same_video(current,doc):
        last=doc.get('accepted_edits',[])[-1:]
        label=last[0].get('operation','Timeline edit').replace('_',' ').capitalize() if last else 'Timeline edit'
        checkpoint(doc,label)


def section(doc,sid):
    pin=next((p for p in doc['pins'] if p['id']==sid),None)
    if not pin:raise ValueError('Select an existing section with start/end pins.')
    revision.bounds(doc,pin)
    return pin


def saved_note_attempt(doc,body):
    """Recognize a committed note when the original response was lost.

    A fresh identical note is still a new request: only the exact stale creation
    version, scope and payload can resume a still-queued note in the same set.
    """
    action=body.get('action');version=body.get('expected_version')
    if action not in ('add_note','add_general_note') or type(version) is not int or version>=doc['version']:return False
    if any(k in body for k in ('annotations','pinpoints')):return False
    general=action=='add_general_note'
    if general and any(k in body for k in ('section_id','source_time_ms')):return False
    if not general and type(body.get('source_time_ms')) is not int:return False
    output=body.get('output_time_ms') if type(body.get('output_time_ms')) is int else None
    return any(n.get('created_version')==version and n.get('revision_set_id')==doc.get('active_revision_set_id')
        and n.get('status')=='queued' and n.get('included') is not False
        and not n.get('annotations') and n.get('scope')==('general' if general else 'section')
        and n.get('section_id')==(None if general else body.get('section_id'))
        and n.get('source_time_ms')==(None if general else body.get('source_time_ms'))
        and n.get('output_time_ms')==output and n.get('instruction')==body.get('instruction')
        for n in doc.get('notes',[]))


def act(app,pid,body):
    action=body.get('action')
    with timeline.LOCK:
        doc=timeline.load(app,pid)
        # A repeated request token resumes exactly the original frozen set, even after completion.
        if action=='apply_notes':
            token=body.get('request_id','')
            if not isinstance(token,str) or not re.fullmatch('[a-zA-Z0-9_-]{8,80}',token):raise ValueError('Supply a stable request_id to apply this revision set.')
            if any(p.get('request_id')==token for p in doc['proposals']):return timeline.public(doc)
        if saved_note_attempt(doc,body):return timeline.public(doc)
        if type(body.get('expected_version')) is not int or body['expected_version']!=doc['version']:
            raise timeline.Conflict('Revision changed. Reload the note list before applying.')
        if action in ('attach_reference_clip','remove_reference_clip'):
            if body.get('note_id'):
                target=next((n for n in doc['notes'] if n['id']==body['note_id']),None)
                if not target:raise ValueError('Revision not found.')
            else:target=section(doc,body.get('section_id'))
            refs=target.setdefault('reference_clips',[])
            if action=='remove_reference_clip':
                ref=next((r for r in refs if r['id']==body.get('reference_id')),None)
                if not ref:raise ValueError('Reference clip not found.')
                refs.remove(ref)
            else:
                existing=next((r for r in refs if r['id']==body.get('reference_id')),None)
                if body.get('reference_id') and not existing:raise ValueError('Reference clip not found on this revision.')
                if not existing and len(refs)>=6:raise ValueError('Maximum six reference clips per revision.')
                rid=body.get('reference_project_id');aid=body.get('asset_id');eid=body.get('export_id')
                if not isinstance(rid,str) or not re.fullmatch(timeline.ID,rid):raise ValueError('Choose an existing project video.')
                source=doc if rid==pid else timeline.load(app,rid)
                folder=(app.WORK/rid).resolve()
                if aid and eid:raise ValueError('Choose one project video item.')
                if aid:
                    asset=next((a for a in source.get('assets',[]) if a['id']==aid and (a.get('mime_type','').startswith('video/') or str(a.get('name','')).lower().endswith(('.mp4','.mov','.m4v','.webm')))),None)
                    if not asset:raise ValueError('Project video asset not found.')
                    path=(folder/asset['path']).resolve();name=asset['name']
                elif eid:
                    if not isinstance(eid,str) or not re.fullmatch(timeline.ID,eid) or timeline.completed_export(source,eid) is None:raise ValueError('Choose a completed saved video.')
                    path=folder/'versions'/eid/'edited.mp4'
                    saved=next((c for c in reversed(source.get('checkpoints',[])) if (c.get('rendered') or {}).get('proposal_id')==eid),None)
                    name=source['name']+' · '+(saved['label'] if saved else 'Saved export')
                else:
                    path=folder/'input.mp4';name=source['name']
                if not path.is_relative_to(folder):raise ValueError('Invalid project video path.')
                duration=timeline.probe(path,enforce_limit=False)['duration']
                start=timeline.number(body.get('start'));end=timeline.number(body.get('end'))
                if not 0<=start<end<=duration:raise ValueError('Pin a start and end inside the reference video.')
                import hashlib
                digest=hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
                attachment={'id':existing['id'] if existing else uuid.uuid4().hex,'project_id':rid,'asset_id':aid,'export_id':eid,'name':name,
                    'start':start,'end':end,'duration':duration,'sha256':digest.hexdigest(),'created_at':existing['created_at'] if existing else time.time()}
                if existing:refs[refs.index(existing)]=attachment
                else:refs.append(attachment)
            doc['version']+=1
            timeline.write(app.WORK/pid/'timeline.json',doc);return timeline.public(doc)
        if action in ('add_video_reference','remove_video_reference'):
            rid=body.get('reference_project_id')
            if not isinstance(rid,str) or not re.fullmatch(timeline.ID,rid) or rid==pid:raise ValueError('Choose a different saved video as reference.')
            refs=doc.setdefault('video_references',[])
            if action=='add_video_reference':
                source=timeline.load(app,rid)
                if any(r['project_id']==rid for r in refs):return timeline.public(doc)
                if len(refs)>=20:raise ValueError('Maximum 20 reference videos per project.')
                import hashlib
                digest=hashlib.sha256()
                with (app.WORK/rid/'input.mp4').open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
                duplicate=next((r for r in refs if r.get('sha256')==digest.hexdigest()),None)
                if duplicate:return timeline.public(doc) | {'linked_reference_project_id':duplicate['project_id']}
                refs.append({'project_id':rid,'name':source['name'],'duration':source['source_duration'],'sha256':digest.hexdigest(),'created_at':time.time()})
            else:
                ref=next((r for r in refs if r['project_id']==rid),None)
                if not ref:raise ValueError('Reference video not found.')
                refs.remove(ref)
            doc['version']+=1
            timeline.write(app.WORK/pid/'timeline.json',doc);return timeline.public(doc)
        if action in ('add_reference','remove_reference','add_reference_moment'):
            pin=section(doc,body.get('section_id'))
            moment=None
            if action=='add_reference_moment':
                rid=body.get('reference_project_id')
                if not any(r['project_id']==rid for r in doc.get('video_references',[])):raise ValueError('Save this reference video first.')
                source=timeline.load(app,rid);t=timeline.number(body.get('reference_time'))
                if not 0<=t<source['source_duration']:raise ValueError('Choose a frame inside the reference video.')
                validate_text(body.get('instruction'))
                if len(doc['notes'])>=300:raise ValueError('Maximum 300 review notes per project.')
                moment={'project_id':rid,'time':t,'name':source['name']}
            refs=pin.setdefault('references',[])
            if action=='remove_reference':
                ref=next((r for r in refs if r['id']==body.get('reference_id')),None)
                if not ref:raise ValueError('Reference image not found.')
                refs.remove(ref) # Retain bytes for project history; unlink only this section attachment.
            else:
                import base64,hashlib
                if len(refs)>=6:raise ValueError('Maximum six reference images per section.')
                try:raw=base64.b64decode(body.get('image_base64',''),validate=True)
                except Exception:raise ValueError('Invalid reference image.')
                if not 0<len(raw)<=262144:raise ValueError('Reference must be at most 256 KB. Choose a smaller image.')
                if raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg';ext='jpg'
                elif raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png';ext='png'
                elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP':mime='image/webp';ext='webp'
                else:raise ValueError('Choose a PNG, JPEG or WebP image.')
                from PIL import Image
                import io
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.width*image.height>16000000:raise ValueError('Reference image dimensions are too large.')
                        image.verify()
                except Exception:raise ValueError('Reference image could not be decoded.')
                rid=uuid.uuid4().hex;relative='assets/'+rid+'/reference.'+ext
                target=app.WORK/pid/relative;target.parent.mkdir(parents=True)
                target.write_bytes(raw)
                name=str(body.get('name','Reference image')).replace('\\','/').split('/')[-1][:180]
                ref={'id':rid,'name':name,'mime_type':mime,'path':relative,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'created_at':time.time()}
                if moment:ref['video_reference']=moment
                refs.append(ref)
                if moment:
                    doc['notes'].append({'id':uuid.uuid4().hex,'project_id':pid,'section_id':pin['id'],
                        'revision_set_id':doc['active_revision_set_id'],'source_time_ms':int(pin['start']*1000),
                        'base_version_id':doc.get('current_checkpoint_id','source'),'output_time_ms':None,
                        'order':max((n['order'] for n in doc['notes']),default=0)+1,'created_at':time.time(),
                        'status':'queued','included':True,'reference_id':rid,'video_reference':moment,
                        'instruction':body['instruction']})
                doc.setdefault('assets',[]).append(copy.deepcopy(ref))
            doc['version']+=1
            timeline.write(app.WORK/pid/'timeline.json',doc);return timeline.public(doc)
        if action=='manual_range_edit':
            pin=section(doc,body.get('section_id'));a,b=revision.bounds(doc,pin)
            before=copy.deepcopy(doc['clips'])
            if body.get('operation')=='cut':
                doc=revision.candidate(doc,{'operation':'delete_range','clip_id':pin['clip_id'],'range_start':a,'range_end':b})
            elif body.get('operation')=='keep':
                a,b=round(a*30)/30,round(b*30)/30
                doc['clips']=[dict(c,start=max(a,c['start']),end=min(b,c['end'])) for c in doc['clips'] if c.get('origin_id',c['id'])==pin['clip_id'] and min(b,c['end'])>max(a,c['start'])]
                timeline.validate(doc)
                if not doc['clips']:raise ValueError('This section is no longer retained.')
            else:raise ValueError('Use Cut section or Keep section.')
            if doc['clips']==before:raise ValueError('This section already matches the current edit.')
            doc['undo']=(doc['undo']+[before])[-100:];doc['redo']=[];doc['version']+=1
            doc['accepted_edits'].append({'id':uuid.uuid4().hex,'provider':'manual','operation':body['operation']+'_section','source_start':a,'source_end':b,'accepted_at':time.time()})
            revision.persist(app,pid,doc);return timeline.public(doc)
        if action=='restore_checkpoint':
            target=next((c for c in doc['checkpoints'] if c['id']==body.get('checkpoint_id')),None)
            if not target:raise ValueError('Saved version not found.')
            if any(p['status'] in ('planning','rendering') for p in doc['proposals']):raise ValueError('Wait for the current proposal or render before restoring.')
            import quick_studio
            doc['undo']=(doc['undo']+[quick_studio.snapshot(doc)])[-100:];doc['redo']=[]
            doc['clips']=copy.deepcopy(target['clips']);doc['rendered']=copy.deepcopy(target['rendered']);doc['studio']=copy.deepcopy(target.get('studio',{}))
            # Preserve the complete accepted-operation journal and every playable checkpoint.
            doc['current_checkpoint_id']=target['id'];doc['version']+=1
            checkpoint(doc,'Restored '+target['label'])
            revision.persist(app,pid,doc);return timeline.public(doc)
        if action in ('add_note','add_general_note','add_annotation'):
            if len(doc['notes'])>=300:raise ValueError('Maximum 300 review notes per project.')
            text=body.get('instruction','')
            validate_text(text)
            annotations=None
            if action=='add_general_note':
                pin=None;anchor=None
                if any(key in body for key in ('section_id','source_time_ms','pinpoints','annotations')):
                    raise ValueError('General revisions apply to the whole version without section or timestamp anchors.')
            elif action=='add_annotation':
                import quick_markup
                pin,anchor,annotations=quick_markup.prepare(doc,body)
            else:
                pin=section(doc,body.get('section_id'));a,b=revision.bounds(doc,pin)
                anchor=timeline.number(body.get('source_time_ms'))
                if int(anchor)!=anchor or not a*1000<=anchor<b*1000:raise ValueError('The note playhead must be inside the section (end excluded).')
            note={'id':uuid.uuid4().hex,'project_id':pid,'section_id':pin['id'] if pin else None,
                  'scope':'section' if pin else 'general',
                  'created_version':doc['version'],
                  'revision_set_id':doc['active_revision_set_id'],'source_time_ms':int(anchor) if anchor is not None else None,
                  'base_version_id':doc.get('current_checkpoint_id','source'),
                  'output_time_ms':body.get('output_time_ms') if type(body.get('output_time_ms')) is int else None,
                  'order':max((n['order'] for n in doc['notes']),default=0)+1,'created_at':time.time(),
                  'status':'queued','included':True}
            note['instruction']=text
            if annotations is not None:note['annotations']=annotations
            doc['notes'].append(note)
        elif action in ('edit_note','remove_note','keep_note'):
            note=next((n for n in doc['notes'] if n['id']==body.get('note_id')),None)
            if not note:raise ValueError('Review note not found.')
            if any(note['id'] in [n['id'] for n in p.get('frozen_notes',[])] and p['status'] in ('planning','rendering') for p in doc['proposals']):
                raise ValueError('This note is in an active frozen revision set. Wait for it to finish.')
            if action=='edit_note':
                validate_text(body.get('instruction'))
                if 'pinpoints' in body:
                    if note.get('scope')=='general':raise ValueError('General revisions do not have pinpoints.')
                    points=body['pinpoints'];pin=section(doc,note['section_id']);a,b=revision.bounds(doc,pin)
                    if not isinstance(points,list) or not 1<=len(points)<=24 or any(type(t) is not int or not any(c['start']*1000<=t<c['end']*1000 for c in doc['clips']) for t in points):
                        raise ValueError('Use 1–24 retained source timestamps for this revision.')
                    note['pinpoints']=list(dict.fromkeys([note['source_time_ms'],*points]))
                    if len(note['pinpoints'])>24:raise ValueError('Maximum 24 pinpoints per revision.')
                note['instruction']=body['instruction']
            note.update(included=action!='remove_note',status='removed' if action=='remove_note' else 'queued',revision_set_id=doc['active_revision_set_id'])
            note.pop('error',None)
        elif action=='apply_notes':
            if any(p['status'] in ('planning','rendering') for p in doc['proposals']):raise ValueError('A revision set is already being planned or rendered.')
            notes=sorted((copy.deepcopy(n) for n in doc['notes'] if n['included'] and n['status'] in ('queued','unsupported','failed')),key=lambda n:n['order'])
            if not notes:raise ValueError('Add or keep at least one queued revision note.')
            if len(notes)>20:raise ValueError('Apply at most 20 notes in one set.')
            for n in notes:
                if n.get('scope')!='general':section(doc,n['section_id'])
            proposal={'id':uuid.uuid4().hex,'base_version':doc['version'],'status':'planning','created_at':time.time(),
                      'request_id':token,'revision_set_id':doc['active_revision_set_id'],'frozen_notes':notes,
                      'note_results':[],'base_checkpoint_id':doc.get('current_checkpoint_id','source')}
            doc['proposals'].append(proposal);revision.persist(app,pid,doc)
            threading.Thread(target=plan_set,args=(app,pid,copy.deepcopy(doc),proposal['id']),daemon=True).start()
            return timeline.public(doc)
        else:raise ValueError('Unsupported note action.')
        doc['version']+=1;revision.persist(app,pid,doc);return timeline.public(doc)


def validate_text(text):
    if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Write a revision note using 1–2000 characters.')


def overlapping(a,b):
    return a['clip_id']==b['clip_id'] and min(a['range_end'],b['range_end'])>max(a['range_start'],b['range_start'])


def plan_set(app,pid,snapshot,proposal_id):
    frozen=next(p for p in snapshot['proposals'] if p['id']==proposal_id)
    operations=[];results=[]
    try:
        for n in frozen['frozen_notes']:
            if n.get('scope')=='general':
                results.append({'note_id':n['id'],'status':'unsupported','message':'Send general revisions to the chat using the implementation prompt.'})
                continue
            pin=copy.deepcopy(section(snapshot,n['section_id']))
            pin.update(instruction=n['instruction'],note_source_time_ms=n['source_time_ms'])
            try:
                operation=revision.interpret(snapshot,pin,app)
                duplicate=False
                for prior in operations:
                    if not overlapping(prior,operation):continue
                    if prior['operation']==operation['operation']=='position_clip' and prior['x']==operation['x'] and prior['y']==operation['y']:
                        if (prior['range_start'],prior['range_end'])==(operation['range_start'],operation['range_end']):duplicate=True
                        continue
                    raise ValueError('Conflicting notes target overlapping footage. Adjust or remove one note before applying; no render was started.')
                if not duplicate:operations.append(operation)
                results.append({'note_id':n['id'],'status':'supported','operation':operation,
                                'message':'Same operation as an earlier note; shared in the combined render.' if duplicate else operation['message']})
            except revision.Unsupported as exc:
                results.append({'note_id':n['id'],'status':'unsupported','message':str(exc)})
            with timeline.LOCK:
                doc=timeline.load(app,pid);p=next(p for p in doc['proposals'] if p['id']==proposal_id)
                p['note_results']=copy.deepcopy(results);revision.persist(app,pid,doc)
        if not operations:raise ValueError('None of these notes can be executed. Review the unsupported explanations; no video was changed.')
        operation={'operation':'batch','operations':operations,'provider':'claude',
                   'message':'One render for the supported notes, in creation order. Unsupported notes remain visible and unchanged.'}
        revision.candidate(snapshot,operation)
        result={'status':'pending','operation':operation,'note_results':results,
                'warning':'Transcript is unavailable for this review flow. Cuts may remove speech or context; inspect exact source intervals before approval.'}
    except Exception as exc:result={'status':'failed','error':str(exc)[-1200:],'note_results':results}
    with timeline.LOCK:
        doc=timeline.load(app,pid);p=next(p for p in doc['proposals'] if p['id']==proposal_id);p.update(result)
        for n in doc['notes']:
            r=next((r for r in results if r['note_id']==n['id']),None)
            if r and r['status']=='unsupported':n.update(status='unsupported',error=r['message'])
        revision.persist(app,pid,doc)


def mark_applied(doc,proposal):
    for n in doc['notes']:
        result=next((r for r in proposal.get('note_results',[]) if r['note_id']==n['id']),None)
        if result:
            n.update(status='applied' if result['status']=='supported' else 'unsupported',applied_checkpoint_id=proposal['id'])
            if result['status']=='unsupported':n['error']=result['message']
    if 'frozen_notes' in proposal:doc['active_revision_set_id']=uuid.uuid4().hex
