import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),pid='a'.repeat(32),cid='b'.repeat(32),hash='c'.repeat(64),eid='d'.repeat(32);
const clip={id:'clip',start:0,end:4};
let parent={project_id:pid,name:'Before',version:2,source_duration:4,clips:[clip],pins:[],notes:[],exports:[],checkpoints:[{id:'saved',label:'Saved render',clips:[clip],rendered:{proposal_id:'old',clips:[clip]},notes:[{id:'historical',instruction:'Original request'}],pins:[]}],rendered:{proposal_id:'old',clips:[clip]}};
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
 if(name==='split_clip'){assert.equal(a.project_id,cid);child={...child,version:2,clips:[{...clip,end:1},{...clip,id:'two',start:1}]};}
 return {structuredContent:structuredClone(a.project_id===cid?child:parent)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(')).toString('base64'));
assert.equal($('split').disabled,false,'rendered working timeline supports direct cuts');
parent.next_revision={project_id:cid,source_version:2,export_id:eid,sha256:hash};
await $('pin').onclick();
await poll();assert.equal($('continuationLink').textContent,'Open revised copy','unfinished section input prevents automatic navigation');
await $('rangeCancel').onclick();
// Incoming revised copies must wait while the user works in any modal or in References.
for(const dialog of document.querySelectorAll('dialog:not(#clipReferenceDialog)')){
 dialog.setAttribute('open','');const reads=writes.filter(x=>x.name==='read_video_chunk'&&x.a.project_id===cid).length;
 await poll();assert.equal($('continuationLink').textContent,'Open revised copy',dialog.id+' retains the active project');
 assert.equal(writes.filter(x=>x.name==='read_video_chunk'&&x.a.project_id===cid).length,reads,dialog.id+' must not load a new project behind the dialog');dialog.removeAttribute('open');
}
await $('referencesTab').onclick();await poll();
assert.equal($('continuationLink').textContent,'Open revised copy','reference work retains its section and project');
await $('editTab').onclick();
$('generalPromptText').value='Keep this unsaved request';$('generalPromptText').dispatchEvent(new w.Event('input'));
await poll();assert.equal($('generalPromptText').value,'Keep this unsaved request');assert.equal($('continuationLink').textContent,'Open revised copy','unsaved general request prevents switching projects');
$('generalPromptText').value='';$('generalPromptText').dispatchEvent(new w.Event('input'));
await poll();
assert.equal($('split').disabled,false,'automatic imported copy is directly editable');
assert.match($('continuationLabel').textContent,/ready for more edits/);
assert.ok(writes.some(x=>x.name==='read_video_chunk'&&x.a.project_id===cid&&!x.a.export_id),'loaded new source bytes, not old render');
assert.match(JSON.stringify(context.at(-1)),new RegExp(cid),'next notes are routed to revised source project');
assert.equal($('projects').options[0].value,'latest');
const earlier='ancestor:'+pid+':saved';
assert.ok([...$('editHistory').options].some(o=>o.value===earlier),'previous rounds accumulate in version history');
$('editHistory').value=earlier;await $('editHistory').onchange({target:$('editHistory')});
assert.equal($('split').disabled,true);assert.match($('versionRecordText').textContent,/Original request/);
await poll();assert.equal($('editHistory').value,earlier,'polling preserves earlier round inspection');
$('projects').value='latest';await $('projects').onchange();
v.currentTime=1;await $('split').onclick();assert.equal(child.clips.length,2);assert.equal(parent.clips.length,1);
await $('continuationLink').onclick();await new Promise(r=>setTimeout(r,20));
assert.match($('continuationLabel').textContent,/revised copy is ready/);
await poll();assert.match($('continuationLabel').textContent,/revised copy is ready/,'explicit previous-project inspection is retained');
console.log('PASS: completed revision auto-loads exact scoped editable source; next edit targets new copy; parent/history inspection retained; unrelated library recency ignored');
await w.happyDOM.abort();
