import {createStudio} from './studio.js';
import {createCreativeFeedback} from './creative-feedback.js';
import {createProjectFiles} from './project-files.js';
import {createProjectLibrary, projectId, clipDuration, timeLabel} from './project-library.js';
import { createReferenceClips } from './reference-clips.js';
import { createReferences } from './references.js';
import { App, applyDocumentTheme, applyHostStyleVariables } from '@modelcontextprotocol/ext-apps';
import { createMarkup, drawMarkup } from './markup.js';
import { createSectionTimeline, sectionColors } from './section-timeline.js';
import { validateSectionRange } from './section-range.js';
import { projectHistory, revisionOptions, revisionView, videoVersionOptions, savedVideoReady } from './revision-history.js';
import { buildImplementationPrompt } from './revision-prompt.js';
import { deliverRevisionPrompt, deliveryLabel, sendToCurrentChat, latestBrowserHandoff } from './revision-delivery.js';
import { createPresenterStudio } from './presenter-studio.js';

const app = new App({name:'Frame',version:'1.2.0'}, {availableDisplayModes:['inline','fullscreen']});
function theme(context){if(context?.theme)applyDocumentTheme(context.theme);if(context?.styles?.variables)applyHostStyleVariables(context.styles.variables)}
const $=id=>document.getElementById(id), video=$('video');
let downloadBlob=null,downloadBusy=false,relayBusy=false;
let activeHandoff=null,projectPanelBusy=false;
let liveDoc=null,historyId=null,historyKey='';
const workingProjects=new Map(),ancestorProjects=new Map();
async function loadAncestry(project){
 const seen=new Set([project.project_id]),parents=[];let child=project;
 while(child.revision_parent){
  const id=child.revision_parent.project_id;if(seen.has(id)||seen.size>100)throw Error('Invalid project version lineage.');seen.add(id);
  const parent=data(await rpc('get_project',{project_id:id}));
  if(parent.project_id!==id)throw Error('Version history did not match the requested project.');
  parents.push(parent);child=parent;
 }
 await library.load();
 const group=library.groupFor(project);
 for(const member of group?.members||[]){if(member.project_id!==project.project_id&&!parents.some(p=>p.project_id===member.project_id))parents.push(member)}
 ancestorProjects.set(project.project_id,parents);
}
function historySelection(project,id){
 if(!id?.startsWith('ancestor:'))return revisionView(project,id);
 const [,pid,cid]=id.split(':');const parent=ancestorProjects.get(project.project_id)?.find(p=>p.project_id===pid);
 return parent?revisionView(parent,cid):null;
}
function ancestorOptions(project){return (ancestorProjects.get(project?.project_id)||[]).flatMap(parent=>videoVersionOptions(parent).slice(1).map(r=>({value:'ancestor:'+parent.project_id+':'+r.value,label:'Saved cut · '+parent.name+' · '+r.label})));}

let rangeProject=null,rangePin=null,rangeSaving=false,sectionRevisionDraft=null;
let refreshing=null, mediaLoadPromise=null, mediaError=false, sectionPlayback=null;
let doc=null, connected=false, hostReady=false, busy=false, polling=false, loadingMedia=false, rpcQueue=Promise.resolve(), mediaGeneration=0, mediaKey='', mediaUrl='', resultMode=false, selectedPin=null, sheetKind='', sheetClip=null, noteTime=0, savedNote=null, opening=null, latestInput={}, pendingResult=null, pendingTimelinePosition=null, playbackClipIndex=-1;
const fmt=t=>`${Math.floor((t||0)/60)}:${Math.floor((t||0)%60).toString().padStart(2,'0')}`;
const commentaryDrafts=new Map(),noteDraftAttempts=new Map();
const heldParents=new Set();
const completedFeedbackCorrections=new Set();
let markersKey='';
const referenceUrls=new Map();let projectItems=[];
let markupUI=null,projectFiles=null,creativeFeedback=null,studioUI=null;
let homeLibrary=null,homeUpload=null,homeUploading=false,homeChecking=false;
let referenceTabActive=false;
function publishProjectContext(){if(!doc||!hostReady)return;void app.updateModelContext({content:[{type:'text',text:JSON.stringify({app:'Frame',active_project_id:doc.project_id,project_name:doc.name,active_tab:referenceTabActive?'references':'edit',project_file_routing:'For re-recordings, additional footage, documents, audio, images or new context in this project, use add_project_asset with project_id='+doc.project_id+'. Keep the current cut; use start_project_revision only when the user chooses a saved take as a new direction.',attachment_routing:'For a video supplied as a reference in this conversation, call import_reference_video with project_id='+doc.project_id+' and the actual host file handoff. Keep this project open. Do not pick a project from another chat or global recency.'})}]}).catch(()=>{});}

let sectionTimeline=null;
const referenceClips=createReferenceClips({getDoc:()=>doc,getProjects:()=>projectItems,getPreview:()=>mediaKey===doc?.project_id+':'+(currentExport()||'source')&&video.readyState>=2?{project_id:doc.project_id,export_id:currentExport(),src:mediaUrl}:null,rpc:(...args)=>rpc(...args),data:r=>data(r),update:body=>update(body),say:(...args)=>say(...args),canEdit:()=>connected&&!!doc&&!historyId});
const referencesUI=createReferences({app,getDoc:()=>doc,rpc,data,update,list,getProjects:()=>projectItems,prepareReference,say:(...args)=>say(...args),onTabChange:refs=>{referenceTabActive=refs;publishProjectContext()}});
const say=(s,error=false)=>{$('status').textContent=s;$('status').classList.toggle('error',error)};
const health=ok=>{connected=ok;$('connection').textContent=ok?'Connected · saved locally':'Connection unavailable';controls()};
function controls(){
 creativeFeedback?.render();
 studioUI?.render();
 $('homeAddFootage').disabled=!connected||homeUploading;
 $('homeRefresh').disabled=homeChecking||!!refreshing;
 $('homeResumeUpload').hidden=!homeUpload;
 $('projectHome').disabled=busy||relayBusy;
 projectFiles?.render();
 const previewReady=!!doc&&!loadingMedia&&!mediaError&&mediaKey===doc.project_id+':'+(currentExport()||'source')&&video.readyState>=2;
 $('refresh').disabled=busy||!!refreshing;$('refresh').textContent=refreshing?'Refreshing…':'Refresh';
 $('retryMedia').disabled=!!refreshing||loadingMedia;
 document.querySelector('main').toggleAttribute('data-project-ready',!!doc);
 for(const id of ['trim','split','trimIn','trimOut','deleteClip','pin','note','export'])$(id).disabled=!connected||!doc||busy||!!historyId||!!markupUI?.active;
 $('undo').disabled=!connected||!doc?.can_undo||busy||!!historyId||!!markupUI?.active;$('redo').disabled=!connected||!doc?.can_redo||busy||!!historyId||!!markupUI?.active;
 $('sendRevisions').disabled=!connected||!doc||busy||relayBusy||!!markupUI?.active;
 $('play').disabled=!previewReady||!doc?.clips?.length;$('scrub').disabled=!previewReady||!doc?.clips?.length;$('timelineSeek').disabled=!previewReady||!doc?.clips?.length;
 $('view').disabled=!doc?.rendered||busy||comparing;$('view').textContent=resultMode?'Edited':'Original';
 $('pin').textContent=rangeProject===doc?.project_id?'Reset start · I':'Start section · I';
 $('finishSection').disabled=!previewReady||!connected||busy||rangeSaving||relayBusy||!!historyId||!!markupUI?.active||rangeProject!==doc?.project_id;
 $('finishSection').textContent=rangeSaving?'Saving section…':'End & save · O';
 $('pin').disabled ||= !previewReady;
 if(relayBusy){for(const id of ['trim','split','trimIn','trimOut','deleteClip','pin','note','export','undo','redo','annotate','browseProjects'])$(id).disabled=true;}
 if(doc&&!doc.clips?.length){video.pause();video.hidden=true;$('empty').hidden=false;$('empty').querySelector('p').textContent='Timeline is empty. Undo to restore your clips.'}else if(previewReady&&mediaUrl){video.hidden=false;$('empty').hidden=true}
 generalControls();
 if(!previewReady)for(const id of ['split','trimIn','trimOut','deleteClip'])$(id).disabled=true;
 rangeControls();sectionRevisionControls();
 selectedSectionControls(previewReady);
 for(const button of document.querySelectorAll('[data-save-comment]'))button.disabled=!connected||busy;
 for(const button of document.querySelectorAll('.section-card button:not([data-save-comment])'))button.disabled=!connected||busy||!!markupUI?.active;
 $('browseProjects').disabled=!connected||busy;
 $('compareVersions').disabled=!connected||!doc||busy||!!historyId||!!markupUI?.active;
 renderComparisonOptions();
 for(const input of document.querySelectorAll('.section-card input'))input.disabled=!connected||busy;
 for(const button of document.querySelectorAll('[data-export-working]'))button.disabled=true;
 $('projects').disabled=busy||relayBusy||comparing;$('editHistory').disabled=busy||relayBusy||comparing;$('closeWorkingProject').disabled=busy||relayBusy||!doc;$('saveSheet').disabled=busy;$('sendNote').disabled=busy||!savedNote;

 $('annotate').disabled=!connected||!doc||busy||!previewReady;
 if(markupUI?.active){for(const id of ['play','scrub','timelineSeek','pin','finishSection','view','projects','trim','split','trimIn','trimOut','deleteClip','export','undo','redo','note'])$(id).disabled=true}
 if(connected&&doc)$('connection').textContent='Connected · v'+doc.version+(resultMode&&doc.rendered?.timeline_version!==doc.version?' · preview needs export':'');
 if(historyId){
  for(const id of ['trim','split','trimIn','trimOut','deleteClip','timelineSeek','pin','finishSection','note','export','undo','redo','sendRevisions','annotate','rangeSave','saveSheet','sendNote'])$(id).disabled=true;
  for(const input of document.querySelectorAll('.section-card button,.section-card input,.section-card textarea'))input.disabled=true;
  $('connection').textContent='Connected · viewing saved revision';
 }
 $('restoreRevision').disabled=!connected||busy||!historyId;
 $('revisionNotice').hidden=!historyId;
 renderRevisionOptions();
 if(relayBusy){for(const el of document.querySelectorAll('.section-card button,.section-card input,.section-card textarea,#generalRevisions button,#generalRevisions textarea'))el.disabled=true;$('compareVersions').disabled=true;}
 referencesUI.render();
 sectionTimeline?.render(video.currentTime||0);
}
function rpc(name,args){
 const task=rpcQueue.then(async()=>{
  const attempts=['list_projects','get_project','read_video_chunk'].includes(name)?3:1;
  for(let attempt=0;attempt<attempts;attempt++)try{const r=await app.callServerTool({name,arguments:args});if(r.isError)throw Error(r.content?.find(c=>c.type==='text')?.text||'The operation failed.');health(true);return r}
  catch(e){if(attempt+1<attempts&&/not initialized/i.test(e.message)){await new Promise(resolve=>setTimeout(resolve,400));continue}if(/fetch|connect|timeout|closed|unavailable|not initialized/i.test(e.message))health(false);throw e}
 });rpcQueue=task.catch(()=>{});return task;
}
function data(r){return r.structuredContent||{}}
async function list(){const r=data(await rpc('list_projects',{}));projectItems=r.projects||[];renderRevisionOptions()}
function renderRevisionOptions(){
 const historyList=$('projectHistoryLog');
 const historyRows=projectHistory(liveDoc,ancestorProjects.get(liveDoc?.project_id)||[]);
 const grouped=library.groupFor(liveDoc);
 for(const cut of grouped?.cuts||[])historyRows.unshift({id:'cut:'+cut.project_id,selection:'cut:'+cut.project_id,title:timeLabel(clipDuration(cut))+' · '+(cut.work_project?.label||cut.name),detail:cut.project_id===liveDoc?.project_id?'Open cut':'Saved cut',created_at:cut.created,project:grouped.title});
 const fullKey=JSON.stringify(historyRows);
 if(historyList.dataset.key!==fullKey){
  historyList.dataset.key=fullKey;historyList.replaceChildren();
  for(const row of historyRows){
   const li=document.createElement('li'),title=document.createElement(row.selection?'button':'strong');
   title.textContent=row.title;
   if(row.selection){title.onclick=()=>{if(busy||relayBusy)return;const select=$('editHistory');if(![...select.options].some(o=>o.value===row.selection))select.add(new Option(row.title,row.selection));select.value=row.selection;select.dispatchEvent(new Event('change'));};}
   const detail=document.createElement('p');detail.textContent=[row.project,row.detail,row.created_at?new Date(row.created_at*1000).toLocaleString():'Date unavailable'].filter(Boolean).join(' · ');
   li.append(title,detail);historyList.append(li);
  }
  if(!historyRows.length)historyList.textContent='No saved history yet.';
 }

 const group=library.groupFor(liveDoc);
 const cuts=(group?.cuts||[]).filter(p=>p.project_id!==liveDoc?.project_id).map(p=>({value:'cut:'+p.project_id,label:timeLabel(clipDuration(p))+' · '+(p.work_project?.label||p.name)}));
 const rows=[...videoVersionOptions(liveDoc),...cuts],edits=[...revisionOptions(liveDoc),...cuts,...ancestorOptions(liveDoc)],key=JSON.stringify([liveDoc?.project_id,rows,edits,[...workingProjects]]);
 if(key!==historyKey){historyKey=key;$('projects').replaceChildren(...(rows.length?rows.map(r=>new Option(r.label,r.value)):[new Option('Open a project from All projects…','')]));$('editHistory').replaceChildren(...edits.map(r=>new Option(r.label,r.value)))}
 $('projects').value=liveDoc?(historyId||'latest'):'';$('editHistory').value=historyId||'latest';
 const snapshot=doc?.revision_snapshot;$('versionRecord').hidden=!historyId;
 $('versionRecordText').textContent=snapshot?.prompt|| (snapshot&&Object.hasOwn(snapshot,'notes')?JSON.stringify({notes:snapshot.notes,pins:snapshot.pins},null,2):'No review snapshot was recorded for this older checkpoint. Current notes are not shown as historical data.');
}

