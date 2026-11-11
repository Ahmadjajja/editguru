const sameStudio=(a,b)=>JSON.stringify(a?.studio||{})===JSON.stringify(b?.studio||{});
export function historyTime(value){
 const n=Math.max(0,Math.floor(Number(value)||0));
 return Math.floor(n/60)+':'+String(n%60).padStart(2,'0');
}
export function historyDuration(doc){return (doc?.clips||[]).reduce((sum,c)=>sum+c.end-c.start,0)}
export function projectHistory(project,ancestors=[]){
 const rows=[];
 for(const doc of [project,...ancestors].filter(Boolean)){
  const prefix=doc===project?'':'ancestor:'+doc.project_id+':';
  for(const c of doc.checkpoints||[])rows.push({id:doc.project_id+':checkpoint:'+c.id,created_at:c.created_at||0,title:c.label||'Saved version',detail:'Duration '+historyTime(historyDuration(c))+(c.timeline_version?' · timeline v'+c.timeline_version:''),selection:prefix+c.id,project:doc.name});
  for(const a of doc.activity||[])rows.push({id:doc.project_id+':activity:'+a.id,created_at:a.updated_at||a.created_at||0,title:(a.command||'Update').replaceAll('_',' '),detail:[a.status,a.message].filter(Boolean).join(' · '),project:doc.name});
  for(const e of doc.exports||[])rows.push({id:doc.project_id+':export:'+e.id,created_at:e.completed_at||e.created||0,title:e.section_id?'Section export':'Video export',detail:[e.status,e.error,e.clips?'Duration '+historyTime(historyDuration(e)):null].filter(Boolean).join(' · '),project:doc.name});
  for(const n of doc.notes||[])rows.push({id:doc.project_id+':note:'+n.id,created_at:n.updated_at||n.created_at||0,title:'Revision note',detail:(Number.isFinite(n.source_time_ms)?historyTime(n.source_time_ms/1000)+' · ':'')+(n.instruction||n.text||''),project:doc.name});
  for(const a of doc.proposals||[])rows.push({id:doc.project_id+':proposal:'+a.id,created_at:a.updated_at||a.created_at||0,title:'Revision proposal',detail:[a.status,a.error||a.prompt].filter(Boolean).join(' · '),project:doc.name});
 }
 return rows.sort((a,b)=>b.created_at-a.created_at);
}
// Saved video history belongs to the open project; the library is in Browse projects.
export function revisionOptions(doc){
 if(!doc)return [];
 const rows=(doc.checkpoints||[]).map((c,index)=>({...c,number:index}));
 rows.sort((a,b)=>a.id==='source'?1:b.id==='source'?-1:(b.created_at||0)-(a.created_at||0)||b.number-a.number);
 return [{value:'latest',label:(doc.work_project?.title||doc.name)+' · '+historyTime(historyDuration(doc))+' · Working copy · timeline v'+doc.version},...rows.map(c=>({
  value:c.id,label:historyTime(historyDuration(c))+' · '+(c.id==='source'?'Original upload':(c.kind==='prompt'?'Prompt version':c.rendered&&JSON.stringify(c.rendered.clips)===JSON.stringify(c.clips)&&sameStudio(c.rendered,c)?'Saved video':'Edit checkpoint')+' · '+c.label)+(c.timeline_version?' · timeline v'+c.timeline_version:'')+(c.created_at?' · saved '+new Date(c.created_at*1000).toLocaleString():''),
 }))];
}
export function revisionView(live,id){
 const saved=live?.checkpoints?.find(c=>c.id===id);
 if(!saved)return null;
 const playable=saved.rendered&&JSON.stringify(saved.rendered.clips)===JSON.stringify(saved.clips)&&sameStudio(saved.rendered,saved);
 return {...live,notes:structuredClone(saved.notes||[]),pins:structuredClone(saved.pins||[]),revision_snapshot:saved,studio:structuredClone(saved.studio||{}),clips:structuredClone(saved.clips),rendered:playable?structuredClone(saved.rendered):null,
  duration:saved.clips.reduce((sum,c)=>sum+c.end-c.start,0),can_undo:false,can_redo:false};
}

// Internal timeline counters are not video-version numbers.
export function videoVersionOptions(doc){
 const submitted=new Set((doc?.checkpoints||[]).filter(c=>c.kind==='prompt').map(c=>c.saved_video_id));
 const rows=revisionOptions(doc).filter(r=>r.value==='latest'||r.value==='source'||doc.checkpoints.some(c=>c.id===r.value&&(c.kind==='prompt'||(c.rendered&&!submitted.has(c.rendered.proposal_id)&&JSON.stringify(c.rendered.clips)===JSON.stringify(c.clips)&&sameStudio(c.rendered,c)))));
 const sequence=[...rows].filter(r=>r.value!=='latest').reverse();
 return rows.map(r=>{if(r.value==='latest')return {...r,label:(doc.work_project?.title||doc.name)+' · '+historyTime(historyDuration(doc))+' · Current'};const saved=doc.checkpoints.find(c=>c.id===r.value);return {...r,label:historyTime(historyDuration(saved))+' · Version '+(sequence.findIndex(x=>x.value===r.value)+1)+' · '+saved.label+(saved.created_at?' · '+new Date(saved.created_at*1000).toLocaleString():'')};});
}
export function savedVideoReady(doc){
 return !!doc && ((doc.rendered&&JSON.stringify(doc.rendered.clips)===JSON.stringify(doc.clips)&&sameStudio(doc.rendered,doc))||(!doc.rendered&&JSON.stringify(doc.checkpoints?.find(c=>c.id==='source')?.clips)===JSON.stringify(doc.clips)&&sameStudio(doc.checkpoints?.find(c=>c.id==='source'),doc)));
}
