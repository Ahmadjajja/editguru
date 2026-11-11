import {createStudio} from '../widget/studio.js';
globalThis.createStudio=createStudio;
import {createCreativeFeedback} from '../widget/creative-feedback.js';
globalThis.createCreativeFeedback=createCreativeFeedback;
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {revisionOptions,revisionView} from '../widget/revision-history.js';
const root=new URL('../',import.meta.url);
const clips=[{id:'b'.repeat(32),start:0,end:10}];
let doc={project_id:'a'.repeat(32),name:'One video',version:4,source_duration:10,clips,pins:[],notes:[],exports:[],checkpoints:[
 {id:'source',label:'Original upload',created_at:1,clips,rendered:null},
 {id:'old',label:'First edit',timeline_version:2,created_at:2,clips:[{...clips[0],start:1}],rendered:null},
 {id:'new',label:'Export',timeline_version:3,created_at:2,clips,rendered:{proposal_id:'e',clips}},
]};
assert.deepEqual(revisionOptions(doc).map(r=>r.value),['latest','new','old','source']);
const view=revisionView(doc,'old');assert.equal(view.clips[0].start,1);view.clips[0].start=8;assert.equal(doc.checkpoints[1].clips[0].start,1);
assert.equal(revisionView({...doc,checkpoints:[{id:'stale',clips:[{...clips[0],start:2}],rendered:{clips}}]},'stale').rendered,null);
const w=new Window({url:'http://127.0.0.1:18966'});w.document.write(readFileSync(new URL('widget/editor.html',root),'utf8'));
for(const key of ['window','document','ResizeObserver','Option','HTMLElement'])globalThis[key]=w[key];
globalThis.Option=function(text,value){const el=w.document.createElement('option');el.text=text;el.value=value;return el};
globalThis.requestAnimationFrame=()=>0;globalThis.cancelAnimationFrame=()=>{};let poll;globalThis.setInterval=fn=>{poll=fn;return 0};
const video=document.getElementById('video');Object.defineProperties(video,{readyState:{value:2},duration:{value:10},videoWidth:{value:640},videoHeight:{value:360}});video.pause=()=>{};video.load=()=>{};
let appInstance;let holdRead=null,holdProject=null;
let writes=[],fail=false,messages=[],reject=false,hasMedia=false,failComparison=false;
class App{async sendMessage(message){messages.push(message);return {isError:reject}}async connect(){appInstance=this}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='project_link')return {structuredContent:{project_id:args.project_id,url:'http://127.0.0.1:18966/frame?project='+args.project_id}};if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'}]}};
 if(name==='get_project'&&args.project_id==='f'.repeat(32))return {structuredContent:{...structuredClone(doc),project_id:args.project_id,name:'Other project',rendered:null}};
 if(name==='get_project'&&holdProject){const gate=holdProject;holdProject=null;await gate;}
 if(name==='read_video_chunk'){if(holdRead){const gate=holdRead;holdRead=null;await gate;}if(!hasMedia)throw Error('fixture has no media');return {structuredContent:{project_id:args.project_id,export_id:args.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};}
 if(name==='export_video'){if(failComparison)throw Error('Render failed');doc={...doc,rendered:{proposal_id:'comparison-export',clips:structuredClone(doc.clips)}};}
 if(name==='update_editor'){if(fail)throw Error('Conflict');assert.equal(args.action,'restore_checkpoint');doc={...doc,version:doc.version+1,clips:structuredClone(doc.checkpoints.find(c=>c.id===args.checkpoint_id).clips)};}
 return {structuredContent:structuredClone(doc)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
const src=readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(');
await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const $=id=>document.getElementById(id);
const main=document.querySelector('main');
assert.equal(main.hasAttribute('data-project-ready'),false,'saved projects alone must not open the editor');
assert.equal(w.getComputedStyle($('editPanel')).display,'none','empty editor stays hidden');
assert.equal(w.getComputedStyle($('generalRevisions')).display,'none');
assert.equal(w.getComputedStyle($('footageOnboarding')).display,'block');
assert.equal($('homeAddFootage').textContent,'Add new footage');
assert.ok($('homeProjectList').querySelector('.open-project-latest'));
assert.equal(writes.some(r=>r.name==='read_video_chunk'),false,'do not open media before selection');
appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});
for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));
assert.equal(main.hasAttribute('data-project-ready'),true,'explicit footage handoff opens the editor');
assert.equal(w.getComputedStyle($('footageOnboarding')).display,'none');

const tick=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r))};
await $('closeWorkingProject').onclick();await tick();
// A failed replacement must never leave the prior video's pixels or controls active.
doc={...doc,project_id:'9'.repeat(32),rendered:null};hasMedia=false;await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();
assert.equal(video.getAttribute('src'),null,'failed replacement detaches old video');
assert.equal(video.hidden,true);assert.equal($('play').disabled,true);assert.equal($('split').disabled,true);
assert.equal($('mediaState').hidden,false);assert.equal($('retryMedia').hidden,false);
const editsBefore=writes.filter(r=>r.name==='split_clip').length;
document.body.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'k',metaKey:true}));await tick();
assert.equal(writes.filter(r=>r.name==='split_clip').length,editsBefore,'keyboard cut cannot use stale preview');
hasMedia=true;await $('retryMedia').onclick();await tick();
assert.equal($('play').disabled,false);assert.equal($('mediaState').hidden,true,'successful retry clears recovery state');
// Repeated refresh presses share one reload and closing during the request wins.
let release;holdProject=new Promise(resolve=>{release=resolve});
const beforeRefresh=writes.filter(r=>r.name==='get_project'&&r.args.project_id==='9'.repeat(32)).length;
const refreshOne=$('refresh').onclick(),refreshTwo=$('refresh').onclick();await tick();
assert.equal($('refresh').disabled,true);assert.equal($('refresh').textContent,'Refreshing…');
assert.equal(writes.filter(r=>r.name==='get_project'&&r.args.project_id==='9'.repeat(32)).length,beforeRefresh+1,'double refresh has one project read');
await $('closeWorkingProject').onclick();release();await Promise.all([refreshOne,refreshTwo]);await tick();
assert.equal(main.hasAttribute('data-project-ready'),false,'in-flight refresh must not reopen a closed project');
assert.equal($('refresh').disabled,false);
// Closing while a media chunk is in flight must release the loading lock and URL.
let releaseRead;holdRead=new Promise(resolve=>{releaseRead=resolve});
appInstance.ontoolresult({structuredContent:{project:{...structuredClone(doc),project_id:'8'.repeat(32),rendered:null}}});await tick();
assert.equal($('videoStage').getAttribute('aria-busy'),'true');assert.equal($('play').disabled,true);
await $('closeWorkingProject').onclick();releaseRead();await tick();
assert.equal(video.getAttribute('src'),null);assert.equal($('mediaState').hidden,true);
await appInstance.ontoolresult({structuredContent:{project:{...structuredClone(doc),project_id:'7'.repeat(32),rendered:null}}});await tick();
assert.equal($('play').disabled,false,'opening after cancelled chunk must recover');
assert.equal($('videoStage').getAttribute('aria-busy'),'false');
console.log('PASS: project/history controls plus failed-preview isolation, keyboard guard, retry, duplicate Refresh, close-during-refresh and close-during-load recovery');
await w.happyDOM.abort();
