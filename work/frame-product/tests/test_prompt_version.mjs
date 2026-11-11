import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),pid='a'.repeat(32),clips=[{id:'b'.repeat(32),start:1,end:4}];
let doc={project_id:pid,name:'Video',version:2,clips,pins:[],notes:[{id:'n',scope:'general',order:1,instruction:'Warm colors',status:'queued'}],exports:[],checkpoints:[{id:'source',label:'Original',clips:[{...clips[0],start:0}],rendered:null}],rendered:null};
const w=new Window({url:'http://127.0.0.1:18966'});w.document.write(readFileSync(new URL('widget/editor.html',root),'utf8'));
for(const k of ['window','document','ResizeObserver','HTMLElement'])globalThis[k]=w[k];
globalThis.Option=function(text,value){const e=document.createElement('option');e.text=text;e.value=value;return e};
globalThis.requestAnimationFrame=()=>0;globalThis.cancelAnimationFrame=()=>{};globalThis.setInterval=()=>0;
const $=id=>document.getElementById(id),video=$('video');Object.defineProperties(video,{readyState:{value:2},duration:{value:3},videoWidth:{value:640},videoHeight:{value:360}});video.pause=()=>{};video.load=()=>{};
let calls=[],messages=[],failExport=false;
class App{
 async connect(){this.ontoolresult({structuredContent:{project:structuredClone(doc)}})}getHostContext(){return {}}async updateModelContext(){}
 async sendMessage(message){messages.push(message);return {}}
 async callServerTool({name,arguments:args}){
  calls.push(name);
  if(name==='list_projects')return {structuredContent:{projects:[{id:pid,name:'Video'},{id:'f'.repeat(32),name:'Past project'}]}};
  if(name==='read_video_chunk')throw Error('No fixture media');
  if(name==='export_video'){
   if(failExport)throw Error('Fixture export failure');
   doc={...doc,version:3,rendered:{proposal_id:'c'.repeat(32),clips:structuredClone(clips)},exports:[{id:'c'.repeat(32),status:'done'}]};
  }
  if(name==='get_frame_comments')return {structuredContent:{comments:[]}};
  if(name==='begin_revision_handoff'){
   assert.equal(args.expected_version,3);assert.match(args.prompt,/Warm colors/);assert.ok(doc.rendered);
   return {structuredContent:{id:'d'.repeat(32),checkpoint_id:'d'.repeat(32),prompt:args.prompt,status:'sending',attempt:1,may_send:true,version:3}};
  }
  if(name==='finish_revision_handoff')return {structuredContent:{id:'d'.repeat(32),status:'submitted',version:3}};
  return {structuredContent:structuredClone(doc)};
 }
}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(')).toString('base64'));
await $('sendRevisions').onclick();
assert.equal(messages.length,1);
assert.ok(calls.indexOf('export_video')<calls.indexOf('begin_revision_handoff'));
assert.ok(calls.indexOf('begin_revision_handoff')<calls.indexOf('finish_revision_handoff'));
assert.equal($('projects').options.length,2);assert.equal(document.querySelector('#videoVersions'),null);
await $('browseProjects').onclick();assert.match($('projectBrowserList').textContent,/Past project/);
failExport=true;doc={...doc,rendered:null};await $('sendRevisions').onclick();assert.equal(messages.length,1,'export failure must block prompt delivery');assert.match($('status').textContent,/not sent/);
await $('closeWorkingProject').onclick();assert.equal($('projects').options[0].value,'');assert.equal($('download').hidden,true);
console.log('PASS: automatic video save precedes version reservation and delivery, export failure blocks send, working projects excludes library, close retains saved library');
await w.happyDOM.abort();
