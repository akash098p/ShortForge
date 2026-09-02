"use client";
import {useRef,useState} from "react";
import {Upload, WandSparkles, Play, Sparkles, Scissors, Captions, SlidersHorizontal} from "lucide-react";

const presets=["Viral Shorts","Podcast","Cinematic","High Energy"];
export default function Home(){
 const input=useRef<HTMLInputElement>(null); const [video,setVideo]=useState<string|null>(null); const [preset,setPreset]=useState("Viral Shorts");
 const onFile=(f?:File)=>{if(f?.type.startsWith("video/")) setVideo(URL.createObjectURL(f))};
 return <main className="shell">
  <header><div className="brand"><div className="logo">S</div><div><b>ShortForge</b><span>AI SHORT-FORM EDITOR</span></div></div><button className="ghost">Projects</button></header>
  <section className="hero"><div><p className="eyebrow">CREATE • EDIT • EXPORT</p><h1>Turn raw footage into <em>scroll-stopping</em> Shorts.</h1><p className="sub">Smart cuts, dynamic reframing, captions and motion — built for high-quality 9:16 video.</p>
  <button className="primary" onClick={()=>input.current?.click()}><Upload size={18}/> Upload video</button><input ref={input} hidden type="file" accept="video/*" onChange={e=>onFile(e.target.files?.[0])}/></div>
  <div className="stage"><div className="phone">{video?<video src={video} controls autoPlay muted/>:<div className="empty"><WandSparkles size={34}/><strong>Your Short preview</strong><span>Upload footage to begin</span></div>}</div></div></section>
  <section className="workspace"><div className="section-head"><div><p className="eyebrow">AUTO EDIT</p><h2>Choose a starting style</h2></div><button className="auto"><Sparkles size={16}/> Auto Edit</button></div>
  <div className="presets">{presets.map((p,i)=><button key={p} className={preset===p?"preset active":"preset"} onClick={()=>setPreset(p)}><div className="preset-icon">{i===0?<WandSparkles/>:i===1?<Captions/>:i===2?<SlidersHorizontal/>:<Scissors/>}</div><b>{p}</b><span>{i===0?"Fast cuts · captions · zoom":i===1?"Speaker focus · captions":i===2?"Clean · cinematic motion":"Punchy · beat-driven"}</span></button>)}</div>
  <div className="timeline"><div className="timeline-top"><span>Timeline</span><span>{preset}</span></div><div className="track">{video?<div className="clip">SOURCE FOOTAGE</div>:<div className="track-empty">Upload a video to populate the timeline</div>}</div></div></section>
 </main>
}