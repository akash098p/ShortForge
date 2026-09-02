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
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is not installed on the API worker")
    cmd=["ffprobe","-v","error","-show_entries","format=duration:stream=width,height,r_frame_rate","-of","json",path]
    data=json.loads(subprocess.check_output(cmd,text=True))
    stream=next((s for s in data.get("streams",[]) if "width" in s),{})
    rate=stream.get("r_frame_rate","30/1").split("/")
    fps=float(rate[0])/float(rate[1]) if float(rate[1]) else 30
    return MediaInfo(float(data["format"]["duration"]),int(stream["width"]),int(stream["height"]),fps)

def _filter(zoom:float)->str:
    # Scale beyond canvas then crop. Zoom is intentionally subtle to preserve source quality.
    z=max(1.0,min(float(zoom),1.14))
    return f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=trunc(iw*{z}/2)*2:trunc(ih*{z}/2)*2,crop=1080:1920"

def render_vertical(source: str, output: str, start: float=0, end: float|None=None, zoom:float=1.0) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed on the API worker")
    duration=(end-start) if end is not None else None
    cmd=["ffmpeg","-y","-ss",str(start),"-i",source]
    if duration is not None: cmd += ["-t",str(duration)]
    cmd += ["-vf",_filter(zoom),"-r","30","-pix_fmt","yuv420p","-c:v","libx264","-preset","medium","-crf","18","-c:a","aac","-b:a","192k","-movflags","+faststart",output]
    subprocess.run(cmd,check=True)

def render_plan(source:str,output:str,segments:list[dict])->None:
    if not segments: raise ValueError("No segments to render")
    # Render each planned segment and concatenate without lossy intermediate re-encoding.
    work=Path("/tmp/shortforge-render"); work.mkdir(parents=True,exist_ok=True)
    parts=[]
    try:
        for i,s in enumerate(segments):
            part=work/f"part-{i:04d}.mp4"
            render_vertical(source,str(part),float(s["start"]),float(s["end"]),float(s.get("zoom",1.0)))
            parts.append(part)
        concat=work/"concat.txt"
        concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts),encoding="utf-8")
        cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",output]
        subprocess.run(cmd,check=True)
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
        (work/"concat.txt").unlink(missing_ok=True)
