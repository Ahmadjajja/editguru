// Feedback belongs to the exact media in the player, including saved versions.
export function createCreativeFeedback({getTarget,getDoc,rpc,data,refresh,say,onRevise}){
 const host=document.getElementById('creativeFeedback'),form=document.getElementById('creativeFeedbackForm');
 const reason=document.getElementById('feedbackReason'),reviewed=document.getElementById('feedbackReviewed');
 const status=document.getElementById('feedbackStatus'),list=document.getElementById('feedbackExamples');
 let targetKey='',listKey='',submitting=false,attempt=null;
 function render(){
  const target=getTarget(),doc=getDoc();host.hidden=!doc;
  if(!doc)return;
  const key=target?JSON.stringify(target):'';
  if(key!==targetKey){targetKey=key;reason.value='';reviewed.checked=false;attempt=null;status.textContent=''}
  form.hidden=!target;
  document.getElementById('feedbackOutput').textContent=target?'Reviewing '+(target.export_id==='source'?'this revised copy':'saved output '+target.export_id.slice(0,8)+' · v'+target.export_version):'Open an edited output to leave feedback.';
  for(const b of form.querySelectorAll('button'))b.disabled=submitting||!target;
  const memory=doc.creative_memory||{},rows=memory.examples||[],own=memory.project_feedback||[];
  const combined=[...own,...rows.filter(r=>!own.some(x=>x.id===r.id))];
  const next=JSON.stringify(combined);if(next===listKey)return;listKey=next;list.replaceChildren();
  document.getElementById('feedbackMemoryCount').textContent='What FRAME has learned · '+(memory.total_examples||0)+' examples';
  for(const row of combined){
   const item=document.createElement('li'),text=document.createElement('span');
   text.textContent=row.verdict+' · '+row.category+' · '+row.reason+' ('+(row.scope==='creator'?'across my projects':'this project')+')';item.append(text);
   const forget=document.createElement('button');forget.type='button';forget.textContent='Forget';
   forget.onclick=async()=>{forget.disabled=true;try{data(await rpc('forget_edit_feedback',{project_id:row.project_id,feedback_id:row.id}));await refresh()}catch(e){say(e.message,true);forget.disabled=false}};item.append(forget);list.append(item);
  }
 }
 form.onsubmit=async event=>{
  event.preventDefault();if(submitting)return;
  const target=getTarget();if(!target||JSON.stringify(target)!==targetKey)return;
  const verdict=event.submitter?.value;if(!['accept','reject','revise'].includes(verdict))return;
  if(!reason.value.trim()||!reviewed.checked){status.textContent='Review this output and explain your judgment first.';return}
  const args={...target,verdict,reason:reason.value.trim(),reviewed:true,category:document.getElementById('feedbackCategory').value,scope:document.getElementById('feedbackScope').value};
  const fingerprint=JSON.stringify(args);if(attempt?.fingerprint!==fingerprint)attempt={fingerprint,id:crypto.randomUUID()};
  const requestId=attempt.id;submitting=true;render();
  try{
   data(await rpc('record_edit_feedback',{...args,request_id:requestId}));
   const correction=verdict==='revise'?await onRevise(args,requestId):true;
   await refresh();status.textContent=correction?'Saved. FRAME will use this example when planning relevant edits.':'Feedback saved. Open the current video to add this correction.';say('Creative feedback saved.');
  }catch(e){status.textContent=e.message;say(e.message,true)}finally{submitting=false;render()}
 };
 return {render};
}
