#!/usr/bin/env python3
"""Dependency-free MCP stdio bridge to the loopback Quick Edit API.

Run with the same Python as the editor. FRAME_URL defaults to localhost:8876.
No footage or service is published by this bridge.
"""
import json
import base64
import os
import re
import sys
import urllib.request
import urllib.error
import quick_widget
import quick_runtime
import quick_presenter
import quick_learning
import quick_asset_mcp

BASE=os.environ.get('FRAME_URL','http://127.0.0.1:8876').rstrip('/')
if not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost):\d+',BASE):
    raise SystemExit('FRAME_URL must be loopback HTTP.')

def ensure_backend():
    global BASE
    BASE = quick_runtime.ensure_server(BASE)


def editor_contents():
    base, html = quick_runtime.active_editor(BASE)
    contents = quick_widget.contents(base)
    if html is not None:
        contents['text'] = html
    return contents


def prop(kind,description):return {'type':kind,'description':description}
P=prop('string','Stable project identifier returned by upload or list_projects.')
V=prop('integer','Current timeline version; required for mutations. Re-read after a conflict.')
C=prop('string','Stable segment id returned by get_timeline.')
FILE={'type':'object','properties':{key:prop('string',description) for key,description in {
 'download_url':'Fresh HTTPS URL supplied by the conversation host. Never invent a URL.',
 'file_id':'Conversation attachment identifier.', 'mime_type':'Video MIME type if supplied.',
 'file_name':'Original filename if supplied.'}.items()},'required':['download_url','file_id'],'additionalProperties':False}
SPECS={
 'import_reference_video':({'project_id':P,'file':FILE,'source_path':prop('string','Absolute video path supplied by the conversation host; use only when the host provides a local file instead of a download URL.'),'reference_project_id':prop('string','Already imported video project to reuse as a reference without uploading again.')},['project_id'],'Add a video from this conversation directly to the active Frame project References tab. Get project_id from the current conversation or Frame app context; never guess from global recency. Supply exactly one file (actual host attachment), source_path (actual host path), or reference_project_id (already saved video). Reuses matching imported reference bytes. Returns the target project with References open; does not change its edit timeline.'),
 'import_video':({'file':FILE},['file'],'Import video footage attached to the current conversation into FRAME. Call when a user attaches footage for editing. Use the host-provided file handoff. The result opens the Frame app for this project. Use editor_url only as a fallback in hosts without MCP Apps UI; no second upload is needed.'),
 'import_local_video':({'source_path':prop('string','Absolute path to video footage made available by the conversation host on this laptop.')},['source_path'],'Import conversation footage when the local host exposes an absolute video file path instead of a download URL. Return the Frame app for this exact imported project, with an editor URL fallback for hosts without UI.'),
 'get_frame_comments':({'project_id':P},['project_id'],'Read saved mouse-selected frame comments and requested visual changes. Comments are not applied edits.'),
 'get_frame_comment':({'project_id':P,'comment_id':prop('string','Frame comment identifier from get_frame_comments.')},['project_id','comment_id'],'Read one frame comment and its source-frame image with the selected area outlined. Visual pixel edits are not implemented by this tool.'),
 'list_projects':({},[],'List locally imported projects.'),
 'get_project':({'project_id':P},['project_id'],'Read the complete current FRAME revision, including source-anchored user notes, start/end pins, proposed edits, accepted operations, saved checkpoints and render status. Use this to receive edits left on the FRAME canvas in this chat. Reading does not apply edits.'),
 'get_timeline':({'project_id':P},['project_id'],'Read ordered clips with original-source times and version.'),
 'position_clip':({'clip_id':C,'x':prop('number','Horizontal offset as frame fraction: .01 = 1% right, -.01 = 1% left. Range -.5 to .5.'),'y':prop('number','Vertical offset as frame fraction: .01 = 1% down. Range -.5 to .5.')},['clip_id','x','y'],'Move the selected video asset slightly within the frame. Saved, previewed, undoable, and included in MP4 export. Does not move individual objects baked into video.'),
 'split_clip':({'clip_id':C,'source_time':prop('number','Split at original-source seconds.')},['clip_id','source_time'],'Split a clip without rendering.'),
 'trim_clip':({'clip_id':C,'start':prop('number','New source in seconds.'),'end':prop('number','New source out seconds.')},['clip_id','start','end'],'Trim a clip inside source bounds.'),
 'delete_segment':({'clip_id':C},['clip_id'],'Remove a segment; undo restores it.'),
 'move_segment':({'clip_id':C,'position':prop('integer','Destination index, zero based.')},['clip_id','position'],'Reorder a timeline segment.'),
 'undo':({},[],'Undo the previous timeline edit.'),
 'redo':({},[],'Redo an undone timeline edit.'),
 'export_video':({'section_id':prop('string','Optional complete section ID: export only its original source interval without changing the edited preview.')},[],'Queue a versioned FFmpeg MP4 export; poll get_project for status.'),
 'tighten_pacing':({'cut_first_seconds':prop('number','Seconds to cut from the edited timeline opening; use 3 for the sprint scenario.'),'remove_pauses':prop('boolean','Whether to remove measured low-energy pauses. Defaults true.')},[],'Cut opening and remove long low-energy pauses, retaining padding. Review and undo if necessary.')}
