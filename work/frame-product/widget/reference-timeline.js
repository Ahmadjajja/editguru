const clock=t=>`${Math.floor((t||0)/60).toString().padStart(2,'0')}:${((t||0)%60).toFixed(2).padStart(5,'0')}`;
export function validClipRange(start,end,duration){return Number.isFinite(start)&&Number.isFinite(end)&&Number.isFinite(duration)&&start>=0&&end>start&&end<=duration}
// Same filmstrip, ruler, frame stepping and playhead interaction as the editor timeline.
export function createReferenceTimeline({root,video,onRangeChange}){
 const make=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls;if(text)e.textContent=text;return e};
 const header=make('div','section-overview-header'),title=make('strong','timeline-heading','Reference timeline'),time=make('span','',clock(0));header.append(title,time);
 const surface=make('div','clip-timeline-surface'),ruler=make('div','clip-timeline-ruler'),strip=make('div','clip-filmstrip'),head=make('span','clip-playhead'),track=make('div','clip-range-track'),band=make('div','clip-range-band'),startHandle=make('button','clip-range-handle clip-range-start','['),endHandle=make('button','clip-range-handle clip-range-end',']'),summary=make('div','timeline-footer');
 strip.tabIndex=0;strip.setAttribute('role','slider');strip.setAttribute('aria-label','Reference timeline playhead');strip.setAttribute('aria-valuemin','0');
 startHandle.type=endHandle.type='button';startHandle.setAttribute('role','slider');endHandle.setAttribute('role','slider');startHandle.setAttribute('aria-label','Reference range start');endHandle.setAttribute('aria-label','Reference range end');
 track.append(band,startHandle,endHandle);surface.append(ruler,strip,head,track);root.classList.add('clip-timeline','section-overview');root.append(header,surface,summary);
 let duration=0,start=0,end=0,enabled=false,generation=0,capture=null,animation=0,source='';
 function paint(){
  const percent=t=>100*Math.max(0,Math.min(1,t/(duration||1)))+'%';
  head.style.left=percent(video.currentTime);time.textContent=clock(video.currentTime);strip.setAttribute('aria-valuemax',String(duration));strip.setAttribute('aria-valuenow',String(video.currentTime||0));strip.setAttribute('aria-valuetext',clock(video.currentTime));strip.setAttribute('aria-disabled',String(!enabled));
  band.style.left=startHandle.style.left=percent(start);band.style.width=percent(Math.max(0,end-start));endHandle.style.left=percent(end);
  for(const [el,value] of [[startHandle,start],[endHandle,end]]){el.disabled=!enabled;el.setAttribute('aria-valuemin','0');el.setAttribute('aria-valuemax',String(duration));el.setAttribute('aria-valuenow',String(value));el.setAttribute('aria-valuetext',clock(value))}
  summary.textContent=duration?`${clock(start)} → ${clock(end)} · ${Math.max(0,end-start).toFixed(3)} seconds`:'Load a project video to select a section';
 }
 function drawRuler(){ruler.replaceChildren();const width=surface.clientWidth||500,target=duration/Math.max(2,Math.floor(width/64)),step=[.25,.5,1,2,5,10,15,30,60,120,300,600,1800,3600].find(t=>t>=target)||3600;
  const times=[];for(let t=0;t<duration;t+=step)if(duration-t>step*.4)times.push(t);times.push(duration);
  for(const t of times){const tick=make('span','ruler-tick'),text=make('span','',duration<60?`${+t.toFixed(1)}s`:clock(t));tick.style.left=100*t/(duration||1)+'%';tick.append(text);ruler.append(tick)}
 }
 function seek(t){if(!enabled)return;video.pause();video.currentTime=Math.max(0,Math.min(duration,t));paint()}
 function at(event){const r=strip.getBoundingClientRect();return Math.max(0,Math.min(duration,(event.clientX-r.left)/(r.width||1)*duration))}
 function move(which,t){t=Math.round(t*1000)/1000;const step=Math.min(1/30,duration);if(which==='start')start=Math.max(0,Math.min(end-step,t));else end=Math.max(start+step,Math.min(duration,t));onRangeChange(start,end);seek(which==='start'?start:end);paint()}
 function pointer(el,which){el.onpointerdown=e=>{if(e.button!==0||!enabled)return;e.preventDefault();el.focus({preventScroll:true});el.setPointerCapture(e.pointerId);which?move(which,at(e)):seek(at(e))};el.onpointermove=e=>{if(el.hasPointerCapture(e.pointerId)){which?move(which,at(e)):seek(at(e))}};el.onpointerup=e=>{if(el.hasPointerCapture(e.pointerId)){which?move(which,at(e)):seek(at(e));el.releasePointerCapture(e.pointerId)}};
  el.onkeydown=e=>{if(!enabled)return;let value=which==='start'?start:which==='end'?end:video.currentTime,step=e.shiftKey?1:1/30;if(e.key==='ArrowLeft')value-=step;else if(e.key==='ArrowRight')value+=step;else if(e.key==='Home')value=0;else if(e.key==='End')value=duration;else return;e.preventDefault();which?move(which,value):seek(value)};
 }
 pointer(strip);pointer(startHandle,'start');pointer(endHandle,'end');
 function animate(){cancelAnimationFrame(animation);const frame=()=>{paint();if(!video.paused)animation=requestAnimationFrame(frame)};frame()}
 video.addEventListener('timeupdate',paint);video.addEventListener('seeked',paint);video.addEventListener('play',animate);video.addEventListener('pause',()=>{cancelAnimationFrame(animation);paint()});
 const resize=new ResizeObserver(drawRuler);resize.observe(surface);
 async function thumbnails(src){
  if(!src||source===src)return;source=src;const token=++generation;const v=document.createElement('video');capture=v;v.muted=true;v.playsInline=true;v.preload='auto';
  const tiles=Array.from({length:10},()=>{const canvas=make('canvas','');canvas.width=160;canvas.height=90;return canvas});strip.replaceChildren(...tiles);
  const event=name=>new Promise((resolve,reject)=>{const timeout=setTimeout(()=>finish(Error('Thumbnail timeout')),7000);const ok=()=>finish(),fail=()=>finish(Error('Thumbnail unavailable'));function finish(error){clearTimeout(timeout);v.removeEventListener(name,ok);v.removeEventListener('error',fail);error?reject(error):resolve()}v.addEventListener(name,ok,{once:true});v.addEventListener('error',fail,{once:true})});
  try{const ready=event('loadeddata');v.src=src;v.load();await ready;
   for(const [i,c] of tiles.entries()){if(token!==generation)return;const sought=event('seeked');v.currentTime=Math.max(0,Math.min(v.duration-.001,(i+.5)/tiles.length*v.duration));await sought;if(token!==generation)return;const scale=Math.max(160/v.videoWidth,90/v.videoHeight),w=v.videoWidth*scale,h=v.videoHeight*scale;c.getContext('2d').drawImage(v,(160-w)/2,(90-h)/2,w,h);c.dataset.ready='true'}
  }catch{/* Playback remains available when a thumbnail cannot be decoded. */}finally{v.removeAttribute('src');v.load();if(capture===v)capture=null}
 }
 return {setRange(a,b){start=a;end=b;paint()},ready(src,seconds){duration=seconds;enabled=true;drawRuler();paint();void thumbnails(src)},setEnabled(value){enabled=value;paint()},seek,
  reset(){++generation;source='';if(capture){capture.removeAttribute('src');capture.load();capture=null}cancelAnimationFrame(animation);duration=0;start=end=0;enabled=false;strip.replaceChildren();drawRuler();paint()},destroy(){this.reset();resize.disconnect()}};
}
