from dataclasses import dataclass
from pathlib import Path
import subprocess,json,shutil,tempfile

@dataclass
class MediaInfo:
    duration:float
    width:int
    height:int
    fps:float

def ffprobe(path:str)->MediaInfo:
    if not shutil.which("ffprobe"): raise RuntimeError("ffprobe is not installed")
    data=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration:stream=width,height,r_frame_rate","-of","json",path],text=True))
    stream=next(s for s in data["streams"] if "width" in s)
    n,d=stream.get("r_frame_rate","30/1").split("/")
    return MediaInfo(float(data["format"]["duration"]),int(stream["width"]),int(stream["height"]),float(n)/float(d))

def _escape_filter_path(path:str)->str:
    return path.replace("\\","/").replace(":","\\:")

def _tracked_crop_filter(width:int,height:int,track:list[dict]|None,fps:float=30.0)->str:
    target=9/16
    if width/height>=target:
        cw=height*target; ch=height
    else:
        cw=width; ch=width/target
    if not track:
        x=(width-cw)/2; y=(height-ch)/2
        return f"crop={int(cw)}:{int(ch)}:{int(x)}:{int(y)},scale=1080:1920:flags=lanczos"
    # FFmpeg evaluates x/y per frame. Interpolate between tracked points and clamp to valid bounds.
    pts=sorted(track,key=lambda p:float(p["time"]))
    def expr(axis,limit):
        vals=[]
        for p in pts:
            t=float(p["time"]); center=float(p[axis])
            start=max(0,min(limit,center-(cw if axis=="x" else ch)/2))
            vals.append((t,start))
        if len(vals)==1:return str(vals[0][1])
        e=str(vals[-1][1])
        for i in range(len(vals)-1,0,-1):
            t0,v0=vals[i-1]; t1,v1=vals[i]
            if t1<=t0: continue
            e=f"if(lt(t,{t1:.6f}),{v0:.3f}+({v1-v0:.3f})*(t-{t0:.6f})/{t1-t0:.6f},{e})"
        return e
    return f"crop={int(cw)}:{int(ch)}:{expr('x',width-cw)}:{expr('y',height-ch)},scale=1080:1920:flags=lanczos"

def render_vertical(source:str,output:str,start:float=0,end:float|None=None,zoom:float=1.0,subtitle_file:str|None=None,track:list[dict]|None=None)->None:
    info=ffprobe(source)
    z=max(1.0,min(float(zoom),1.14))
    vf=_tracked_crop_filter(info.width,info.height,track)
    if z!=1.0:
        vf+=f",scale=trunc(iw*{z}/2)*2:trunc(ih*{z}/2)*2,crop=1080:1920"
    if subtitle_file: vf+=f",subtitles={_escape_filter_path(subtitle_file)}"
    cmd=["ffmpeg","-y","-ss",str(start),"-i",source]
    if end is not None: cmd+=["-t",str(max(0,end-start))]
    cmd+=["-vf",vf,"-r","30","-pix_fmt","yuv420p","-c:v","libx264","-preset","medium","-crf","18","-c:a","aac","-b:a","192k","-movflags","+faststart",output]
    subprocess.run(cmd,check=True)

def render_plan(source:str,output:str,segments:list[dict],subtitle_file:str|None=None,track:list[dict]|None=None)->None:
    if not segments: raise ValueError("No segments to render")
    work=Path(tempfile.mkdtemp(prefix="shortforge-render-")); parts=[]
    try:
        for i,s in enumerate(segments):
            part=work/f"part-{i:04d}.mp4"
            st=float(s["start"]); en=float(s["end"])
            local=[dict(p,time=float(p["time"])-st) for p in (track or []) if st<=float(p["time"])<=en]
            render_vertical(source,str(part),st,en,float(s.get("zoom",1.0)),subtitle_file,local)
            parts.append(part)
        concat=work/"concat.txt"
        concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts),encoding="utf-8")
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",output],check=True)
    finally:
        shutil.rmtree(work,ignore_errors=True)

def transition_filter(kind: str, duration: float = 0.18) -> str:
    d = max(0.08, min(0.5, float(duration)))
    if kind == "fade":
        return f"fade=t=in:st=0:d={d}"
    if kind == "flash":
        return "eq=brightness=0.04"
    if kind == "zoom":
        return "scale=1120:1992:flags=lanczos,crop=1080:1920"
    return "null"

def apply_transition_metadata(segments: list[dict], beats: list[float] | None = None) -> list[dict]:
    beats = beats or []
    result = []
    for i, segment in enumerate(segments):
        item = dict(segment)
        if i == 0:
            item["transition"] = "none"
        elif item.get("beat_sync"):
            item["transition"] = "zoom" if i % 2 == 0 else "flash"
        elif float(item.get("speech_density", 0)) < 0.35:
            item["transition"] = "fade"
        else:
            item["transition"] = "cut"
        item["transition_duration"] = 0.16 if item["transition"] != "cut" else 0.0
        result.append(item)
    return result
