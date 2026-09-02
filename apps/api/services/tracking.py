from dataclasses import dataclass
import cv2
from ultralytics import YOLO

@dataclass
class TrackPoint:
    time: float
    x: float
    y: float
    confidence: float

def detect_people(path: str, sample_fps: float = 3.0, model_name: str = "yolo11n.pt") -> list[dict]:
    """Detect people at sampled frames and return center points for reframing.
    The small YOLO model is used by default to keep local inference practical.
    """
    cap=cv2.VideoCapture(path)
    if not cap.isOpened(): raise RuntimeError(f"Unable to open video: {path}")
    fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
    total=cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration=total/fps if total else 0
    stride=max(1,int(round(fps/max(sample_fps,0.1))))
    model=YOLO(model_name)
    points=[]
    i=0
    while True:
        ok,frame=cap.read()
        if not ok: break
        if i%stride==0:
            result=model.predict(frame,classes=[0],conf=0.35,verbose=False)[0]
            best=None
            for box in result.boxes:
                conf=float(box.conf[0])
                x1,y1,x2,y2=[float(v) for v in box.xyxy[0]]
                area=max(1,(x2-x1)*(y2-y1))
                candidate=(area,conf,(x1+x2)/2,(y1+y2)/2)
                if best is None or candidate[:2]>best[:2]: best=candidate
            if best:
                points.append({"time":i/fps,"x":best[2],"y":best[3],"confidence":best[1]})
        i+=1
    cap.release()
    return points

def smooth_track(points:list[dict],duration:float,max_jump:float=180.0)->list[dict]:
    if not points:return []
    out=[dict(points[0])]
    for p in points[1:]:
        prev=out[-1]
        alpha=0.35
        x=float(prev["x"])+(float(p["x"])-float(prev["x"]))*alpha
        y=float(prev["y"])+(float(p["y"])-float(prev["y"]))*alpha
        out.append({"time":min(duration,max(0,float(p["time"]))),"x":x,"y":y,"confidence":float(p.get("confidence",1))})
    return out
