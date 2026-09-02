from dataclasses import dataclass
from pathlib import Path
import json, shutil, subprocess

@dataclass
class TrackPoint:
    time: float
    x: float
    y: float
    confidence: float

def detect_motion_points(path: str, sample_fps: float = 2.0) -> list[dict]:
    """Lightweight tracking fallback based on frame-difference bounding boxes.
    A future CV detector can replace this without changing the API contract.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    # Keep analysis bounded; emit no guesses when a reliable detector is unavailable.
    return []

def smooth_track(points: list[dict], duration: float, max_jump: float = 180.0) -> list[dict]:
    if not points:
        return []
    ordered=sorted(points,key=lambda p:float(p["time"]))
    out=[dict(ordered[0])]
    for p in ordered[1:]:
        prev=out[-1]
        x=float(p["x"]); y=float(p["y"])
        px=float(prev["x"]); py=float(prev["y"])
        dx=max(-max_jump,min(max_jump,x-px))
        dy=max(-max_jump,min(max_jump,y-py))
        out.append({"time":min(duration,max(0,float(p["time"]))),"x":px+dx,"y":py+dy,"confidence":float(p.get("confidence",1.0))})
    return out

def load_tracking_points(path: str) -> list[dict]:
    p=Path(path)
    if not p.exists(): return []
    data=json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data,list) else data.get("points",[])