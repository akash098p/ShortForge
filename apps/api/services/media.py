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

def render_vertical(source: str, output: str, start: float=0, end: float|None=None) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed on the API worker")
    duration=(end-start) if end is not None else None
    vf="scale=1080:-2:force_original_aspect_ratio=increase,crop=1080:1920"
    cmd=["ffmpeg","-y","-ss",str(start),"-i",source]
    if duration is not None: cmd += ["-t",str(duration)]
    cmd += ["-vf",vf,"-r","30","-c:v","libx264","-preset","medium","-crf","18","-c:a","aac","-b:a","192k","-movflags","+faststart",output]
    subprocess.run(cmd,check=True)