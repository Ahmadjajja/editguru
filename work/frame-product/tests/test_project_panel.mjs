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
let appInstance;
let writes=[],fail=false,messages=[],reject=false,hasMedia=false,failComparison=false;
class App{async sendMessage(message){messages.push(message);return {isError:reject}}async connect(){appInstance=this}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='project_link')return {structuredContent:{project_id:args.project_id,url:'http://127.0.0.1:18966/frame?project='+args.project_id}};if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'}]}};
 if(name==='get_project'&&args.project_id==='f'.repeat(32))return {structuredContent:{...structuredClone(doc),project_id:args.project_id,name:'Other project',rendered:null}};
 if(name==='read_video_chunk'){if(!hasMedia)throw Error('fixture has no media');return {structuredContent:{project_id:args.project_id,export_id:args.export_id||null,offset:0,next_offset:4,total_bytes:4},_meta:{videoChunk:'AAAAAA=='}};}
 if(name==='export_video'){if(failComparison)throw Error('Render failed');doc={...doc,rendered:{proposal_id:'comparison-export',clips:structuredClone(doc.clips)}};}
 if(name==='move_segment'){const index=doc.clips.findIndex(c=>c.id===args.clip_id),[clip]=doc.clips.splice(index,1);doc.clips.splice(args.position,0,clip);doc={...doc,version:doc.version+1};}
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
// Modal controls must never dispatch background timeline edits, including when focus is on a button.
const editKeys=[{key:'ArrowLeft',code:'ArrowLeft',altKey:true},{key:'ArrowRight',code:'ArrowRight',altKey:true},{key:'Delete'},{key:'Backspace'},{key:'q'},{key:'w'},{key:'k',ctrlKey:true},{key:'z',metaKey:true},{key:'z',metaKey:true,shiftKey:true},{key:' ',code:'Space'}];
for(const dialog of document.querySelectorAll('dialog')){
 dialog.setAttribute('open','');
 const target=dialog.querySelector('button')||dialog;
 const before=writes.length;
 for(const key of editKeys){const event=new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,...key});target.dispatchEvent(event);assert.equal(event.defaultPrevented,false,dialog.id+' must keep modal keyboard behavior');}
 await tick();assert.equal(writes.length,before,dialog.id+' must not edit the timeline');dialog.removeAttribute('open');
}
let undoClicks=0;const savedUndoClick=$('undo').click;$('undo').click=()=>{undoClicks++};
const handled=new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'z',metaKey:true});handled.preventDefault();document.body.dispatchEvent(handled);assert.equal(undoClicks,0,'already handled keys must not edit');
document.body.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'z',metaKey:true}));assert.equal(undoClicks,1,'timeline shortcut remains available outside dialogs');$('undo').click=savedUndoClick;
const press=(target=document.body,extra={})=>target.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,code:'KeyO',ctrlKey:true,altKey:true,shiftKey:true,...extra}));
press();press();await tick();assert.equal(messages.length,1);assert.match(messages[0].content[0].text,/open_in_codex/);assert.match(messages[0].content[0].text,new RegExp('project='+doc.project_id));assert.equal(writes.filter(r=>r.name==='update_editor').length,0);
press(document.body,{repeat:true});await tick();assert.equal(messages.length,1);
const input=document.createElement('textarea');document.body.append(input);press(input);await tick();assert.equal(messages.length,1);
press(document.body,{metaKey:true,ctrlKey:false,altKey:false});await tick();assert.equal(messages.length,1,'old native shortcut must not send');
press(document.body,{altKey:false});await tick();assert.equal(messages.length,1,'all modifiers required');
press();await tick();assert.equal(messages.length,2);
reject=true;press();await tick();assert.match($('status').textContent,/host declined/);assert.equal($('openProjectPanel'),null);
await $('compareVersions').onclick();await tick();assert.equal($('compareVersions').getAttribute('aria-pressed'),'true');assert.equal($('comparisonPane').hidden,false);assert.equal($('projects').disabled,true);assert.deepEqual([...$('comparisonVersion').options].map(o=>o.value),['new','source','ffffffffffffffffffffffffffffffff:new','ffffffffffffffffffffffffffffffff:source']);assert.match($('comparisonStatus').textContent,/unavailable/);assert.equal(writes.filter(r=>r.name==='update_editor').length,0);
hasMedia=true;$('comparisonVersion').value='ffffffffffffffffffffffffffffffff:new';await $('comparisonVersion').onchange();await tick();assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.export_id,'e');assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.project_id,'f'.repeat(32));$('comparisonVersion').value='new';await $('comparisonVersion').onchange();await tick();const previous=$('comparisonVideo');assert.match(previous.src,/^blob:/);assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.export_id,'e');
Object.defineProperties(previous,{readyState:{value:2},duration:{value:5}});let plays=0,pauses=0;previous.play=async()=>{plays++};previous.pause=()=>{pauses++};Object.defineProperty(video,'paused',{value:false,configurable:true});video.currentTime=3;video.dispatchEvent(new w.Event('play'));assert.equal(previous.currentTime,3);assert.equal(plays,1);video.currentTime=8;video.dispatchEvent(new w.Event('seeking'));assert.equal(previous.currentTime,5);assert.ok(pauses>0);video.dispatchEvent(new w.Event('pause'));assert.ok(pauses>1);
$('comparisonLinked').checked=false;$('comparisonLinked').onchange();assert.equal(previous.controls,true);assert.equal(video.controls,true);assert.equal(previous.muted,false);
previous.currentTime=4;video.currentTime=1;video.dispatchEvent(new w.Event('seeking'));assert.equal(previous.currentTime,4,'independent preview keeps its own time');const beforePause=pauses;video.dispatchEvent(new w.Event('pause'));assert.equal(pauses,beforePause,'independent playback does not pause other video');
$('comparisonLinked').checked=true;$('comparisonLinked').onchange();assert.equal(previous.currentTime,1);assert.equal(previous.muted,true);
$('comparisonVersion').value='ffffffffffffffffffffffffffffffff:source';await $('comparisonVersion').onchange();await tick();assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.project_id,'f'.repeat(32));assert.equal($('projects').disabled,true,'current project stays locked');
$('comparisonVersion').value='source';await $('comparisonVersion').onchange();await tick();assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.export_id,undefined);
await $('compareVersions').onclick();assert.equal(previous.getAttribute('src'),null);assert.equal($('comparisonPane').hidden,true);assert.equal($('projects').disabled,false);
doc={...doc,clips:[{...clips[0],start:2}],rendered:null};await poll();await tick();failComparison=true;await $('compareVersions').onclick();assert.equal($('comparisonPane').hidden,true);assert.match($('status').textContent,/Could not prepare comparison.*Render failed/);
failComparison=false;await $('compareVersions').onclick();await tick();assert.equal($('comparisonPane').hidden,false);assert.equal(writes.filter(r=>r.name==='read_video_chunk'&&r.args.project_id===doc.project_id&&r.args.export_id==='comparison-export').length,1,'current comparison loads newly rendered timeline');await $('compareVersions').onclick();
await $('closeWorkingProject').onclick();assert.equal(main.hasAttribute('data-project-ready'),false,'closing last project returns to upload prompt');
// Recovery must reload even when the selected project/export did not change.
hasMedia=true;await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();
let reads=writes.filter(r=>r.name==='read_video_chunk').length;
await $('refresh').onclick();await tick();
assert.ok(writes.filter(r=>r.name==='read_video_chunk').length>reads,'Refresh must rebuild unchanged media');
reads=writes.filter(r=>r.name==='read_video_chunk').length;
const restored=new w.Event('pageshow');Object.defineProperty(restored,'persisted',{value:true});w.dispatchEvent(restored);await tick();
assert.ok(writes.filter(r=>r.name==='read_video_chunk').length>reads,'Restoring a suspended tab must rebuild media');
// Reordering preserves the selected source frame and disables impossible moves.
doc={...doc,project_id:'c'.repeat(32),rendered:null,clips:[{id:'first',start:0,end:2},{id:'second',start:2,end:4}],can_undo:true};await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();
$('clipTimeline').querySelectorAll('button')[1].click();video.currentTime=3;await $('moveEarlier').onclick();await tick();
assert.equal(writes.filter(r=>r.name==='move_segment').at(-1).args.clip_id,'second');assert.equal(writes.filter(r=>r.name==='move_segment').at(-1).args.position,0);assert.equal(doc.clips[0].id,'second');assert.equal(video.currentTime,3);assert.equal($('moveEarlier').disabled,true);assert.equal($('moveLater').disabled,false);
await $('moveLater').onclick();await tick();assert.equal(doc.clips[1].id,'second');assert.equal(video.currentTime,3);
document.body.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'ArrowLeft',code:'ArrowLeft',altKey:true}));await tick();assert.equal(doc.clips[1].id,'second','reorder shortcut is not dispatched by the section workflow');
const count=writes.filter(r=>r.name==='move_segment').length;const typing=document.createElement('textarea');document.body.append(typing);typing.dispatchEvent(new w.KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'ArrowRight',code:'ArrowRight',altKey:true}));await tick();assert.equal(writes.filter(r=>r.name==='move_segment').length,count,'typing keeps native word-navigation keys');
// Source end may occur before the timeline end after reordering.
doc={...doc,project_id:'e'.repeat(32),source_duration:8,rendered:null,clips:[{id:'tail',start:4,end:8},{id:'head',start:0,end:4}],can_undo:true};await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();
$('clipTimeline').querySelectorAll('button')[1].click();Object.defineProperty(video,'paused',{value:true,configurable:true});video.currentTime=4;video.ontimeupdate();assert.equal($('clock').textContent,'0:08 / 0:08','logical end remains selected when source ranges meet');assert.equal($('moveEarlier').disabled,false);assert.equal($('moveLater').disabled,true);
// Select the second occurrence when clips share source ranges.
doc={...doc,project_id:'d'.repeat(32),rendered:null,clips:[{id:'first',start:0,end:4},{id:'second',start:0,end:4}],can_undo:true};await appInstance.ontoolresult({structuredContent:{project:structuredClone(doc)}});await tick();
$('clipTimeline').querySelectorAll('button')[1].click();video.currentTime=1;
await $('split').onclick();await tick();
assert.equal(writes.filter(r=>r.name==='split_clip').at(-1).args.clip_id,'second','cut targets the selected repeated source occurrence');
await appInstance.ontoolresult({structuredContent:{project:{...structuredClone(doc),rendered:null,clips:[],can_undo:true}}});await tick();
assert.equal($('play').disabled,true,'empty timeline cannot play deleted source footage');assert.equal(video.hidden,true);assert.match($('empty').textContent,/Undo to restore/);
await appInstance.ontoolresult({structuredContent:{project:{...structuredClone(doc),rendered:null,clips:[{id:'restored',start:1,end:3}],can_undo:true}}});await tick();
assert.equal($('play').disabled,false,'restored timeline can play again');assert.equal(video.hidden,false);
console.log('PASS: automatic current-edit render, failed render blocks misleading comparison, exact project routing, right panel request, duplicate suppression, repeat suppression, typing guard, old shortcut removed and all modifiers required, host rejection, split comparison dropdown, failed and successful media loading, shared play/seek/pause, shorter-version clamp, source selection, cleanup, no project mutation');
await w.happyDOM.abort();
