from dataclasses import dataclass
from pathlib import Path
import subprocess, json, shutil

@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float

def ffprobe(path: str) -> MediaInfo:
    if not shutil.which("ffprobe"): raise RuntimeError("ffprobe is not installed")
    data=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration:stream=width,height,r_frame_rate","-of","json",path],text=True))
    stream=next(s for s in data.get("streams",[]) if "width" in s)
    n,d=stream.get("r_frame_rate","30/1").split("/")
    return MediaInfo(float(data["format"]["duration"]),int(stream["width"]),int(stream["height"]),float(n)/float(d))

def vertical_filter(zoom:float=1.0)->str:
    z=max(1.0,min(float(zoom),1.14))
    return f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=trunc(iw*{z}/2)*2:trunc(ih*{z}/2)*2,crop=1080:1920"

def render_vertical(source:str,output:str,start:float=0,end:float|None=None,zoom:float=1.0,subtitle_file:str|None=None)->None:
    if not shutil.which("ffmpeg"): raise RuntimeError("ffmpeg is not installed")
    vf=vertical_filter(zoom)
    if subtitle_file:
        vf += f",subtitles={subtitle_file.replace(chr(92),'/').replace(':','\\:')}"
    cmd=["ffmpeg","-y","-ss",str(start),"-i",source]
    if end is not None: cmd += ["-t",str(max(0,end-start))]
    cmd += ["-vf",vf,"-r","30","-pix_fmt","yuv420p","-c:v","libx264","-preset","medium","-crf","18","-c:a","aac","-b:a","192k","-movflags","+faststart",output]
    subprocess.run(cmd,check=True)

def render_plan(source:str,output:str,segments:list[dict],subtitle_file:str|None=None)->None:
    if not segments: raise ValueError("No segments to render")
    work=Path("/tmp/shortforge-render"); work.mkdir(parents=True,exist_ok=True)
    parts=[]
    try:
        for i,s in enumerate(segments):
            part=work/f"part-{i:04d}.mp4"
            render_vertical(source,str(part),float(s["start"]),float(s["end"]),float(s.get("zoom",1.0)),subtitle_file)
            parts.append(part)
        concat=work/"concat.txt"; concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts),encoding="utf-8")
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",output],check=True)
    finally:
        for p in parts: p.unlink(missing_ok=True)
        (work/"concat.txt").unlink(missing_ok=True)
