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
let writes=[],fail=false,messages=[],reject=false,hasMedia=true,failComparison=false;
class App{async sendMessage(message){messages.push(message);return {isError:reject}}async connect(){appInstance=this}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='project_link')return {structuredContent:{project_id:args.project_id,url:'http://127.0.0.1:18966/frame?project='+args.project_id}};if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'}]}};
 if(name==='get_project'&&args.project_id==='f'.repeat(32))return {structuredContent:{...structuredClone(doc),project_id:args.project_id,name:'Other project',rendered:null}};
 if(name==='get_project'&&holdProject){const gate=holdProject;holdProject=null;await gate;}
 if(name==='read_video_chunk'){if(holdRead){const gate=holdRead;holdRead=null;await gate;}if(!hasMedia)throw Error('fixture has no media');return {structuredContent:{project_id:args.project_id,export_id:args.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};}
 if(name==='export_video'){if(failComparison)throw Error('Render failed');doc={...doc,rendered:{proposal_id:'comparison-export',clips:structuredClone(doc.clips)}};}
 if(name==='update_editor'&&['add_pin','edit_pin'].includes(args.action)){doc=structuredClone(doc);if(args.action==='add_pin')doc.pins.push({id:'section-'+doc.version,start:args.start,end:args.end,clip_id:args.clip_id,time:args.start,instruction:''});else Object.assign(doc.pins.find(p=>p.id===args.pin_id),{start:args.start,end:args.end,time:args.start});doc.version++;return {structuredContent:structuredClone(doc)};}
 if(name==='update_editor'){if(fail)throw Error('Conflict');assert.equal(args.action,'restore_checkpoint');doc={...doc,version:doc.version+1,clips:structuredClone(doc.checkpoints.find(c=>c.id===args.checkpoint_id).clips)};}
 return {structuredContent:structuredClone(doc)};
}}
globalThis.TestApp=App;globalThis.applyDocumentTheme=()=>{};globalThis.applyHostStyleVariables=()=>{};
for(const name of ['project-files','project-library','markup','section-timeline','revision-prompt','revision-delivery','section-range','references','reference-clips','revision-history','presenter-studio'])Object.assign(globalThis,await import(new URL('widget/'+name+'.js',root)));
const src=readFileSync(new URL('widget/editor.js',root),'utf8').replace(/^import .*\n/gm,'').replace('new App(','new TestApp(');
try{await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));}catch(e){console.error(e.name+': '+e.message);process.exit(1)}
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
const pressKey=(key,target=document.body,extra={})=>target.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key,...extra}));
const initialClips=structuredClone(doc.clips);
video.currentTime=1.25;pressKey('i');await tick();
assert.equal($('sectionPicker').hidden,false);assert.equal($('rangeStart').value,'1.25');assert.equal($('rangeEnd').value,'');
assert.equal(writes.filter(r=>r.name==='update_editor').length,0,'setting the start creates no incomplete saved section');
assert.equal($('finishSection').disabled,false);assert.match($('rangeStatus').textContent,/Play or scrub/);
video.currentTime=4.75;video.ontimeupdate();assert.equal($('rangeDraft').hidden,false);
pressKey('o');pressKey('o');await tick();
assert.equal(doc.pins.length,1,'two rapid end presses save exactly once');assert.equal(doc.pins[0].start,1.25);assert.equal(doc.pins[0].end,4.75);
assert.equal($('sectionPicker').hidden,true);assert.equal($('finishSection').disabled,true);
assert.deepEqual(doc.clips,initialClips,'marking a section preserves the cut');
// Existing sections have directly editable bounds.
const adjust=()=>[...document.querySelectorAll('.section-card button')].find(b=>b.textContent==='Adjust start / end');
adjust().click();assert.equal($('rangeStart').value,'1.25');assert.equal($('rangeEnd').value,'4.75');
$('rangeStart').value='2.125';$('rangeStart').oninput();$('rangeEnd').value='5.875';$('rangeEnd').oninput();await $('rangeSave').onclick();await tick();
assert.equal(doc.pins.length,1);assert.equal(doc.pins[0].start,2.125);assert.equal(doc.pins[0].end,5.875);
// Text entry keeps I/O characters, and abandoned drafts never save.
video.currentTime=6;pressKey('i');const field=document.createElement('textarea');document.body.append(field);pressKey('o',field);await tick();assert.equal(doc.pins.length,1);
video.currentTime=5;pressKey('o');await tick();assert.equal(doc.pins.length,1);assert.equal($('sectionPicker').hidden,false);assert.match($('rangeStatus').textContent,/End must be after/);
pressKey('Escape');assert.equal($('sectionPicker').hidden,true);
// The end boundary may be the exact final frame of the source.
video.currentTime=7;pressKey('i');video.currentTime=10;pressKey('o');await tick();assert.equal(doc.pins.length,2);assert.equal(doc.pins[1].end,10);
// Preview is bounded, rather than merely jumping to the start.
let plays=0,pauses=0;video.play=async()=>{plays++};video.pause=()=>{pauses++};
await [...document.querySelectorAll('.section-card button')].find(b=>b.textContent==='Preview section').onclick();
assert.equal(video.currentTime,2.125);assert.equal(plays,1);video.currentTime=6;video.ontimeupdate();assert.equal(video.currentTime,5.875);assert.ok(pauses>0);assert.match($('status').textContent,/preview finished/);
const before=writes.length;for(const key of ['q','w','Delete','Backspace'])pressKey(key);pressKey('k',document.body,{metaKey:true});await tick();assert.equal(writes.length,before,'quick-cut keyboard actions are absent');
assert.equal($('trimToolbar').hidden,true);assert.equal(w.getComputedStyle($('trimToolbar')).display,'none');
// Edited playback ends at its retained source endpoint, not the source duration.
doc={...doc,project_id:'e'.repeat(32),source_duration:10,clips:[{id:'edited-clip',start:2,end:5}],pins:[],rendered:{proposal_id:'saved-cut',clips:[{id:'edited-clip',start:2,end:5}],duration:3},duration:3};
await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();video.currentTime=1;pressKey('i');video.currentTime=3;pressKey('o');await tick();
assert.equal(doc.pins[0].start,3);assert.equal(doc.pins[0].end,5,'edited end maps to the last retained source frame');
await $('previewSelectedSection').onclick();assert.equal(video.currentTime,1,'edited section preview uses composed time');video.currentTime=3;video.ontimeupdate();assert.match($('status').textContent,/preview finished/);
console.log('PASS: I/O boundaries, duplicate-save suppression, boundary edits, typing guards, invalid/end-of-source bounds, cancel, bounded preview, composed endpoint mapping and no quick-cut dispatch');
await w.happyDOM.abort();
