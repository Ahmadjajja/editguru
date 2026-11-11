"""Frame's persisted finishing tools and layered MP4 compositor."""
import base64
import copy
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
from editor import run, probe

DEFAULT = {'aspect':'source','fit':'contain','brightness':0,'contrast':1,'saturation':1,'volume':1,'captions':[],'layers':[]}

def snapshot(doc):
    return {'clips':copy.deepcopy(doc['clips']),'studio':copy.deepcopy(doc.get('studio',{}))}

def restore(doc, state):
    if isinstance(state,list): doc['clips']=copy.deepcopy(state)
    else:
        doc['clips']=copy.deepcopy(state['clips']);doc['studio']=copy.deepcopy(state.get('studio',{}))

def num(value, low, high, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(label+' must be between '+str(low)+' and '+str(high)+'.')
    return value

def asset_path(app,pid,doc,aid):
    asset=next((a for a in doc.get('assets',[]) if a['id']==aid),None)
    if not asset:raise ValueError('Save this media file inside the current project first.')
    root=(app.WORK/pid).resolve();path=root/asset['path']
    if path.is_symlink() or root not in path.resolve().parents or not path.is_file():raise ValueError('Saved media is unavailable.')
    return asset,path

def media_info(path):
    data=json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],timeout=30))
    streams=data.get('streams',[])
    v=next((s for s in streams if s.get('codec_type')=='video'),None)
    duration=float((data.get('format') or {}).get('duration',0))
    return {'video':bool(v),'audio':any(s.get('codec_type')=='audio' for s in streams), 'duration':duration}

def validate(app,pid,doc,value):
    if not isinstance(value,dict):raise ValueError('Supply studio settings.')
    if set(value)-set(DEFAULT):raise ValueError('Unknown studio setting.')
    s=copy.deepcopy(DEFAULT);s.update(copy.deepcopy(value))
    if s['fit'] not in ('contain','cover'):raise ValueError('Choose fit or fill framing.')
    if s['aspect'] not in ('source','9:16','16:9','1:1'):raise ValueError('Choose a supported frame shape.')
    for key,low,high in [('brightness',-.3,.3),('contrast',.5,2),('saturation',0,2),('volume',0,2)]:num(s[key],low,high,key)
    if not isinstance(s['captions'],list) or len(s['captions'])>150:raise ValueError('Use up to 150 captions.')
    if not isinstance(s['layers'],list) or len(s['layers'])>16:raise ValueError('Use up to 16 media layers.')
    seen=set()
    for row in s['captions']+s['layers']:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',row['id']) or row['id'] in seen:raise ValueError('Each item needs a unique identifier.')
        seen.add(row['id'])
        num(row.get('start'),0,300,'Start');num(row.get('end'),0,300,'End')
        if row['end']-row['start']<1/30:raise ValueError('Each item must last at least one frame.')
    for row in s['captions']:
        if row.get('origin') not in (None,'speech'):raise ValueError('Unknown caption origin.')
        if set(row)-{'id','text','start','end','x','y','size','color','origin'}:raise ValueError('Unknown caption setting.')
        if not isinstance(row.get('text'),str) or not row['text'].strip() or len(row['text'])>500:raise ValueError('Use 1–500 characters per caption.')
        for key,default,low,high in [('x',.5,0,1),('y',.8,0,1),('size',.045,.015,.12)]:row[key]=num(row.get(key,default),low,high,key)
        row.setdefault('color','#ffffff')
        if not re.fullmatch('#[a-fA-F0-9]{6}',row['color']):raise ValueError('Choose a hex caption color.')
    for row in s['layers']:
        if set(row)-{'id','asset_id','kind','start','end','inpoint','x','y','width','volume'}:raise ValueError('Unknown layer setting.')
        if row.get('kind') not in ('video','image','audio'):raise ValueError('Choose video, image or audio.')
        asset,path=asset_path(app,pid,doc,row.get('asset_id'))
        for key,default,low,high in [('inpoint',0,0,300),('x',.5,0,1),('y',.5,0,1),('width',.4,.05,1),('volume',.5,0,2)]:row[key]=num(row.get(key,default),low,high,key)
        if row['kind']=='image':
            from PIL import Image
            try:
                with Image.open(path) as im:
                    if im.width*im.height>40000000:raise ValueError('Use an image below 40 megapixels.')
                    im.verify()
            except (OSError,SyntaxError):raise ValueError('This file is not a readable image.') from None
        else:
            try:info=media_info(path)
            except (RuntimeError,ValueError):raise ValueError('This file cannot be used as a media layer.') from None
            if not info[row['kind']]:raise ValueError('This file does not contain '+row['kind']+'.')
            if row['inpoint']+row['end']-row['start']>info['duration']+.05:raise ValueError('Layer range exceeds its media. Shorten the end or source in time.')
    return s

