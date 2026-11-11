"""MCP App registration and bounded video transport through the existing bridge.

The sandbox never fetches localhost or an external media service. Video bytes
travel only in app-only MCP results, outside model-visible structured content.
"""
import base64
import json
import re
import urllib.request
import urllib.error
from pathlib import Path

URI = 'ui://frame/editor-v8.html'
MIME = 'text/html;profile=mcp-app'
CHUNK = 1024 * 1024
MAX_VIDEO = 1024 * 1024 * 1024
CUSTOM_TOOLS = {'open_editor', 'read_video_chunk', 'read_video_poster', 'add_project_asset', 'start_project_revision', 'update_editor', 'prepare_download', 'get_section_reference', 'project_link'}


def specs(prop, project, version):
    return {
        'project_link': ({'project_id':project}, ['project_id'], 'Open a saved project in its own browser tab.'),
        'get_section_reference': ({'project_id': project,'section_id': prop('string','Section ID.'),'reference_id': prop('string','Attached reference image ID.')}, ['project_id','section_id','reference_id'], 'Read an image attached to a section as a visual reference.'),
        'prepare_download': ({'project_id': project, 'export_id': prop('string', 'Completed export identifier.')},
                             ['project_id', 'export_id'],
                             'Return a download link for the saved export on the computer running Frame. Available to the app only.'),
        'open_editor': ({'project_id': project}, [],
                        'Open Frame beside this conversation. Without a project_id, show the project library and Add new footage start page. Let the user choose a saved project or upload a new video; never automatically choose another chat project by recency. With project_id, open that exact project. Import tools also display shared chat footage automatically.'),
        'add_project_asset': ({'project_id':project, 'file':{'type':'object','properties':{'file_id':{'type':'string'},'download_url':{'type':'string'},'file_name':{'type':'string'},'mime_type':{'type':'string'}},'required':['file_id','download_url']}, 'source_path':prop('string','Actual absolute host file path supplied in this conversation.')}, ['project_id'], 'Save additional footage, re-recordings, images, audio, documents or context files inside the current Frame project. Use the real conversation attachment or host path. Keeps the current cut and all previous versions.'),
        'start_project_revision': ({'project_id':project,'expected_version':version,'asset_project_id':prop('string','Project family member that owns the saved file; omit for current project.'),'asset_id':prop('string','Video asset saved in this project family.'),'brief':{'type':'string','maxLength':2000},'request_id':prop('string','Stable ID for this new-cut request. Reuse on retries to avoid duplicate branches.')}, ['project_id','expected_version','asset_id','request_id'], 'Start a new editable cut from a saved re-recording inside the same project folder. Preserves earlier cuts, notes, source files and creative context. Only call when the user chooses to take the project in a new direction.'),
        'read_video_poster': ({'project_id': project, 'export_id': prop('string', 'Completed full-video export; omit for source.')}, ['project_id'], 'Read a small JPEG preview of an exact saved project video. Available to the app only.'),
        'read_video_chunk': ({'project_id': project, 'asset_id': prop('string','Video asset in this project folder.'),
                              'export_id': prop('string', 'Completed export identifier; omit for original footage.'),
                              'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': CHUNK, 'description': 'App transport chunk budget. Older app versions default to 256 KiB.'},
                              'offset': {'type': 'integer', 'minimum': 0}}, ['project_id', 'offset'],
                             'Read a bounded video chunk for playback in the FRAME app. Available to the app only.'),
        'update_editor': ({'project_id': project, 'expected_version': version,
                           'action': {'type': 'string', 'enum': ['attach_reference_clip', 'remove_reference_clip', 'add_pin', 'edit_pin', 'delete_pin', 'add_note', 'add_general_note', 'remove_note', 'keep_note', 'add_annotation', 'edit_note', 'add_reference', 'remove_reference', 'add_video_reference', 'remove_video_reference', 'add_reference_moment', 'restore_checkpoint']},
                           'checkpoint_id': prop('string', 'Saved video revision to restore as a new version.'),
                           'clip_id': prop('string', 'Current clip ID for a start pin.'),
                           'pin_id': prop('string', 'Existing pin ID.'),
                           'note_id': prop('string', 'Existing revision note ID.'),
                           'asset_id': prop('string','Video asset ID inside this project folder.'),
                           'reference_project_id': prop('string','Selected saved project ID.'),
                           'export_id': prop('string','Completed saved video in the selected project; omit for source.'),
                           'reference_time': prop('number','Original reference video timestamp in seconds.'),
                           'reference_id': prop('string','Reference image ID.'),
                           'name': prop('string','Reference filename.'),
                           'image_base64': {'type':'string','maxLength':349528,'description':'PNG, JPEG or WebP image bytes, base64 encoded; max 256 KB.'},
                           'pinpoints': {'type':'array','minItems':1,'maxItems':24,'items':{'type':'integer'}},
                           'section_id': prop('string', 'Existing complete start/end range ID.'),
                           'time': prop('number', 'Original source seconds.'),
                           'start': prop('number', 'Original source start seconds.'),
                           'end': prop('number', 'Original source end seconds.'),
                           'source_time_ms': prop('integer', 'Original source milliseconds.'),
                           'instruction': {'type': 'string', 'maxLength': 2000},
                           'annotations': {'type': 'array', 'minItems': 1, 'maxItems': 24,
                                           'items': {'type': 'object'},
                                           'description': 'Normalized drawing strokes, boxes and text on the source frame.'}},
                          ['project_id', 'expected_version', 'action'],
                          'Save source-anchored start/end pins or notes from the editor. Notes do not apply video edits.')}


