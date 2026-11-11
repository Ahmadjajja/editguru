// The host bridge has no retry/idempotency contract. Reserve before submitting,
// and leave ambiguous attempts unresolved until the receiving chat acknowledges.
export const deliveryLabel=row=>({
 sending:'Delivery pending · awaiting the chat',
 submitted:'Submitted to chat · awaiting receipt',
 received:'Received by chat',
 uncertain:'Delivery unconfirmed · prompt preserved',
 not_sent:'Not sent · prompt preserved',
}[row.status]||'Delivery unconfirmed');

export const missingMethod=error=>error?.code===-32601||/\b(unknown tool|tool (?:is )?not found|method not found|unsupported method|no such tool)\b/i.test(error?.message||'');

// Only fall back on a definitive unsupported-method response. Timeouts and lost
// connections may already have delivered the message and must never be retried.
export async function sendToCurrentChat(app,message,legacy=globalThis.window?.openai){
 try{return await app.sendMessage(message)}catch(error){
  if(!missingMethod(error)||typeof legacy?.sendFollowUpMessage!=='function')throw error;
  const prompt=(message.content||[]).filter(c=>c.type==='text').map(c=>c.text).join('\n');
  return await legacy.sendFollowUpMessage({prompt,scrollToBottom:false})||{};
 }
}

// Older, already-connected MCP bridges cannot discover a newly added tool until
// reconnect. Keep sending usable there without treating a browser record as a
// server receipt. Web Locks serialize reservations across same-origin panels.
export function browserHandoffJournal(storage=globalThis.localStorage,locks=globalThis.navigator?.locks){
 const prefix='frame.revision-handoffs.v1.';
 const locked=async(pid,fn)=>{
  if(!storage||!locks?.request)throw Error('Reconnect the Frame plugin to register its delivery tools. Browser delivery tracking is unavailable; your saved prompt is preserved.');
  return locks.request(prefix+pid,async()=>fn(prefix+pid));
 };
 const read=key=>JSON.parse(storage.getItem(key)||'[]');
 return {
  async begin({project_id,expected_version,prompt}){
   return locked(project_id,key=>{
    const rows=read(key);let row=rows.findLast(r=>r.original===prompt),may_send=false;
    if(!row){
     if(rows.length>=200)throw Error('Reconnect Frame to continue sending. This browser has 200 saved handoffs; their history is preserved.');
     const id=globalThis.crypto.randomUUID().replaceAll('-','');
     row={id,project_id,version:expected_version,original:prompt,prompt:prompt+'\n\nBrowser handoff ID: '+id+'. Delivery tracking is local to this browser because this connection has not registered the server receipt tools. Report this ID when you receive the prompt; do not claim a server-recorded receipt.',status:'not_sent',attempt:0,tracking:'browser',created_at:Date.now()/1000};rows.push(row);
    }
    if(row.status==='not_sent'){row.status='sending';row.attempt++;may_send=true;}
    storage.setItem(key,JSON.stringify(rows));return {...row,may_send};
   });
  },
  async finish({project_id,handoff_id,attempt,status,error}){
   return locked(project_id,key=>{
    const rows=read(key),row=rows.find(r=>r.id===handoff_id);
    if(!row||row.attempt!==attempt)throw Error('This browser handoff attempt is no longer current.');
    if(row.status==='sending')Object.assign(row,{status,error});
    storage.setItem(key,JSON.stringify(rows));return {...row};
   });
  }
 };
}

export function latestBrowserHandoff(projectId){
 try{
  const row=JSON.parse(globalThis.localStorage?.getItem('frame.revision-handoffs.v1.'+projectId)||'[]').at(-1);
  if(!row||row.tracking!=='browser')return null;
  const {prompt,original,...metadata}=row;return metadata;
 }catch{return null;}
}

export async function deliverRevisionPrompt({rpc,sendMessage,projectId,version,text,isCurrent=()=>true,onReserved=()=>{},journal,requireSnapshot=false}){
 const args={project_id:projectId,expected_version:version,prompt:text};
 let row,browserJournal;
 try{row=await rpc('begin_revision_handoff',args)}catch(error){
  if(!missingMethod(error))throw error;
  if(requireSnapshot)throw Error('Reconnect Frame before sending: this connection cannot save a durable video version.');
  browserJournal=journal||browserHandoffJournal();row=await browserJournal.begin(args);
 }
 onReserved(row);
 if(!row.may_send)return row;
 let status='uncertain',error='';
 try{
  if(!isCurrent()){
   status='not_sent';throw Error('Project changed before sending. Open the intended project and try again.');
  }
  const result=await sendMessage({role:'user',content:[{type:'text',text:row.prompt}]});
  if(result?.isError){status='not_sent';throw Error('The chat rejected the implementation prompt.');}
  status='submitted';
 }catch(e){
  error=e?.message||'The host did not confirm submission.';
  // Capability failure occurs before the local adapter sends anything.
  if(e?.code==='FRAME_NO_CHAT_HOST')status='not_sent';
 }
 try{
  const result={project_id:projectId,handoff_id:row.id,attempt:row.attempt,status,error};
  return browserJournal?await browserJournal.finish(result):await rpc('finish_revision_handoff',result);
 }catch(e){
  // The reservation remains durable, blocking an accidental repeat after reload.
  return {...row,status:status==='not_sent'?'not_sent':'uncertain',error:error||'Could not save the delivery result. Refresh to check receipt before retrying.'};
 }
}
