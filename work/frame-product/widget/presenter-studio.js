import { sendToCurrentChat, missingMethod } from './revision-delivery.js';

export async function deliverPresenter({rpc,app,reservation}){
 if(!reservation.may_send)return reservation;
 let status='uncertain',error='';
 try{
  const result=await sendToCurrentChat(app,{role:'user',content:[{type:'text',text:reservation.prompt}]});
  if(result?.isError){status='not_sent';throw Error('The chat rejected the request.');}
  status='submitted';
 }catch(e){error=e.message||'Delivery was not confirmed.';if(e.code==='FRAME_NO_CHAT_HOST'||missingMethod(e))status='not_sent';}
 try{return {...await rpc('finish_presenter_handoff',{creation_id:reservation.presenter_job.creation_id,handoff_id:reservation.handoff_id,status}),error};}
 catch(e){return {...reservation,delivery_status:status==='not_sent'?'not_sent':'uncertain',error:error||e.message};}
}

export function createPresenterStudio({app,rpc,data,openProject}){
 const root=document.createElement('dialog');root.id='presenterStudio';root.setAttribute('aria-labelledby','presenterTitle');
 root.innerHTML=`<style>
 #presenterStudio{width:650px;max-width:94vw;max-height:92dvh;overflow:auto;padding:24px}
 #presenterStudio h2{font-size:24px;letter-spacing:-.04em;margin:0}#presenterStudio .intro{line-height:1.6;opacity:.75}
 #presenterStudio input:not([type=checkbox]),#presenterStudio select{display:block;width:100%;max-width:100%;margin:6px 0 0}
 #presenterStudio textarea{min-height:84px;margin:6px 0 0}#presenterStudio label{font-weight:500;margin:16px 0}
 #presenterStudio .ps-options{display:grid;grid-template-columns:1fr 1fr;gap:14px}#presenterStudio .ps-options label{margin:0}
 #presenterStudio .ps-actions{margin-top:20px;display:flex;gap:8px;flex-wrap:wrap}#presenterStudio .ps-primary{background:#d5ff61;color:#151515;border-color:#d5ff61;font-weight:650}
 #presenterStudio pre{white-space:pre-wrap;font:inherit;line-height:1.6}#presenterStudio .ps-state{padding:12px;border:1px solid #8885;border-radius:10px;margin-top:16px}
 #presenterStudio #psPrompt{min-height:160px}#presenterStudio #psProgress{padding-left:20px;line-height:1.7}#presenterStudio .ps-error{color:var(--frame-error)}
 @media(max-width:420px){#presenterStudio{padding:16px}#presenterStudio .ps-options{grid-template-columns:1fr}}
 </style><div class="row" style="justify-content:space-between"><h2 id="presenterTitle">Create a presenter video</h2><button id="psClose" type="button" aria-label="Close Create video">Close</button></div>
 <p class="intro">Turn a script or idea into a video with one consistent character, voice, and style. Then make it yours in Frame.</p>
 <label for="psLibrary">Saved creations</label><div class="row"><select id="psLibrary" style="flex:1"><option value="">New video</option></select><button id="psRefresh" type="button">Refresh</button></div>
 <form id="psForm"><label>Title<input id="psName" maxlength="120" placeholder="My next video"></label>
 <label>Topic or idea<textarea id="psTopic" maxlength="2000" placeholder="What should the video be about?"></textarea></label>
 <label>Script <span class="hint">Optional · your exact words</span><textarea id="psScript" maxlength="12000" placeholder="Paste a script to keep its wording, or leave this empty to write from your idea."></textarea></label>
 <label>Character<textarea id="psCharacter" maxlength="2000" placeholder="Describe the presenter, or say which photos attached to this chat to use."></textarea></label>
 <label>Voice<input id="psVoice" maxlength="2000" placeholder="Describe a voice, or use a voice sample attached to this chat."></label>
 <p class="hint">Attach character photos and voice samples to this conversation. The chat uses those references with the connected Higgsfield tools.</p>
 <label>Style<textarea id="psStyle" maxlength="2000" placeholder="The look, pacing, motion, music, and sound you want."></textarea></label>
 <div class="ps-options"><label>Length<select id="psDuration"><option value="15">15 seconds</option><option value="30">30 seconds</option><option value="60" selected>1 minute</option><option value="90">90 seconds</option><option value="120">2 minutes</option></select></label>
 <label>Frame<select id="psRatio"><option value="9:16">Portrait · 9:16</option><option value="16:9">Landscape · 16:9</option><option value="1:1">Square · 1:1</option></select></label></div>
 <label><input id="psCaptions" type="checkbox" checked> Captions</label>
 <div class="ps-actions"><button id="psSave" type="submit">Save brief</button><button id="psPlan" class="ps-primary" type="button">Plan video</button><button id="psNew" type="button">New video</button></div></form>
 <section id="psState" class="ps-state" hidden><p id="psStage" role="status" aria-live="polite"></p><ol id="psProgress"></ol></section>
 <section id="psQuote" class="ps-state" hidden><h3>Generation plan</h3><pre id="psQuotePlan"></pre><p id="psQuoteCost"></p><button id="psApprove" class="ps-primary" type="button">Approve and generate</button><p class="hint">Uses your connected Higgsfield account. The saved estimate is a credit ceiling; a higher cost requires a new approval.</p></section>
 <div class="ps-actions"><button id="psOpen" type="button" hidden>Open video in Frame</button><button id="psResume" type="button" hidden>Show saved request</button></div>
 <section id="psFallback" hidden><p id="psDelivery"></p><textarea id="psPrompt" readonly aria-label="Saved creation request"></textarea><button id="psCopy" type="button">Copy request</button><p class="hint">Paste this into the same conversation to resume. Saved provider attempts must be checked before any generation is repeated.</p></section>
 <p id="psMessage" role="status" aria-live="polite"></p>`;
 document.body.append(root);
 const $=id=>root.querySelector('#'+id),button=document.createElement('button');button.id='createPresenterVideo';button.type='button';button.textContent='Create video';
 document.querySelector('header')?.append(button);
 let job=null,busy=false,requestId=null,briefSnapshot='',polling=false,library=[],generation=0;
 const call=async(name,args)=>data(await rpc(name,args));
 const message=(text,error=false)=>{$('psMessage').textContent=text;$('psMessage').classList.toggle('ps-error',error);};
 const fields={name:'psName',topic:'psTopic',script:'psScript',character:'psCharacter',voice:'psVoice',style:'psStyle'};
 function brief(){return {...Object.fromEntries(Object.entries(fields).map(([k,id])=>[k,$(id).value])),duration:Number($('psDuration').value),aspect_ratio:$('psRatio').value,captions:$('psCaptions').checked};}
 function fill(row){
  job=row||null;const b=row?.brief||{};
  for(const [k,id]of Object.entries(fields))$(id).value=b[k]||'';
  if(b.duration&&!Array.from($('psDuration').options).some(o=>o.value===String(b.duration)))$('psDuration').add(new Option(b.duration+' seconds',b.duration));
  $('psDuration').value=String(b.duration||60);$('psRatio').value=b.aspect_ratio||'9:16';$('psCaptions').checked=b.captions!==false;
  briefSnapshot=JSON.stringify(brief());requestId=null;$('psFallback').hidden=true;message('');render();
 }
 function render(){
  const locked=!!job&&job.status!=='draft';
  for(const el of root.querySelectorAll('#psForm input,#psForm textarea,#psForm select'))el.disabled=busy||locked;
  for(const id of ['psSave','psPlan'])$(id).disabled=busy||locked;
  for(const id of ['psNew','psRefresh','psLibrary','psResume'])$(id).disabled=busy;
  $('psState').hidden=!job;$('psStage').textContent=job?.stage||'';
  $('psProgress').replaceChildren(...(job?.steps||[]).map(s=>{const li=document.createElement('li');li.textContent=s.description+' · '+s.status;return li;}));
  const quote=job?.quote;$('psQuote').hidden=!quote;
  $('psQuotePlan').textContent=quote?.plan||'';$('psQuoteCost').textContent=quote?`${quote.credits} Higgsfield credits${quote.approved_at?' · approved':''}`:'';
  $('psApprove').hidden=job?.status!=='awaiting_approval';$('psApprove').disabled=busy;
  $('psApprove').textContent=quote?`Approve and generate · ${quote.credits} credits`:'Approve and generate';
  $('psOpen').hidden=job?.status!=='complete';$('psOpen').disabled=busy;
  $('psResume').hidden=!job||job.status==='draft'||job.status==='complete';
 }
 async function list(){
  const mine=generation,result=await call('list_presenter_videos',{});if(mine!==generation)return;
  library=result.presenter_jobs||[];const select=$('psLibrary');select.replaceChildren(new Option('New video',''),...library.map(r=>new Option(r.brief.name+' · '+r.status,r.creation_id)));select.value=job?.creation_id||'';
 }
 async function refresh(){if(job){const r=await call('get_presenter_video',{creation_id:job.creation_id});job=r.presenter_job;render();}await list();}
 async function saveBrief(){
  const b=brief(),snapshot=JSON.stringify(b);
  if(job&&snapshot===briefSnapshot)return job;
  requestId ||= crypto.randomUUID().replaceAll('-','');
  const args={request_id:requestId,brief:b,...(job?{creation_id:job.creation_id,expected_version:job.version}:{})};
  const r=await call('save_presenter_brief',args);job=r.presenter_job;requestId=null;briefSnapshot=snapshot;render();await list();return job;
 }
 async function deliver(reservation){
  $('psPrompt').value=reservation.prompt;$('psFallback').hidden=false;
  const r=await deliverPresenter({rpc:call,app,reservation});job=r.presenter_job;
  $('psDelivery').textContent=({submitted:'Sent to chat. Waiting for receipt.',received:'Received by chat.',not_sent:'Copy this saved request into the same chat to continue.',uncertain:'Delivery is unconfirmed. Check the chat before sending this request again.'})[r.delivery_status]||'The saved request is preserved.';
  if(r.error)message(r.error,true);render();await list();
 }
 async function run(fn){if(busy)return;busy=true;render();try{await fn();}catch(e){message(e.message,true);}finally{busy=false;render();}}
 async function open(row=null){generation++;if(!root.open)root.showModal();if(row)fill(row);await run(async()=>{await list();if(job)await refresh();});}
 button.onclick=()=>void open();$('psClose').onclick=()=>root.close();
 $('psNew').onclick=()=>{generation++;fill(null);$('psLibrary').value='';};
 $('psLibrary').onchange=()=>void run(async()=>{generation++;const id=$('psLibrary').value;if(!id){fill(null);return;}fill((await call('get_presenter_video',{creation_id:id})).presenter_job);});
 $('psRefresh').onclick=()=>void run(refresh);
 $('psForm').onsubmit=e=>{e.preventDefault();void run(async()=>{await saveBrief();message('Brief saved.');});};
 $('psPlan').onclick=()=>void run(async()=>{await saveBrief();await deliver(await call('begin_presenter_handoff',{creation_id:job.creation_id,expected_version:job.version}));});
 $('psApprove').onclick=()=>void run(async()=>{await deliver(await call('approve_presenter_quote',{creation_id:job.creation_id,expected_version:job.version,quote_id:job.quote.id}));});
 $('psResume').onclick=()=>void run(async()=>{
  const r=await call('begin_presenter_handoff',{creation_id:job.creation_id,expected_version:job.version});
  if(r.may_send)await deliver(r);else{$('psPrompt').value=r.prompt;$('psFallback').hidden=false;$('psDelivery').textContent='Saved request. Check the existing job ledger in this conversation before resuming; do not repeat submitted or uncertain generations.';}
 });
 $('psOpen').onclick=()=>void run(async()=>{await openProject(job.result.project_id);root.close();});
 $('psCopy').onclick=async()=>{try{await navigator.clipboard.writeText($('psPrompt').value);message('Request copied.');}catch{$('psPrompt').focus();$('psPrompt').select();message('Select and copy the saved request.');}};
 const interval=setInterval(async()=>{
  if(!root.open||document.hidden||busy||polling||!job||['draft','complete','failed'].includes(job.status))return;
  polling=true;const id=job.creation_id,mine=generation;
  try{const r=await call('get_presenter_video',{creation_id:id});if(id===job?.creation_id&&mine===generation){job=r.presenter_job;render();}}catch(e){message('Progress could not sync. Your saved creation is preserved. '+e.message,true);}finally{polling=false;}
 },3000);
 window.addEventListener('pagehide',()=>clearInterval(interval),{once:true});
 return {open,async receive(value){if(value.presenter_studio)await open();else if(value.presenter_job){if(root.open||value.presenter_job.status!=='complete')await open(value.presenter_job);}}};
}
