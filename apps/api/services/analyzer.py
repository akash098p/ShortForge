from dataclasses import dataclass
import subprocess, json, re

@dataclass
class Silence:
    start: float
    end: float

def detect_silences(path: str, noise_db: int=-32, min_duration: float=0.35) -> list[Silence]:
    cmd=["ffmpeg","-hide_banner","-i",path,"-af",f"silencedetect=noise={noise_db}dB:d={min_duration}","-f","null","-"]
    p=subprocess.run(cmd,text=True,capture_output=True)
    text=p.stderr
    starts=[float(x) for x in re.findall(r"silence_start: ([0-9.]+)",text)]
    ends=[float(x) for x in re.findall(r"silence_end: ([0-9.]+)",text)]
    return [Silence(s,e) for s,e in zip(starts,ends)]

def detect_scenes(path: str, threshold: float=0.35) -> list[float]:
    cmd=["ffprobe","-v","error","-f","lavfi",f"movie={path},select=gt(scene\,{threshold})","-show_entries","frame=pts_time","-of","csv=p=0"]
    try:
        out=subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL)
        return [float(x) for x in out.splitlines() if x.strip()]
    except Exception:
        return []

def build_highlight_windows(duration: float, silences: list[Silence], max_gap: float=0.15) -> list[dict]:
    if duration<=0:return []
    blocked=[(max(0,s.start-max_gap),min(duration,s.end+max_gap)) for s in silences]
    windows=[]; cursor=0.0
    for a,b in blocked:
        if a>cursor: windows.append({"start":round(cursor,3),"end":round(a,3)})
        cursor=max(cursor,b)
    if cursor<duration: windows.append({"start":round(cursor,3),"end":round(duration,3)})
    return [w for w in windows if w["end"]-w["start"]>=0.5]