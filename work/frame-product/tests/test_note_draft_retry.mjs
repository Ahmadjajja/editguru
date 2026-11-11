import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),pid='a'.repeat(32),clip={id:'clip',start:0,end:4};
let doc={project_id:pid,name:'Retry test',version:3,source_duration:4,clips:[clip],pins:[{id:'section',clip_id:'clip',start:1,end:3}],notes:[],exports:[],checkpoints:[],rendered:null,active_revision_set_id:'set'};
const w=new Window({url:'http://127.0.0.1:18966'});w.document.write(readFileSync(new URL('widget/editor.html',root),'utf8'));
for(const k of ['window','document','ResizeObserver','HTMLElement'])globalThis[k]=w[k];
globalThis.Option=function(text,value){const e=document.createElement('option');e.text=text;e.value=value;return e};globalThis.requestAnimationFrame=()=>0;globalThis.cancelAnimationFrame=()=>{};
let poll;globalThis.setInterval=fn=>{poll=fn;return 0};const $=id=>document.getElementById(id),v=$('video');Object.defineProperties(v,{readyState:{value:2},duration:{value:4},videoWidth:{value:640},videoHeight:{value:360}});v.pause=()=>{};v.load=()=>{};
let loseConfirmation=false,failBeforeCommit=false,editDuringSave=null,loseReads=0,writes=[],messages=[];
class App{
 async connect(){this.ontoolresult({structuredContent:{project:structuredClone(doc)}})}getHostContext(){return {}}async updateModelContext(){}
 async sendMessage(message){messages.push(message);return {}}
 async callServerTool({name,arguments:a}){
  if(name==='list_projects')return {structuredContent:{projects:[{id:pid,name:doc.name}]}};
  if(name==='read_video_chunk')return {structuredContent:{project_id:pid,export_id:a.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};
  if(name==='get_project'&&loseReads){loseReads--;throw Error('confirmation read lost')}
  if(name==='update_editor'){
   writes.push(structuredClone(a));if(editDuringSave!==null){$('instruction').value=editDuringSave;editDuringSave=null}if(failBeforeCommit){failBeforeCommit=false;loseReads=1;throw Error('save did not commit')}assert.equal(a.expected_version,doc.version,'unnecessary stale or duplicate write');
   assert.ok(['add_note','add_general_note'].includes(a.action));
   const n={id:'note-'+doc.notes.length,project_id:pid,scope:a.action==='add_general_note'?'general':'section',section_id:a.section_id||null,source_time_ms:a.source_time_ms??null,output_time_ms:null,created_version:doc.version,revision_set_id:'set',status:'queued',included:true,instruction:a.instruction,order:doc.notes.length};doc={...doc,version:doc.version+1,notes:[...doc.notes,n]};
   if(loseConfirmation){loseConfirmation=false;loseReads=1;throw Error('save confirmation lost')}
  }
  return {structuredContent:structuredClone(doc)};
 }
}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
const editorSource=readFileSync(new URL('widget/editor.js',root),'utf8').split(String.fromCharCode(10)).filter(line=>!line.startsWith('import ')).join(String.fromCharCode(10)).replace('new App(','new TestApp(');
try{await import('data:text/javascript;base64,'+Buffer.from(editorSource).toString('base64'));}catch(e){console.error(e.message);process.exit(1)}
await new Promise(r=>setImmediate(r));
$('generalPromptText').value='Whole video change';$('generalPromptText').oninput();loseConfirmation=true;
await $('generalPromptForm').onsubmit({preventDefault(){}});assert.equal(doc.notes.length,1);assert.equal($('generalPromptText').value,'Whole video change');
await poll();await $('generalPromptForm').onsubmit({preventDefault(){}});
assert.equal(doc.notes.length,1,'general revision retry after poll must not create another note');assert.equal($('generalPromptText').value,'');assert.equal(writes.length,1);
$('generalPromptText').value='Whole video change';$('generalPromptText').oninput();await $('generalPromptForm').onsubmit({preventDefault(){}});assert.equal(doc.notes.length,2,'fresh identical request remains intentional');
v.currentTime=2;let input=$('comment-section');input.value='Section change';input.oninput();loseConfirmation=true;await input.closest('form').onsubmit({preventDefault(){}});const anchor=doc.notes.at(-1).source_time_ms;
await poll();v.currentTime=2.5;input=$('comment-section');await input.closest('form').onsubmit({preventDefault(){}});
assert.equal(doc.notes.length,3,'commentary retry after poll/seek must not duplicate or move its saved anchor');assert.equal(doc.notes.at(-1).source_time_ms,anchor);assert.equal($('comment-section').value,'');
$('note').onclick();$('instruction').value='Dialog change';loseConfirmation=true;await $('saveSheet').onclick();const dialogNote=doc.notes.at(-1);
// Another request arrives before this dialog's lost confirmation is resolved.
doc={...doc,version:doc.version+1,notes:[...doc.notes,{...dialogNote,id:'other-note',instruction:'Other request',created_version:doc.version,source_time_ms:1000}]};
await poll();await $('saveSheet').onclick();assert.equal(doc.notes.length,5,'dialog retry must not duplicate its saved note');await $('sendNote').onclick();assert.match(messages.at(-1).content[0].text,new RegExp('saved note '+dialogNote.id+' '),'send targets the reconciled note, not the newest unrelated note');
const beforeFailed=doc.notes.length;$('generalPromptText').value='Retry unsaved draft';$('generalPromptText').oninput();failBeforeCommit=true;await $('generalPromptForm').onsubmit({preventDefault(){}});assert.equal(doc.notes.length,beforeFailed);await poll();await $('generalPromptForm').onsubmit({preventDefault(){}});assert.equal(doc.notes.length,beforeFailed+1,'uncommitted retry still saves');
$('generalPromptText').value='First wording';$('generalPromptText').oninput();loseConfirmation=true;await $('generalPromptForm').onsubmit({preventDefault(){}});await poll();$('generalPromptText').value='Changed wording';$('generalPromptText').oninput();await $('generalPromptForm').onsubmit({preventDefault(){}});assert.equal(doc.notes.at(-1).instruction,'Changed wording','changed draft is a new request');
$('note').onclick();$('instruction').value='Original dialog text';editDuringSave='Newer dialog text';await $('saveSheet').onclick();assert.equal(doc.notes.at(-1).instruction,'Original dialog text');assert.equal($('instruction').value,'Newer dialog text');assert.equal($('instruction').readOnly,false,'text typed during a save remains an unsaved editable draft');assert.equal($('saveSheet').hidden,false);await $('saveSheet').onclick();assert.equal(doc.notes.at(-1).instruction,'Newer dialog text');
console.log('PASS: lost-confirmation plus failed-read plus poll recovery for general, section commentary and dialog notes; stable anchors, exact sent note, intentional fresh identical request.');
await w.happyDOM.abort();