def decorate(tool):
    name = tool['name']
    # Every successful tool returns an object, including list_projects' wrapper.
    tool['outputSchema'] = {'type': 'object', 'additionalProperties': True}
    meta = tool.setdefault('_meta', {})
    if name in ('open_editor', 'import_video', 'import_local_video', 'import_reference_video', 'add_project_asset', 'start_project_revision'):
        meta.update({'ui': {'resourceUri': URI, 'visibility': ['model', 'app']},
                     'openai/outputTemplate': URI,
                     'openai/widgetAccessible': True})
    elif name in ('read_studio_asset', 'read_video_chunk', 'read_video_poster', 'update_editor', 'prepare_download', 'project_link', 'begin_revision_handoff', 'finish_revision_handoff'):
        meta['ui'] = {'visibility': ['app']}
        meta['openai/widgetAccessible'] = True
    else:
        meta['ui'] = {'visibility': ['model', 'app']}
        meta['openai/widgetAccessible'] = True
    if name == 'open_editor':
        tool['title'] = 'Frame'
        meta['openai/ui'] = {'entrypoints': [{'type': 'thread'}]}
    if name in ('read_studio_asset', 'open_editor', 'read_video_chunk', 'read_video_poster', 'prepare_download', 'get_section_reference', 'project_link'):
        tool['annotations']['readOnlyHint'] = True
    return tool


def resource():
    return {'uri': URI, 'name': 'Frame editor', 'mimeType': MIME,
            'description': 'Video playback, timeline edits and saved frame notes beside the chat.'}


def contents(base='http://127.0.0.1:8876'):
    return {'uri': URI, 'mimeType': MIME, 'text': Path(__file__).with_name('frame_widget.html').read_text(),
            '_meta': {'ui': {'prefersBorder': False,
                             'csp': {'connectDomains': [], 'resourceDomains': ['blob:']}},
                      'openai/widgetDescription': 'Frame video editor. Project state is saved on the connected computer; notes are editing requests, not applied effects.',
                      'openai/widgetCSP': {'connect_domains': [], 'resource_domains': ['blob:'], 'redirect_domains': [base]},
                      'openai/ui': {'availableDisplayModes': ['inline', 'fullscreen'],
                                    'preferredDisplayMode': 'fullscreen'}}}


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Invalid project or export identifier.')
    return value


