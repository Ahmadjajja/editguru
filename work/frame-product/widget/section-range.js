// Source seconds are used in both Original and Edited views.
export function validateSectionRange(doc,start,end){
 if(!doc||!Number.isFinite(start)||!Number.isFinite(end))return {error:'Choose both a start and an end.'};
 if(start<0||end>doc.source_duration)return {error:'Keep the range inside the video.'};
 if(end<=start)return {error:'End must be after start.'};
 const clip=doc.clips.find(c=>c.start<=start&&start<c.end);
 if(!clip)return {error:'Start must be inside retained footage.'};
 const lineage=clip.origin_id||clip.id;
 const covered=doc.clips.filter(c=>(c.origin_id||c.id)===lineage).reduce((n,c)=>n+Math.max(0,Math.min(end,c.end)-Math.max(start,c.start)),0);
 if(Math.abs(covered-(end-start))>.00001)return {error:'This range crosses removed footage. Choose a continuous retained section.'};
 return {start,end,clip};
}