SPECS['generate_studio_captions']=({},[],'Generate English captions from source speech using the installed local transcription model. Runs in the background; poll get_project. Captions follow the current cuts and are saved as editable studio captions. No paid generation.')
SPECS['set_studio']=({'studio':{'type':'object','description':'Complete studio settings: aspect (source, 9:16, 16:9, 1:1), fit (contain or cover), brightness (-.3 to .3), contrast (.5 to 2), saturation (0 to 2), volume (0 to 2), captions [{id,text,start,end,x,y,size,color}], layers [{id,asset_id,kind (video,image,audio),start,end,inpoint,x,y,width,volume}]. Times use edited output seconds. x/y/width/size are normalized frame fractions. Assets must already belong to this project.'}},['studio'],'Save directly applied color, framing, captions and media layers. Versioned, undoable and included in MP4 export. Re-read project before changing settings; preserve existing studio fields and layers.')
SPECS['sync_editor_state']=({'clips':{'type':'array','description':'Ordered sections as original-source ranges [{id?,start,end}]; 1–240 items.','items':{'type':'object'}},'studio':{'type':'object','description':'Complete studio settings, same shape as set_studio.'},'editor_state':{'type':['object','null'],'description':'Opaque editor project saved for exact reload; null clears it.'},'provider':prop('string','Who made the change, e.g. editor or style-agents.')},['clips'],'Replace the cut and finishing settings in one versioned, undoable revision. Used by the FRAME editor to save every change.')
SPECS['read_studio_asset']=({'project_id':P,'asset_id':prop('string','Saved asset identifier in this project.'),'offset':prop('integer','Byte offset, starting at zero.')},['project_id','asset_id'],'Read at most 1 MiB of a saved project asset for in-app preview. No external files are accessible.')
SPECS['log_activity']=({'message':prop('string','Progress update for Frame, including analysis, timing audits and external rendering. Do not include secrets.'),'status':{'type':'string','enum':['running','done','failed']}},['message'],'Publish ongoing work in the live Frame activity feed. Call before lengthy analysis or external rendering and after meaningful steps; commands outside Frame are only visible when reported here.')
SPECS['record_revision_result']=({'note_id':prop('string','Original saved revision note ID.'),'result_project_id':P,'result_version':V,'export_id':prop('string','Completed full-video export in the result project.'),'message':prop('string','Implemented change and its source-to-output mapping.')},['note_id','result_project_id','result_version','export_id','message'],'Record an implemented saved revision against an existing completed Frame export. Validates the output file, duration, audio and current result version, preserves the original timeline, and prevents the applied request from being sent again.')
SPECS.update({
 'begin_revision_handoff': ({'prompt':prop('string','Complete saved revision implementation prompt; maximum 128000 UTF-8 bytes.')}, ['prompt'], 'Reserve a saved revision handoff before sending it. Duplicate unresolved or received handoffs return may_send=false.'),
 'finish_revision_handoff': ({'project_id':P,'handoff_id':prop('string','Saved handoff ID.'),'attempt':prop('integer','Attempt returned by begin_revision_handoff.'),'status':{'type':'string','enum':['submitted','not_sent','uncertain']},'error':prop('string','Transport error, if any.')}, ['project_id','handoff_id','attempt','status'], 'Record the host transport result. Submission does not prove receipt.'),
 'get_revision_handoff': ({'project_id':P,'handoff_id':prop('string','Saved handoff ID.')}, ['project_id','handoff_id'], 'Read persisted revision delivery status without editing the timeline.'),
 'acknowledge_revision_handoff': ({'project_id':P,'handoff_id':prop('string','Handoff ID in the received implementation prompt.'),'receipt_token':prop('string','Receipt token from that same received message.')}, ['project_id','handoff_id','receipt_token'], 'After receiving a Frame implementation prompt, acknowledge receipt using its handoff ID and receipt token before implementing the revisions. Receipt does not apply edits or complete a render.')
})
SPECS.update(quick_widget.specs(prop, P, V))
SPECS.update(quick_presenter.specs(prop))
SPECS.update(quick_learning.specs(prop,P))
SPECS.update(quick_asset_mcp.specs(prop,P,V))

