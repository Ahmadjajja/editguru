export const sectionColors=['#85b7ff','#ba9bff','#64d6bb','#ffb07c','#f38fbd','#d7cf68'];
// Map source intervals onto the visible cut, including sections split by removed footage.
export function visibleSections(pins,clips,duration,edited=false,width=0){
 const spans=[];
 for(const [index,pin] of pins.entries()){
  const segments=edited?clips:[{start:0,end:duration}];let offset=0;
  for(const clip of segments){
   const start=Math.max(pin.start,clip.start),end=Math.min(pin.end??pin.start,clip.end);
   if(pin.end==null?clip.start<=pin.start&&pin.start<clip.end:end>start){
    spans.push({id:pin.id,index,start:offset+start-clip.start,end:offset+end-clip.start,pending:pin.end==null});
   }
   offset+=clip.end-clip.start;
  }
 }
 // Reserve the full visible button footprint, including short ranges and start labels.
 // Process in creation order so a newly added overlapping section takes the next row.
 const lanes=[];
 for(const span of spans){
  let start=span.start,end=span.end;
  if(width>0&&duration>0){
   if(span.pending){
    const size=Math.min(58,width),center=Math.max(size/2,Math.min(width-size/2,width*start/duration));
    start=center-size/2;end=center+size/2;
   }else{
    start=Math.min(width*start/duration,Math.max(0,width-8));
    end=start+Math.max(8,width*(span.end-span.start)/duration);
   }
  }else end=Math.max(end,start+.12);
  let lane=lanes.findIndex(intervals=>intervals.every(prior=>prior.end<=start||end<=prior.start));
  if(lane<0){lane=lanes.length;lanes.push([])}
  span.lane=lane;lanes[lane].push({start,end});
 }

 return {spans,lanes:Math.max(1,lanes.length)};
}

