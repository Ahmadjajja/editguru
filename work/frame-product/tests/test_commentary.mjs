import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),pid='a'.repeat(32),cid='b'.repeat(32),hash='c'.repeat(64),eid='d'.repeat(32);
const clip={id:'clip',start:0,end:4};
let parent={project_id:pid,name:'Before',version:2,source_duration:4,clips:[clip],pins:[{id:'section',clip_id:'clip',start:1,end:3}],notes:[],exports:[],checkpoints:[{id:'source',label:'Original',clips:[clip],pins:[{id:'section',clip_id:'clip',start:1,end:3}],rendered:null}],rendered:{proposal_id:'old',clips:[clip]}};
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
 if(name==='update_editor'){
  assert.equal(a.project_id,pid);assert.equal(a.expected_version,parent.version);
  if(a.action==='add_note'){
   assert.equal(a.section_id,'section');assert.ok(a.source_time_ms>=1000&&a.source_time_ms<3000,'anchor stays inside the section');
   parent={...parent,version:parent.version+1,notes:[...parent.notes,{id:'n'+parent.notes.length,...a,status:'queued'}]};
  }else if(a.action==='add_annotation'){
   parent={...parent,version:parent.version+1,notes:[...parent.notes,{id:'drawing',...a,status:'queued'}]};
  }else throw Error('Unexpected mutation '+a.action);
 }
 if(name==='split_clip'){assert.equal(a.project_id,cid);child={...child,version:2,clips:[{...clip,end:1},{...clip,id:'two',start:1}]};}
 return {structuredContent:structuredClone(a.project_id===cid?child:parent)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(')).toString('base64'));


const comment=()=>document.querySelector('[data-save-comment]');
async function saveComment(time,text){
 v.currentTime=time;
 const input=$('comment-section');input.value=text;input.oninput();
 assert.equal(comment().disabled,false,'commentary stays available inside/outside outlined section');
 await comment().closest('form').onsubmit({preventDefault(){}});
 assert.equal(parent.notes.at(-1).instruction,text);
}
await saveComment(0,'Before section');
await saveComment(2,'Inside section');
await saveComment(3,'At section end');
v.currentTime=2;$('annotate').onclick();
$('boxTool').onclick();
const canvas=$('markupCanvas');
canvas.getBoundingClientRect=()=>({left:0,top:0,width:640,height:360});
canvas.setPointerCapture=()=>{};canvas.hasPointerCapture=()=>false;
canvas.onpointerdown({button:0,pointerId:1,clientX:50,clientY:50,preventDefault(){}});
canvas.onpointermove({pointerId:1,clientX:150,clientY:150});
canvas.onpointerup({pointerId:1});
assert.equal($('markupTools').hidden,false);
await saveComment(2,'Comment while box is outlined');
assert.equal($('markupTools').hidden,false,'saving commentary preserves unsaved markup');
assert.equal($('saveMarkup').disabled,false);
await $('saveMarkup').onclick();
assert.equal(parent.notes.at(-1).annotations[0].kind,'box','draft box can still be saved after commentary');
await saveComment(2.9999,'Last fractional frame');
$('editHistory').value='source';await $('editHistory').onchange({target:$('editHistory')});
assert.equal(comment().disabled,true,'saved history remains read only');
console.log('PASS: commentary before/inside/after section, active box draft preserved and saved, fractional boundary, read-only history');
await w.happyDOM.abort();
