from dataclasses import dataclass
import cv2
from ultralytics import YOLO

@dataclass
class TrackPoint:
    time: float
    x: float
    y: float
    confidence: float
    track_id: int = 0

def detect_people(path:str,sample_fps:float=3.0,model_name:str="yolo11n.pt")->list[dict]:
    """Persistent YOLO tracking. Keeps the same track_id while a person remains visible."""
    cap=cv2.VideoCapture(path)
    if not cap.isOpened(): raise RuntimeError(f"Unable to open video: {path}")
    fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride=max(1,int(round(fps/max(sample_fps,0.1))))
    model=YOLO(model_name)
    points=[]; i=0
    try:
        while True:
            ok,frame=cap.read()
            if not ok: break
            if i%stride==0:
                result=model.track(frame,persist=True,classes=[0],conf=0.35,verbose=False)[0]
                boxes=result.boxes
                if boxes is not None and boxes.id is not None:
                    for box,tid in zip(boxes,boxes.id):
                        conf=float(box.conf[0]); x1,y1,x2,y2=[float(v) for v in box.xyxy[0]]
                        points.append({"time":i/fps,"x":(x1+x2)/2,"y":(y1+y2)/2,"confidence":conf,"track_id":int(tid)})
            i+=1
    finally: cap.release()
    return choose_primary_track(points)

def choose_primary_track(points:list[dict])->list[dict]:
    if not points:return []
    # Prefer the track with the most confident observations, then longest persistence.
    stats={}
    for p in points:
        s=stats.setdefault(p["track_id"],{"n":0,"conf":0.0})
        s["n"]+=1;s["conf"]+=float(p["confidence"])
    best=max(stats,key=lambda k:(stats[k]["conf"],stats[k]["n"]))
    return [p for p in points if p["track_id"]==best]

def smooth_track(points:list[dict],duration:float,alpha:float=0.28,max_jump:float=140.0)->list[dict]:
    if not points:return []
    points=sorted(points,key=lambda p:float(p["time"]))
    out=[dict(points[0])]
    for p in points[1:]:
        prev=out[-1]
        target_x=float(p["x"]);target_y=float(p["y"])
        dx=max(-max_jump,min(max_jump,target_x-float(prev["x"])))
        dy=max(-max_jump,min(max_jump,target_y-float(prev["y"])))
        out.append({"time":min(duration,max(0,float(p["time"]))),
                    "x":float(prev["x"])+dx*alpha,
                    "y":float(prev["y"])+dy*alpha,
                    "confidence":float(p.get("confidence",1.0)),
                    "track_id":p.get("track_id",prev.get("track_id",0))})
    return out