let comparing=false,comparisonGeneration=0,comparisonUrl='',comparisonKey='',comparisonRows=[];
const comparisonVideo=$('comparisonVideo'),comparisonProjects=new Map();
let comparisonSelection='';
function closeComparison(){
 comparing=false;comparisonGeneration++;comparisonKey='';comparisonSelection='';comparisonProjects.clear();video.controls=false;comparisonVideo.pause();comparisonVideo.removeAttribute('src');comparisonVideo.load();
 if(comparisonUrl)URL.revokeObjectURL(comparisonUrl);comparisonUrl='';
 $('comparisonLayout').classList.remove('comparing');$('comparisonPane').hidden=true;$('currentVersionLabel').hidden=true;
 $('compareVersions').setAttribute('aria-pressed','false');$('compareVersions').textContent='Compare versions';
}
function renderComparisonOptions(){
 if(!liveDoc)return;
 const projects=[liveDoc,...(ancestorProjects.get(liveDoc.project_id)||[]),...comparisonProjects.values()];
 const rows=[],seen=new Set();
 for(const project of projects){
  if(seen.has(project.project_id))continue;seen.add(project.project_id);
  for(const option of videoVersionOptions(project).slice(1)){
   const saved=revisionView(project,option.value);
   if(!saved||(!saved.rendered&&option.value!=='source'))continue;
   const exportId=saved.rendered?.proposal_id||null;
   if(project.project_id===liveDoc.project_id&&exportId&&exportId===liveDoc.rendered?.proposal_id)continue;
   rows.push({value:project.project_id===liveDoc.project_id?option.value:project.project_id+':'+option.value,label:project.name+' · '+option.label,project:project.project_id,exportId});
  }
 }
 // Every upload is selectable even while its saved-version history is loading.
 for(const item of [...projectItems].sort((a,b)=>(b.created||0)-(a.created||0))){
  const pid=item.id||item.project_id;if(!pid||seen.has(pid))continue;
  rows.push({value:pid+':source',label:item.name+' · Original upload',project:pid,exportId:null});
 }
 const key=JSON.stringify(rows);if(key===comparisonKey)return;comparisonKey=key;comparisonRows=rows;
 const selected=comparisonSelection||$('comparisonVersion').value;$('comparisonVersion').replaceChildren(...rows.map(r=>new Option(r.label,r.value)));
 if(rows.some(r=>r.value===selected))$('comparisonVersion').value=selected;
 else {
  const parent=liveDoc.revision_parent;
  const previous=parent&&rows.find(r=>r.project===parent.project_id&&(r.exportId===parent.export_id||r.exportId===parent.video_id));
  const upload=rows.find(r=>r.project===parent?.project_id&&r.value.endsWith(':source'))||rows.find(r=>r.project!==liveDoc.project_id&&r.value.endsWith(':source'));
  $('comparisonVersion').value=(previous||upload||rows[0])?.value||'';
 }
 comparisonSelection=$('comparisonVersion').value;
 if(comparing)void loadComparison();
}
async function loadComparisonLibrary(pid){
 for(const item of projectItems){
  const id=item.id||item.project_id;if(!comparing||liveDoc?.project_id!==pid)return;
  if(!id||id===pid||comparisonProjects.has(id))continue;
  try{const project=data(await rpc('get_project',{project_id:id}));if(project.project_id===id)comparisonProjects.set(id,project)}catch{}
 }
 if(comparing&&liveDoc?.project_id===pid)renderComparisonOptions();
}
async function loadComparison(){
 const generation=++comparisonGeneration,row=comparisonRows.find(r=>r.value===$('comparisonVersion').value);
 comparisonVideo.pause();comparisonVideo.removeAttribute('src');comparisonVideo.load();if(comparisonUrl)URL.revokeObjectURL(comparisonUrl);comparisonUrl='';
 const current=()=>comparing&&generation===comparisonGeneration;
 if(!row){$('comparisonStatus').textContent='No previous playable version yet. Export a revision to compare it here.';return}
 $('comparisonStatus').textContent='Loading previous version…';
 try{
  const exportId=row.exportId;
  let offset=0,total=null;const chunks=[];
  do{
   const r=await rpc('read_video_chunk',{project_id:row.project,offset,max_bytes:1048576,...(exportId?{export_id:exportId}:{})});if(!current())return;
   const d=data(r),raw=r._meta?.videoChunk;if(typeof raw!=='string'||d.project_id!==row.project||d.export_id!==(exportId||null)||d.offset!==offset)throw Error('Video chunk did not match this version.');
   if(total!==null&&total!==d.total_bytes)throw Error('Video changed while loading.');total=d.total_bytes;
   const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0));if(bytes.length!==d.next_offset-offset||!bytes.length||bytes.length>1048576||!Number.isSafeInteger(total)||total>1073741824||d.next_offset>total)throw Error('Invalid video chunk.');
   chunks.push(bytes);offset=d.next_offset;
  }while(offset<total);
  if(!current())return;comparisonUrl=URL.createObjectURL(new Blob(chunks,{type:'video/mp4'}));comparisonVideo.src=comparisonUrl;comparisonVideo.load();
  comparisonStatus();
 }catch(e){if(current())$('comparisonStatus').textContent='Previous version unavailable. '+e.message}
}
function comparisonStatus(){
 if(!comparing||!comparisonUrl)return;
 const duration=t=>Number.isFinite(t)?fmt(t)+'.'+Math.floor((t%1)*100).toString().padStart(2,'0'):'…';
 const length=duration(comparisonVideo.duration);
 $('comparisonStatus').textContent=$('comparisonLinked').checked
  ?'Linked playback · current '+duration(video.duration)+' · previous '+length+'. The shorter video holds at its end. Unlink to play either full video.'
  :'Independent playback · use each video’s controls to compare different moments and lengths.';
}
$('comparisonLinked').onchange=()=>{
 const linked=$('comparisonLinked').checked;video.controls=!linked;comparisonVideo.controls=!linked;
 comparisonVideo.muted=linked;comparisonStatus();if(linked)syncComparison(true);
};
function syncComparison(force=false){
 if(!comparing||!$('comparisonLinked').checked||comparisonVideo.readyState<1)return;
 const time=Math.min(video.currentTime||0,Number.isFinite(comparisonVideo.duration)?comparisonVideo.duration:video.currentTime||0);
 if(force||Math.abs(comparisonVideo.currentTime-time)>.25)comparisonVideo.currentTime=time;
 comparisonVideo.playbackRate=video.playbackRate;
 if(video.paused||comparisonVideo.currentTime>=comparisonVideo.duration)comparisonVideo.pause();
 else if(comparisonVideo.paused)void comparisonVideo.play().catch(()=>{$('comparisonStatus').textContent='Press Play again to start both previews.'});
}
comparisonVideo.onloadedmetadata=()=>{comparisonStatus();syncComparison(true)};
video.addEventListener('play',()=>syncComparison(true));video.addEventListener('pause',()=>{if($('comparisonLinked').checked)comparisonVideo.pause()});
video.addEventListener('seeking',()=>syncComparison(true));video.addEventListener('timeupdate',()=>syncComparison());video.addEventListener('ratechange',()=>syncComparison(true));
$('comparisonVersion').onchange=()=>{comparisonSelection=$('comparisonVersion').value;void loadComparison()};
$('compareVersions').onclick=async()=>{
 if(comparing){closeComparison();controls();return}if(!liveDoc||busy)return;
 historyId=null;accept(liveDoc);const pid=doc.project_id,generation=++comparisonGeneration;
 // Compare the actual latest edit, including timeline changes not exported yet.
 busy=true;controls();
 try{
  let latest=liveDoc;
  if(!savedVideoReady(latest)){
   say('Preparing the current edit for comparison…');
   latest=data(await rpc('export_video',{project_id:pid,expected_version:latest.version}));
   const expected=latest.version,exportId=latest.exports?.at(-1)?.id,deadline=Date.now()+180000;
   while(!savedVideoReady(latest)){
    if(doc?.project_id!==pid||latest.version!==expected||generation!==comparisonGeneration)throw Error('Project changed while preparing comparison. Open comparison again.');
    const output=latest.exports?.find(e=>e.id===exportId);
    if(output?.status==='failed')throw Error(output.error||'The current edit could not be rendered.');
    if(Date.now()>deadline)throw Error('The current edit is still rendering. Open comparison once export finishes.');
    await new Promise(resolve=>setTimeout(resolve,1000));latest=data(await rpc('get_project',{project_id:pid}));
   }
   if(doc?.project_id!==pid||generation!==comparisonGeneration)return;accept(latest);
  }
  resultMode=!!doc.rendered;await loadVideo();
 }catch(e){say('Could not prepare comparison. '+e.message,true);return}
 finally{busy=false;controls()}

 if(generation!==comparisonGeneration||doc?.project_id!==pid)return;
 const uploaded=projectItems.find(p=>(p.id||p.project_id)===pid);
 const priorUpload=[...projectItems].filter(p=>(p.id||p.project_id)!==pid&&(!uploaded?.created||p.created<uploaded.created)).sort((a,b)=>(b.created||0)-(a.created||0))[0];
 const preferred=comparisonRows.find(r=>r.project===pid&&r.exportId)||comparisonRows.find(r=>r.project===doc.revision_parent?.project_id&&r.value.endsWith(':source'))||comparisonRows.find(r=>r.project===(priorUpload?.id||priorUpload?.project_id)&&r.value.endsWith(':source'))||comparisonRows[0];
 if(preferred){comparisonSelection=preferred.value;$('comparisonVersion').value=preferred.value}
 comparing=true;$('comparisonLayout').classList.add('comparing');$('comparisonPane').hidden=false;$('currentVersionLabel').hidden=false;
 $('currentVersionLabel').textContent=doc.name+' · Current revision (locked)';
 $('comparisonLinked').checked=true;comparisonVideo.controls=false;comparisonVideo.muted=true;
 $('compareVersions').setAttribute('aria-pressed','true');$('compareVersions').textContent='Close comparison';void loadComparison();controls();void loadComparisonLibrary(pid);
};

