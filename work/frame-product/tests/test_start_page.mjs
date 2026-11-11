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
let appInstance;let legacyOpen=false;let uploadedRow=null;const openedLinks=[];const session='9'.repeat(32);
let writes=[],fail=false,messages=[],reject=false,hasMedia=false,failComparison=false;
class App{async openLink(value){openedLinks.push(value)}async sendMessage(message){messages.push(message);return {isError:reject}}async connect(){appInstance=this}getHostContext(){return {}}async updateModelContext(){}async callServerTool({name,arguments:args}){
 writes.push({name,args});if(name==='open_editor'&&legacyOpen)return {structuredContent:{status:'Upload footage to ChatGPT to continue with Frame.'}};if(name==='open_editor')return {structuredContent:{home:true,upload_session_id:session,upload_url:'http://127.0.0.1:18966/frame/new?session='+session}};if(name==='get_project'&&uploadedRow?.id===args.project_id)return {structuredContent:{...structuredClone(doc),project_id:uploadedRow.id,work_project:uploadedRow.work_project}};if(name==='project_link')return {structuredContent:{project_id:args.project_id,url:'http://127.0.0.1:18966/frame?project='+args.project_id}};if(name==='list_projects')return {structuredContent:{projects:[{id:doc.project_id,name:doc.name},{id:'f'.repeat(32),name:'Other project'},...(uploadedRow?[uploadedRow]:[])]}};
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
assert.ok($('homeProjectList').querySelector('.open-project-latest'),'saved projects are selectable from the start page');
assert.equal(writes.some(r=>r.name==='read_video_chunk'),false,'listing projects must not open or download a video without selection');

const tick=async()=>{for(let i=0;i<30;i++)await new Promise(r=>setImmediate(r))};
legacyOpen=true;await $('homeAddFootage').onclick();assert.equal(openedLinks.length,0,'legacy response must not open an unscoped upload');assert.match($('homeStatus').textContent,/Reconnect the Frame plugin in this chat/);assert.ok($('homeProjectList').querySelector('.open-project-latest'),'saved project selection remains available');legacyOpen=false;

assert.equal(document.querySelector('dialog[open]'),null);
$('homeProjectList').querySelector('.open-project-latest').click();await tick();
assert.equal(main.hasAttribute('data-project-ready'),true,'explicit selection opens the project');
assert.ok(writes.some(r=>r.name==='read_video_chunk'));
await $('projectHome').onclick();await tick();assert.equal(main.hasAttribute('data-project-ready'),false);
await $('homeAddFootage').onclick();await tick();
assert.equal(openedLinks.length,1);assert.equal(new URL(openedLinks[0].url).searchParams.get('session'),session);
assert.equal($('homeResumeUpload').hidden,false);
await $('homeResumeUpload').onclick();assert.equal(openedLinks[1].url,openedLinks[0].url,'reopen retains the same upload request');
uploadedRow={id:'d'.repeat(32),name:'Unrelated upload',work_project:{upload_session_id:'8'.repeat(32)}};
await poll();await tick();assert.equal(main.hasAttribute('data-project-ready'),false,'another panel upload is never opened by recency');
uploadedRow={...uploadedRow,name:'My new footage',work_project:{id:'d'.repeat(32),upload_session_id:session}};
await poll();await tick();assert.equal(main.hasAttribute('data-project-ready'),true,'the matching upload opens in its originating panel');
assert.equal(writes.filter(r=>r.name==='read_video_chunk').at(-1).args.project_id,uploadedRow.id);
console.log('PASS: selectable project home, no automatic recency selection, direct upload link, same-session retry, and exact originating-panel handoff');await w.happyDOM.abort();
