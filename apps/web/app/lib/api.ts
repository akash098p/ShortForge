const API_BASE=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";

export async function uploadVideo(file:File){
 const body=new FormData(); body.append("file",file);
 const r=await fetch(API_BASE+"/v1/upload",{method:"POST",body});
 if(!r.ok) throw new Error(await r.text()); return r.json() as Promise<{source_path:string;source_name:string}>;
}
export async function createEditPlan(input:{sourceName:string;sourcePath:string;duration:number;width:number;height:number;fps:number;preset:string}){
 const r=await fetch(API_BASE+"/v1/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:input.sourceName,source_path:input.sourcePath,duration:input.duration,width:input.width,height:input.height,fps:input.fps,preset:input.preset})});
 if(!r.ok) throw new Error(await r.text()); return r.json();
}
