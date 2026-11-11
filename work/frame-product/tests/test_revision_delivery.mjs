import assert from 'node:assert/strict';
import {deliverRevisionPrompt,sendToCurrentChat,browserHandoffJournal} from '../widget/revision-delivery.js';
import {webcrypto} from 'node:crypto';
globalThis.crypto ||= webcrypto;

let calls=[],sent=[],row;
const reserved={id:'handoff',project_id:'project',version:3,attempt:1,status:'sending',prompt:'Saved prompt plus receipt token',may_send:true};
const rpc=async(name,args)=>{calls.push({name,args});if(name==='begin_revision_handoff')return {...reserved,...row};return {id:reserved.id,status:args.status,error:args.error}};
const run=options=>deliverRevisionPrompt({rpc,sendMessage:async message=>{sent.push(message);return {}},projectId:'project',version:3,text:'Saved prompt',...options});
let result=await run();assert.equal(result.status,'submitted');assert.equal(sent[0].content[0].text,reserved.prompt);
row={may_send:false,status:'submitted'};await run();assert.equal(sent.length,1);
row={};result=await run({sendMessage:async()=>({isError:true})});assert.equal(result.status,'not_sent');
result=await run({sendMessage:async()=>{throw Error('Connection closed after submission')}});assert.equal(result.status,'uncertain');
result=await run({sendMessage:async()=>{throw Object.assign(Error('Open in chat'),{code:'FRAME_NO_CHAT_HOST'})}});assert.equal(result.status,'not_sent');
result=await run({isCurrent:()=>false});assert.equal(result.status,'not_sent');assert.equal(sent.length,1);
result=await run({rpc:async(name)=>{if(name==='begin_revision_handoff')return reserved;throw Error('Result save failed')}});assert.equal(result.status,'uncertain');
result=await run({rpc:async(name)=>name==='begin_revision_handoff'?reserved:{id:reserved.id,status:'received'}});assert.equal(result.status,'received');
console.log('PASS: real send payload, duplicate suppression, rejection, ambiguous result, no-host fallback, project switch, journal failure and receipt race');

let standard=0,legacy=0;
const message={role:'user',content:[{type:'text',text:'Full saved revision'}]};
await sendToCurrentChat({sendMessage:async()=>{standard++;throw Object.assign(Error('Method not found'),{code:-32601})}},message,{sendFollowUpMessage:async args=>{legacy++;assert.equal(args.prompt,'Full saved revision');return {}}});
assert.deepEqual([standard,legacy],[1,1]);
for(const failure of [Error('Connection closed'),Error('Timed out'),Error('Permission denied')]){
 await assert.rejects(()=>sendToCurrentChat({sendMessage:async()=>{throw failure}},message,{sendFollowUpMessage:async()=>{legacy++}}));
}
assert.equal(legacy,1);
const rejected=await sendToCurrentChat({sendMessage:async()=>({isError:true})},message,{sendFollowUpMessage:async()=>{legacy++}});assert.equal(rejected.isError,true);assert.equal(legacy,1);
const stored=new Map();let lockTail=Promise.resolve();
const storage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)};
const locks={request:(_key,fn)=>{const task=lockTail.then(fn);lockTail=task.catch(()=>{});return task}};
const journal=browserHandoffJournal(storage,locks);
let browserSent=0;
const missingRpc=async()=>{throw Error('Unknown tool.')};
const browserRun=()=>deliverRevisionPrompt({rpc:missingRpc,journal,projectId:'legacy-project',version:1,text:'Saved browser revision',sendMessage:async()=>{browserSent++;return {}}});
const [a,b]=await Promise.all([browserRun(),browserRun()]);assert.equal(browserSent,1);assert.equal(a.id,b.id);assert.equal(a.status,'submitted');assert.equal(a.tracking,'browser');
await browserRun();assert.equal(browserSent,1);
const reloaded=browserHandoffJournal(storage,locks);assert.equal((await reloaded.begin({project_id:'legacy-project',expected_version:1,prompt:'Saved browser revision'})).may_send,false);
await assert.rejects(()=>deliverRevisionPrompt({rpc:async()=>{throw Error('Timeline changed')},journal,projectId:'p',version:1,text:'x',sendMessage:async()=>{browserSent++}}));assert.equal(browserSent,1);
await assert.rejects(()=>deliverRevisionPrompt({rpc:missingRpc,journal:browserHandoffJournal({getItem:()=>null,setItem:()=>{throw Error('Storage denied')}},locks),projectId:'p',version:1,text:'x',sendMessage:async()=>{browserSent++}}));assert.equal(browserSent,1);
console.log('PASS: standard-to-legacy only on missing method, no retry on ambiguity/rejection, stale tool registry browser fallback, concurrent/reloaded duplicate suppression, storage/validation failures block sending');