def tools():
    result=[]
    for name,(properties,required,description) in SPECS.items():
        properties=dict(properties);required=list(required)
        if name not in quick_asset_mcp.TOOLS and name not in quick_learning.TOOLS and name not in quick_presenter.TOOLS and name not in quick_widget.CUSTOM_TOOLS and name not in ('import_video','import_local_video','import_reference_video','get_frame_comments','get_frame_comment','list_projects','get_project','get_timeline','read_studio_asset','finish_revision_handoff','get_revision_handoff','acknowledge_revision_handoff'):
            properties.update(project_id=P,expected_version=V);required+=['project_id','expected_version']
        result.append({'name':name,'description':description,'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False},
                       'annotations':{'readOnlyHint':name in quick_asset_mcp.READ_ONLY or name=='get_creative_memory' or name in ('list_projects','get_project','get_timeline','get_frame_comments','get_frame_comment','get_revision_handoff'),'destructiveHint':False,'openWorldHint':name=='import_video'}})
        if name in ('import_video','import_reference_video','add_project_asset'):result[-1]['_meta']={'openai/fileParams':['file']}
        quick_widget.decorate(result[-1])
        if name in quick_presenter.TOOLS:
            result[-1]['annotations']['readOnlyHint'] = name in ('open_presenter_studio','list_presenter_videos','get_presenter_video')
            if name in ('open_presenter_studio','save_presenter_brief','get_presenter_video','quote_presenter_video','complete_presenter_video','import_presenter_video'):
                result[-1]['_meta'].update({'ui':{'resourceUri':quick_widget.URI,'visibility':['model','app']},'openai/outputTemplate':quick_widget.URI})
            if name in ('begin_presenter_handoff','finish_presenter_handoff','approve_presenter_quote'):
                result[-1]['_meta']['ui']={'visibility':['app']}
    return result

