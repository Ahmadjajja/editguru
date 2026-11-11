import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),pid='a'.repeat(32),cid='b'.repeat(32),hash='c'.repeat(64),eid='d'.repeat(32);
const clip={id:'clip',start:0,end:4};
let parent={project_id:pid,name:'Before',version:2,source_duration:4,clips:[clip],pins:[],notes:[],exports:[],checkpoints:[{id:'source',label:'Original',clips:[clip],rendered:null}],rendered:{proposal_id:'old',clips:[clip]}};
let child={project_id:cid,name:'Revised',version:1,source_duration:4,clips:[clip],pins:[],notes:[],exports:[],checkpoints:[],rendered:null,revision_parent:{project_id:pid,export_id:eid,sha256:hash}};
const w=new Window({url:'http://127.0.0.1:18966'});w.document.write(readFileSync(new URL('widget/editor.html',root),'utf8'));
for(const k of ['window','document','ResizeObserver','HTMLElement'])globalThis[k]=w[k];
globalThis.Option=function(text,value){const e=document.createElement('option');e.text=text;e.value=value;return e};
globalThis.requestAnimationFrame=()=>0;globalThis.cancelAnimationFrame=()=>{};let poll;globalThis.setInterval=fn=>{poll=fn;return 0};
const $=id=>document.getElementById(id),v=$('video');Object.defineProperties(v,{readyState:{value:2},duration:{value:4},videoWidth:{value:640},videoHeight:{value:360}});v.pause=()=>{};v.load=()=>{};
let writes=[],context=[];
class App{async connect(){this.ontoolresult({structuredContent:{project:structuredClone(parent)}})}getHostContext(){return {}}async updateModelContext(x){context.push(x)}async callServerTool({name,arguments:a}){
 writes.push({name,a});if(name==='list_projects')return {structuredContent:{projects:[{id:pid,name:'Before'},{id:cid,name:'Revised'},{id:'f'.repeat(32),name:'Unrelated latest'}]}};
 if(name==='read_video_chunk')return {structuredContent:{project_id:a.project_id,export_id:a.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};
 if(name==='update_editor'){assert.equal(a.project_id,pid);assert.equal(a.expected_version,parent.version);assert.equal('section_id' in a,false);assert.equal('source_time_ms' in a,false);if(a.action==='add_general_note')parent={...parent,version:parent.version+1,notes:[...parent.notes,{id:'n'+parent.notes.length,scope:'general',section_id:null,source_time_ms:null,created_version:parent.version,instruction:a.instruction,status:'queued',included:true,order:parent.notes.length}]};else parent={...parent,version:parent.version+1,notes:parent.notes.map(n=>n.id===a.note_id?{...n,included:a.action==='keep_note',status:a.action==='keep_note'?'queued':'removed'}:n)}}
 if(name==='split_clip'){assert.equal(a.project_id,cid);child={...child,version:2,clips:[{...clip,end:1},{...clip,id:'two',start:1}]};}
 return {structuredContent:structuredClone(a.project_id===cid?child:parent)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(')).toString('base64'));

assert.equal($('generalRevisions').hidden,false);
assert.ok($('generalRevisions').compareDocumentPosition($('savedPinDetails'))&4,'general bar precedes sections');
for(const text of ['Warm up the entire video.','Keep the titles consistent.']){
 $('generalPromptText').value=text;$('generalPromptText').oninput();
 await $('generalPromptForm').onsubmit({preventDefault(){}});
 assert.equal($('generalPromptText').value,'');
}
assert.equal($('generalRevisionList').children.length,2);
assert.equal(parent.pins.length,0);
let prompt=buildImplementationPrompt(parent);
assert.equal(prompt.pending_count,2);assert.equal(prompt.section_count,0);
assert.match(prompt.text,/General revisions · whole version/);
assert.doesNotMatch(prompt.text,/Source timestamp:|All source pinpoints:|Other saved revisions/);
assert.equal(prompt.text.split('User request: Warm up the entire video.').length,2);
await $('generalRevisionList').querySelector('button').onclick();
assert.equal(buildImplementationPrompt(parent).pending_count,1);
await $('generalRevisionList').querySelector('button').onclick();
assert.equal(buildImplementationPrompt(parent).pending_count,2);
await poll();assert.equal($('generalRevisionList').children.length,2,'saved stack survives re-read');
parent.next_revision={project_id:cid,source_version:parent.version,export_id:eid,sha256:hash};
const reads=writes.filter(x=>x.name==='get_project'&&x.a.project_id===cid).length;await poll();
assert.equal(writes.filter(x=>x.name==='get_project'&&x.a.project_id===cid).length,reads,'pending whole-version notes block auto-continuation');
$('editHistory').value='source';await $('editHistory').onchange({target:$('editHistory')});
assert.equal($('generalPromptText').disabled,true,'saved version inspection is read only');
console.log('PASS: general bar above sections, no-section save, stacked notes, no timestamp payload, saved reload, remove/include, whole-version handoff, read-only history');
await w.happyDOM.abort();
