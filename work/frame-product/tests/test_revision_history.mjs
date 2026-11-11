import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {revisionOptions,revisionView,videoVersionOptions} from '../widget/revision-history.js';
const root=new URL('../',import.meta.url);
const clips=[{id:'b'.repeat(32),start:0,end:10}];
let doc={project_id:'a'.repeat(32),name:'One video',version:4,source_duration:10,clips,pins:[],notes:[],exports:[],checkpoints:[
 {id:'source',label:'Original upload',created_at:1,clips,rendered:null},
 {id:'old',label:'First edit',timeline_version:2,created_at:2,clips:[{...clips[0],start:1}],rendered:null},
 {id:'new',label:'Export',timeline_version:3,created_at:2,clips,rendered:{proposal_id:'e',clips}},
]};
assert.deepEqual(revisionOptions(doc).map(r=>r.value),['latest','new','old','source']);
const submitted={...doc,checkpoints:[...doc.checkpoints,{id:'prompt',kind:'prompt',saved_video_id:'e',label:'Before prompt',created_at:3,clips,notes:[],pins:[],rendered:{proposal_id:'e',clips}}]};
assert.deepEqual(videoVersionOptions(submitted).map(r=>r.value),['latest','prompt','source'],'export and its prompt snapshot are one video version');
assert.match(videoVersionOptions(submitted)[1].label,/Version 2/);
const view=revisionView(doc,'old');assert.equal(view.clips[0].start,1);view.clips[0].start=8;assert.equal(doc.checkpoints[1].clips[0].start,1);
assert.equal(revisionView({...doc,checkpoints:[{id:'stale',clips:[{...clips[0],start:2}],rendered:{clips}}]},'stale').rendered,null);
const w=new Window({url:'http://127.0.0.1:18966'});w.document.write(readFileSync(new URL('widget/editor.html',root),'utf8'));
for(const key of ['window','document','ResizeObserver','Option','HTMLElement'])globalThis[key]=w[key];
globalThis.Option=function(text,value){const el=w.document.createElement('option');el.text=text;el.value=value;return el};
globalThis.requestAnimationFrame=()=>0;globalThis.cancelAnimationFrame=()=>{};let poll;globalThis.setInterval=fn=>{poll=fn;return 0};
const video=document.getElementById('video');Object.defineProperties(video,{readyState:{value:2},duration:{value:10},videoWidth:{value:640},videoHeight:{value:360}});video.pause=()=>{};video.load=()=>{};
let writes=[],fail=false;
class App{async connect(){this.ontoolresult({structuredContent:{project:structuredClone(doc)}})}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'}]}};
 if(name==='read_video_chunk')throw Error('fixture has no media');
 if(name==='update_editor'){if(fail)throw Error('Conflict');assert.equal(args.action,'restore_checkpoint');doc={...doc,version:doc.version+1,clips:structuredClone(doc.checkpoints.find(c=>c.id===args.checkpoint_id).clips)};}
 return {structuredContent:structuredClone(doc)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
const src=readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(');
await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const $=id=>document.getElementById(id);
assert.deepEqual([...$('editHistory').options].map(o=>o.value),['latest','new','old','source']);
assert.deepEqual([...$('projects').options].map(o=>o.value),['latest','new','source']);
assert.equal($('projects').options[0].value,'latest');
assert.equal(document.querySelector('#videoVersions'),null,'only one primary dropdown');
const choose=async id=>{$('editHistory').value=id;await $('editHistory').onchange({target:$('editHistory')})};
await choose('old');assert.equal(writes.filter(r=>r.name==='update_editor').length,0);assert.equal($('restoreRevision').disabled,false);assert.equal($('export').disabled,true);assert.equal($('revisionNotice').hidden,false);
await poll();assert.equal($('editHistory').value,'old','poll preserves the inspected revision');
await choose('latest');assert.equal($('revisionNotice').hidden,true);assert.equal($('export').disabled,false);
await choose('old');await $('restoreRevision').onclick();assert.equal(writes.filter(r=>r.name==='update_editor').length,1);assert.equal(doc.clips[0].start,1);assert.equal($('editHistory').value,'latest');
await choose('source');fail=true;await $('restoreRevision').onclick();assert.equal($('editHistory').value,'source','failed restoration preserves selection');
await $('browseProjects').onclick();assert.match($('projectBrowserList').textContent,/Other project/);assert.equal($('projects').options.length,3,'library does not clutter project version history');
console.log('PASS: newest first, stable ordering, immutable preview, stale render suppression, nonmutating selection, live polling, latest return, restore success/failure and full project library');
await w.happyDOM.abort();
