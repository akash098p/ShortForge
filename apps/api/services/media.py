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

def _escape_expr(expr:str)->str:
    """Escape commas used inside FFmpeg expressions.

    FFmpeg's filter parser treats an unescaped comma as the separator
    between filters. Functions such as if() and clip() therefore need
    their commas escaped when embedded in a crop filter.
    """
    return expr.replace(",", "\\,")

def _tracked_crop_filter(width:int,height:int,track:list[dict]|None,fps:float=30.0)->str:
    """Build a safe 9:16 crop filter with optional tracked center movement.

    The crop rectangle is always kept inside the source frame.
    """
    target=9/16
    if width/height>=target:
        cw_f=height*target
        ch_f=height
    else:
        cw_f=width
        ch_f=width/target

    cw=max(2,min(width,int(round(cw_f))))
    ch=max(2,min(height,int(round(ch_f))))
    if cw < width and cw % 2: cw-=1
    if ch < height and ch % 2: ch-=1
    max_x=max(0,width-cw)
    max_y=max(0,height-ch)

    if not track:
        x=max_x/2
        y=max_y/2
        return f"crop={cw}:{ch}:{int(round(x))}:{int(round(y))},scale=1080:1920:flags=lanczos,setsar=1"

    pts=sorted(track,key=lambda p:float(p["time"]))

    def expr(axis,limit,crop_size):
        vals=[]
        for p in pts:
            try:
                t=float(p["time"])
                center=float(p[axis])
            except (KeyError,TypeError,ValueError):
                continue
            if not all(map(lambda v: v==v and abs(v)<1e12,(t,center))):
                continue
            raw=center-crop_size/2
            start=max(0.0,min(float(limit),raw))
            vals.append((t,start))

        if not vals:
            return str(float(limit)/2)

        clean=[]
        for t,v in vals:
            if clean and abs(t-clean[-1][0])<1e-6:
                clean[-1]=(t,v)
            else:
                clean.append((t,v))
        vals=clean

        e=f"clip({vals[-1][1]:.3f},0,{float(limit):.3f})"
        if len(vals)==1:
            return _escape_expr(e)

        for i in range(len(vals)-1,0,-1):
            t0,v0=vals[i-1]
            t1,v1=vals[i]
            dt=t1-t0
            if dt<=0:
                continue
            interp=f"clip({v0:.3f}+({v1-v0:.3f})*(t-{t0:.6f})/{dt:.6f},0,{float(limit):.3f})"
            e=f"if(lt(t,{t1:.6f}),{interp},{e})"
        return _escape_expr(e)

    x_expr=expr("x",max_x,cw)
    y_expr=expr("y",max_y,ch)
    return f"crop={cw}:{ch}:{x_expr}:{y_expr},scale=1080:1920:flags=lanczos,setsar=1"

def render_vertical(source:str,output:str,start:float=0,end:float|None=None,zoom:float=1.0,subtitle_file:str|None=None,track:list[dict]|None=None)->None:
    info=ffprobe(source)
    z=max(1.0,min(float(zoom),1.14))
    vf=_tracked_crop_filter(info.width,info.height,track)
    if z!=1.0:
        vf+=f",scale=trunc(iw*{z}/2)*2:trunc(ih*{z}/2)*2,crop=1080:1920"
    if subtitle_file: vf+=f",subtitles={_escape_filter_path(subtitle_file)}"
    cmd=["ffmpeg","-y","-ss",str(start),"-i",source]
    if end is not None: cmd+=["-t",str(max(0,end-start))]
    cmd+=["-vf",vf,"-r","30","-pix_fmt","yuv420p","-c:v","libx264","-preset","medium","-crf","20","-c:a","aac","-b:a","160k","-movflags","+faststart",output]
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
