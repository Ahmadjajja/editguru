import {createReferenceTimeline,validClipRange} from './reference-timeline.js';
export {validClipRange};
const identity=ref=>`${ref.project_id}:${ref.asset_id?'asset:'+ref.asset_id:ref.export_id?'export:'+ref.export_id:'source'}`;
const videoAsset=a=>a.mime_type?.startsWith('video/')||/\.(mp4|mov|m4v|webm)$/i.test(a.name||'');
export function clipCandidates(doc){
 if(!doc?.project_id)return [];
 const pid=doc.project_id,rows=[{project_id:pid,name:doc.name||'Original video',kind:'Original video',duration:doc.source_duration}];
 const seen=new Set();
 const addExport=(id,name,duration)=>{if(!id||seen.has(id))return;seen.add(id);rows.push({project_id:pid,export_id:id,name:name||'Saved video',kind:'Saved video',duration})};
 for(const [i,e] of (doc.exports||[]).entries())if(e.status==='done'){const checkpoint=[...(doc.checkpoints||[])].reverse().find(c=>c.rendered?.proposal_id===e.id);addExport(e.id,e.section_id?'Exported section':checkpoint?.label||'Saved export '+(i+1),e.duration)}
 for(const c of [...(doc.checkpoints||[])].reverse())if(c.rendered&&((doc.exports||[]).some(e=>e.id===c.rendered.proposal_id&&e.status==='done')||(doc.proposals||[]).some(p=>p.id===c.rendered.proposal_id&&p.status==='accepted')))addExport(c.rendered.proposal_id,c.label,c.rendered.duration);
 for(const a of doc.assets||[])if(videoAsset(a))rows.push({...a,asset_id:a.id,project_id:pid,kind:'Project file'});
 for(const r of doc.video_references||[])if(r.project_id!==pid)rows.push({...r,kind:'Linked reference'});
 return rows.map(r=>({...r,key:identity(r)}));
}
export function createReferenceClips({getDoc,getProjects=()=>[],getPreview=()=>null,rpc,data,update,say,canEdit}){
 const make=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e};
 const button=(text,cls='')=>{const e=make('button',cls,text);e.type='button';return e};
 const dialog=make('dialog','clip-reference-dialog');dialog.id='clipReferenceDialog';dialog.setAttribute('aria-labelledby','clipReferenceTitle');
 const title=make('h2','','Attach reference clip');title.id='clipReferenceTitle';const close=button('Cancel'),top=make('div','row');top.append(title,close);
 const browser=make('div','clip-reference-browser'),folders=make('section','clip-reference-projects'),search=make('input');search.type='search';search.placeholder='Find a project…';search.setAttribute('aria-label','Find a reference project');
 const projectList=make('div','clip-project-list');projectList.setAttribute('aria-label','Projects');folders.append(make('h3','','Projects'),search,projectList);
 const items=make('section','clip-reference-items'),itemTitle=make('h3','','Project videos'),itemList=make('div','clip-item-list');itemList.setAttribute('aria-label','Videos in selected project');items.append(itemTitle,itemList);browser.append(folders,items);
 const previewBox=make('div','clip-reference-preview'),video=make('video'),placeholder=make('div','clip-preview-placeholder','Choose a project video to preview.');video.id='clipReferenceVideo';video.playsInline=true;video.preload='auto';video.hidden=true;previewBox.append(video,placeholder);
 const status=make('p','hint');status.id='clipReferenceStatus';status.setAttribute('role','status');
 const timelineRoot=make('section');timelineRoot.id='clipReferenceTimeline';timelineRoot.setAttribute('aria-label','Reference clip timeline');
 const play=button('Play'),clock=make('span'),preview=button('Preview section'),retry=button('Retry loading');retry.hidden=true;const playback=make('div','row clip-reference-playback');playback.append(play,clock,preview,retry);
 const start=make('input'),end=make('input');start.type=end.type='number';start.step=end.step='0.001';start.min=end.min='0';start.id='clipReferenceStart';end.id='clipReferenceEnd';
 const a=make('label','','Start (seconds)'),b=make('label','','End (seconds)');a.htmlFor=start.id;b.htmlFor=end.id;a.append(start);b.append(end);
 const pinStart=button('Pin start at playhead'),pinEnd=button('Pin end at playhead'),range=make('div','clip-reference-range');range.append(a,pinStart,b,pinEnd);
 const save=button('Attach selected section','primary'),footer=make('div','row clip-reference-footer');footer.append(save);
 dialog.append(top,browser,previewBox,timelineRoot,playback,range,status,footer);document.body.append(dialog);
 let owner=null,target=null,active=null,selectedProject=null,retained=null,rows=[],projects=[],projectGeneration=0,generation=0,url=null,ownsUrl=false,loading=false,saving=false,playingRange=false,pendingRange=null,decodeTimer=null;
 const current=()=>dialog.open&&getDoc()?.project_id===owner&&canEdit();
 const timeline=createReferenceTimeline({root:timelineRoot,video,onRangeChange:(a,b)=>{playingRange=false;start.value=String(a);end.value=String(b);render()}});
 function render(){
  const ready=current()&&!loading&&!saving&&video.readyState>=2&&!video.hidden,valid=ready&&start.value!==''&&end.value!==''&&validClipRange(Number(start.value),Number(end.value),video.duration);
  save.disabled=preview.disabled=!valid;play.disabled=pinStart.disabled=pinEnd.disabled=!ready;start.disabled=end.disabled=!ready;close.disabled=saving;search.disabled=saving;retry.disabled=saving;
  for(const b of dialog.querySelectorAll('[data-project-id],[data-video-key]'))b.disabled=saving;
  timeline.setEnabled(!!ready);if(Number.isFinite(Number(start.value))&&Number.isFinite(Number(end.value)))timeline.setRange(Number(start.value),Number(end.value));
  clock.textContent=video.hidden?'':`${(video.currentTime||0).toFixed(3)} / ${(video.duration||0).toFixed(3)}s`;
 }
 function clear(){++generation;clearTimeout(decodeTimer);decodeTimer=null;video.pause();video.removeAttribute('src');video.load();video.hidden=true;placeholder.hidden=false;if(url&&ownsUrl)URL.revokeObjectURL(url);url=null;ownsUrl=false;loading=false;playingRange=false;timeline.reset();start.value=end.value='';retry.hidden=true}
 function setStatus(text){status.textContent=text}
 function projectRows(){
  const doc=getDoc(),all=[{id:doc?.project_id,name:doc?.name},...(doc?.video_references||[]).map(r=>({id:r.project_id,name:r.name})),...projects];
  const seen=new Set();return all.filter(p=>{const id=p.id||p.project_id;if(!id||seen.has(id))return false;seen.add(id);return true}).map(p=>({...p,id:p.id||p.project_id}));
 }
 function renderProjects(){projectList.replaceChildren();const query=search.value.trim().toLowerCase();for(const p of projectRows()){
  if(query&&!`${p.name} ${p.id}`.toLowerCase().includes(query))continue;
  const row=button(p.name||p.id.slice(0,6),'clip-project');row.dataset.projectId=p.id;row.setAttribute('aria-pressed',String(p.id===selectedProject));const meta=make('small','',p.id===owner?'Current project':p.id.slice(0,6));row.append(meta);row.onclick=()=>void chooseProject(p.id);projectList.append(row)
 }if(!projectList.children.length)projectList.append(make('p','hint','No matching projects.'));render()}
 function renderItems(){itemList.replaceChildren();for(const ref of rows){const row=button(ref.name||'Video','clip-video-item');row.dataset.videoKey=ref.key;row.setAttribute('aria-pressed',String(active?.key===ref.key));const meta=make('small','',ref.kind+(Number.isFinite(ref.duration)?' · '+ref.duration.toFixed(2)+'s':''));row.append(meta);row.onclick=()=>void load(ref);itemList.append(row)}render()}
 async function chooseProject(pid,preferred=null){
  const request=++projectGeneration;selectedProject=pid;active=null;clear();rows=[];renderProjects();renderItems();itemTitle.textContent='Loading project videos…';placeholder.textContent='Loading project videos…';setStatus('Reading saved project items…');
  try{const doc=pid===owner?getDoc():data(await rpc('get_project',{project_id:pid}));if(request!==projectGeneration||!current())return;if(doc.project_id!==pid)throw Error('The selected project did not match.');
   rows=clipCandidates(doc);if(retained&&retained.project_id===pid&&!rows.some(r=>r.key===retained.key))rows.push(retained);itemTitle.textContent=(doc.name||'Project')+' · videos';
   const preferredKey=preferred?identity(preferred):null,live=getPreview();const selected=rows.find(r=>r.key===preferredKey)||rows.find(r=>pid===owner&&live&&identity(r)===identity(live))||rows[0];
   renderItems();if(selected)await load(selected,preferred);else{placeholder.textContent='No playable videos in this project.';setStatus('Select another project.');render()}
  }catch(e){if(request===projectGeneration&&current()){itemTitle.textContent='Could not read this project';placeholder.textContent='Project unavailable';setStatus(e.message);render()}}
 }
 function fail(text){loading=false;video.hidden=true;placeholder.hidden=false;placeholder.textContent='Preview unavailable';setStatus(text);retry.hidden=false;render()}
 async function load(ref,restore=null){
  clear();active=ref;pendingRange=restore;const token=generation;loading=true;placeholder.textContent='Loading '+ref.name+'…';setStatus('Loading the selected video…');renderItems();
  const stillCurrent=()=>token===generation&&current()&&active?.key===ref.key;
  try{
   const shared=getPreview();if(shared?.src&&identity(shared)===ref.key){url=shared.src;ownsUrl=false}else{
    let offset=0,total=null;const chunks=[];do{
     const response=await rpc('read_video_chunk',{project_id:ref.project_id,...(ref.asset_id?{asset_id:ref.asset_id}:{}),...(ref.export_id?{export_id:ref.export_id}:{}),offset,max_bytes:1048576});if(!stillCurrent())return;
     const d=data(response),raw=response._meta?.videoChunk;
     if(typeof raw!=='string'||d.project_id!==ref.project_id||d.offset!==offset||(d.export_id||null)!==(ref.export_id||null)||(d.asset_id||null)!==(ref.asset_id||null))throw Error('Reference video identity did not match.');
     const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0));if(!bytes.length||bytes.length>1048576||!Number.isSafeInteger(d.total_bytes)||d.total_bytes>1073741824||d.next_offset!==offset+bytes.length||d.next_offset>d.total_bytes||(total!==null&&total!==d.total_bytes))throw Error('Invalid reference video chunk.');
     chunks.push(bytes);offset=d.next_offset;total=d.total_bytes;setStatus(`Loading ${ref.name} · ${Math.round(offset/total*100)}%`);
    }while(offset<total);if(!stillCurrent())return;url=URL.createObjectURL(new Blob(chunks,{type:ref.mime_type||'video/mp4'}));ownsUrl=true;
   }
   if(!stillCurrent())return;video.src=url;video.load();decodeTimer=setTimeout(()=>{if(stillCurrent()&&loading)fail('The video has not decoded. Retry loading or select another item.');},20000);
  }catch(e){if(stillCurrent())fail('Could not load this video. '+e.message)}
 }
 video.onloadedmetadata=()=>{const duration=video.duration;if(!Number.isFinite(duration)||duration<=0)return fail('This file has no playable video duration.');start.max=end.max=String(duration);const keep=pendingRange&&validClipRange(pendingRange.start,pendingRange.end,duration);start.value=String(keep?pendingRange.start:0);end.value=String(keep?pendingRange.end:duration)};
 video.onloadeddata=()=>{if(!current()||!active)return;clearTimeout(decodeTimer);loading=false;video.hidden=false;placeholder.hidden=true;timeline.ready(url,video.duration);timeline.setRange(Number(start.value),Number(end.value));if(pendingRange){video.currentTime=Number(start.value);pendingRange=null}setStatus('Scrub the filmstrip. Drag the start/end pins, or pin the playhead.');render()};
 video.onerror=()=>{if(current()&&active)fail('This video could not be decoded. Retry or select another project item.')};video.ontimeupdate=()=>{if(playingRange&&video.currentTime>=Number(end.value)){playingRange=false;video.pause();video.currentTime=Number(end.value);setStatus('Selected section preview complete.')}render()};video.addEventListener('seeked',render);video.oncanplay=render;video.onplay=()=>{play.textContent='Pause'};video.onpause=()=>{play.textContent='Play'};
 start.oninput=end.oninput=()=>{playingRange=false;video.pause();render()};
 pinStart.onclick=()=>{video.pause();playingRange=false;start.value=String(Math.min(video.duration,Math.round(video.currentTime*1000)/1000));render()};pinEnd.onclick=()=>{video.pause();playingRange=false;end.value=String(Math.min(video.duration,Math.round(video.currentTime*1000)/1000));render()};
 play.onclick=async()=>{playingRange=false;try{video.paused?await video.play():video.pause()}catch(e){setStatus(e.message)}};
 preview.onclick=async()=>{const token=generation;playingRange=false;video.pause();try{const t=Number(start.value);if(Math.abs(video.currentTime-t)>.001){const seeked=new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true}));video.currentTime=t;await seeked}if(token!==generation||!current())return;playingRange=true;await video.play();setStatus('Previewing the selected section.')}catch(e){setStatus(e.message)}};
 retry.onclick=()=>{if(active)void load(active,pendingRange)};search.oninput=renderProjects;close.onclick=()=>dialog.close();dialog.addEventListener('cancel',e=>{if(saving)e.preventDefault()});dialog.addEventListener('close',()=>{++projectGeneration;clear();target=null;owner=null;active=null});
 save.onclick=async()=>{if(save.disabled||!current()||!active)return;video.pause();const ref=active,pid=owner,token=generation;saving=true;render();try{
  const next=await update({action:'attach_reference_clip',...target,reference_project_id:ref.project_id,...(ref.asset_id?{asset_id:ref.asset_id}:{}),...(ref.export_id?{export_id:ref.export_id}:{}),...(retained?{reference_id:retained.id}:{}),start:Number(start.value),end:Number(end.value)});
  if(next&&pid===getDoc()?.project_id&&token===generation){dialog.close();say('Reference clip attached to this revision.')}else setStatus('Could not attach. Review the selection and try again.');
 }catch(e){setStatus(e.message)}finally{saving=false;render()}};
 window.addEventListener('pagehide',()=>{clear();timeline.destroy()});
 return {
  sync(){if(dialog.open&&!current())dialog.close()},
  open(to,ref=null){if(!canEdit())return;document.getElementById('video')?.pause();document.getElementById('referenceVideo')?.pause();retained=ref?{...ref,key:identity(ref),kind:'Attached clip'}:null;owner=getDoc().project_id;target=to;projects=getProjects();search.value='';dialog.showModal();void chooseProject(ref?.project_id||owner,ref);
   const openedOwner=owner;void rpc('list_projects',{}).then(r=>{if(current()&&owner===openedOwner){projects=data(r).projects||[];renderProjects()}}).catch(()=>{});
  },
  append(container,to,clips=[]){const open=button('Attach reference clip');open.dataset.attachReferenceClip='true';open.onclick=()=>this.open(to);const attachments=make('div','reference-clip-attachments');attachments.append(open);container.append(attachments);
   for(const ref of clips){const row=make('div','row'),view=button(`${ref.name} · ${ref.start.toFixed(3)}–${ref.end.toFixed(3)}s`),remove=button('Remove clip');view.onclick=()=>this.open(to,ref);remove.onclick=()=>update({action:'remove_reference_clip',...to,reference_id:ref.id});row.append(view,remove);attachments.append(row)}
  }
 };
}
