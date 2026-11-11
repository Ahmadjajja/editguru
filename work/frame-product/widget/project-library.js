import {videoVersionOptions} from './revision-history.js';
// Logical projects group uploads and revisions without changing their source media.
export const projectId = doc => doc?.project_id || doc?.id;
export const clipDuration = doc => (doc?.clips || []).reduce((sum,c)=>sum+c.end-c.start,0);
export const timeLabel = value => {const n=Math.max(0,Math.floor(Number(value)||0));return Math.floor(n/60)+':'+String(n%60).padStart(2,'0')};
export function latestMedia(doc){
 const matches = value => value && JSON.stringify(value.clips)===JSON.stringify(doc.clips);
 if(matches(doc.rendered))return {exportId:doc.rendered.proposal_id,duration:doc.rendered.duration??clipDuration(doc)};
 const complete=(doc.exports||[]).filter(e=>e.status==='done'&&!e.section_id).sort((a,b)=>(b.completed_at||b.created||0)-(a.completed_at||a.created||0));
 const done=complete.filter(e=>e.status==='done'&&!e.section_id&&matches(e)).sort((a,b)=>(b.created||0)-(a.created||0))[0];
 if(done)return {exportId:done.id,duration:done.duration??clipDuration(doc)};
 const original=doc.checkpoints?.find(c=>c.id==='source');
 if(complete[0])return {exportId:complete[0].id,duration:complete[0].duration??clipDuration(complete[0]),pending:true};
 return {exportId:null,duration:doc.source_duration??clipDuration(doc),pending:!!original&&JSON.stringify(original.clips)!==JSON.stringify(doc.clips)};
}
const videoEventTime=doc=>Math.max(0,...(doc.checkpoints||[]).filter(c=>c.id!=='source').map(c=>c.created_at||0),...(doc.exports||[]).filter(e=>e.status==='done'&&!e.section_id).map(e=>e.completed_at||e.created||0),...(doc.accepted_edits||[]).map(e=>e.accepted_at||0));
// File rewrites and library reads are not editing activity.
export const projectWorkTime=doc=>Math.max(doc.created||0,doc.last_worked_at||0,
 ...(doc.activity||[]).filter(e=>e.status!=='failed'&&!/^(get_|read_|list_)/.test(e.command||'')).map(e=>e.updated_at||e.created_at||0),
 ...(doc.notes||[]).map(n=>n.updated_at||n.created_at||0),...(doc.assets||[]).map(a=>a.created_at||0),
 ...(doc.accepted_edits||[]).map(e=>e.accepted_at||0),...(doc.exports||[]).map(e=>e.completed_at||e.created||0),
 ...(doc.proposals||[]).map(p=>p.approved_at||p.created_at||0));