function sourcePoint(){let t=video.currentTime||0;if(!resultMode){const active=doc?.clips?.[playbackClipIndex];return {time:t,clip:active&&active.start<=t&&t<=active.end?active:doc?.clips.find(c=>c.start<=t&&t<c.end)}};const rendered=doc?.rendered;for(const c of rendered?.clips||[]){const length=c.end-c.start;if(t<length)return {time:c.start+t,clip:doc.clips.find(n=>n.id===c.id)||c};t-=length}return {time:rendered?.clips?.at(-1)?.end??doc?.source_duration??0,clip:null}}
function timelineDuration(){return (doc?.clips||[]).reduce((sum,clip)=>sum+clip.end-clip.start,0)}
function timelineOffset(index){return (doc?.clips||[]).slice(0,index).reduce((sum,clip)=>sum+clip.end-clip.start,0)}
function moveControls(){const index=doc?.clips?.findIndex(c=>c.id===sourcePoint().clip?.id)??-1,locked=!connected||!doc||busy||!!historyId||!!markupUI?.active||relayBusy;$('moveEarlier').disabled=locked||index<=0;$('moveLater').disabled=locked||index<0||index>=doc.clips.length-1}
function nextPlaybackClip(){if(!doc?.clips?.length||playbackClipIndex<0||playbackClipIndex+1>=doc.clips.length){video.pause();return false}playbackClipIndex++;video.currentTime=doc.clips[playbackClipIndex].start;updateClipTimelineActive();return true}
async function moveTimelineClip(direction){if(!doc||busy||historyId||relayBusy||markupUI?.active)return;const point=sourcePoint(),index=doc.clips.findIndex(c=>c.id===point.clip?.id),clip=doc.clips[index],position=index+direction;if(!clip)return say('Select a timeline clip to move.',true);if(position<0||position>=doc.clips.length)return say(direction<0?'This clip is already first.':'This clip is already last.');const local=Math.max(0,Math.min(point.time-clip.start,clip.end-clip.start)),next=await command('move_segment',{clip_id:clip.id,position});if(!next)return;resultMode=false;const resumeAt=timelineOffset(position)+local;if(mediaKey===doc.project_id+':source')seekTimelinePosition(resumeAt);else{pendingTimelinePosition=resumeAt;mediaKey='';await loadVideo()}say(direction<0?'Clip moved earlier. Undo with ⌘Z.':'Clip moved later. Undo with ⌘Z.')}
function updateClipTimelineActive(){const point=sourcePoint(),id=doc?.clips?.[playbackClipIndex]?.id||point.clip?.id;for(const button of $('clipTimeline').querySelectorAll('button'))button.classList.toggle('active',button.dataset.clipId===id);moveControls()}
function renderClipTimeline(){const track=$('clipTimeline');if(!track)return;track.replaceChildren();if(!doc?.clips?.length){track.textContent='Timeline clips appear here. Trimmed gaps close automatically.';return}doc.clips.forEach((clip,index)=>{const button=document.createElement('button');button.type='button';button.dataset.clipId=clip.id;button.style.flexGrow=String(Math.max(1/30,clip.end-clip.start));button.textContent=`Clip ${index+1} · ${(clip.end-clip.start).toFixed(1)}s`;button.title=`Source ${clip.start.toFixed(3)}–${clip.end.toFixed(3)} seconds`;button.setAttribute('aria-label',`Clip ${index+1}, ${(clip.end-clip.start).toFixed(2)} seconds`);button.onclick=()=>seekTimelinePosition(timelineOffset(index));track.append(button)});updateClipTimelineActive()}
function seekTimelinePosition(position){video.pause();const total=timelineDuration();let remaining=Math.max(0,Math.min(Number(position)||0,total));if(resultMode){video.currentTime=Math.min(remaining,video.duration||remaining);return}for(let i=0;i<(doc?.clips||[]).length;i++){const clip=doc.clips[i],length=clip.end-clip.start;if(remaining<length-1e-7||i===doc.clips.length-1){playbackClipIndex=i;video.currentTime=clip.start+Math.max(0,Math.min(remaining,length));updateClipTimelineActive();return}remaining-=length}}
function timelinePlayhead(){if(resultMode)return video.currentTime||0;const point=sourcePoint(),index=playbackClipIndex>=0?playbackClipIndex:doc?.clips.findIndex(c=>c.id===point.clip?.id),clip=doc?.clips[index];return clip?timelineOffset(index)+Math.max(0,Math.min(point.time-clip.start,clip.end-clip.start)):0}
function advanceMagneticPlayback(){if(resultMode||video.paused||!doc?.clips?.length)return;let index=playbackClipIndex,clip=doc.clips[index],time=video.currentTime||0;if(clip&&time>=clip.end-.012){nextPlaybackClip();return}if(!clip||time<clip.start-1/30){index=doc.clips.findIndex(c=>c.start<=time&&time<c.end);if(index<0)index=doc.clips.findIndex(c=>c.start>time);if(index<0){video.pause();return}playbackClipIndex=index;clip=doc.clips[index];if(time<clip.start||time>=clip.end)video.currentTime=clip.start}}
async function historyTimeline(operation){if(!doc||busy)return;const position=timelinePlayhead(),next=await command(operation);if(!next)return;resultMode=false;const resumeAt=Math.min(position,timelineDuration());if(mediaKey===doc.project_id+':source')seekTimelinePosition(resumeAt);else{pendingTimelinePosition=resumeAt;mediaKey='';await loadVideo()}say(operation==='undo'?'Undo saved. Export to review the current timeline.':'Redo saved. Export to review the current timeline.')}
async function editTimelineAtPlayhead(operation){if(!doc||busy||loadingMedia||mediaError||!mediaUrl)return;const point=sourcePoint(),index=doc.clips.findIndex(c=>c.id===point.clip?.id),clip=doc.clips[index];if(!clip)return say('Move the playhead inside a retained timeline clip first.',true);const at=Math.round(point.time*30)/30,offset=timelineOffset(index),local=Math.max(0,Math.min(at-clip.start,clip.end-clip.start));let resumeAt=offset+local,args={clip_id:clip.id};if(operation==='split_clip'){if(at<=clip.start+.04||at>=clip.end-.04)return say('Place the playhead inside the clip, away from its edges.',true);args.source_time=at}else if(operation==='trim_in'){if(at<=clip.start||at>=clip.end-1/30)return say('Move the playhead past the clip start to ripple-trim its head.',true);operation='trim_clip';args.start=at;args.end=clip.end;resumeAt=offset}else if(operation==='trim_out'){if(at<=clip.start+1/30||at>=clip.end)return say('Move the playhead before the clip end to ripple-trim its tail.',true);operation='trim_clip';args.start=clip.start;args.end=at;resumeAt=offset+Math.max(0,local-1/30)}else if(operation==='delete_segment')resumeAt=offset;const next=await command(operation,args);if(!next)return;resultMode=false;resumeAt=Math.min(resumeAt,timelineDuration());if(mediaKey===doc.project_id+':source')seekTimelinePosition(resumeAt);else{pendingTimelinePosition=resumeAt;mediaKey='';await loadVideo()}say(operation==='delete_segment'?'Clip deleted. The remaining timeline closed the gap. Undo with ⌘Z.':operation==='split_clip'?'Cut saved at the playhead. Undo with ⌘Z.':'Ripple trim saved. Following clips shifted to close the gap. Undo with ⌘Z.')}

