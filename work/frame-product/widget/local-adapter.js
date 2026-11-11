export const applyDocumentTheme=theme=>{document.documentElement.dataset.theme=theme},applyHostStyleVariables=variables=>{for(const [key,value] of Object.entries(variables||{}))if(key.startsWith('--'))document.documentElement.style.setProperty(key,value)};
export class App {
 projectPosterUrl(projectId,exportId){
  if(!/^[a-f0-9]{32}$/.test(projectId)||(exportId&&!/^[a-f0-9]{32}$/.test(exportId)))throw Error('Invalid video id');
  return '/api/quick/projects/'+projectId+'/poster'+(exportId?'?export_id='+exportId:'');
 }
 projectMediaUrl(projectId,exportId){
  if(!/^[a-f0-9]{32}$/.test(projectId)||(exportId&&!/^[a-f0-9]{32}$/.test(exportId)))throw Error('Invalid video id');
  return '/media/'+projectId+(exportId?'/versions/'+exportId+'/edited.mp4':'/input.mp4');
 }

 async uploadStudioAsset(pid,file){
  if(!/^[a-f0-9]{32}$/.test(pid)||!file.size||file.size>700*1024*1024)throw Error('Choose a file up to 700 MB.');
  const response=await fetch('/api/quick/projects/'+pid+'/assets',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file});
  const body=await response.json();if(!response.ok)throw Error(body.error||'Media upload failed.');return body;
 }
 async connect(){const query=new URL(location.href).searchParams,id=query.get('project');this.ontoolresult?.({structuredContent:query.get('create')==='presenter'?{presenter_studio:true}:id?{project_id:id,open_references:query.get('tab')==='references',reference_project_id:query.get('reference')}:{}})}
 getHostContext(){return {theme:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
 getHostCapabilities(){return {}}
 async importReferenceFile(file){
  if(!file.size||file.size>1073741824)throw Error('Choose a reference video up to 1 GiB.');
  const response=await fetch('/upload-reference',{method:'POST',headers:{'Content-Type':'video/mp4','X-Filename':encodeURIComponent(file.name)},body:file});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Reference upload failed.');return result;
 }
 async updateModelContext(message){
  try{const context=JSON.parse(message.content?.find(c=>c.type==='text')?.text||'{}');if(context.home===true){const url=new URL(location.href);url.searchParams.delete('project');url.searchParams.delete('create');history.replaceState(null,'',url)}else if(/^[a-f0-9]{32}$/.test(context.active_project_id)){const url=new URL(location.href);url.searchParams.set('project',context.active_project_id);history.replaceState(null,'',url)}}catch{}
 }
 async requestDisplayMode(){if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}
 async sendMessage(message){
  const text=(message.content||[]).filter(item=>item.type==='text').map(item=>item.text).join('\n');
  if(typeof window.openai?.sendFollowUpMessage==='function')return await window.openai.sendFollowUpMessage({prompt:text,scrollToBottom:false})||{};
  const error=Error('Open Frame as an app in this chat to send directly. Your saved revisions are preserved.');error.code='FRAME_NO_CHAT_HOST';throw error;
 }
 async openLink({url}){if(new URL(url).origin!==location.origin)throw Error('Unexpected download origin');const a=document.createElement('a');a.href=url;if(new URL(url).pathname.startsWith('/frame')){a.target='_blank';a.rel='noopener noreferrer'}else a.download='Frame-export.mp4';a.click()}
 async callServerTool(request){const response=await fetch('/api/frame/tools',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});if(!response.ok)throw Error('Frame request failed: '+response.status);return await response.json()}
}