def caption_image(caption,width,height,path):
    from PIL import Image,ImageDraw,ImageFont
    fonts=['/System/Library/Fonts/Supplemental/Arial Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
    size=round(height*caption.get('size',.045))
    font=next((ImageFont.truetype(f,size) for f in fonts if Path(f).is_file()),ImageFont.load_default())
    im=Image.new('RGBA',(width,height));d=ImageDraw.Draw(im);lines=[]
    # Character wrapping handles long words and scripts without whitespace too.
    for paragraph in caption['text'].split('\n'):
        line=''
        for char in paragraph:
            if line and d.textlength(line+char,font=font)>width*.88:lines.append(line.rstrip());line=char.lstrip()
            else:line+=char
        lines.append(line)
    lineheight=round(size*1.22);blockheight=len(lines)*lineheight
    y=max(0,min(height-blockheight,round(height*caption.get('y',.8)-blockheight/2)))
    for line in lines:
        tw=d.textlength(line,font=font);x=max(6,min(width-tw-6,width*caption.get('x',.5)-tw/2))
        d.text((x,y),line,font=font,fill=caption.get('color','#ffffff'),stroke_width=max(1,round(size*.07)),stroke_fill='#000000');y+=lineheight
    im.save(path)

def render(app,pid,doc,folder):
    s={**DEFAULT,**doc.get('studio',{})};base=folder/'edited.mp4';info=probe(base,False)
    sizes={'9:16':(720,1280),'16:9':(1280,720),'1:1':(1080,1080)}
    width,height=sizes.get(s['aspect'],(info['width']//2*2,info['height']//2*2))
    duration=sum(c['end']-c['start'] for c in doc['clips'])
    cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(base)]
    framing=('scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d'%(width,height,width,height)) if s['fit']=='cover' else ('scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black'%(width,height,width,height))
    filters=["[0:v]%s,setsar=1,eq=brightness=%s:contrast=%s:saturation=%s[v0]"%(framing,s['brightness'],s['contrast'],s['saturation'])]
    # Fit protects framing; all normalized layer coordinates refer to the output frame.
    current='v0';index=1;audio=[]
    if info['audio']:
        filters.append('[0:a]volume=%s,apad,atrim=duration=%.9f[a0]'%(s['volume'],duration));audio.append('a0')
    for layer in s['layers']:
        if layer['start']>=duration:continue
        asset,path=asset_path(app,pid,doc,layer['asset_id']);kind=layer['kind'];n=index;index+=1
        if kind=='image':
            from PIL import Image,ImageOps
            converted=folder/('layer-%d.png'%n)
            with Image.open(path) as im:ImageOps.exif_transpose(im).convert('RGBA').save(converted)
            cmd+=['-loop','1','-i',str(converted)]
        else:cmd+=['-ss',str(layer['inpoint']),'-t',str(layer['end']-layer['start']),'-i',str(path)]
        if kind=='audio':
            filters.append('[%d:a]asetpts=PTS-STARTPTS,volume=%s,adelay=%d:all=1,apad,atrim=duration=%.9f[a%d]'%(n,layer['volume'],round(layer['start']*1000),duration,n));audio.append('a%d'%n)
        else:
            filters.append('[%d:v]fps=30,scale=%d:-2,setsar=1,setpts=PTS-STARTPTS+%.9f/TB[l%d]'%(n,max(2,round(width*layer['width']/2)*2),layer['start'],n))
            out='v%d'%n
            filters.append("[%s][l%d]overlay=x='max(0,min(W-w,W*%.9f-w/2))':y='max(0,min(H-h,H*%.9f-h/2))':eof_action=pass:enable='gte(t,%.9f)*lt(t,%.9f)'[%s]"%(current,n,layer['x'],layer['y'],layer['start'],layer['end'],out));current=out
    for caption in s['captions']:
        if caption['start']>=duration:continue
        n=index;index+=1;path=folder/('caption-%d.png'%n);caption_image(caption,width,height,path)
        cmd+=['-loop','1','-i',str(path)];out='v%d'%n
        filters.append("[%s][%d:v]overlay=0:0:eof_action=pass:enable='gte(t,%.9f)*lt(t,%.9f)'[%s]"%(current,n,caption['start'],caption['end'],out));current=out
    if audio:
        filters.append('%samix=inputs=%d:duration=longest:normalize=0,alimiter=limit=.95:latency=1,atrim=duration=%.9f[aout]'%(''.join('['+a+']' for a in audio),len(audio),duration))
    script=';\n'.join(filters);(folder/'studio-filter.txt').write_text(script)
    cmd+=['-filter_complex_threads','2','-filter_complex',script,'-map','['+current+']']
    if audio:cmd+=['-map','[aout]','-c:a','aac','-ar','48000','-ac','2']
    cmd+=['-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-r','30','-threads','4','-t',str(duration),'-movflags','+faststart',str(folder/'composed.mp4')]
    run(cmd)
    result=probe(folder/'composed.mp4',False)
    if abs(result['duration']-duration)>.06 or result['audio']!=bool(audio):raise RuntimeError('The composed export failed duration/audio verification.')
    (folder/'composed.mp4').replace(base)

def route(handler,app,method):
    match=re.fullmatch('/api/quick/projects/([a-f0-9]{32})/studio-asset/([a-f0-9]{32})',urlparse(handler.path).path)
    if method!='GET' or not match:return False
    import quick_timeline
    try:
        with quick_timeline.LOCK:
            doc=quick_timeline.load(app,match[1]);asset,path=asset_path(app,match[1],doc,match[2])
        offset=int(parse_qs(urlparse(handler.path).query).get('offset',['0'])[0]);total=path.stat().st_size
        if offset<0 or offset>=total:raise ValueError('Invalid media byte offset.')
        with path.open('rb') as f:f.seek(offset);chunk=f.read(1024*1024)
        handler.json(200,{'_video_base64':base64.b64encode(chunk).decode(),'offset':offset,'next_offset':offset+len(chunk),'total':total,'mime_type':asset['mime_type']})
    except (ValueError,OSError) as exc:handler.json(400,{'error':str(exc)})
    return True

def transcript_captions(clips, transcript):
    """Map recognized source words through cuts/reordering into output time."""
    import uuid
    cues=[];offset=0
    for clip in clips:
        words=[]
        for segment in transcript:
            for word in segment.get('words') or [segment]:
                a=max(clip['start'],word['start']);b=min(clip['end'],word['end'])
                if b>a:words.append({'start':offset+a-clip['start'],'end':offset+b-clip['start'],'text':word['text'].strip()})
        group=[]
        def flush():
            if not group:return
            cues.append({'id':uuid.uuid4().hex,'origin':'speech','text':' '.join(w['text'] for w in group),'start':round(group[0]['start'],3),'end':round(max(group[-1]['end'],group[0]['start']+1/30),3),'x':.5,'y':.8,'size':.045,'color':'#ffffff'})
        for word in words:
            if group and (len(group)>=6 or word['end']-group[0]['start']>2.2):flush();group=[]
            group.append(word)
        flush();offset+=clip['end']-clip['start']
    if not cues:raise ValueError('No speech was detected. You can add captions manually or import SRT.')
    if len(cues)>150:raise ValueError('This speech needs more than 150 caption cues. Trim the video first or import shorter captions.')
    return cues

def queue_captions(app,pid,args):
    import quick_timeline as q
    import threading,time,uuid
    with q.LOCK:
        doc=q.load(app,pid)
        if type(args.get('expected_version')) is not int or args['expected_version']!=doc['version']:raise q.Conflict('Timeline changed. Refresh before generating captions.')
        if not doc['audio']:raise ValueError('This footage has no audio. Add captions manually or import an SRT file.')
        if doc.get('caption_job',{}).get('status')=='working':return q.public(doc)
        job=uuid.uuid4().hex;doc['caption_job']={'id':job,'status':'working','created_at':time.time(),'base_version':doc['version']};q.write(app.WORK/pid/'timeline.json',doc)
        frozen=copy.deepcopy(doc)
    threading.Thread(target=caption_worker,args=(app,pid,frozen,job),daemon=True).start()
    return q.public(doc)

def caption_worker(app,pid,frozen,job):
    import quick_timeline as q
    try:
        cached=app.WORK/pid/'analysis.json';transcript=json.loads(cached.read_text()).get('transcript') if cached.exists() else None
        if not transcript:
            from editor import transcribe
            with app.WORKERS:transcript=transcribe(app.WORK/pid/'input.mp4')
        cues=transcript_captions(frozen['clips'],transcript)
        state={**copy.deepcopy(DEFAULT),**frozen.get('studio',{})};state['captions']=[c for c in state['captions'] if c.get('origin')!='speech']+cues
        try:q.execute(app,pid,'set_studio',{'expected_version':frozen['version'],'studio':state});result={'status':'done','count':len(cues)}
        except q.Conflict:result={'status':'ready','captions':cues,'message':'Your edit changed while transcribing. Generated captions are ready to add.'}
    except Exception as exc:result={'status':'failed','error':str(exc)[-600:]}
    with q.LOCK:
        doc=q.load(app,pid)
        if doc.get('caption_job',{}).get('id')==job:doc['caption_job'].update(result);q.write(app.WORK/pid/'timeline.json',doc)