function timeInView(t,endBoundary=false){if(!resultMode)return t;let offset=0;for(const c of doc.rendered?.clips||[]){if(endBoundary?c.start<t&&t<=c.end:c.start<=t&&t<c.end)return offset+t-c.start;offset+=c.end-c.start}return null}
let generalProject=null;
function generalControls(){
 const disabled=!connected||!doc||busy||!!historyId||!!markupUI?.active;
 $('generalRevisions').hidden=!doc;
 for(const input of document.querySelectorAll('#generalRevisions textarea,#generalRevisions button'))input.disabled=disabled;
}
function renderGeneralRevisions(){
 const pid=doc?.project_id||null;
 if(generalProject!==pid){generalProject=pid;$('generalPromptText').value=commentaryDrafts.get(pid+':general')||''}
 const box=$('generalRevisionList');box.replaceChildren();
 for(const note of (doc?.notes||[]).filter(n=>n.scope==='general').sort((a,b)=>(a.order||0)-(b.order||0))){
  const item=document.createElement('li'),text=document.createElement('div'),meta=document.createElement('div'),remove=document.createElement('button');
  text.className='general-text';text.textContent=note.instruction;
  meta.className='general-meta';meta.textContent=`Whole version · v${note.created_version??doc.version} · ${note.status||'saved'}`;
  remove.type='button';remove.textContent=note.included===false?'Include':'Remove';
  remove.onclick=async()=>{if(await update({action:note.included===false?'keep_note':'remove_note',note_id:note.id}))say('General revision updated.')};
  item.append(text,meta,remove);referenceClips.append(item,{note_id:note.id},note.reference_clips);box.append(item);
 }
 generalControls();
}
$('generalPromptText').oninput=()=>{const key=doc?.project_id+':general',text=$('generalPromptText').value;if(text)commentaryDrafts.set(key,text);else{commentaryDrafts.delete(key);noteDraftAttempts.delete(key)}};
$('generalPromptForm').onsubmit=async event=>{
 event.preventDefault();if(!doc||historyId||busy)return;
 const pid=doc.project_id,text=$('generalPromptText').value,instruction=text.trim();if(!instruction)return;
 const next=await saveDraftNote(pid+':general',{action:'add_general_note',instruction});
 if(next){
  if(commentaryDrafts.get(pid+':general')===text)commentaryDrafts.delete(pid+':general');
  if(doc?.project_id===pid&&$('generalPromptText').value===text)$('generalPromptText').value='';
  say('General revision saved for this version.');
 }
};
function markers(){
 referenceClips.sync();
 const key=JSON.stringify([doc?.project_id,doc?.pins,doc?.notes,doc?.exports,selectedPin,sectionRevisionDraft]);
 if(key===markersKey)return;markersKey=key;
 renderGeneralRevisions();
 const box=$('markers');box.replaceChildren();
 if(!doc?.pins?.length){const empty=document.createElement('p');empty.className='section-empty';empty.textContent='Your selected sections will appear here, with room for commentary on each one.';box.append(empty);return}
 for(const [index,pin] of doc.pins.entries()){
  const card=document.createElement('article');card.className='section-card';card.dataset.selected=String(pin.id===selectedPin);card.dataset.sectionId=pin.id;
  card.style.setProperty('--section-color',sectionColors[index%sectionColors.length]);
  const row=document.createElement('div');row.className='row';const title=document.createElement('h3');title.textContent=`Section ${index+1} · ${pin.start.toFixed(2)}${pin.end==null?'s → choose end':'–'+pin.end.toFixed(2)+'s'}`;
  const select=document.createElement('button');select.textContent=pin.end==null?'Finish section':'Preview section';select.onclick=()=>{if(pin.end==null){openRange(pin);return}void previewSection(pin)};const adjust=document.createElement('button');adjust.textContent='Adjust start / end';adjust.onclick=()=>openRange(pin);const remove=document.createElement('button');remove.textContent='Remove section marker';remove.title='Remove this section and its review notes; keep the footage';remove.onclick=async()=>{const next=await update({action:'delete_pin',pin_id:pin.id});if(next){if(selectedPin===pin.id)selectedPin=null;markersKey='';markers();controls();say('Section deleted. Footage preserved.')}};row.append(title,select,adjust,remove);card.append(row);
  const state=document.createElement('span');state.className='pin-state'+(pin.end==null?' pending':'');state.textContent=pin.end==null?'Start pinned · choose an end':'Pinned section';card.append(state);
  const notes=(doc.notes||[]).filter(n=>n.section_id===pin.id);
  if(notes.length){const list=document.createElement('ol');for(const note of notes){const item=document.createElement('li'),text=document.createElement('span'),meta=document.createElement('span');text.className='commentary-text';text.textContent=note.instruction;meta.className='comment-meta';meta.textContent=`${(note.source_time_ms/1000).toFixed(2)}s · ${note.status||'saved'}`;item.append(text,meta);
   const points=document.createElement('div');points.className='revision-points';
   for(const time of note.pinpoints||[note.source_time_ms]){const jump=document.createElement('button');jump.textContent=(time/1000).toFixed(2)+'s';jump.onclick=()=>{const t=timeInView(time/1000);if(t===null)return say('Switch to Original to view this pinpoint.');video.pause();video.currentTime=t};points.append(jump)}
   const addPoint=document.createElement('button');addPoint.textContent='Add playhead to this revision';addPoint.onclick=async()=>{const t=Math.round(sourcePoint().time*1000);const next=await update({action:'edit_note',note_id:note.id,instruction:note.instruction,pinpoints:[...new Set([...(note.pinpoints||[note.source_time_ms]),t])]});if(next)say('Pinpoint saved to this revision.')};points.append(addPoint);item.append(points);
   if(note.annotations?.length){const preview=document.createElementNS('http://www.w3.org/2000/svg','svg');preview.classList.add('markup-preview');preview.setAttribute('role','img');preview.setAttribute('aria-label','Saved frame markup');drawMarkup(preview,note.annotations,video.videoWidth||1000,video.videoHeight||562);const view=document.createElement('button');view.className='markup-review';view.textContent='View marked frame';view.onclick=()=>{if(markupUI?.active)return;const t=timeInView(note.source_time_ms/1000);if(t===null)return say('This frame is outside the edited preview. Switch to Original to view it.');selectedPin=pin.id;video.pause();video.currentTime=t;markupUI?.render();video.scrollIntoView({behavior:'smooth',block:'center'});markers();controls()};item.append(preview,view)}
   referenceClips.append(item,{note_id:note.id},note.reference_clips);list.append(item)}card.append(list)}
  if(pin.end!=null){
   const actions=document.createElement('div');actions.className='row section-actions';
   const latest=(doc.exports||[]).filter(e=>e.section_id===pin.id&&e.source_start===pin.start&&e.source_end===pin.end).at(-1);
   const download=document.createElement('button');download.textContent=latest?.status==='done'?'Download section MP4':latest?.status==='working'?'Rendering section…':latest?.status==='failed'?'Retry section MP4':'Export section MP4';
   if(latest?.status==='working')download.dataset.exportWorking='true';
   download.onclick=()=>exportSection(pin);
   const attach=document.createElement('button'),file=document.createElement('input');attach.textContent='Attach reference image';file.type='file';file.accept='image/png,image/jpeg,image/webp';file.hidden=true;attach.onclick=()=>file.click();
   file.onchange=async()=>{const chosen=file.files?.[0];if(!chosen)return;const pid=doc.project_id;attach.disabled=true;try{const encoded=await prepareReference(chosen);if(doc.project_id!==pid)return;const next=await update({action:'add_reference',section_id:pin.id,name:chosen.name,image_base64:encoded});if(next)say('Reference image saved to this section.')}catch(e){say(e.message,true)}finally{file.value='';controls()}};
   actions.append(download,attach,file);referenceClips.append(actions,{section_id:pin.id},pin.reference_clips);card.append(actions);
   if(latest?.status==='failed'){const error=document.createElement('p');error.textContent=latest.error||'Section export failed. Retry to render it again.';card.append(error)}
   const refs=document.createElement('div');refs.className='section-references';
   for(const ref of pin.references||[]){const figure=document.createElement('figure'),image=document.createElement('img'),caption=document.createElement('figcaption'),remove=document.createElement('button');figure.className='section-reference';image.alt=ref.name;caption.textContent=ref.name;remove.textContent='Remove image';remove.onclick=()=>update({action:'remove_reference',section_id:pin.id,reference_id:ref.id});figure.append(image,caption,remove);refs.append(figure);const pid=doc.project_id;
    void referenceImage(pid,pin.id,ref.id).then(url=>{if(image.isConnected)image.src=url}).catch(e=>{image.alt=ref.name+' · '+e.message});
    image.onclick=()=>{if(!image.src)return;$('referenceFull').src=image.src;$('referenceFull').alt=ref.name;$('referenceViewer').showModal()};
   }card.append(refs);

   const form=document.createElement('form'),label=document.createElement('label'),input=document.createElement('textarea'),save=document.createElement('button');
   const draftKey=doc.project_id+':'+pin.id;input.id='comment-'+pin.id;input.maxLength=2000;input.required=true;input.placeholder='What should change in this section?';input.value=commentaryDrafts.get(draftKey)||'';input.oninput=()=>{commentaryDrafts.set(draftKey,input.value);if(!input.value.trim())noteDraftAttempts.delete(draftKey)};label.htmlFor=input.id;label.textContent='Commentary for this section';save.textContent='Save commentary';save.type='submit';save.dataset.saveComment=pin.id;
   form.onsubmit=async event=>{event.preventDefault();const instruction=input.value.trim();if(!instruction)return;selectedPin=pin.id;const point=sourcePoint().time;const sourceTime=point>=pin.start&&point<pin.end?point:pin.start;const next=await saveDraftNote(draftKey,{action:'add_note',section_id:pin.id,source_time_ms:Math.max(Math.ceil(pin.start*1000),Math.min(Math.ceil(pin.end*1000)-1,Math.round(sourceTime*1000))),instruction});if(next){commentaryDrafts.delete(draftKey);markersKey='';markers();controls();say('Commentary saved to this section. Ask the chat to read your Frame notes.')}};
   form.append(label,input,save);form.hidden=sectionRevisionDraft?.project===doc.project_id&&sectionRevisionDraft.pin===pin.id;card.append(form);
  }
  box.append(card);
 }
}
function accept(next){
 if(!next?.project_id)return;
 if(doc?.project_id!==next.project_id){activeHandoff=null;closeSectionRevision();closeRange();$('relayStatus').textContent='';markupUI?.reset();markersKey='';selectedPin=null;savedNote=null;resultMode=!!next.rendered;$('sheet').close()}
 if(next.revision_parent)workingProjects.delete(next.revision_parent.project_id);workingProjects.set(next.project_id,next.name);
 const projectChanged=liveDoc?.project_id!==next.project_id;if(projectChanged){sectionPlayback=null;invalidateMedia();historyId=null;playbackClipIndex=-1;pendingTimelinePosition=null;closeComparison()}liveDoc=next;doc=(historyId&&historySelection(next,historyId))||next;if(projectChanged)publishProjectContext();activeHandoff=[activeHandoff,latestBrowserHandoff(doc.project_id),doc.revision_handoffs?.at(-1)].filter(Boolean).sort((a,b)=>(a.created_at||0)-(b.created_at||0)).at(-1)||null;if(activeHandoff)$('relayStatus').textContent=deliveryLabel(activeHandoff)+' · v'+activeHandoff.version;if(selectedPin&&!doc.pins.some(p=>p.id===selectedPin))selectedPin=null;renderActivity();markers();renderClipTimeline();controls();markupUI?.render();video.ontimeupdate?.();
 const parent=doc.revision_parent,target=doc.next_revision;
 $('newDirectionNotice').hidden=!doc.next_direction;
 $('newDirectionLabel').textContent=doc.next_direction?'New cut ready · '+doc.next_direction.asset_name:'';
 $('openNewDirection').onclick=()=>{if(doc.next_direction)void openProject(doc.next_direction.project_id,false)};
 $('continuationNotice').hidden=!parent&&!target;
 $('continuationLabel').textContent=parent?'Revised copy · ready for more edits':'A revised copy is ready';
 $('continuationLink').textContent=parent?'Previous project':'Open revised copy';
 $('continuationLink').onclick=()=>{const pid=parent?.project_id||target?.project_id;if(!pid)return;if(parent)heldParents.add(pid);void openProject(pid,!parent)};
}
let activityKey='';
function renderActivity(){
 const rows=[...(doc?.activity||[])];
 for(const e of doc?.exports||[])rows.push({id:e.id,command:e.section_id?'Section render':'Video render',message:e.status==='done'?'Preview ready':e.error||'Rendering MP4…',status:e.status==='working'?'running':e.status,created_at:e.created});
 for(const p of doc?.proposals||[])rows.push({id:p.id,command:'Revision',message:p.error||p.status,status:['planning','rendering'].includes(p.status)?'running':p.status,created_at:p.created_at});
 rows.sort((a,b)=>b.created_at-a.created_at);const key=JSON.stringify([doc?.project_id,rows]);if(key===activityKey)return;activityKey=key;
 const list=$('activityLog');list.replaceChildren();for(const row of rows){const li=document.createElement('li');li.textContent=new Date(row.created_at*1000).toLocaleTimeString()+' · '+row.command.replaceAll('_',' ')+' · '+row.status+' · '+row.message;list.append(li)}
 $('activityState').textContent=rows.some(r=>r.status==='running')?'Work in progress · updates automatically':rows.length?'Up to date · watching for commands':'Waiting for commands';
}
function currentExport(){return resultMode&&doc?.rendered?doc.rendered.proposal_id:null}
function mediaState(message,{error=false,progress=false}={}){
 $('mediaState').hidden=!message;$('mediaMessage').textContent=message||'';
 $('mediaProgress').hidden=!progress;$('retryMedia').hidden=!error;
 $('videoStage').setAttribute('aria-busy',String(progress));
}
function invalidateMedia(){
 ++mediaGeneration;mediaKey='';mediaLoadPromise=null;loadingMedia=false;mediaError=false;sectionPlayback=null;
 video.pause();video.hidden=true;video.removeAttribute('src');video.load();
 if(mediaUrl)URL.revokeObjectURL(mediaUrl);mediaUrl='';downloadBlob=null;
 $('download').hidden=true;$('download').removeAttribute('href');
 mediaState(null);
}
function previewFailed(message){
 mediaError=true;video.pause();video.hidden=true;$('empty').hidden=true;
 $('download').hidden=true;mediaState(message,{error:true});say(message,true);controls();
}
function feedbackTarget(){
 if(!doc||loadingMedia||mediaError||comparing||sectionPlayback||!mediaUrl||video.src!==mediaUrl||video.readyState<2)return null;
 const exportId=currentExport();
 if(mediaKey!==doc.project_id+':'+(exportId||'source'))return null;
 if(exportId){return {project_id:doc.project_id,export_id:exportId,export_version:doc.rendered.timeline_version}}
 return doc.revision_parent?{project_id:doc.project_id,export_id:'source',export_version:0}:null;
}
function previewDecoded(){
 if(!doc||mediaError||loadingMedia||!mediaUrl||video.src!==mediaUrl||video.readyState<2)return;
 mediaState(null);controls();
}
function loadVideo(){
 if(!doc)return Promise.resolve();const project=doc.project_id,exportId=currentExport(),key=project+':'+(exportId||'source');
 if(key===mediaKey)return mediaLoadPromise||Promise.resolve();
 invalidateMedia();mediaKey=key;const generation=mediaGeneration;loadingMedia=true;
 $('empty').hidden=true;$('mediaProgress').value=0;mediaState('Loading preview…',{progress:true});controls();
 const work=(async()=>{try{
  let offset=0,total=null;const chunks=[];say('Loading video…');
  do{
   const r=await rpc('read_video_chunk',{project_id:project,offset,max_bytes:1048576,...(exportId?{export_id:exportId}:{})});if(generation!==mediaGeneration)return;
   const d=data(r),raw=r._meta?.videoChunk;if(typeof raw!=='string'||d.offset!==offset||d.project_id!==project||d.export_id!==(exportId||null))throw Error('Video chunk did not match this project.');
   if(total!==null&&total!==d.total_bytes)throw Error('Video changed while loading. Refresh to retry.');total=d.total_bytes;
   const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0));if(bytes.length!==d.next_offset-offset||!bytes.length||bytes.length>1048576||!Number.isSafeInteger(total)||total>1073741824||d.next_offset>total)throw Error('Invalid video chunk.');
   chunks.push(bytes);offset=d.next_offset;const percent=Math.round(offset/total*100);$('mediaProgress').value=percent;$('mediaMessage').textContent=`Loading preview · ${percent}%`;say(`Loading video · ${percent}%`);
  }while(offset<total);
  if(generation!==mediaGeneration)return;
  const blob=new Blob(chunks,{type:'video/mp4'}),url=URL.createObjectURL(blob);mediaUrl=url;downloadBlob=exportId?blob:null;video.src=url;video.load();
  if(exportId){$('download').href=url;$('download').download='frame-edit-'+project.slice(0,6)+'.mp4';$('download').hidden=false}
  mediaState('Preparing playback…',{progress:true});
  say(exportId?'Rendered edit loaded. Play to review, or download the MP4.':doc.revision_parent?'Revised copy loaded. Ready for your next revision.':'Timeline preview ready. Cuts play without gaps. Export to save an MP4.');
 }catch(e){if(generation!==mediaGeneration)return;mediaKey='';previewFailed('Preview unavailable. '+e.message+' Retry preview to reconnect.')}finally{if(generation===mediaGeneration){loadingMedia=false;mediaLoadPromise=null;previewDecoded();controls()}}})();
 mediaLoadPromise=work;return work;
}

