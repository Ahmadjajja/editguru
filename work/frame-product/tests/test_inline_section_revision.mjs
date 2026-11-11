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
let doc={project_id:'a'.repeat(32),name:'One video',version:4,active_revision_set_id:'revision-set',source_duration:10,clips,pins:[],notes:[],exports:[],checkpoints:[
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
let appInstance;let loseNoteResponse=false,failRecoveryRead=false;let failNote=false;let holdRead=null,holdProject=null;
let writes=[],fail=false,messages=[],reject=false,hasMedia=true,failComparison=false;
class App{async sendMessage(message){messages.push(message);return {isError:reject}}async connect(){appInstance=this}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='project_link')return {structuredContent:{project_id:args.project_id,url:'http://127.0.0.1:18966/frame?project='+args.project_id}};if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'}]}};
 if(name==='get_project'&&failRecoveryRead)throw Error('Read disconnected');
 if(name==='get_project'&&args.project_id==='f'.repeat(32))return {structuredContent:{...structuredClone(doc),project_id:args.project_id,name:'Other project',rendered:null}};
 if(name==='get_project'&&holdProject){const gate=holdProject;holdProject=null;await gate;}
 if(name==='read_video_chunk'){if(holdRead){const gate=holdRead;holdRead=null;await gate;}if(!hasMedia)throw Error('fixture has no media');return {structuredContent:{project_id:args.project_id,export_id:args.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};}
 if(name==='export_video'){if(failComparison)throw Error('Render failed');doc={...doc,rendered:{proposal_id:'comparison-export',clips:structuredClone(doc.clips)}};}
 if(name==='update_editor'&&args.action==='add_note'){if(failNote)throw Error('Simulated save failure');if(args.expected_version<doc.version&&doc.notes.some(n=>n.created_version===args.expected_version&&n.section_id===args.section_id&&n.source_time_ms===args.source_time_ms&&n.instruction===args.instruction))return {structuredContent:structuredClone(doc)};assert.equal(args.expected_version,doc.version);doc={...doc,version:doc.version+1,notes:[...doc.notes,{created_version:doc.version,revision_set_id:doc.active_revision_set_id,scope:'section',output_time_ms:null,id:'note-'+doc.version,section_id:args.section_id,source_time_ms:args.source_time_ms,instruction:args.instruction,status:'queued',included:true,order:doc.notes.length+1}]};if(loseNoteResponse){loseNoteResponse=false;throw Error('Save confirmation disconnected')}return {structuredContent:structuredClone(doc)};}
 if(name==='update_editor'&&['add_pin','edit_pin'].includes(args.action)){doc=structuredClone(doc);if(args.action==='add_pin')doc.pins.push({id:'section-'+doc.version,start:args.start,end:args.end,clip_id:args.clip_id,time:args.start,instruction:''});else Object.assign(doc.pins.find(p=>p.id===args.pin_id),{start:args.start,end:args.end,time:args.start});doc.version++;return {structuredContent:structuredClone(doc)};}
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
video.currentTime=1;await $('pin').onclick();video.currentTime=3;await $('finishSection').onclick();await tick();
assert.equal($('pinPrompt').hidden,false,'completing a section opens the change box');assert.equal($('pinPrompt').previousElementSibling.id,'sectionOverview','composer is directly below the timeline');
assert.match($('pinPromptAnchor').textContent,/Section 1/);assert.equal($('savePinPrompt').disabled,true,'blank changes cannot be saved');
$('pinPromptText').value='Replace this opening with the new take';$('pinPromptText').oninput();assert.equal($('savePinPrompt').disabled,false);
failNote=true;await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();assert.equal($('pinPrompt').hidden,false);assert.equal($('pinPromptText').value,'Replace this opening with the new take');assert.match($('pinPromptStatus').textContent,/text is preserved/);assert.equal(doc.notes.length,0);
failNote=false;await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();assert.equal($('pinPrompt').hidden,true);assert.equal(doc.notes.length,1);assert.equal(doc.notes[0].section_id,doc.pins[0].id);assert.equal(doc.notes[0].source_time_ms,1000,'end playhead anchors safely within the saved section');assert.match(document.querySelector('.section-card').textContent,/Replace this opening with the new take/);
assert.equal($('pinPromptText').value,'');
video.currentTime=4;await $('pin').onclick();video.currentTime=6;await $('finishSection').onclick();await tick();assert.equal($('pinPrompt').hidden,false);assert.match($('pinPromptAnchor').textContent,/Section 2/);
$('pinPromptText').value='Keep this draft for later';$('pinPromptText').oninput();$('skipPinPrompt').click();assert.equal($('pinPrompt').hidden,true);assert.equal([...document.querySelectorAll('.section-card textarea')].at(-1).value,'Keep this draft for later','Later forwards unsaved text to the section form without dropping it');
// A committed save whose response is lost is recovered from persisted notes.
video.currentTime=6;await $('pin').onclick();video.currentTime=8;await $('finishSection').onclick();await tick();
$('pinPromptText').value='Use the rerecorded ending';$('pinPromptText').oninput();
loseNoteResponse=true;const beforeLost=writes.filter(w=>w.name==='update_editor'&&w.args.action==='add_note').length;
await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();
assert.equal($('pinPrompt').hidden,true,'saved note is reconciled after lost acknowledgement');
assert.equal(doc.notes.filter(n=>n.instruction==='Use the rerecorded ending').length,1);
assert.equal(writes.filter(w=>w.name==='update_editor'&&w.args.action==='add_note').length,beforeLost+1);

// If both save confirmation and recovery read fail, preserve the original version/anchor.
video.currentTime=8;await $('pin').onclick();video.currentTime=9;await $('finishSection').onclick();await tick();
$('pinPromptText').value='Keep only the final sentence';$('pinPromptText').oninput();
const expected=doc.version;failNote=true;failRecoveryRead=true;
await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();
assert.equal($('pinPrompt').hidden,false);assert.equal($('pinPromptText').value,'Keep only the final sentence');
video.currentTime=8.5;failNote=false;failRecoveryRead=false;await $('refresh').onclick();await tick();
await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();
const retries=writes.filter(w=>w.name==='update_editor'&&w.args.action==='add_note').slice(-2);
assert.equal(retries[0].args.expected_version,expected);assert.deepEqual(retries[0].args,retries[1].args,'retry retains exact version and source anchor');
assert.equal($('pinPrompt').hidden,true);
// The server committed, both confirmation and recovery read were lost, and Refresh saw it.
video.currentTime=.1;await $('pin').onclick();video.currentTime=.8;await $('finishSection').onclick();await tick();
$('pinPromptText').value='One final change';$('pinPromptText').oninput();
loseNoteResponse=true;failRecoveryRead=true;
await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();
assert.equal($('pinPrompt').hidden,false);assert.equal(doc.notes.filter(n=>n.instruction==='One final change').length,1);
failRecoveryRead=false;await $('refresh').onclick();await tick();
await $('sectionRevisionForm').onsubmit({preventDefault(){}});await tick();
assert.equal($('pinPrompt').hidden,true);assert.equal(doc.notes.filter(n=>n.instruction==='One final change').length,1,'lost confirmation retry never adds a second revision');
console.log('PASS: section completion opens inline composer below timeline; failed save retains text; successful save moves the exact revision to its section; Later preserves the draft');await w.happyDOM.abort();
