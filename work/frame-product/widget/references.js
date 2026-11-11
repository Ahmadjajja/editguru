import { sendToCurrentChat } from './revision-delivery.js';
// Reference playback has its own generation and object URL; never changes the edit preview.
export function createReferences({app,getDoc,rpc,data,update,list,getProjects,prepareReference,say,onTabChange=()=>{}}){
 const $=id=>document.getElementById(id),video=$('referenceVideo');
 let selected=null,owner=null,generation=0,url=null,key='',saving=false,loading=false,chatSending=false;
 function clear(){++generation;video.pause();video.removeAttribute('src');video.load();video.hidden=true;if(url)URL.revokeObjectURL(url);url=null;loading=false;$('referenceMoment').hidden=true}
 function status(text){$('referenceStatus').textContent=text}
 function render(){
  const doc=getDoc();if(owner!==doc?.project_id){owner=doc?.project_id;selected=null;clear();key='';$('referenceAspect').value='';status('')}
  const refs=doc?.video_references||[];
  if(selected&&!refs.some(r=>r.project_id===selected)){selected=null;clear()}
  const next=JSON.stringify([owner,refs,doc?.pins,getProjects(),selected]);
  if(next!==key){key=next;
   const candidates=$('referenceCandidates'),choice=candidates.value;candidates.replaceChildren(new Option('Choose an imported video…',''));
   for(const p of getProjects())if(p.id!==owner&&!refs.some(r=>r.project_id===p.id))candidates.append(new Option(p.name,p.id));candidates.value=choice;
   const library=$('referenceLibrary');library.replaceChildren();
   for(const ref of refs){const row=document.createElement('div'),open=document.createElement('button'),remove=document.createElement('button');open.textContent=ref.name;open.setAttribute('aria-pressed',String(selected===ref.project_id));open.onclick=()=>void load(ref);remove.textContent='Remove';remove.setAttribute('aria-label','Remove reference '+ref.name);remove.onclick=()=>update({action:'remove_video_reference',reference_project_id:ref.project_id});row.append(open,remove);library.append(row)}
   if(!refs.length){const empty=document.createElement('p');empty.className='hint';empty.textContent='No references yet. Added videos stay with this project.';library.append(empty)}
   const target=$('referenceTarget'),previous=target.value;target.replaceChildren(new Option('Choose a section…',''));
   for(const [i,p] of (doc?.pins||[]).entries())if(p.end!=null)target.append(new Option(`Section ${i+1} · ${p.start.toFixed(2)}–${p.end.toFixed(2)}s`,p.id));target.value=previous;
  }
  $('addReferenceFromChat').disabled=!doc||chatSending;
  $('addVideoReference').disabled=!doc||saving;$('saveReferenceMoment').disabled=!doc||saving||loading||video.readyState<2;
  $('uploadVideoReference').hidden=typeof app.importReferenceFile!=='function';$('uploadVideoReference').disabled=!doc||saving;
 }
 async function load(ref){
  clear();selected=ref.project_id;render();const token=generation,pid=owner;loading=true;status('Loading reference…');
  try{let offset=0,total=null;const chunks=[];
   do{const response=await rpc('read_video_chunk',{project_id:ref.project_id,offset,max_bytes:1048576});if(token!==generation||getDoc()?.project_id!==pid)return;
    const d=data(response),raw=response._meta?.videoChunk;
    if(typeof raw!=='string'||d.project_id!==ref.project_id||d.offset!==offset||d.export_id!=null)throw Error('Reference chunk did not match.');
    const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0));if(!bytes.length||bytes.length>1048576||!Number.isSafeInteger(d.total_bytes)||d.total_bytes>1073741824||d.next_offset!==offset+bytes.length||d.next_offset>d.total_bytes||(total!==null&&total!==d.total_bytes))throw Error('Invalid reference chunk.');
    total=d.total_bytes;offset=d.next_offset;chunks.push(bytes);status(`Loading reference · ${Math.round(offset/total*100)}%`);
   }while(offset<total);
   if(token!==generation||getDoc()?.project_id!==pid)return;
   url=URL.createObjectURL(new Blob(chunks,{type:'video/mp4'}));video.src=url;video.hidden=false;video.load();$('referenceMoment').hidden=false;status('Pause on a visual you want to use.');
  }catch(e){if(token===generation)status('Reference unavailable. '+e.message)}finally{if(token===generation){loading=false;render()}}
 }
 $('editTab').onclick=()=>switchTab(false);$('referencesTab').onclick=async()=>{switchTab(true);try{await list();render()}catch(e){status(e.message)}};
 function switchTab(refs){onTabChange(refs);$('editPanel').hidden=refs;$('referencesPanel').hidden=!refs;$('editTab').setAttribute('aria-selected',String(!refs));$('referencesTab').setAttribute('aria-selected',String(refs));if(refs)document.getElementById('video').pause();else video.pause()}
 $('addReferenceFromChat').onclick=async()=>{
  if(chatSending||!getDoc())return;const pid=getDoc().project_id,name=getDoc().name;chatSending=true;render();
  try{const response=await sendToCurrentChat(app,{role:'user',content:[{type:'text',text:`Add the video attachment I provided in this conversation to the References tab of Frame project ${pid} (${name||'current edit'}). Use import_reference_video with project_id="${pid}" and the actual host-provided attachment file or local source_path. If this video is already imported, reuse its reference_project_id. If this chat has an older tool registry, invoke the same project connector through its command interface if available, or refresh its tools. Never switch project stores to work around a missing tool. Keep this edit project selected and open References after saving. Do not create a new edit project or select another chat's project. If multiple attachments are ambiguous, ask which video. If no usable host handoff is available, explain what is missing; never invent an attachment URL or path.`}]});if(response?.isError)throw Error('The chat declined the reference request.');if(getDoc()?.project_id===pid)status('Reference request sent to this chat. Waiting for the video to be saved…');}
  catch(e){if(getDoc()?.project_id===pid)status('Could not send the request. Attach a video and ask this chat to add it as a reference to project '+pid+'. '+e.message)}finally{chatSending=false;render()}
 };
 $('addVideoReference').onclick=async()=>{const id=$('referenceCandidates').value;if(!id)return status('Choose an imported video first.');const next=await update({action:'add_video_reference',reference_project_id:id});if(next){const ref=next.video_references.find(r=>r.project_id===id);if(ref)void load(ref)}};
 $('uploadVideoReference').onclick=()=>$('referenceVideoFile').click();
 $('referenceVideoFile').onchange=async()=>{const file=$('referenceVideoFile').files?.[0],pid=getDoc()?.project_id;if(!file||!pid)return;saving=true;render();status('Importing reference…');try{const result=await app.importReferenceFile(file);await list();if(getDoc()?.project_id!==pid)return;const next=await update({action:'add_video_reference',reference_project_id:result.id});if(next)void load(next.video_references.find(r=>r.project_id===result.id))}catch(e){status(e.message)}finally{saving=false;$('referenceVideoFile').value='';render()}};
 $('saveReferenceMoment').onclick=async()=>{
  if(saving||loading)return;const doc=getDoc(),pid=doc?.project_id,version=doc?.version,section=$('referenceTarget').value,text=$('referenceAspect').value.trim(),ref=selected,time=video.currentTime,token=generation;
  if(!section||!text||video.readyState<2||video.seeking)return status('Choose a section, pause on a loaded frame, and describe the aspect to use.');
  video.pause();saving=true;render();
  try{const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.9));if(!blob)throw Error('Could not capture reference frame.');const image=await prepareReference(blob);
   if(getDoc()?.project_id!==pid||getDoc()?.version!==version||token!==generation||video.currentTime!==time)throw Error('Project or reference changed. Review the frame and save again.');
   const name=doc.video_references.find(r=>r.project_id===ref)?.name||'Reference';
   const next=await update({action:'add_reference_moment',section_id:section,reference_project_id:ref,reference_time:time,instruction:text,name:`${name} · ${time.toFixed(3)}s.jpg`,image_base64:image});
   if(next){$('referenceAspect').value='';status(`Saved reference frame at ${time.toFixed(3)}s and implementation request to the section.`);say('Reference visual and request saved.')}
  }catch(e){status(e.message)}finally{saving=false;render()}
 };
 video.addEventListener('loadeddata',render);window.addEventListener('pagehide',clear);
 return {render,async open(id){switchTab(true);render();const ref=getDoc()?.video_references?.find(r=>r.project_id===id);if(ref)await load(ref)}};
}