function continuation(doc){const p=doc?.next_revision;return p?.source_version===doc.version&&!(doc.notes||[]).some(n=>n.included!==false&&!['applied','done','removed'].includes(n.status))?p:null}
async function resolveContinuation(next,isCurrent){
 const seen=new Set();
 while(continuation(next)&&!heldParents.has(next.project_id)){
  if(seen.has(next.project_id))throw Error('Invalid revised-copy loop.');seen.add(next.project_id);
  const pointer=continuation(next),child=data(await rpc('get_project',{project_id:pointer.project_id}));if(!isCurrent())return null;
  const parent=child.revision_parent;
  if(parent?.project_id!==next.project_id||parent.sha256!==pointer.sha256||parent.export_id!==pointer.export_id)throw Error('Revised copy did not match this project.');
  next=child;
 }
 return next;
}
async function openProject(pid,follow=true){if(!pid)return;homeUpload=null;homeLibrary?.clear();invalidateMedia();mediaState('Opening project…',{progress:true});$('empty').hidden=true;const request=Symbol();opening=request;try{let next=data(await rpc('get_project',{project_id:pid}));if(follow)next=await resolveContinuation(next,()=>opening===request);if(!next||opening!==request)return;await loadAncestry(next);if(opening!==request)return;accept(next);await list();await loadVideo()}catch(e){say(e.message,true)}finally{if(opening===request)opening=null}}
async function followContinuation(next){
 const pid=next.project_id,canFollow=()=>doc?.project_id===pid&&!heldParents.has(pid)&&!historyId&&!comparing&&!busy&&!relayBusy&&!markupUI?.active&&!document.querySelector('dialog[open]')&&!referenceTabActive&&!rangeProject&&!sectionRevisionDraft&&![...commentaryDrafts.keys()].some(k=>k.startsWith(pid+':'));
 if(!continuation(next)||!canFollow())return false;
 const child=await resolveContinuation(next,canFollow);
 if(!child||!canFollow()||child.project_id===pid)return false;
 await loadAncestry(child);if(!canFollow())return false;accept(child);await list();await loadVideo();return true;
}
function savedDraftNote(next,request){
 if(!['add_note','add_general_note'].includes(request.action)||!Number.isInteger(request.expected_version)||request.expected_version>=next.version)return null;
 const general=request.action==='add_general_note';
 return (next.notes||[]).find(n=>n.created_version===request.expected_version&&n.revision_set_id===next.active_revision_set_id&&n.status==='queued'&&n.included!==false&&!n.annotations?.length&&n.scope===(general?'general':'section')&&n.section_id===(general?null:request.section_id)&&n.source_time_ms===(general?null:request.source_time_ms)&&n.output_time_ms===(Number.isInteger(request.output_time_ms)?request.output_time_ms:null)&&n.instruction===request.instruction)||null;
}
function savedNoteAttempt(next,request){return !!savedDraftNote(next,request)}
async function mutate(name,args){
 if(!doc||busy||relayBusy||historyId)return null;
 busy=true;video.pause();controls();const pid=doc.project_id,request={project_id:pid,expected_version:doc.version,...args};
 try{const next=data(await rpc(name,request));if(doc?.project_id!==pid)return null;accept(next);return next}
 catch(e){say(e.message,true);try{
  const next=data(await rpc('get_project',{project_id:pid}));if(doc?.project_id!==pid)return null;accept(next);
  if(name==='update_editor'&&savedNoteAttempt(next,request))return next;
 }catch{}return null}
 finally{busy=false;controls()}
}
function update(args){return mutate('update_editor',args)}
function noteDraftAttempt(key,args){
 const previous=noteDraftAttempts.get(key);
 if(previous&&previous.action===args.action&&previous.section_id===args.section_id&&previous.instruction===args.instruction)return previous;
 const attempt={...args,expected_version:doc.version};noteDraftAttempts.set(key,attempt);return attempt;
}
async function saveDraftNote(key,args){
 const pid=doc.project_id,attempt=noteDraftAttempt(key,args);
 const next=savedNoteAttempt(doc,attempt)?doc:await update(attempt);
 if(doc?.project_id!==pid)return null;
 if(next||doc.version>attempt.expected_version)noteDraftAttempts.delete(key);
 return next;
}
function command(name,args={}){return mutate(name,args)}
markupUI=createMarkup({video,getDoc:()=>doc,getPoint:sourcePoint,getSelected:()=>selectedPin,save:update,onChange:controls,say});
studioUI=createStudio({app,video,getDoc:()=>doc,isResult:()=>resultMode,getTime:()=>timelinePlayhead(),seek:time=>{video.pause();seekTimelinePosition(time)},canEdit:()=>connected&&!!doc&&!busy&&!historyId&&!relayBusy&&!markupUI?.active,command,toOriginal:async()=>{resultMode=false;if(mediaKey!==doc?.project_id+':source'){mediaKey='';await loadVideo()}controls()},rpc,data,say,accept});
sectionTimeline=createSectionTimeline({video,getDoc:()=>doc,getSelected:()=>selectedPin,isEdited:()=>resultMode,onSelect:pin=>{if(busy||markupUI?.active)return;selectedPin=pin.id;const t=timeInView(pin.start);if(t!==null){video.pause();video.currentTime=t}markers();controls()}});
async function referenceImage(project_id,section_id,reference_id){
 const key=project_id+':'+reference_id;if(referenceUrls.has(key))return referenceUrls.get(key);
 const pending=(async()=>{const result=await rpc('get_section_reference',{project_id,section_id,reference_id});const image=result.content?.find(c=>c.type==='image');if(!image)throw Error('Image unavailable');const bytes=Uint8Array.from(atob(image.data),c=>c.charCodeAt(0));return URL.createObjectURL(new Blob([bytes],{type:image.mimeType}))})();referenceUrls.set(key,pending);try{return await pending}catch(e){referenceUrls.delete(key);throw e}
}
async function prepareReference(file){
 if(file.size>20*1024*1024)throw Error('Choose an image under 20 MB.');
 if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('Choose a PNG, JPEG or WebP image.');
 const bitmap=await createImageBitmap(file);try{const canvas=document.createElement('canvas');const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
 for(const quality of [.88,.72,.55,.35]){const encoded=canvas.toDataURL('image/jpeg',quality).split(',')[1];if(encoded.length<=349528)return encoded}throw Error('Image is too detailed. Choose a smaller reference.');}finally{bitmap.close()}
}
async function downloadSection(project_id,export_id,number){
 if(downloadBusy)return;downloadBusy=true;try{
  const filename='Frame-section-'+number+'.mp4';say('Preparing section download…');
  if(app.getHostCapabilities()?.downloadFile){let offset=0,total=null;const chunks=[];do{const r=await rpc('read_video_chunk',{project_id,export_id,offset,max_bytes:1048576}),d=data(r),raw=r._meta?.videoChunk;if(typeof raw!=='string'||d.project_id!==project_id||d.export_id!==export_id||d.offset!==offset)throw Error('Section chunk did not match.');const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0));if(!bytes.length||bytes.length!==d.next_offset-offset||bytes.length>1048576||!Number.isSafeInteger(d.total_bytes)||d.total_bytes>1073741824||d.next_offset>d.total_bytes||(total!==null&&total!==d.total_bytes))throw Error('Invalid section chunk.');total=d.total_bytes;chunks.push(bytes);offset=d.next_offset;}while(offset<total);
   const blob=new Blob(chunks,{type:'video/mp4'});const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not prepare section.'));reader.readAsDataURL(blob)});
   const result=await app.downloadFile({contents:[{type:'resource',resource:{uri:'file:///'+filename,mimeType:'video/mp4',blob:encoded}}]});if(result?.isError)throw Error('Download was declined.');
  }else{const result=data(await rpc('prepare_download',{project_id,export_id}));await app.openLink({url:result.download_url})}
  say('Section MP4 opened for download.');
 }catch(e){say('Section download failed. '+e.message,true)}finally{downloadBusy=false}
}
$('closeReferenceViewer').onclick=()=>$('referenceViewer').close();
$('closeProjectBrowser').onclick=()=>$('projectBrowser').close();
async function openCurrentProjectPanel(){
 if(!connected||!doc||busy||projectPanelBusy)return;
 const projectId=doc.project_id;
 projectPanelBusy=true;controls();
 try{
  const link=data(await rpc('project_link',{project_id:projectId}));
  if(doc?.project_id!==projectId)throw Error('The open project changed. Use the shortcut again.');
  const result=await sendToCurrentChat(app,{role:'user',content:[{type:'text',text:'Open this Frame project in an additional right-hand browser panel beside this chat. Use open_in_codex with placement "right" and target {type:"browser",url:'+JSON.stringify(link.url)+'}. Current Frame project ID: '+projectId+'. Open the saved project without editing it. This is a panel-opening request, not a video revision.'}]});
  if(result?.isError)throw Error('The host declined the panel request.');
  say('Panel request sent to chat. The project will open beside this conversation.');
 }catch(e){say('Could not request the extra project panel. '+e.message,true)}
 finally{projectPanelBusy=false;controls()}
}