const preciseTime=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${(t%60).toFixed(2).padStart(5,'0')}`;
export function createSectionTimeline({video,getDoc,getSelected,isEdited,onSelect}){
 const $=id=>document.getElementById(id);let key='',spans=[],duration=0,width=0,animation=0,thumbnailGeneration=0,thumbnailSource='',thumbnailVideo=null;
 function ruler(){
  const root=$('timelineRuler');root.replaceChildren();
  const count=Math.max(2,Math.floor(width/64)),target=duration/count;
  const interval=[.25,.5,1,2,5,10,15,30,60,120,300,600,1800,3600].find(n=>n>=target)||3600;
  const times=[];for(let t=0;t<duration;t+=interval)if(duration-t>=interval*.4)times.push(t);times.push(duration);
  for(const t of times){const tick=document.createElement('span'),label=document.createElement('span');tick.className='ruler-tick';tick.style.left=100*t/(duration||1)+'%';label.textContent=duration<60?t.toFixed(t%1?1:0)+'s':Math.floor(t/60)+':'+Math.floor(t%60).toString().padStart(2,'0');tick.append(label);root.append(tick)}
 }
 function updatePlayhead(time){
  const needle=$('sectionPlayhead');needle.style.transform=`translate3d(${Math.max(0,Math.min(1,time/(duration||1)))*width}px,0,0)`;
  needle.setAttribute('aria-valuemax',String(duration));needle.setAttribute('aria-valuenow',String(Math.max(0,time)));needle.setAttribute('aria-valuetext',preciseTime(Math.max(0,time)));
  $('timelineTime').textContent=preciseTime(Math.max(0,time));
 }
 function animate(){cancelAnimationFrame(animation);if(!video.paused){const frame=()=>{updatePlayhead(video.currentTime);if(!video.paused)animation=requestAnimationFrame(frame)};animation=requestAnimationFrame(frame)}}
 async function thumbnails(){
  const src=video.currentSrc;if(!src||src===thumbnailSource)return;
  thumbnailSource=src;const generation=++thumbnailGeneration;
  if(thumbnailVideo){thumbnailVideo.removeAttribute('src');thumbnailVideo.load()}
  const capture=document.createElement('video');thumbnailVideo=capture;capture.muted=true;capture.playsInline=true;capture.preload='auto';
  const box=$('filmstrip');box.replaceChildren();
  const tiles=Array.from({length:10},()=>{const c=document.createElement('canvas');c.width=160;c.height=90;box.append(c);return c});
  const event=name=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>done(Error('Thumbnail timeout')),5000);const finish=()=>done();const fail=()=>done(Error('Thumbnail unavailable'));function done(error){clearTimeout(timer);capture.removeEventListener(name,finish);capture.removeEventListener('error',fail);error?reject(error):resolve()}capture.addEventListener(name,finish,{once:true});capture.addEventListener('error',fail,{once:true})});
  try{
   const loaded=event('loadeddata');capture.src=src;capture.load();await loaded;
   for(let i=0;i<tiles.length;i++){
    if(generation!==thumbnailGeneration)return;
    const sought=event('seeked');capture.currentTime=Math.min(capture.duration-.001,(i+.5)/tiles.length*capture.duration);await sought;
    if(generation!==thumbnailGeneration)return;
    const w=capture.videoWidth,h=capture.videoHeight,scale=Math.max(160/w,90/h),dw=w*scale,dh=h*scale;
    tiles[i].getContext('2d').drawImage(capture,(160-dw)/2,(90-dh)/2,dw,dh);
    tiles[i].dataset.ready='true';
   }
  }catch{/* Filmstrip loading never blocks playback or edits. */}
  finally{capture.removeAttribute('src');capture.load();if(thumbnailVideo===capture)thumbnailVideo=null}
 }
 function render(time=0){
  const doc=getDoc(),edited=isEdited(),clips=doc?.rendered?.clips||[];
  duration=edited?clips.reduce((n,c)=>n+c.end-c.start,0):doc?.source_duration||0;
  const pins=doc?.pins||[],selected=getSelected();
  width=$('timelineSurface').clientWidth;
  const next=JSON.stringify([pins,edited,clips,duration,width]);
  $('sectionOverview').hidden=!doc;
  $('sectionPlayhead').setAttribute('aria-disabled',String($('scrub').disabled));
  if(next!==key){
   key=next;const layout=visibleSections(pins,clips,duration,edited,width);spans=layout.spans;
   const track=$('sectionTrack');track.replaceChildren();track.style.height=layout.lanes*26+'px';track.dataset.rows=String(layout.lanes);
   for(const span of spans){
    const pin=pins[span.index],button=document.createElement('button');button.type='button';
    button.className='section-range'+(span.pending?' pending':'');button.dataset.pin=span.id;button.dataset.row=String(span.lane+1);
    button.style.setProperty('--section-color',sectionColors[span.index%sectionColors.length]);
    button.style.setProperty('--pin-left',100*span.start/duration+'%');
    Object.assign(button.style,{left:`min(${100*span.start/duration}%, calc(100% - 8px))`,width:span.pending?'24px':`max(8px, ${100*(span.end-span.start)/duration}%)`,top:span.lane*26+'px'});
    button.textContent=span.pending?`${span.index+1} · start`:`${span.index+1}`;
    const label=`Section ${span.index+1} · ${pin.start.toFixed(2)}s${span.pending?' · choose an end':'–'+pin.end.toFixed(2)+'s · pinned'}`;
    button.title=label;button.setAttribute('aria-label',label);button.onclick=()=>onSelect(pin);track.append(button);
   }
   width=$('timelineSurface').clientWidth;ruler();
  }
  const complete=pins.filter(p=>p.end!=null).length;
  $('sectionCount').textContent=complete?`${complete} pinned`:'No sections yet';
  const chosen=pins.find(p=>p.id===selected);
  $('sectionSelection').textContent=chosen?`Section ${pins.indexOf(chosen)+1} · ${chosen.start.toFixed(2)}${chosen.end==null?'s → set end':'–'+chosen.end.toFixed(2)+'s'}`:pins.length?'Select a section below the filmstrip':'Scrub the filmstrip to choose a moment';
  $('sectionScaleEnd').textContent=preciseTime(duration);
  updatePlayhead(time);
  for(const button of document.querySelectorAll('.section-range')){
   button.setAttribute('aria-pressed',String(button.dataset.pin===selected));
   button.classList.toggle('at-playhead',spans.some(s=>s.id===button.dataset.pin&&!s.pending&&s.start<=time&&time<s.end));
   button.disabled=!doc||$('projects').disabled;
  }
 }
 const handle=$('sectionPlayhead');
 function seek(event){if($('scrub').disabled)return;const rect=$('timelineSurface').getBoundingClientRect();if(!rect.width)return;video.pause();video.currentTime=Math.max(0,Math.min(duration,(event.clientX-rect.left)/rect.width*duration));updatePlayhead(video.currentTime)}
 handle.onpointerdown=event=>{if(event.button!==0||$('scrub').disabled)return;event.preventDefault();handle.focus({preventScroll:true});handle.setPointerCapture(event.pointerId);seek(event)};
 handle.onpointermove=event=>{if(handle.hasPointerCapture(event.pointerId))seek(event)};
 handle.onpointerup=event=>{if(handle.hasPointerCapture(event.pointerId)){seek(event);handle.releasePointerCapture(event.pointerId)}};
 handle.onkeydown=event=>{if($('scrub').disabled)return;const step=event.shiftKey?1:1/30;let next=video.currentTime;if(event.key==='ArrowLeft')next-=step;else if(event.key==='ArrowRight')next+=step;else if(event.key==='Home')next=0;else if(event.key==='End')next=duration;else return;event.preventDefault();video.pause();video.currentTime=Math.max(0,Math.min(duration,next));updatePlayhead(video.currentTime)};
 new ResizeObserver(()=>{render(video.currentTime||0);ruler()}).observe($('timelineSurface'));
 video.addEventListener('loadeddata',thumbnails);video.addEventListener('play',animate);
 video.addEventListener('pause',()=>{cancelAnimationFrame(animation);updatePlayhead(video.currentTime)});
 window.addEventListener('pagehide',()=>{cancelAnimationFrame(animation);++thumbnailGeneration;if(thumbnailVideo){thumbnailVideo.removeAttribute('src');thumbnailVideo.load()}});
 return {render,updatePlayhead};
}
