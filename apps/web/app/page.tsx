"use client";
import {useRef,useState} from "react";
import {Upload,WandSparkles,Sparkles,Scissors,Captions,SlidersHorizontal,CheckCircle2,Loader2} from "lucide-react";
import {readVideoMetadata,makeSmartCrop} from "./lib/video";
import {createEditPlan,uploadVideo,renderEditPlan} from "./lib/api";
type Preset={id:string;name:string;desc:string;icon:any};
const presets:Preset[]=[
{id:"viral",name:"Viral Shorts",desc:"Fast cuts · captions · zoom",icon:WandSparkles},
{id:"podcast",name:"Podcast",desc:"Speaker focus · captions",icon:Captions},
{id:"cinematic",name:"Cinematic",desc:"Clean · cinematic motion",icon:SlidersHorizontal},
{id:"energy",name:"High Energy",desc:"Punchy · beat-driven",icon:Scissors}
];
export default function Home(){
 const input=useRef<HTMLInputElement>(null); const [video,setVideo]=useState<string|null>(null); const [file,setFile]=useState<File|null>(null); const [meta,setMeta]=useState<any>(null); const [preset,setPreset]=useState("viral"); const [status,setStatus]=useState("idle"); const [sourcePath,setSourcePath]=useState<string|null>(null); const [error,setError]=useState<string|null>(null); const [drag,setDrag]=useState(false); const [plan,setPlan]=useState<any>(null); const [rendered,setRendered]=useState<string|null>(null);
 const onFile=async(f?:File)=>{if(!f?.type.startsWith("video/"))return;setFile(f);setVideo(URL.createObjectURL(f));setMeta(await readVideoMetadata(f));setStatus("uploading");setError(null);try{const uploaded=await uploadVideo(f);setSourcePath(uploaded.source_path);setStatus("ready")}catch(e){setStatus("error");setError(e instanceof Error?e.message:"Upload failed")}};
 const autoEdit=async()=>{if(!meta||!file||!sourcePath)return;setStatus("analyzing");setError(null);try{const result=await createEditPlan({sourceName:file.name,sourcePath,...meta,preset});setPlan(result);setStatus("complete")}catch(e){setStatus("error");setError(e instanceof Error?e.message:"Analysis failed")}};
 const renderShort=async()=>{if(!plan||!sourcePath)return;setStatus("rendering");setError(null);try{const result=await renderEditPlan({sourcePath,segments:plan.segments||[],captions:plan.captions||[],reframe:plan.reframe||[],preset});setRendered((result.preview_url?.startsWith("http")?result.preview_url:"http://localhost:8000"+result.preview_url));setStatus("rendered")}catch(e){setStatus("error");setError(e instanceof Error?e.message:"Render failed")}};
 const onDrop=(e:React.DragEvent)=>{e.preventDefault();setDrag(false);onFile(e.dataTransfer.files?.[0])};
 const crop=meta?makeSmartCrop(meta.width,meta.height):null;
 return <main className="shell">
  <header><div className="brand"><div className="logo">S</div><div><b>ShortForge</b><span>AI SHORT-FORM EDITOR</span></div></div><button className="ghost">Projects</button></header>
  <section className="hero"><div><p className="eyebrow">CREATE • EDIT • EXPORT</p><h1>Turn raw footage into <em>scroll-stopping</em> Shorts.</h1><p className="sub">Smart cuts, dynamic reframing, captions and motion — built for high-quality 9:16 video.</p>
  <div className="actions"><button className="primary" onClick={()=>input.current?.click()}><Upload size={18}/> {file?"Replace video":"Upload video"}</button>{file&&<button className="secondary" onClick={autoEdit}>{status==="analyzing"?<><Loader2 className="spin" size={17}/> Analyzing…</>:status==="complete"?<><CheckCircle2 size={17}/> Edit plan ready</>:status==="rendering"?<><Loader2 className="spin" size={17}/> Rendering…</>:status==="rendered"?<><CheckCircle2 size={17}/> Render complete</>:status==="error"?<><Sparkles size={17}/> Retry Auto Edit</>:<><Sparkles size={17}/> Auto Edit</>}</button>}</div>
  {status==="complete"&&<button className="secondary" onClick={renderShort}><Sparkles size={17}/> Render Short</button>}{status==="rendering"&&<div className="meta">Rendering your Short…</div>}{status==="rendered"&&rendered&&<div className="result"><p className="eyebrow">RESULT</p><h2>Rendered Short</h2><video src={rendered} controls autoPlay playsInline/><a className="secondary" href={rendered} download="shortforge-short.mp4">Download Short</a></div>}{error&&<div className="meta">{error}</div>}
  <input ref={input} hidden type="file" accept="video/*" onChange={e=>onFile(e.target.files?.[0])}/>{meta&&<div className="meta">{Math.round(meta.duration*10)/10}s · {meta.width}×{meta.height} · 9:16 crop {crop?.width}×{crop?.height}</div>}</div>
  <div className="stage"><div className={"phone dropzone "+(drag?"drag":"")} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={onDrop}>{video?<video src={video} controls autoPlay muted/>:<div className="empty"><WandSparkles size={34}/><strong>Your Short preview</strong><span>Upload footage to begin</span></div>}</div></div></section>
  <section className="workspace"><div className="section-head"><div><p className="eyebrow">AUTO EDIT</p><h2>Choose a starting style</h2></div></div>
  <div className="presets">{presets.map(p=>{const Icon=p.icon;return <button key={p.id} className={preset===p.id?"preset active":"preset"} onClick={()=>setPreset(p.id)}><div className="preset-icon"><Icon/></div><b>{p.name}</b><span>{p.desc}</span></button>})}</div>
  <div className="timeline"><div className="timeline-top"><span>Timeline</span><span>{presets.find(p=>p.id===preset)?.name}</span></div><div className="track">{file?<div className="clip" style={{width:"100%"}}><span>SOURCE FOOTAGE</span>{status==="complete"&&<small>AUTO EDIT PLAN READY</small>}</div>:<div className="track-empty">Upload a video to populate the timeline</div>}</div></div></section>
 </main>
}