async function openLibraryFiles(pid){await openProject(pid,false);if(doc?.project_id===pid)projectFiles?.open()}
async function openLibraryRevision(pid,checkpoint){
 await openProject(pid,false);if(doc?.project_id!==pid)return;
 if(!liveDoc.checkpoints?.some(c=>c.id===checkpoint))return say('This saved version is unavailable. The current project is open.',true);
 historyId=checkpoint;closeRange();markupUI?.reset();video.pause();accept(liveDoc);resultMode=!!doc.rendered;mediaKey='';await loadVideo();say('Viewing a saved version. Restore it to continue editing.');
}
const library=createProjectLibrary({rpc,data,getItems:()=>projectItems,refresh:list,openProject,openRevision:openLibraryRevision,openFiles:openLibraryFiles,app,say,dialog:$('projectBrowser'),list:$('projectBrowserList'),summary:$('projectBrowserSummary')});
homeLibrary=createProjectLibrary({rpc,data,getItems:()=>projectItems,refresh:list,openProject,openRevision:openLibraryRevision,openFiles:openLibraryFiles,app,say,dialog:$('homeProjects'),list:$('homeProjectList'),summary:$('homeProjectSummary'),embedded:true});
async function showHome(){if(doc)return;if(!homeUpload)$('homeStatus').textContent='';void app.updateModelContext({content:[{type:'text',text:JSON.stringify({app:'Frame',view:'projects',home:true,active_project_id:null,instructions:'Let the user select a project or add footage. Do not choose a project by global recency.'})}]}).catch(()=>{});await homeLibrary.show();if(!projectItems.length)$('homeProjectSummary').textContent='No projects yet. Add your first video to begin.'}
async function checkHomeUpload(){
 if(!homeUpload||doc||homeChecking||!connected)return;homeChecking=true;const pending=homeUpload;
 try{await list();if(homeUpload!==pending||doc)return;const match=projectItems.find(p=>p.work_project?.upload_session_id===pending.id);if(match){homeUpload=null;await openProject(projectId(match),false)}}
 catch(e){$('homeStatus').textContent='Waiting for your upload. Refresh projects to reconnect. '+e.message}
 finally{homeChecking=false;controls()}
}
$('homeAddFootage').onclick=async()=>{
 if(homeUploading||!connected)return;homeUploading=true;controls();
 try{const result=data(await rpc('open_editor',{}));if(!/^[a-f0-9]{32}$/.test(result.upload_session_id||''))throw Error('Reconnect the Frame plugin in this chat, then reopen Frame to add new footage.');const url=new URL(result.upload_url);if(!['http:','https:'].includes(url.protocol)||url.pathname!=='/frame/new'||url.searchParams.get('session')!==result.upload_session_id)throw Error('Invalid upload link.');homeUpload={id:result.upload_session_id,url:url.href};await app.openLink({url:url.href});$('homeStatus').textContent='Choose a video on the upload page, then return here. Your new project will open automatically.'}
 catch(e){$('homeStatus').textContent='Could not open the upload. '+e.message}
 finally{homeUploading=false;controls()}
};
$('homeResumeUpload').onclick=async()=>{if(!homeUpload)return;try{await app.openLink({url:homeUpload.url})}catch(e){$('homeStatus').textContent=e.message}};
$('homeRefresh').onclick=async()=>{await refreshPreview();if(!doc){await checkHomeUpload();if(!doc)await showHome()}};
$('browseProjects').onclick=()=>library.show();
$('projectHome').onclick=()=>{if(busy||relayBusy)return;homeUpload=null;historyId=null;liveDoc=null;doc=null;opening=null;closeSectionRevision();closeRange();sectionPlayback=null;invalidateMedia();closeComparison();$('empty').hidden=false;controls();void showHome()};
$('closeWorkingProject').onclick=async()=>{if(busy||relayBusy||!doc)return;const id=doc.project_id;workingProjects.delete(id);if(workingProjects.size)await openProject([...workingProjects.keys()].at(-1));else{historyId=null;liveDoc=null;doc=null;opening=null;closeSectionRevision();closeRange();sectionPlayback=null;invalidateMedia();closeComparison();$('empty').hidden=false;controls();say('Project saved in All projects.');void showHome()}};
$('projects').onchange=$('editHistory').onchange=async event=>{
 if(busy||markupUI?.active||!liveDoc)return;
 const id=(event?.target||$('projects')).value;if(id.startsWith('cut:')){await openProject(id.slice(4),false);return;}historyId=id==='latest'?null:id;closeRange();markupUI?.reset();video.pause();
 accept(liveDoc);resultMode=!!doc.rendered;await loadVideo();
 if(historyId)say(doc.rendered?'Viewing a saved export. Restore this revision to continue editing.':'Saved timeline selected. Restore and export to preview its edits; the player shows the original source.');
};
$('restoreRevision').onclick=async()=>{
 if(!historyId||busy)return;
 if(historyId.startsWith('ancestor:')){
  const [,pid,cid]=historyId.split(':'),parent=ancestorProjects.get(liveDoc.project_id)?.find(p=>p.project_id===pid);
  if(!parent)return;busy=true;controls();
  try{const next=data(await rpc('update_editor',{project_id:pid,expected_version:parent.version,action:'restore_checkpoint',checkpoint_id:cid}));heldParents.add(pid);historyId=null;await loadAncestry(next);accept(next);resultMode=!!doc.rendered;await loadVideo();say('Earlier version restored as a new branch. Later versions remain in All projects.')}catch(e){say('Could not restore earlier version. '+e.message,true)}finally{busy=false;controls()}return;
 }
 const id=historyId;historyId=null;accept(liveDoc);
 const next=await update({action:'restore_checkpoint',checkpoint_id:id});
 if(next){resultMode=!!doc.rendered;await loadVideo();say('Revision restored as a new version. All previous revisions are preserved.')}
 else{historyId=id;accept(liveDoc)}
};
async function refreshPreview(){
 if(busy)return;if(refreshing)return refreshing;
 const pid=doc?.project_id,selection=historyId,mode=resultMode,requestOpening=opening,position=doc?timelinePlayhead():0;
 const current=()=>doc?.project_id===pid&&historyId===selection&&resultMode===mode&&opening===requestOpening;
 const work=(async()=>{try{
  if(!hostReady){await app.connect();hostReady=true;theme(app.getHostContext())}
  await list();if(!current())return;
  if(pid){const next=data(await rpc('get_project',{project_id:pid}));if(!current())return;
   await loadAncestry(next);if(!current())return;accept(next);
   if(!await followContinuation(next)){if(!current())return;pendingTimelinePosition=position;mediaKey='';await loadVideo()}
  }else say('Connected. Choose a project or attach a video in chat.');
 }catch(e){if(!current())return;health(false);say('Could not refresh. Saved work is preserved. '+e.message,true)}finally{refreshing=null;controls()}})();
 refreshing=work;controls();return work;
}
$('refresh').onclick=refreshPreview;
$('retryMedia').onclick=refreshPreview;
$('expand').onclick=async()=>{try{await app.requestDisplayMode({mode:app.getHostContext()?.displayMode==='fullscreen'?'inline':'fullscreen'})}catch{say('This host controls the panel size.')}};
$('play').onclick=async()=>{if($('play').disabled)return;try{if(video.paused)await video.play();else video.pause()}catch(e){say('Playback failed. '+e.message,true)}};
let scrubFrame=0;
$('scrub').oninput=()=>{video.pause();const time=Number($('scrub').value);sectionTimeline?.updatePlayhead(time);cancelAnimationFrame(scrubFrame);video.currentTime=time};
function scrubAt(event){const r=$('scrub').getBoundingClientRect();$('scrub').value=Math.max(0,Math.min(1,(event.clientX-r.left)/r.width))*Number($('scrub').max);$('scrub').oninput()}
$('scrub').onpointerdown=event=>{if(event.button!==0||$('scrub').disabled)return;event.preventDefault();$('scrub').focus({preventScroll:true});$('scrub').setPointerCapture(event.pointerId);scrubAt(event)};
$('scrub').onpointermove=event=>{if($('scrub').hasPointerCapture(event.pointerId))scrubAt(event)};
$('scrub').onpointerup=event=>{if($('scrub').hasPointerCapture(event.pointerId)){$('scrub').releasePointerCapture(event.pointerId);scrubAt(event)}};
$('timelineSeek').oninput=()=>{video.pause();seekTimelinePosition(Number($('timelineSeek').value))};
video.ontimeupdate=()=>{if(!checkSectionPlayback())advanceMagneticPlayback();renderRangeDraft();const playhead=timelinePlayhead(),duration=resultMode?(doc?.duration||video.duration):timelineDuration();$('scrub').value=video.currentTime;$('timelineSeek').max=duration;$('timelineSeek').value=playhead;$('clock').textContent=`${fmt(playhead)} / ${fmt(duration)}`;markupUI?.render();sectionTimeline?.render(video.currentTime||0);updateClipTimelineActive()};
video.onloadedmetadata=()=>{if(pendingTimelinePosition!==null){seekTimelinePosition(pendingTimelinePosition);pendingTimelinePosition=null}else if(!resultMode&&!sourcePoint().clip&&doc?.clips?.length)seekTimelinePosition(0);$('scrub').max=video.duration;$('timelineSeek').max=resultMode?(doc?.duration||video.duration):timelineDuration();video.ontimeupdate();controls()};video.onloadeddata=previewDecoded;video.oncanplay=previewDecoded;video.onseeked=previewDecoded;
video.onplay=()=>{if(!resultMode){const point=sourcePoint();let index=doc?.clips.findIndex(c=>c.id===point.clip?.id)??-1;if(index<0)index=doc?.clips.findIndex(c=>c.start>video.currentTime)??-1;if(index<0)index=0;playbackClipIndex=index;const clip=doc?.clips[index];if(clip&&(video.currentTime<clip.start||video.currentTime>=clip.end))video.currentTime=clip.start;updateClipTimelineActive()}$('play').textContent='Pause'};video.onpause=()=>{$('play').textContent='Play';updateClipTimelineActive()};
video.onended=()=>{if(checkSectionPlayback())return;if(!resultMode&&video.ended&&nextPlaybackClip())void video.play().catch(e=>say('Playback failed. '+e.message,true))};
$('moveEarlier').onclick=()=>moveTimelineClip(-1);$('moveLater').onclick=()=>moveTimelineClip(1);
video.onerror=()=>{if(!mediaUrl||loadingMedia)return;mediaKey='';previewFailed('Playback interrupted. Retry preview to reload this saved video.');};
video.onclick=()=>{$('play').click()};
$('view').onclick=()=>{resultMode=!resultMode;controls();void loadVideo()};
$('undo').onclick=()=>historyTimeline('undo');
$('redo').onclick=()=>historyTimeline('redo');
$('split').onclick=()=>editTimelineAtPlayhead('split_clip');$('trimIn').onclick=()=>editTimelineAtPlayhead('trim_in');$('trimOut').onclick=()=>editTimelineAtPlayhead('trim_out');$('deleteClip').onclick=()=>editTimelineAtPlayhead('delete_segment');
$('trim').onclick=()=>{video.pause();const point=sourcePoint(),clip=doc?.clips.find(c=>c.id===point.clip?.id)||doc?.clips[0];if(!clip)return;sheetKind='trim';sheetClip=clip;$('sheetTitle').textContent='Trim segment';$('trimFields').hidden=false;$('noteFields').hidden=true;$('sendNote').hidden=true;$('saveSheet').textContent='Save trim';$('start').value=clip.start;$('end').value=clip.end;$('sheet').showModal()};
$('trim').onclick=()=>{video.pause();const point=sourcePoint(),clip=doc?.clips.find(c=>c.id===point.clip?.id)||doc?.clips[0];if(!clip)return;sheetKind='trim';sheetClip=clip;$('sheetTitle').textContent='Trim segment';$('trimFields').hidden=false;$('noteFields').hidden=true;$('sendNote').hidden=true;$('saveSheet').textContent='Save trim';$('start').value=clip.start;$('end').value=clip.end;$('sheet').showModal()};
const sectionTime=time=>`${Math.floor(time/60).toString().padStart(2,'0')}:${(time%60).toFixed(3).padStart(6,'0')}`;
const boundaryTime=()=>Math.round(sourcePoint().time*1000)/1000;
function renderRangeDraft(){
 const draft=$('rangeDraft');if(!rangeProject||rangeProject!==doc?.project_id){draft.hidden=true;return}
 const start=rangeValue('rangeStart'),chosenEnd=rangeValue('rangeEnd'),end=Number.isFinite(chosenEnd)?chosenEnd:boundaryTime();
 const a=timeInView(start),b=timeInView(end,true),duration=resultMode?doc?.duration:doc?.source_duration;
 draft.hidden=!Number.isFinite(a)||!Number.isFinite(b)||a===null||b===null||b<a||!duration;
 if(!draft.hidden){draft.style.left=100*a/duration+'%';draft.style.width=`max(2px, ${100*(b-a)/duration}%)`}
}
function closeRange(){rangeProject=null;rangePin=null;$('sectionPicker').hidden=true;$('rangeDraft').hidden=true;controls()}
function rangeValue(id){const raw=$(id).value;return raw.trim()===''?NaN:Number(raw)}
function rangeControls(){
 if(!$('sectionPicker')||$('sectionPicker').hidden)return;
 const start=rangeValue('rangeStart'),end=rangeValue('rangeEnd'),check=validateSectionRange(doc,start,end);
 const locked=!connected||busy||rangeSaving||relayBusy||!!historyId||!!markupUI?.active||rangeProject!==doc?.project_id;
 for(const id of ['rangeStart','rangeEnd','rangeCancel'])$(id).disabled=locked;
 for(const id of ['rangeSetStart','rangeSetEnd'])$(id).disabled=locked||loadingMedia||mediaError||!mediaUrl;
 $('rangeSave').disabled=locked||!!check.error;
 $('rangeSave').textContent=rangeSaving?'Saving…':rangePin?'Save boundaries':'Save section';
 $('rangeHeading').textContent=rangePin?'Adjust section':'New section';
 $('rangeStatus').textContent=!Number.isFinite(end)&&Number.isFinite(start)?`Start set at ${sectionTime(start)}. Play or scrub to the end, then choose End & save (O).`:check.error||`${sectionTime(check.start)} → ${sectionTime(check.end)} · ${(check.end-check.start).toFixed(3)}s selected`;
 $('rangeStatus').classList.toggle('error',Number.isFinite(end)&&!!check.error);renderRangeDraft();
}
function openRange(pin=null){
 if(!doc||busy||rangeSaving||relayBusy||historyId||loadingMedia||mediaError||!mediaUrl||markupUI?.active)return;
 video.pause();closeSectionRevision();sectionPlayback=null;rangeProject=doc.project_id;rangePin=pin?.id||null;
 const start=pin?.start??boundaryTime();
 $('rangeStart').value=String(start);$('rangeEnd').value=pin?.end==null?'':String(pin.end);
 $('sectionPicker').hidden=false;controls();
 say(pin?'Adjust the boundaries, then Save boundaries.':`Section start set at ${sectionTime(start)}. Play or scrub to the end, then press O.`);
}
async function saveRange(){
 if(rangeSaving||busy||relayBusy||historyId||rangeProject!==doc?.project_id)return;
 const check=validateSectionRange(doc,rangeValue('rangeStart'),rangeValue('rangeEnd'));
 if(check.error){rangeControls();say(check.error,true);return}
 rangeSaving=true;controls();
 try{
  const before=new Set(doc.pins.map(p=>p.id)),pid=doc.project_id,editing=rangePin;
  const next=await update(editing?{action:'edit_pin',pin_id:editing,start:check.start,end:check.end}:{action:'add_pin',clip_id:check.clip.id,time:check.start,start:check.start,end:check.end});
  if(next&&doc?.project_id===pid){selectedPin=editing||next.pins.find(p=>!before.has(p.id))?.id||null;closeRange();openSectionRevision(selectedPin);markersKey='';markers();say(`Section saved · ${sectionTime(check.start)} → ${sectionTime(check.end)}. Preview it or add your revision below.`)}
 }finally{rangeSaving=false;controls()}
}
$('pin').onclick=()=>openRange();
$('finishSection').onclick=async()=>{if($('finishSection').disabled)return;video.pause();$('rangeEnd').value=String(boundaryTime());await saveRange()};
$('rangeStart').oninput=$('rangeEnd').oninput=rangeControls;
$('rangeSetStart').onclick=()=>{video.pause();$('rangeStart').value=String(boundaryTime());rangeControls()};
$('rangeSetEnd').onclick=()=>{video.pause();$('rangeEnd').value=String(boundaryTime());rangeControls()};
$('rangeCancel').onclick=()=>{closeRange();say('Section selection cancelled.')};
$('rangeSave').onclick=saveRange;
function closeSectionRevision(){sectionRevisionDraft=null;$('pinPrompt').hidden=true;$('pinPromptStatus').textContent='';markersKey='';}
function sectionRevisionControls(){
 if(!sectionRevisionDraft)return;
 const pin=doc?.project_id===sectionRevisionDraft.project?doc.pins.find(p=>p.id===sectionRevisionDraft.pin&&p.end!=null):null;
 if(!pin){closeSectionRevision();return}
 const locked=!connected||busy||relayBusy||!!historyId||!!markupUI?.active;
 $('pinPromptText').disabled=locked;$('savePinPrompt').disabled=locked||!$('pinPromptText').value.trim();$('skipPinPrompt').disabled=busy;
 $('savePinPrompt').textContent=busy?'Saving…':'Save revision';
 $('pinPromptAnchor').textContent=`Section ${doc.pins.indexOf(pin)+1} · ${sectionTime(pin.start)} → ${sectionTime(pin.end)}`;
}
function openSectionRevision(pinId){
 const pin=doc?.pins.find(p=>p.id===pinId&&p.end!=null);if(!pin)return;
 sectionRevisionDraft={project:doc.project_id,pin:pinId};$('pinPromptText').value=commentaryDrafts.get(doc.project_id+':'+pinId)||'';
 $('pinPrompt').hidden=false;$('pinPromptStatus').textContent='Describe the change, then save it to this section.';sectionRevisionControls();
 $('pinPromptText').focus({preventScroll:true});$('pinPrompt').scrollIntoView({behavior:'smooth',block:'nearest'});
}
$('pinPromptText').oninput=()=>{if(!sectionRevisionDraft)return;commentaryDrafts.set(sectionRevisionDraft.project+':'+sectionRevisionDraft.pin,$('pinPromptText').value);sectionRevisionControls()};
$('skipPinPrompt').onclick=()=>{closeSectionRevision();markers();say('You can add the section revision below whenever you are ready.')};
$('sectionRevisionForm').onsubmit=async event=>{
 event.preventDefault();if(!sectionRevisionDraft||busy||relayBusy||historyId||!connected)return;
 const target={...sectionRevisionDraft},text=$('pinPromptText').value,instruction=text.trim();if(!instruction)return;
 const pin=doc?.project_id===target.project?doc.pins.find(p=>p.id===target.pin):null;if(!pin)return;
 const point=sourcePoint().time,anchor=point>=pin.start&&point<pin.end?point:pin.start;
 const previous=sectionRevisionDraft.attempt;
 const attempt=previous?.instruction===instruction?previous:{action:'add_note',section_id:pin.id,source_time_ms:Math.max(Math.ceil(pin.start*1000),Math.min(Math.ceil(pin.end*1000)-1,Math.round(anchor*1000))),instruction,expected_version:doc.version};
 sectionRevisionDraft.attempt=attempt;
 const next=savedNoteAttempt(doc,attempt)?doc:await update(attempt);
 if(next&&doc?.project_id===target.project&&sectionRevisionDraft?.pin===target.pin){
  if(commentaryDrafts.get(target.project+':'+target.pin)===text)commentaryDrafts.delete(target.project+':'+target.pin);
  $('pinPromptText').value='';closeSectionRevision();markers();controls();say('Revision saved to Section '+(doc.pins.findIndex(p=>p.id===target.pin)+1)+' below.');
 }else if(sectionRevisionDraft?.project===target.project&&sectionRevisionDraft.pin===target.pin){
  // An observed newer version without this note proves this attempt did not commit.
  // Otherwise reuse the original version and anchor until its outcome is known.
  if(doc.version>attempt.expected_version)sectionRevisionDraft.attempt=null;
  $('pinPromptStatus').textContent='Could not save. Your text is preserved; retry Save revision.';sectionRevisionControls()
 }
};
function selectedSectionControls(previewReady){
 const pin=doc?.pins?.find(p=>p.id===selectedPin&&p.end!=null);
 $('selectedSectionActions').hidden=!pin||!!rangeProject;
 const locked=!pin||!previewReady||busy||relayBusy||!!historyId||!!markupUI?.active;
 for(const id of ['previewSelectedSection','adjustSelectedSection','exportSelectedSection'])$(id).disabled=locked;
 if(pin){
  $('selectedSectionLabel').textContent=`Section ${doc.pins.indexOf(pin)+1} · ${sectionTime(pin.start)} → ${sectionTime(pin.end)}`;
  const output=sectionOutput(pin);$('exportSelectedSection').textContent=output?.status==='done'?'Download section MP4':output?.status==='working'?'Exporting section…':'Export section MP4';
  $('exportSelectedSection').disabled ||= output?.status==='working';
 }
}
function selectedSection(){return doc?.pins?.find(p=>p.id===selectedPin&&p.end!=null)}
function sectionOutput(pin){return (doc.exports||[]).filter(e=>e.section_id===pin.id&&e.source_start===pin.start&&e.source_end===pin.end).at(-1)}
async function exportSection(pin){
 if(!pin||busy||relayBusy||historyId)return;
 const latest=sectionOutput(pin);
 if(latest?.status==='done')return downloadSection(doc.project_id,latest.id,doc.pins.indexOf(pin)+1);
 if(latest?.status==='working')return;
 if(await command('export_video',{section_id:pin.id}))say('Exporting this section. Its download button will appear when ready.');
}
$('previewSelectedSection').onclick=()=>{const pin=selectedSection();if(pin)return previewSection(pin)};
$('adjustSelectedSection').onclick=()=>{const pin=selectedSection();if(pin)openRange(pin)};
$('exportSelectedSection').onclick=()=>exportSection(selectedSection());
async function previewSection(pin){
 if(busy||loadingMedia||mediaError||!mediaUrl)return;
 const start=timeInView(pin.start),end=timeInView(pin.end,true);
 if(start===null||end===null||end<=start)return say('Choose Original to preview this source section.',true);
 video.pause();selectedPin=pin.id;sectionPlayback={project:doc.project_id,id:pin.id,start,end};video.currentTime=start;markers();controls();
 try{await video.play();say('Previewing section · '+sectionTime(pin.start)+' → '+sectionTime(pin.end))}catch(e){sectionPlayback=null;say('Could not play section. '+e.message,true)}
}
function checkSectionPlayback(){
 if(!sectionPlayback)return;const selection=sectionPlayback;
 if(selection.project!==doc?.project_id||video.currentTime<selection.start-.05){sectionPlayback=null;return}
 if(video.currentTime>=selection.end){sectionPlayback=null;video.pause();video.currentTime=selection.end;say('Section preview finished.');return true}
 return false;
}
$('note').onclick=()=>{video.pause();const point=sourcePoint();const pin=doc.pins.find(p=>p.id===selectedPin&&p.end!=null&&p.start<=point.time&&point.time<p.end);if(!pin)return say('Set a start and end pin, then seek inside that range to leave a note.');sheetKind='note';noteDraftAttempts.delete(doc.project_id+':sheet');noteTime=point.time;savedNote=null;$('sheetTitle').textContent='Note at '+noteTime.toFixed(3)+' seconds';$('trimFields').hidden=true;$('noteFields').hidden=false;$('noteAnchor').textContent='Anchored to the original source frame.';$('instruction').value='';$('sendNote').hidden=true;$('saveSheet').textContent='Save note';$('sheet').showModal();$('instruction').focus()};
$('closeSheet').onclick=()=>$('sheet').close();
$('saveSheet').onclick=async()=>{if(sheetKind==='trim'){const next=await command('trim_clip',{clip_id:sheetClip.id,start:Number($('start').value),end:Number($('end').value)});if(next){$('sheet').close();say('Trim saved. Choose Export to render and review.')}}else{const key=doc.project_id+':sheet',attempt=noteDraftAttempt(key,{action:'add_note',section_id:selectedPin,source_time_ms:Math.round(noteTime*1000),instruction:$('instruction').value});const next=await saveDraftNote(key,attempt);if(next&&$('instruction').value===attempt.instruction){savedNote=savedDraftNote(next,attempt);$('sendNote').hidden=false;$('instruction').readOnly=true;$('saveSheet').hidden=true;controls();say('Note saved. Send it to the chat when ready.')}else if(next){savedNote=null;controls();say('Previous note saved. Your newer text is ready to save.')}}};
$('sheet').addEventListener('close',()=>{noteDraftAttempts.delete(doc?.project_id+':sheet');$('instruction').readOnly=false;$('saveSheet').hidden=false});
$('instruction').addEventListener('input',()=>{if(!$('instruction').value.trim())noteDraftAttempts.delete(doc?.project_id+':sheet')});
$('sendNote').onclick=async()=>{if(!savedNote)return;try{const r=await app.sendMessage({role:'user',content:[{type:'text',text:'Read Frame project '+doc.project_id+' and saved note '+savedNote.id+' at source '+(savedNote.source_time_ms/1000).toFixed(3)+' seconds. Explain the requested change and supported options before applying anything.'}]});if(r.isError)throw Error('Chat rejected the message.');$('sheet').close();say('Saved note sent to this chat.')}catch{say('Note remains saved. In chat, ask: “Read the notes in Frame project '+doc.project_id+'.”',true)}};
$('sendRevisions').onclick=async()=>{
 if(!doc||busy||relayBusy||historyId||markupUI?.active)return;relayBusy=true;controls();const pid=doc.project_id;$('revisionPromptText').value='';$('revisionPromptCopyStatus').textContent='';let stage='Reading saved revisions';
 const diagnostics=error=>{$('revisionPromptDiagnostics').textContent='Editor: handoff-20261103.2\nView: '+(window.parent===window?'standalone':'embedded')+'\nStage: '+stage+'\nCompatibility message API: '+(typeof window.openai?.sendFollowUpMessage==='function'?'available':'unavailable')+'\nError: '+(error||'none')};
 try{
  $('relayStatus').textContent='Building implementation prompt…';
  let latest=data(await rpc('get_project',{project_id:pid}));
  if(!savedVideoReady(latest)){
   stage='Saving current video';$('relayStatus').textContent='Saving the current video before sending…';
   latest=data(await rpc('export_video',{project_id:pid,expected_version:latest.version}));
   const expected=latest.version,exportId=latest.exports?.at(-1)?.id,deadline=Date.now()+180000;
   while(!savedVideoReady(latest)){
    if(doc?.project_id!==pid||latest.version!==expected)throw Error('Project changed while saving. Send again from the intended version.');
    const output=latest.exports?.find(e=>e.id===exportId);
    if(output?.status==='failed')throw Error('Video could not be saved. '+(output.error||''));
    if(Date.now()>deadline)throw Error('Video is still rendering. Wait for export to finish, then send again.');
    await new Promise(resolve=>setTimeout(resolve,1000));latest=data(await rpc('get_project',{project_id:pid}));
   }
  }
  if(doc?.project_id!==pid)throw Error('Project changed; send again from the intended project.');accept(latest);
  const comments=data(await rpc('get_frame_comments',{project_id:pid}));
  if(doc?.project_id!==pid)throw Error('Project changed; send again from the intended project.');
  const prompt=buildImplementationPrompt(latest,comments);
  $('revisionPromptText').value=prompt.text;
  $('revisionPromptSummary').textContent=`Project ${pid.slice(0,6)} · v${latest.version} · ${prompt.section_count} sections · ${prompt.revision_count} revisions · ${prompt.reference_count} reference images`;
  $('relayStatus').textContent='Sending implementation prompt…';
  stage='Reserving and submitting handoff';
  const row=await deliverRevisionPrompt({rpc:async(name,args)=>data(await rpc(name,args)),sendMessage:message=>sendToCurrentChat(app,message),projectId:pid,version:latest.version,text:prompt.text,requireSnapshot:true,isCurrent:()=>doc?.project_id===pid,onReserved:row=>{if(doc?.project_id===pid){activeHandoff=row;$('revisionPromptText').value=row.prompt}}});
  if(doc?.project_id!==pid)return;activeHandoff=row;
  $('relayStatus').textContent=deliveryLabel(row)+' · v'+row.version;
  if(['not_sent','uncertain','sending'].includes(row.status)){
   const reason=row.error||(row.may_send===false?'This saved prompt already has a pending handoff. Check the chat before sending it again.':'The chat has not confirmed receipt. Check the chat before copying the prompt to avoid duplicates.');
   say(deliveryLabel(row)+'. '+reason,true);$('revisionPromptReason').textContent=reason;diagnostics(reason);$('revisionPrompt').showModal();
  }else say(deliveryLabel(row)+'. Requested edits and rendering are tracked separately.');
 }catch(e){if(doc?.project_id===pid){$('relayStatus').textContent='Not sent';say('Implementation prompt was not sent. '+e.message,true);$('revisionPromptReason').textContent=e.message;diagnostics(e.message);if($('revisionPromptText').value)$('revisionPrompt').showModal()}}finally{relayBusy=false;controls()}
};
$('closeRevisionPrompt').onclick=()=>$('revisionPrompt').close();
$('copyRevisionPrompt').onclick=async()=>{try{await navigator.clipboard.writeText($('revisionPromptText').value);$('revisionPromptCopyStatus').textContent='Copied. This has not been sent to the chat.'}catch{$('revisionPromptText').focus();$('revisionPromptText').select();$('revisionPromptCopyStatus').textContent='Select and copy the prompt. This has not been sent.'}};
$('export').onclick=async()=>{if(await command('export_video'))say('Rendering MP4… Your previous output remains saved.')};
$('download').onclick=async event=>{
 event.preventDefault();if(!downloadBlob||downloadBusy)return;downloadBusy=true;
 try{
  say('Preparing MP4 download…');const blob=downloadBlob,filename=$('download').download,project_id=doc.project_id,export_id=currentExport();
  if(app.getHostCapabilities()?.downloadFile){
   const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not prepare the saved MP4.'));reader.readAsDataURL(blob)});
   try{const result=await app.downloadFile({contents:[{type:'resource',resource:{uri:'file:///'+encodeURIComponent(filename),mimeType:'video/mp4',blob:encoded}}]});if(result.isError)throw Error('The download was cancelled or denied.');say('MP4 sent to ChatGPT for download. Your export remains saved.');return}catch(e){if(!/method not found/i.test(e.message))throw e}
  }
  const result=data(await rpc('prepare_download',{project_id,export_id}));
  if(typeof window.openai?.openExternal==='function')await window.openai.openExternal({href:result.download_url,redirectUrl:false});
  else await app.openLink({url:result.download_url});
  say('MP4 download opened on the computer running Frame. Your export remains saved.');
 }catch(e){say('Download could not finish. Your export remains saved in Frame. '+e.message,true)}finally{downloadBusy=false}
};
document.addEventListener('keydown',e=>{
 const editing=e.target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]');if(e.isComposing)return;
 if(e.ctrlKey&&e.altKey&&e.shiftKey&&!e.metaKey&&e.code==='KeyO'&&!editing){e.preventDefault();e.stopPropagation();if(!e.repeat)void openCurrentProjectPanel();return}
 if(e.defaultPrevented||editing||document.querySelector('dialog[open]')||markupUI?.active||busy||!doc)return;const key=e.key.toLowerCase(),mod=e.metaKey||e.ctrlKey;
 if(mod&&key==='z'){e.preventDefault();if(!e.repeat)$(e.shiftKey?'redo':'undo').click();return}if(mod||e.altKey)return;
 if(key==='i'){e.preventDefault();if(!e.repeat&&!$('pin').disabled)$('pin').click();return}
 if(key==='o'){e.preventDefault();if(!e.repeat&&!$('finishSection').disabled)$('finishSection').click();return}
 if(e.key==='Escape'&&rangeProject){e.preventDefault();if(!rangeSaving)$('rangeCancel').click();return}
 if(e.code==='Space'&&e.target.tagName!=='BUTTON'){e.preventDefault();$('play').click()}});