def call(name,args):
    if name not in SPECS:raise ValueError('Unknown tool.')
    if name in quick_asset_mcp.TOOLS:
        return quick_asset_mcp.call(name,args,BASE)
    if name in quick_presenter.TOOLS:
        body=json.dumps({**args,'operation':name},ensure_ascii=False).encode()
        req=urllib.request.Request(BASE+'/api/quick/presenter',data=body,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=180) as response:
                result=json.load(response)
                if name=='open_presenter_studio':result['editor_url']=BASE+'/frame?create=presenter'
                return result
        except urllib.error.HTTPError as exc:
            raise ValueError(json.loads(exc.read(16000)).get('error','Presenter request failed.')) from exc
    if name=='import_reference_video':
        import quick_reference_import
        return quick_reference_import.import_reference(BASE,args)
    if name in quick_widget.CUSTOM_TOOLS:
        return quick_widget.call(name,args,BASE,call)
    if name in ('import_video','import_local_video'):
        import quick_import
        result=quick_import.import_attachment(BASE,args.get('file')) if name=='import_video' else quick_import.import_local(BASE,args.get('source_path'))
        result['next_step']='Preview this project in the Frame component. If it is not visible, open this tool result in a tab. Use editor_url as the fallback in hosts without MCP Apps UI.'
        return result
    if name=='read_studio_asset':
        pid=args.get('project_id','');aid=args.get('asset_id','');offset=args.get('offset',0)
        if not re.fullmatch('[a-f0-9]{32}',pid) or not re.fullmatch('[a-f0-9]{32}',aid) or type(offset) is not int or offset<0:raise ValueError('Invalid asset request.')
        with urllib.request.urlopen(BASE+'/api/quick/projects/'+pid+'/studio-asset/'+aid+'?offset='+str(offset),timeout=30) as r:return json.load(r)
    if name=='list_projects':path='/api/projects';body=None
    else:
        pid=args.get('project_id','')
        if not isinstance(pid,str) or not re.fullmatch('[a-f0-9]{32}',pid):raise ValueError('Invalid project id.')
        path='/api/quick/projects/'+pid
        body=None
        if name=='get_frame_comments':path+='/frame-comments'
        elif name=='record_revision_result':
            path+='/revision-result';body=json.dumps({k:v for k,v in args.items() if k!='project_id'}).encode()
        elif name=='get_frame_comment':
            cid=args.get('comment_id','')
            if not isinstance(cid,str) or not re.fullmatch('[a-f0-9]{32}',cid):raise ValueError('Invalid frame comment id.')
            path+='/frame-comments/'+cid
        elif name not in ('get_project','get_timeline'):
            path+='/commands';body=json.dumps({**{k:v for k,v in args.items() if k!='project_id'},'operation':name},ensure_ascii=False).encode()
    req=urllib.request.Request(BASE+path,data=body,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
    except urllib.error.HTTPError as exc:raise ValueError(exc.read().decode()) from exc

def dispatch(req):
    method=req.get('method');rid=req.get('id')
    if rid is None:return None
    try:
        if method=='initialize':result={'protocolVersion':req.get('params',{}).get('protocolVersion','2024-11-05') if req.get('params',{}).get('protocolVersion') in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25') else '2025-03-26','instructions':quick_asset_mcp.INSTRUCTIONS+'Consult get_creative_memory before planning an edit. Use relevant explicit feedback as evidence, with current requests taking precedence. Record feedback only from an explicit user judgment of an exact reviewed output, never from render success or your own review. When the user adds re-recordings, extra footage, images, documents or new information to an existing Frame project, use add_project_asset with the explicit current project_id and actual host attachment or absolute path. Keep files inside that project; do not import them as unrelated projects. Only start_project_revision when the user chooses a new take as the next cut; previous versions remain nested in the project. When the user explicitly wants to create an AI presenter video, open_presenter_studio enters Frame Create video without footage. Save their brief, then follow the durable creation handoff, current Higgsfield Shorts instructions and saved credit approval. Never start paid generation merely from opening the panel or saving a brief. Open Frame when requested, even before footage is shared. Without a project_id, its start page lets the user choose a saved project or add new footage. Import actual conversation footage when supplied to display it automatically. Use open_editor with an explicit project_id to reopen a project from this conversation. Without a project, the sidebar shows the project library and Add new footage. Import tools also return the Frame UI. When the user asks to add a chat video as a reference, or the current Frame context says References is active and a video is provided for that purpose, call import_reference_video with the explicit active project_id and actual host attachment or local file handoff. Do not import it as a new edit project or ask for a second upload. Never select another chat project using global recency; ask which project if this conversation has no explicit target. The service cannot enumerate attachments automatically; use only file handoffs available in this conversation. When the user attaches video footage for FRAME, import it from the current conversation with import_video (host file handoff) or import_local_video (host local path), display the returned Frame app. Use editor_url only if the host cannot render MCP Apps. Do not ask for a duplicate upload. When the user asks about a marked area, read get_frame_comments then get_frame_comment for the annotated source image. Comments alone do not change pixels. When the user leaves revisions on the FRAME canvas, call get_project to read its notes and pending proposals in this conversation. Do not imply that reading them approved or rendered them. These tools run on the user laptop; loopback editor links must be opened on that laptop.', 'capabilities':{'tools':{'listChanged':False},'resources':{'subscribe':False,'listChanged':False}},'serverInfo':{'name':'frame-quick-edit','version':'1.2.0'}}
        elif method=='ping':result={}
        elif method=='resources/list':result={'resources':[quick_widget.resource()]}
        elif method=='resources/templates/list':result={'resourceTemplates':[]}
        elif method=='resources/read':
            if req.get('params',{}).get('uri')!=quick_widget.URI:raise ValueError('Unknown UI resource.')
            result={'contents':[editor_contents()]}
        elif method=='tools/list':result={'tools':tools()}
        elif method=='tools/call':
            try:
                value=call(req['params']['name'],req['params'].get('arguments',{}))
                image_data=value.pop('_image_base64',None) if isinstance(value,dict) else None
                video_data=value.pop('_video_base64',None) if isinstance(value,dict) else None
                result={'content':[{'type':'text','text':json.dumps(value)}],'structuredContent':value if isinstance(value,dict) else {'projects':value},'isError':False}
                if image_data is not None:result['content'].append({'type':'image','mimeType':value['mime_type'],'data':image_data})
                if video_data is not None:result['_meta']={'videoChunk':video_data}
                if req['params']['name']=='get_frame_comment':
                    url=BASE+'/api/quick/projects/'+value['project_id']+'/frame-comments/'+value['id']+'/image'
                    with urllib.request.urlopen(url,timeout=30) as image:
                        data=image.read(4*1024*1024+1)
                    if len(data)>4*1024*1024:raise ValueError('Frame image is too large.')
                    result['content'].append({'type':'image','mimeType':'image/png','data':base64.b64encode(data).decode()})
            except Exception as exc:result={'content':[{'type':'text','text':str(exc)}],'isError':True}
        else:return {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}}
        return {'jsonrpc':'2.0','id':rid,'result':result}
    except Exception as exc:return {'jsonrpc':'2.0','id':rid,'error':{'code':-32602,'message':str(exc)}}

def serve_http(port):
    # Stateless Streamable HTTP: JSON responses, no server-initiated SSE stream.
    import hmac
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    token=os.environ.get('FRAME_MCP_TOKEN','')
    if len(token)<32:raise SystemExit('Set FRAME_MCP_TOKEN to a random secret of at least 32 characters.')
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,value=None):
            data=json.dumps(value).encode() if value is not None else b''
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            self.reply(405,{'error':'MCP endpoint accepts POST requests.'})
        def do_POST(self):
            if self.path!='/mcp':return self.reply(404,{'error':'Not found'})
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                self.close_connection=True;return self.reply(401,{'error':'Bearer token required'})
            origin=self.headers.get('Origin')
            if origin and origin not in ('http://127.0.0.1:'+str(port),'http://localhost:'+str(port)):
                self.close_connection=True;return self.reply(403,{'error':'Untrusted Origin'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=370000:raise ValueError('Invalid request length')
                self.connection.settimeout(20)
                req=json.loads(self.rfile.read(length))
                if not isinstance(req,dict):raise ValueError('Expected JSON-RPC object')
                if req.get('method')=='tools/call' and req.get('params',{}).get('name') in SPECS:
                    ensure_backend()
                response=dispatch(req)
                return self.reply(200,response) if response is not None else self.reply(202)
            except RuntimeError as exc:self.reply(503,{'error':str(exc)})
            except (ValueError,TypeError) as exc:self.reply(400,{'error':str(exc)})
        def log_message(self,*args):pass
    print('FRAME authenticated MCP: http://127.0.0.1:%d/mcp'%port,file=sys.stderr,flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':
    if '--http' in sys.argv:
        serve_http(int(os.environ.get('FRAME_MCP_PORT','8877')))
        sys.exit(0)
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if request.get('method')=='tools/call' and request.get('params',{}).get('name') in SPECS:
                try:ensure_backend()
                except Exception as exc:
                    print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'result':{'isError':True,'content':[{'type':'text','text':str(exc)}]}}),flush=True)
                    continue
            result=dispatch(request)
            if result is not None:print(json.dumps(result),flush=True)
        except Exception as exc:
            print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(exc)}}),flush=True)
