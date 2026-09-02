const API_BASE=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
export async function createEditPlan(input:{sourceName:string;duration:number;width:number;height:number;fps:number;preset:string}){
 const r=await fetch(API_BASE+"/v1/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:input.sourceName,duration:input.duration,width:input.width,height:input.height,fps:input.fps,preset:input.preset})});
 if(!r.ok) throw new Error(await r.text()); return r.json();
}