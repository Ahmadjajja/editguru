import assert from 'node:assert/strict';
import {Window} from 'happy-dom';
import {createPresenterStudio,deliverPresenter} from '../widget/presenter-studio.js';

// Transport ambiguity must never become an automatic second paid workflow.
let sends=0,finishes=[];
const reservation={may_send:true,handoff_id:'handoff',prompt:'saved exact request',presenter_job:{creation_id:'a'.repeat(32)}};
const rpc=async(name,args)=>{finishes.push({name,args});return {...reservation,delivery_status:args.status};};
let r=await deliverPresenter({rpc,app:{async sendMessage(){sends++;throw Error('connection lost');}},reservation});
assert.equal(r.delivery_status,'uncertain');assert.equal(sends,1);
await deliverPresenter({rpc,app:{async sendMessage(){sends++;}},reservation:{...reservation,may_send:false}});assert.equal(sends,1);
r=await deliverPresenter({rpc,app:{async sendMessage(){const e=Error('No chat host');e.code='FRAME_NO_CHAT_HOST';throw e;}},reservation});
assert.equal(r.delivery_status,'not_sent');

const w=new Window({url:'http://127.0.0.1:18966'});w.document.write('<header></header>');
for(const k of ['window','document'])globalThis[k]=w[k];
globalThis.Option=function(text,value){const el=document.createElement('option');el.textContent=text;el.value=value;return el;};
let poll;globalThis.setInterval=fn=>{poll=fn;return 0;};globalThis.clearInterval=()=>{};
const $=id=>document.getElementById(id);let saved=null,writes=[],opened=null,chat=[];
const call=async(name,a)=>{
 writes.push({name,a});
 if(name==='list_presenter_videos')return {presenter_jobs:saved?[saved]:[]};
 if(name==='save_presenter_brief'){saved={creation_id:'a'.repeat(32),version:1,status:'draft',stage:'Brief saved',brief:a.brief,steps:[]};return {presenter_job:structuredClone(saved)};}
 if(name==='get_presenter_video')return {presenter_job:structuredClone(saved)};
 if(name==='begin_presenter_handoff'){saved={...saved,status:'requested',version:2};return {...reservation,presenter_job:structuredClone(saved)};}
 if(name==='finish_presenter_handoff')return {...reservation,presenter_job:structuredClone(saved),delivery_status:a.status};
 if(name==='approve_presenter_quote'){assert.equal(a.quote_id,'quote-one');assert.equal(a.expected_version,3);saved={...saved,status:'approved',version:4};return {...reservation,presenter_job:structuredClone(saved)};}
 throw Error('Unexpected tool '+name);
};
const studio=createPresenterStudio({app:{async sendMessage(m){chat.push(m);return {};}},rpc:async(n,a)=>({structuredContent:await call(n,a)}),data:r=>r.structuredContent,openProject:async pid=>{opened=pid;}});
await studio.open();assert.equal($('presenterStudio').open,true);assert.equal(writes.length,1,'Opening lists drafts, never generates');
$('psScript').value='My exact creator script.';$('psCharacter').value='Use the attached portrait.';$('psVoice').value='Use my voice sample.';
$('psStyle').value='Fast, warm and editorial.';
const settle=async()=>{for(let i=0;i<30;i++)await new Promise(resolve=>setImmediate(resolve));};
$('psPlan').onclick();await settle();
assert.equal(saved.brief.script,'My exact creator script.');assert.equal(saved.brief.character,'Use the attached portrait.');assert.equal(chat.length,1);
assert.equal(writes.filter(c=>c.name==='save_presenter_brief').length,1);assert.equal($('psScript').disabled,true);
assert.equal($('psFallback').hidden,false);assert.match($('psDelivery').textContent,/Waiting for receipt/);
saved={...saved,status:'awaiting_approval',version:3,stage:'Review the plan',quote:{id:'quote-one',credits:42,plan:'Three presenter takes and music.'}};
await poll();assert.equal($('psQuote').hidden,false);assert.match($('psApprove').textContent,/42 credits/);assert.equal(chat.length,1,'Quote alone does not generate');
$('psApprove').onclick();await settle();assert.equal(chat.length,2);assert.equal(saved.status,'approved');
saved={...saved,status:'complete',version:5,stage:'Ready to edit in Frame',result:{project_id:'f'.repeat(32)}};
await poll();assert.equal($('psOpen').hidden,false);$('psOpen').onclick();await settle();assert.equal(opened,'f'.repeat(32));assert.equal($('presenterStudio').open,false);
assert.equal(writes.some(c=>/generate|export_video/.test(c.name)),false,'The UI delegates the approved workflow and never invents provider execution');
console.log('PASS: presenter brief UI, explicit plan/credit approval, persisted progress, exact result routing, no generation on open, uncertain delivery suppression and no-host fallback');
await w.happyDOM.abort();
