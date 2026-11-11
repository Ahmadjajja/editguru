import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { Window } from 'happy-dom';

const root = new URL('..',import.meta.url).pathname;
const PID='a'.repeat(32), V1='b'.repeat(32), V2='c'.repeat(32), SID='d'.repeat(32);
const clone=value=>JSON.parse(JSON.stringify(value));
const flush=()=>new Promise(resolve=>setTimeout(resolve,35));
const quote=()=>({quote_id:'test-quote',total_credits:42,available_credits:100,has_sufficient_balance:true,created_at:Date.now()/1000,expires_at:Date.now()/1000+900});
const result=(vid=V1)=>({url:`/frame-media/${PID}/${vid}/export.mp4`,poster_url:`/frame-media/${PID}/${vid}/poster.jpg`,duration:9.2,width:720,height:1280,frames:276,voice_provider:'fish-mcp',summary:'Let the quiet opening lead to a confident payoff.',warnings:[]});
function project(status='complete') {
  return {id:PID,name:'A real creative project.',idea:'Make a confident introduction.',script:'A real creative project.',status,stage:status==='complete'?'Video ready to review':'Finding the direction',error:null,active_version_id:V1,current_version_id:status==='complete'?V1:null,versions:[{id:V1,number:1,status,summary:'Let the quiet opening lead to a confident payoff.',feedback:'',error:null,result:status==='complete'?result():null,quote:status==='awaiting_quote'?quote():null}]};
}
async function app({initial=null,stored=null,fish=true,url='http://127.0.0.1:8780/',intercept=null,fastPoll=false}={}) {
  const w=new Window({url,settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}});
  w.document.write(fs.readFileSync(root+'/frame.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,''));
  w.HTMLMediaElement.prototype.load=function(){}; w.HTMLMediaElement.prototype.pause=function(){};
  if (stored) w.localStorage.setItem('frame-product-state-v1',JSON.stringify(stored));
  const oldTimeout=w.setTimeout.bind(w);
  if(fastPoll) w.setTimeout=(callback,ms,...args)=>oldTimeout(callback,ms>=1400&&ms<=15000?15:ms,...args);
  const q=s=>w.document.querySelector(s), requests=[];
  let current=initial?clone(initial):null, posts=0, readCount=0;
  w.fetch=async(path,opts={})=>{
    const body=opts.body?JSON.parse(opts.body):null;
    requests.push({path,body,method:opts.method||'GET'});
    const special=await intercept?.({path,body,opts,index:requests.length,current,setCurrent:value=>{current=clone(value);}});
    if(special==='throw') throw new Error('Simulated connection loss');
    if(special?.error) return {ok:false,status:special.status||400,json:async()=>({error:special.error})};
    if(special?.data) return {ok:true,json:async()=>clone(special.data)};
    let data;
    if(path==='/api/frame/config') data={fish_ready:fish,voice_name:'Adrian',default_provider:'fish-mcp',limits:{script_chars:1800,script_words:80,seconds:60},demo_studio_id:SID,existing_studio:[{id:SID,name:'Saved narration'}]};
    else if(path==='/api/frame/projects') data=current?[{id:current.id,name:current.name,status:current.status,created:1}]:[];
    else if(path===`/api/frame/projects/${PID}`) { readCount++; data=current; }
    else if(path==='/api/frame/generate') { posts++; current=project(body.provider==='edge'?'complete':'awaiting_quote'); current.script=body.script; current.idea=body.idea; data=current; }
    else if(path==='/api/frame/import') { posts++; current=project('complete');data=current; }
    else if(path.endsWith('/render')) { posts++;current.status='complete';current.current_version_id=V1;current.versions[0].status='complete';current.versions[0].result=result();data=current; }
    else if(path.endsWith('/quote')) { posts++;current.status='awaiting_quote';current.versions.at(-1).status='awaiting_quote';current.versions.at(-1).quote=quote();data=current; }
    else if(path.endsWith('/retry')) { posts++;current.status='rendering';current.versions.at(-1).status='rendering';data=current; }
    else if(path.endsWith('/revise')) { posts++;current.status='rendering';current.active_version_id=V2;current.versions.push({id:V2,number:2,status:'rendering',feedback:body.feedback,summary:null,result:null,error:null});data=current; }
    else throw new Error(`Unexpected request ${path}`);
    return {ok:true,status:200,json:async()=>clone(data)};
  };
  vm.createContext(w);vm.runInContext(fs.readFileSync(root+'/frame.js','utf8'),w);await flush();
  return {w,q,requests,get current(){return current;},get posts(){return posts;},get readCount(){return readCount;},set current(value){current=clone(value);},input(selector,value){q(selector).value=value;q(selector).dispatchEvent(new w.Event('input'));},submit(selector){q(selector).dispatchEvent(new w.Event('submit',{cancelable:true}));},async close(){await w.happyDOM.close();}};
}

{
  const a=await app();
  assert.equal(a.posts,0,'initial load must not generate or spend credits');
  assert.equal(a.q('#quotePanel').hidden,true);assert.equal(a.q('#resultPanel').hidden,true);
  assert.equal(a.q('#voiceOptions').open,false);assert.equal(a.q('#demoButton').hidden,false);
  assert.equal(a.q('#provider').value,'edge');assert.equal(a.q('#generateButton').disabled,false);
  assert.equal(a.q('#provider').options.length,2,'both explicit narrator choices must parse as options');
  assert.equal(a.q('#feedback').closest('#projectState').hidden,true,'initial page exposes only the brief');
  a.q('#provider').value='fish-mcp';a.q('#provider').dispatchEvent(new a.w.Event('change'));
  a.input('#idea','Explain one useful idea.');a.input('#script','Here is one useful idea.');
  a.submit('#briefForm');await flush();
  assert.equal(a.q('#quotePanel').hidden,false);assert.equal(a.q('#confirmRender').disabled,false);
  assert.match(a.q('#quoteSummary').textContent,/script and vocal direction are ready/);
  assert.doesNotMatch(a.q('#quoteSummary').textContent,/quiet opening|confident payoff/,'unpublished Studio visual rationale must not describe the final compositor');
  assert.match(a.q('.intro-copy').textContent,/bold type, and motion graphics/);
  assert.equal(a.requests.filter(r=>r.path.endsWith('/render')).length,0,'planning and quoting must not spend credits');
  assert.match(a.q('#creditCost').textContent,/42/);assert.equal(a.q('#script').disabled,true);
  assert.equal(new URL(a.w.location.href).searchParams.get('project'),PID);
  a.q('#confirmRender').click();await flush();
  assert.equal(a.requests.filter(r=>r.path.endsWith('/render')).length,1);
  assert.deepEqual(a.requests.find(r=>r.path.endsWith('/render')).body,{version_id:V1,quote_id:'test-quote'});
  assert.equal(a.q('#resultPanel').hidden,false);assert.equal(a.q('#quotePanel').hidden,true);
  assert.equal(a.q('#video').hasAttribute('autoplay'),false);
  assert.match(a.q('#downloadLink').href,/export\.mp4$/);assert.match(a.q('#videoMeta').textContent,/Fish Audio/);
  assert.equal(a.q('#reviseButton').disabled,true);a.input('#feedback','Make the opening quieter.');assert.equal(a.q('#reviseButton').disabled,false);
  a.submit('#revisionForm');await flush();
  assert.equal(a.q('#resultPanel').hidden,false,'prior completed cut remains while revision works');
  assert.equal(a.q('#progressRegion').hidden,false);assert.equal(a.q('#reviseButton').disabled,true);
  assert.equal(a.q('#video').dataset.source,`http://127.0.0.1:8780/frame-media/${PID}/${V1}/export.mp4`);
  assert.deepEqual(Object.keys(a.requests.find(r=>r.path.endsWith('/revise')).body).sort(),['base_version_id','feedback','request_id']);
  await a.close();
}
{
  const a=await app({fish:false});
  assert.equal(a.q('#generateButton').disabled,false);assert.equal(a.q('#connectFish').hidden,true);
  assert.equal(a.q('#provider').value,'edge','pilot defaults to preview voice');
  a.q('#provider').value='edge';a.q('#provider').dispatchEvent(new a.w.Event('change'));
  assert.equal(a.q('#generateButton').disabled,false);assert.match(a.q('#costNote').textContent,/Edge/);
  a.input('#script','A short preview.');a.submit('#briefForm');await flush();
  assert.equal(a.requests.find(r=>r.path==='/api/frame/generate').body.provider,'edge');
  assert.equal(a.requests.filter(r=>r.path.endsWith('/render')).length,0);
  await a.close();
}
for(const invalid of ['expired','balance']) {
  const fixture=project('awaiting_quote');
  if(invalid==='expired') fixture.versions[0].quote.expires_at=Date.now()/1000-1;
  else fixture.versions[0].quote.has_sufficient_balance=false;
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`});
  assert.equal(a.q('#confirmRender').disabled,true);a.q('#confirmRender').click();assert.equal(a.posts,0);
  assert.match(a.q('#quoteDetail').textContent,invalid==='expired'?/expired/:/does not cover/);
  a.q('#refreshQuote').click();await flush();assert.equal(a.q('#confirmRender').disabled,false);
  assert.equal(a.requests.filter(r=>r.path.endsWith('/render')).length,0);await a.close();
}
{
  const a=await app();a.q('#demoButton').click();await flush();
  assert.equal(a.requests.filter(r=>r.path==='/api/frame/import').length,1);
  assert.equal(a.requests.filter(r=>r.path==='/api/frame/generate'||r.path.endsWith('/render')).length,0);
  assert.equal(a.q('#resultPanel').hidden,false);
  a.q('#newProject').click();assert.equal(a.q('#script').value,'');assert.equal(a.q('#resultPanel').closest('#projectState').hidden,true);assert.equal(a.q('#provider').value,'edge');
  await a.close();
}
{
  let losses=0;
  const a=await app({intercept:({path})=>{if(path==='/api/frame/generate'&&losses++===0)return 'throw';}});
  a.input('#script','A saved request.');a.submit('#briefForm');await flush();
  assert.equal(a.q('#connectionNotice').hidden,false);assert.equal(a.q('#script').disabled,true);
  const request=clone(a.requests.find(r=>r.path==='/api/frame/generate').body);
  const saved=JSON.parse(a.w.localStorage.getItem('frame-product-state-v1'));
  assert.equal(saved.request.body.request_id,request.request_id);
  a.q('#reconnectButton').click();await flush();
  const generations=a.requests.filter(r=>r.path==='/api/frame/generate');
  assert.equal(generations.length,2);assert.deepEqual(generations[0].body,generations[1].body,'recovery reuses identical inputs and idempotency key');
  assert.equal(a.q('#connectionNotice').hidden,true);assert.equal(JSON.parse(a.w.localStorage.getItem('frame-product-state-v1')).request,null);
  await a.close();
  const restored=await app({stored:saved});
  assert.equal(restored.q('#connectionNotice').hidden,false);assert.equal(restored.posts,0,'reload must not automatically resubmit an unconfirmed generation');
  restored.q('#reconnectButton').click();await flush();assert.equal(restored.requests.find(r=>r.path==='/api/frame/generate').body.request_id,request.request_id);await restored.close();
}
{
  let lost=false;
  const fixture=project('awaiting_quote');
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`,intercept:({path,setCurrent})=>{if(path.endsWith('/render')&&!lost){lost=true;setCurrent(project('complete'));return 'throw';}}});
  a.q('#confirmRender').click();await flush();
  assert.equal(a.requests.filter(r=>r.path.endsWith('/render')).length,1,'lost paid response only reconciles via GET');
  assert.equal(a.q('#resultPanel').hidden,false);assert.equal(a.q('#quotePanel').hidden,true);
  await a.close();
}
{
  const a=await app({intercept:({path})=>path==='/api/frame/generate'?{data:{accepted:true}}:null});
  a.input('#script','Keep my accepted request.');a.submit('#briefForm');await flush();
  assert.equal(a.q('#connectionNotice').hidden,false);
  assert.ok(JSON.parse(a.w.localStorage.getItem('frame-product-state-v1')).request?.body?.request_id,'malformed successful response retains its idempotency key');
  assert.equal(a.q('#generateButton').disabled,true);await a.close();
}
{
  const a=await app();a.input('#script',Array(81).fill('word').join(' '));a.submit('#briefForm');await flush();
  assert.equal(a.posts,0);assert.match(a.q('#globalError').textContent,/80 words/);assert.match(a.q('#scriptCount').textContent,/81 \/ 80/);await a.close();
}
{
  const fixture=project('complete');fixture.name='<img src=x onerror=alert(1)>';fixture.versions[0].summary='<script>bad()</script>';fixture.versions[0].result.url='javascript:alert(1)';
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`});
  assert.equal(a.q('#directionSummary').textContent,'<script>bad()</script>');assert.equal(a.q('#directionSummary script'),null);
  assert.equal(a.q('#recentProjects img'),null);assert.equal(a.q('#downloadLink').hasAttribute('href'),false);
  assert.equal(a.q('#video').hasAttribute('src'),false);await a.close();
}
{
  const fixture=project('complete');fixture.versions[0].result.warnings=[
    'Fish MCP does not expose numeric volume control; the requested dB change was not applied.',
    'Selected phrases use a smooth +1.5 dB gain accent at measured word boundaries.',
    'Scene 2: measured captions differ from the script. Review the spoken words before publishing.',
    'The recording reaches full scale and may contain clipped audio; it has not been repaired.',
    '<img src=x onerror=alert(1)> Technical note.'
  ];
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`});
  assert.equal(a.q('#warnings').hidden,false);assert.equal(a.q('#warnings details').open,false,'technical notes stay collapsed initially');
  assert.equal(a.q('#warnings summary').textContent,'Narration notes');
  assert.equal(a.w.document.querySelectorAll('#warnings > p').length,2,'script mismatch and clipping remain visibly surfaced');
  assert.match(a.q('#warnings > p').textContent,/captions differ/);
  assert.equal(a.w.document.querySelectorAll('#warnings details p').length,3);
  assert.equal(a.q('#warnings img'),null,'collapsed notes remain escaped text');await a.close();
}
{
  let reads=0;
  const fixture=project('rendering');
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`,fastPoll:true,intercept:({path,setCurrent})=>{
    if(path===`/api/frame/projects/${PID}`){reads++;if(reads===2)return 'throw';if(reads>=3){const ready=project('complete');setCurrent(ready);return {data:ready};}}
  }});
  await new Promise(resolve=>setTimeout(resolve,150));
  assert.ok(reads>=3);assert.equal(a.q('#resultPanel').hidden,false);assert.equal(a.q('#connectionNotice').hidden,true);
  assert.equal(a.posts,0,'polling retry must not resubmit generation');await a.close();
}
{
  const fixture=project('complete');fixture.versions.push({...fixture.versions[0],id:V2,number:2,feedback:'Quieter.',result:result(V2)});fixture.current_version_id=V2;fixture.active_version_id=V2;
  const a=await app({initial:fixture,url:`http://127.0.0.1:8780/?project=${PID}`});
  assert.equal(a.q('#versionSelect').value,V2);a.q('#versionSelect').value=V1;a.q('#versionSelect').dispatchEvent(new a.w.Event('change'));
  assert.match(a.q('#video').src,new RegExp(V1));a.input('#feedback','Try another composition.');a.submit('#revisionForm');await flush();
  assert.equal(a.requests.find(r=>r.path.endsWith('/revise')).body.base_version_id,V1,'revision uses the selected version rather than silently latest');await a.close();
}
console.log('Frame UI passed: explicit credit gates, provider choice, saved-demo import, immutable versions, escaped output, idempotent recovery, reload recovery, transient polling, script limits, and visual revision flow.');