projectFiles=createProjectFiles({app,rpc,data,getDoc:()=>doc,getFamily:()=>library.groupFor(doc)?.members||[],update,openProject,say});
const presenterStudio=createPresenterStudio({app,rpc,data,openProject});
async function receive(r){try{if(r.isError)throw Error(r.content?.find(c=>c.type==='text')?.text||'Frame could not open this project.');const v=data(r);if(v.project){homeUpload=null;homeLibrary?.clear();await loadAncestry(v.project);accept(v.project);if(!await followContinuation(v.project)){await list();await loadVideo()}}else if(v.project_id){await openProject(v.project_id)}else if(v.projects){await list()}if(v.open_references&&v.project_id===doc?.project_id)await referencesUI.open(v.reference_project_id);projectFiles.receive(v);await presenterStudio.receive(v)}catch(e){say(e.message,true)}}
app.ontoolinput=({arguments:args})=>{latestInput=args||{}};
app.ontoolresult=r=>{if(connected)void receive(r);else pendingResult=r};
app.ontoolcancelled=()=>say('Opening was cancelled. Choose a saved project or refresh to try again.');
app.onhostcontextchanged=theme;
try{await app.connect();hostReady=true;theme(app.getHostContext());health(true);if(pendingResult)await receive(pendingResult);else if(latestInput.project_id)await openProject(latestInput.project_id);else await list();if(!doc)await showHome()}catch(e){health(false);say('Frame could not connect to this chat. Keep the connector running and use Refresh to retry. '+e.message,true)}
setInterval(async()=>{if(homeUpload&&!doc){await checkHomeUpload();return}if(!connected||!doc||busy||polling||loadingMedia||opening||document.hidden)return;polling=true;const pid=liveDoc.project_id;try{const next=data(await rpc('get_project',{project_id:pid}));if(liveDoc.project_id!==pid)return;const previous=doc.rendered?.proposal_id;accept(next);if(await followContinuation(next))return;if(activeHandoff&&activeHandoff.tracking!=='browser'&&['sending','submitted','uncertain'].includes(activeHandoff.status)){const handoff=data(await rpc('get_revision_handoff',{project_id:pid,handoff_id:activeHandoff.id}));if(doc?.project_id!==pid)return;activeHandoff=handoff;$('relayStatus').textContent=deliveryLabel(handoff)+' · v'+handoff.version}if(next.exports?.at(-1)?.status==='failed')say(next.exports.at(-1).error||'Export failed. Your previous output remains saved.',true);if(next.rendered?.proposal_id&&next.rendered.proposal_id!==previous){resultMode=true;await loadVideo()}else if(['working','rendering','queued'].includes(next.exports?.at(-1)?.status))say('Rendering MP4…')}catch(e){health(false);say('Sync failed. Saved work remains on the connected computer. Use Refresh to reconnect. '+e.message,true)}finally{polling=false}},1000);
window.addEventListener('pagehide',event=>{if(event.persisted)return;++mediaGeneration;if(mediaUrl)URL.revokeObjectURL(mediaUrl);for(const promise of referenceUrls.values())void Promise.resolve(promise).then(url=>URL.revokeObjectURL(url)).catch(()=>{})});

window.addEventListener('pageshow',event=>{if(event.persisted&&doc&&!loadingMedia)void refreshPreview()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&doc&&!loadingMedia&&!opening&&(video.error||video.readyState===0))void refreshPreview()});

creativeFeedback=createCreativeFeedback({getTarget:feedbackTarget,getDoc:()=>doc,rpc,data,say,
 refresh:async()=>{if(!liveDoc)return;const pid=liveDoc.project_id;const next=data(await rpc('get_project',{project_id:pid}));if(liveDoc?.project_id===pid)accept(next)},
 onRevise:async(args,id)=>{if(completedFeedbackCorrections.has(id))return true;if(historyId||doc?.project_id!==args.project_id){say('Feedback saved. Open the current video to add this correction.');return false}const next=await saveDraftNote('feedback:'+id,{action:'add_general_note',instruction:args.reason});if(!next)throw Error('Feedback saved; the correction note could not be saved. Retry Revise.');completedFeedbackCorrections.add(id);return true;}
});