const workDate=time=>new Date(time*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const videoTime=doc=>Math.max(doc.created||0,videoEventTime(doc));
const revisedTitle = name => String(name||'Untitled project').replace(/\.[a-z0-9]{2,5}$/i,'').replace(/(?:\s*·\s*Revised)+$/i,'').trim();
export function groupProjects(documents){
 const docs=[...new Map(documents.filter(d=>projectId(d)).map(d=>[projectId(d),d])).values()],byId=new Map(docs.map(d=>[projectId(d),d])),parent=new Map(docs.map(d=>[projectId(d),projectId(d)]));
 const find=id=>{let root=id;const seen=new Set();while(parent.has(root)&&parent.get(root)!==root&&!seen.has(root)){seen.add(root);root=parent.get(root)}return root};
 const join=(a,b)=>{if(parent.has(a)&&parent.has(b))parent.set(find(a),find(b))};
 const explicit=new Map();
 for(const d of docs){const id=projectId(d),work=d.work_project?.id;if(work){if(explicit.has(work))join(id,explicit.get(work));else explicit.set(work,id)}
  for(const other of [d.revision_parent?.project_id,d.revision_parent?.result_project_id,d.next_revision?.project_id])if(other)join(id,other);
 }
 const groups=new Map();
 for(const d of docs){const key=find(projectId(d));if(!groups.has(key))groups.set(key,[]);groups.get(key).push(d)}
 return [...groups.values()].map(members=>{
  const byDate=[...members].sort((a,b)=>projectWorkTime(b)-projectWorkTime(a)||projectId(a).localeCompare(projectId(b)));
  const cuts=byDate.filter(d=>!['source','reference'].includes(d.work_project?.role)||(d.work_project?.role==='source'&&videoEventTime(d)>0));
  const candidates=[...(cuts.length?cuts:byDate)].sort((a,b)=>videoTime(b)-videoTime(a)||projectId(a).localeCompare(projectId(b)));
  // A child is newer than its ancestor even if clocks or import dates tie.
  const parentIds=new Set(members.flatMap(d=>[d.revision_parent?.project_id,d.revision_parent?.result_project_id]).filter(Boolean));
  let latest=candidates.find(d=>!parentIds.has(projectId(d)))||candidates[0];
  // Restoring or editing an earlier cut creates a newer working version; notes alone do not.
  const revived=candidates.filter(d=>parentIds.has(projectId(d))&&videoEventTime(d)>videoTime(latest)).sort((a,b)=>videoEventTime(b)-videoEventTime(a))[0];if(revived)latest=revived;
  const metadata=members.find(d=>d.work_project?.title&&d.work_project.id===projectId(d))?.work_project||[...byDate].reverse().find(d=>d.work_project?.title)?.work_project;
  return {id:metadata?.id||find(projectId(latest)),title:metadata?.title||revisedTitle(latest.name),description:metadata?.description||'',members:byDate,cuts,latest,updated:Math.max(...members.map(projectWorkTime))};
 }).sort((a,b)=>b.updated-a.updated);
}

export function createProjectLibrary({rpc,data,getItems,refresh,openProject,openRevision,openFiles,app,say,dialog,list,summary,embedded=false}){
 const documents=new Map(),posterUrls=new Set();let groups=[],generation=0,active=null,focused=null;
 function stopPreview(card=null){
  if(!active||(card&&active.card!==card))return;
  const previous=active;active=null;previous.video.pause();
  previous.video.removeAttribute('src');previous.video.load();if(previous.url)URL.revokeObjectURL(previous.url);
  previous.state.hidden=!!previous.video.poster;
  previous.state.textContent='Hover or focus to preview';
 }
 const clear=()=>{generation++;focused=null;stopPreview();for(const url of posterUrls)URL.revokeObjectURL(url);posterUrls.clear();for(const video of list.querySelectorAll('video')){video.pause();video.removeAttribute('src');video.removeAttribute('poster');video.load()}list.replaceChildren()};
 let previewQueue=Promise.resolve();
 function readPreviewChunk(args,valid){
  const run=()=>valid()?rpc('read_video_chunk',args):null;
  const result=previewQueue.then(run,run);previewQueue=result.then(()=>undefined,()=>undefined);return result;
 }
 async function readMedia(doc,valid,progress){
  const media=latestMedia(doc),pid=projectId(doc);
  let offset=0,total=null;const chunks=[];
  do{if(!valid())return null;const r=await readPreviewChunk({project_id:pid,offset,max_bytes:1048576,...(media.exportId?{export_id:media.exportId}:{})},valid);if(!r||!valid())return null;
   const info=data(r),encoded=r._meta?.videoChunk;if(typeof encoded!=='string'||info.project_id!==pid||info.export_id!==(media.exportId||null)||info.offset!==offset)throw Error('Preview does not match project.');
   const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));if(!bytes.length||bytes.length>1048576||info.next_offset-offset!==bytes.length||!Number.isSafeInteger(info.total_bytes)||info.total_bytes>1073741824||(total!==null&&total!==info.total_bytes))throw Error('Invalid preview data.');
   total=info.total_bytes;offset=info.next_offset;if(offset>total)throw Error('Invalid preview size.');chunks.push(bytes);progress(Math.round(offset/total*100));
  }while(offset<total);
  return new Blob(chunks,{type:'video/mp4'});
 }
 async function load(){
  await refresh();
  // Fetch current metadata for every upload: revision history must survive a refresh.
  const rows=await Promise.all(getItems().map(async item=>{const id=projectId(item);try{const d=data(await rpc('get_project',{project_id:id}));if(projectId(d)!==id)throw Error('Project mismatch');return {...item,...d,created:item.created??d.created??0}}catch{return {...item,project_id:id,unavailable:true}}}));
  documents.clear();for(const d of rows)documents.set(projectId(d),d);groups=groupProjects(rows);return groups;
 }
 async function show(){
  clear();if(!embedded)dialog.showModal();summary.textContent='Loading projects…';const token=generation;
  try{await load();if(token!==generation||(!embedded&&!dialog.open))return;
   summary.textContent=groups.length+(groups.length===1?' project folder':' project folders')+' · revisions stay inside their project';
   for(const group of groups){
    const card=document.createElement('article');card.className='project-folder';card.dataset.workProject=group.id;card.setAttribute('aria-label',group.title+' · latest cut '+timeLabel(latestMedia(group.latest).duration));
    const header=document.createElement('div');header.className='project-folder-header';const media=document.createElement('button');media.type='button';media.className='project-card-preview';media.setAttribute('aria-label','Open latest version of '+group.title);const video=document.createElement('video');video.muted=true;video.loop=true;video.playsInline=true;video.preload='none';video.setAttribute('aria-hidden','true');video.tabIndex=-1;
    const badge=document.createElement('span');badge.className='project-card-duration';badge.textContent=timeLabel(latestMedia(group.latest).duration);const state=document.createElement('span');state.className='project-card-state';state.textContent='Loading preview…';media.append(video,badge,state);
    const text=document.createElement('div');text.className='project-card-copy';const title=document.createElement('h3');title.textContent=group.title;const icon=document.createElement('span');icon.className='folder-icon';icon.setAttribute('aria-hidden','true');icon.textContent='▱';title.prepend(icon);const detail=document.createElement('p');detail.textContent=group.description;const count=document.createElement('p');count.className='project-card-meta';const revisions=group.cuts.length?group.cuts:group.members,sources=group.members.filter(d=>['source','reference'].includes(d.work_project?.role));
    count.textContent=revisions.length+(revisions.length===1?' revision':' revisions')+(latestMedia(group.latest).pending?' · Saved preview ':' · Latest ')+timeLabel(latestMedia(group.latest).duration)+(latestMedia(group.latest).pending?' · Unexported edits':'');
    count.textContent+=(group.updated?' · Worked on '+workDate(group.updated):'');
    const revision=document.createElement('p');revision.className='project-latest-revision';revision.textContent='Latest revision: '+(group.latest.work_project?.label||revisedTitle(group.latest.name));
    const open=document.createElement('button');open.type='button';open.className='open-project-latest';open.textContent='Open latest';
    function launch(pid,checkpoint=null){clear();if(!embedded)dialog.close();if(checkpoint&&openRevision)void openRevision(pid,checkpoint);else void openProject(pid,false)}
    open.onclick=()=>launch(projectId(group.latest));media.onclick=open.onclick;
    text.append(title,detail,revision,count,open);header.append(text,media);card.append(header);
    const tree=document.createElement('details');tree.className='project-revisions';const toggle=document.createElement('summary');toggle.textContent='Revisions · '+revisions.length;tree.append(toggle);
    const rows=document.createElement('ol');rows.className='project-revision-list';
    for(const member of revisions){
     const row=document.createElement('li');row.className='project-revision';row.dataset.projectId=projectId(member);
     const button=document.createElement('button');button.type='button';button.className='open-project-revision';
     const label=document.createElement('span');label.className='revision-title';label.textContent=member.work_project?.label||revisedTitle(member.name);
     const meta=document.createElement('span');meta.className='revision-meta';meta.textContent=(projectId(member)===projectId(group.latest)?'Latest · ':'')+timeLabel(latestMedia(member).duration)+(member.created?' · '+new Date(member.created*1000).toLocaleDateString(): '');
     button.append(label,meta);button.onclick=()=>launch(projectId(member));row.append(button);
     const versions=videoVersionOptions(member).filter(v=>!['latest','source'].includes(v.value));
     if(versions.length){const saved=document.createElement('details'),heading=document.createElement('summary');heading.textContent='Saved versions · '+versions.length;saved.className='project-saved-versions';saved.append(heading);const versionsList=document.createElement('ol');
      for(const version of versions){const item=document.createElement('li'),pick=document.createElement('button');pick.type='button';pick.className='open-saved-version';pick.textContent=version.label;pick.onclick=()=>launch(projectId(member),version.value);item.append(pick);versionsList.append(item)}saved.append(versionsList);row.append(saved)}
     rows.append(row);
    }
    tree.append(rows);card.append(tree);
    if(sources.length&&group.cuts.length){const assets=document.createElement('details'),heading=document.createElement('summary'),assetList=document.createElement('ul');assets.className='project-source-files';heading.textContent='Source footage & references · '+sources.length;assets.append(heading);
     for(const source of sources){const row=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=source.name;button.onclick=()=>launch(projectId(source));row.append(button);assetList.append(row)}assets.append(assetList);card.append(assets)}
    const projectFiles=[...new Map(group.members.flatMap(member=>(member.assets||[]).map(asset=>({owner:projectId(member),asset}))).map(row=>[row.asset.sha256||row.owner+':'+row.asset.id,row])).values()];
    if(projectFiles.length){const files=document.createElement('details'),heading=document.createElement('summary'),fileList=document.createElement('ul');files.className='project-source-files project-family-files';heading.textContent='Project files · '+projectFiles.length;files.append(heading);
     for(const {asset} of projectFiles){const item=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=asset.name;button.onclick=()=>{clear();dialog.close();if(openFiles)void openFiles(projectId(group.latest));else void openProject(projectId(group.latest),false)};item.append(button);fileList.append(item)}files.append(fileList);card.append(files)}
    list.append(card);
    let hovering=false,hasFocus=false,poster=null;
    const local=typeof app.projectMediaUrl==='function';
    const exists=()=>token===generation&&(embedded||dialog.open)&&card.isConnected;
    function capturePoster(){
     if(local||!exists()||!video.videoWidth||!video.videoHeight)return;
     try{const canvas=document.createElement('canvas');canvas.width=Math.min(320,video.videoWidth);canvas.height=Math.max(1,Math.round(canvas.width*video.videoHeight/video.videoWidth));const context=canvas.getContext('2d');if(!context)return;context.drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(!blob||!exists())return;const url=URL.createObjectURL(blob);if(poster){URL.revokeObjectURL(poster);posterUrls.delete(poster)}poster=url;posterUrls.add(url);video.poster=url;if(active?.card!==card)state.hidden=true},'image/jpeg',.75)}catch{}
    }
    async function start(){
     if(!exists())return;
     if(active?.card===card){if(video.readyState>=2)void video.play().catch(()=>{});return}
     stopPreview();const current={card,video,state,url:null};active=current;
     const valid=()=>exists()&&active===current;
     if(local){if(!video.getAttribute('src')){video.src=app.projectMediaUrl(projectId(group.latest),latestMedia(group.latest).exportId);video.load()}if(video.readyState>=2)void video.play().catch(()=>{});return}
     state.hidden=false;state.textContent='Loading preview…';
     try{const blob=await readMedia(group.latest,valid,percent=>{if(valid())state.textContent='Loading preview · '+percent+'%'});if(!blob||!valid())return;current.url=URL.createObjectURL(blob);video.src=current.url;video.load()}
     catch{if(valid()){state.hidden=false;state.textContent='Preview unavailable · select to open'}}
    }
    function leave(){if(hovering||hasFocus)return;stopPreview(card);queueMicrotask(()=>{if(!active&&focused&&(embedded||dialog.open))void focused.start()})}
    media.onpointerenter=()=>{hovering=true;void start()};media.onpointerleave=()=>{hovering=false;leave()};
    media.onfocus=()=>{hasFocus=true;focused={card,start};void start()};media.onblur=()=>{hasFocus=false;if(focused?.card===card)focused=null;leave()};
    video.onloadeddata=()=>{if(!exists()||video.readyState<2)return;state.hidden=true;capturePoster();if(active?.card===card)void video.play().catch(()=>{})};
    video.onerror=()=>{if(exists()&&(local||active?.card===card)){state.hidden=false;state.textContent='Preview unavailable · select to open'}};
    // Small posters are eager; full video is loaded only on deliberate preview interaction.
    state.textContent='Loading latest preview…';
    if(typeof app.projectPosterUrl==='function'){
     const image=document.createElement('img'),url=app.projectPosterUrl(projectId(group.latest),latestMedia(group.latest).exportId);image.onload=()=>{if(exists()){video.poster=url;state.hidden=true}};image.onerror=()=>{if(exists()){state.hidden=false;state.textContent='Preview unavailable · open latest'}};image.src=url;
    }else{void (async()=>{try{
     const selected=latestMedia(group.latest),result=await rpc('read_video_poster',{project_id:projectId(group.latest),...(selected.exportId?{export_id:selected.exportId}:{})});
     if(!exists())return;const info=data(result),image=result.content?.find(c=>c.type==='image');
     if(info.project_id!==projectId(group.latest)||info.export_id!==(selected.exportId||null)||image?.mimeType!=='image/jpeg'||typeof image.data!=='string'||image.data.length>131072)throw Error('Preview image did not match.');
     const bytes=Uint8Array.from(atob(image.data),c=>c.charCodeAt(0));if(!bytes.length||bytes.length>98304)throw Error('Invalid preview image.');
     poster=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));posterUrls.add(poster);video.poster=poster;state.hidden=true;
    }catch{if(exists()){state.hidden=false;state.textContent='Preview unavailable · open latest'}}})();}


   }
  }catch(error){summary.textContent='Could not load projects. '+error.message;say(summary.textContent,true)}
 }
 dialog.addEventListener('close',clear);
 return {show,load,clear,groupFor:doc=>groups.find(g=>g.members.some(d=>projectId(d)===projectId(doc))),documents};
}