def call(name, args, base, existing):
    if name == 'open_editor':
        if args.get('project_id'):
            doc = existing('get_project', {'project_id': valid_id(args['project_id'])})
            import quick_continuation
            doc = quick_continuation.resolve(doc, lambda pid: existing('get_project', {'project_id': pid}))
            return {'project': doc, 'project_id': doc['project_id']}
        import uuid
        session=uuid.uuid4().hex
        return {'home':True,'status':'Choose a project or add new footage to begin.','upload_session_id':session,'upload_url':base+'/frame/new?session='+session}
    pid = valid_id(args.get('project_id'))
    if name == 'project_link':
        existing('get_project',{'project_id':pid})
        return {'project_id':pid,'url':base+'/frame?project='+pid}
    if name in ('add_project_asset','start_project_revision'):
        import quick_project_inputs
        if name == 'add_project_asset':return quick_project_inputs.add_asset(base,args)
        return quick_project_inputs.request(base,'/api/quick/projects/'+pid+'/new-cut',{k:v for k,v in args.items() if k!='project_id'})
    if name == 'read_video_poster':
        export_id = valid_id(args['export_id']) if args.get('export_id') else None
        path = '/api/quick/projects/' + pid + '/poster' + ('?export_id=' + export_id if export_id else '')
        with urllib.request.urlopen(base + path, timeout=20) as response:
            if response.headers.get_content_type() != 'image/jpeg':
                raise ValueError('Unexpected preview image type.')
            raw = response.read(98305)
        if not 0 < len(raw) <= 98304 or not raw.startswith(b'\xff\xd8'):
            raise ValueError('Invalid preview image.')
        return {'project_id':pid, 'export_id':export_id, 'mime_type':'image/jpeg', '_image_base64':base64.b64encode(raw).decode()}
    if name == 'get_section_reference':
        doc=existing('get_project',{'project_id':pid})
        pin=next((p for p in doc['pins'] if p['id']==args.get('section_id')),None)
        ref=next((r for r in (pin or {}).get('references',[]) if r['id']==args.get('reference_id')),None)
        if not ref:raise ValueError('Reference image not found on this section.')
        aid=valid_id(ref['id'])
        with urllib.request.urlopen(base+'/api/quick/projects/'+pid+'/assets/'+aid+'/download',timeout=30) as response:raw=response.read(262145)
        if len(raw)>262144:raise ValueError('Reference image is too large.')
        return {'project_id':pid,'section_id':pin['id'],'reference_id':aid,'name':ref['name'],'mime_type':ref['mime_type'],'_image_base64':base64.b64encode(raw).decode()}
    if name == 'prepare_download':
        export_id = valid_id(args.get('export_id'))
        doc = existing('get_project', {'project_id': pid})
        from quick_timeline import completed_export
        if completed_export(doc, export_id) is None:
            raise ValueError('Choose a completed export.')
        return {'project_id': pid, 'export_id': export_id, 'file_name': 'Frame-export.mp4',
                'download_url': base + '/media/' + pid + '/versions/' + export_id + '/edited.mp4?download=1',
                'scope': 'Open in the browser on the computer running Frame.'}
    if name == 'update_editor':
        action = args.get('action')
        allowed = {'attach_reference_clip': {'note_id','section_id','reference_project_id','asset_id','export_id','reference_id','start','end'}, 'remove_reference_clip': {'note_id','section_id','reference_id'}, 'add_video_reference': {'reference_project_id'}, 'remove_video_reference': {'reference_project_id'}, 'add_reference_moment': {'section_id','reference_project_id','reference_time','instruction','name','image_base64'}, 'add_reference': {'section_id','name','image_base64'}, 'remove_reference': {'section_id','reference_id'}, 'add_pin': {'time', 'clip_id', 'start', 'end'}, 'edit_pin': {'pin_id', 'start', 'end', 'instruction'},
                   'add_general_note': {'instruction'}, 'remove_note': {'note_id'}, 'keep_note': {'note_id'},
                   'delete_pin': {'pin_id'}, 'add_note': {'section_id', 'source_time_ms', 'instruction'},
                   'add_annotation': {'section_id', 'source_time_ms', 'instruction', 'annotations'},
                   'edit_note': {'note_id','instruction','pinpoints'}, 'restore_checkpoint': {'checkpoint_id'}}
        if action not in allowed or set(args) - (allowed[action] | {'project_id', 'expected_version', 'action'}):
            raise ValueError('Unsupported editor action or fields.')
        payload = {k: v for k, v in args.items() if k != 'project_id'}
        data = json.dumps(payload).encode()
        if len(data) > (370000 if action in ('add_reference','add_reference_moment') else 16000):
            raise ValueError('Editor request is too large.')
        req = urllib.request.Request(base + '/api/quick/projects/' + pid + '/revision', data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = json.loads(exc.read(16000))
            raise ValueError(detail.get('error', 'The editor rejected this action.')) from exc
    if name != 'read_video_chunk':
        raise ValueError('Unknown editor tool.')
    offset = args.get('offset')
    if type(offset) is not int or not 0 <= offset < MAX_VIDEO:
        raise ValueError('Invalid video byte offset.')
    chunk_size = args.get('max_bytes', 256 * 1024)
    if type(chunk_size) is not int or not 1 <= chunk_size <= CHUNK:
        raise ValueError('Invalid video chunk budget.')
    doc = existing('get_project', {'project_id': pid})
    export_id = args.get('export_id')
    asset_id=args.get('asset_id')
    if asset_id is not None:
        valid_id(asset_id)
        if export_id is not None:raise ValueError('Choose a project asset or export, not both.')
        asset=next((a for a in doc.get('assets',[]) if a['id']==asset_id and (a.get('mime_type','').startswith('video/') or str(a.get('name','')).lower().endswith(('.mp4','.mov','.m4v','.webm')))),None)
        if not asset:raise ValueError('Project video asset not found.')
        path='/api/quick/projects/'+pid+'/assets/'+asset_id+'/download'
    elif export_id is not None:
        valid_id(export_id)
        from quick_timeline import completed_export
        if completed_export(doc, export_id) is None:
            raise ValueError('Choose a completed export.')
        path = '/media/' + pid + '/versions/' + export_id + '/edited.mp4'
    else:
        path = '/media/' + pid + '/input.mp4'
    req = urllib.request.Request(base + path, headers={'Range': 'bytes=%d-%d' % (offset, offset + chunk_size - 1)})
    with urllib.request.urlopen(req, timeout=30) as response:
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
        if response.status != 206 or not match:
            raise ValueError('Video server did not return a bounded byte range.')
        start, end, total = map(int, match.groups())
        if start != offset or not start <= end < total <= MAX_VIDEO or end - start + 1 > chunk_size:
            raise ValueError('Invalid video range response.')
        data = response.read(chunk_size + 1)
        if len(data) != end - start + 1:
            raise ValueError('Video chunk was truncated.')
    return {'project_id': pid, 'offset': start, 'next_offset': end + 1, 'total_bytes': total,
            'export_id': export_id, 'asset_id': asset_id, '_video_base64': base64.b64encode(data).decode()}
