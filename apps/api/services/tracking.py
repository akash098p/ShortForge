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

def _track_stats(points):
    stats={}
    for p in points:
        s=stats.setdefault(p["track_id"],{"n":0,"conf":0.0})
        s["n"]+=1; s["conf"]+=float(p["confidence"])
    return stats

def choose_primary_track(points:list[dict],preferred_id:int|None=None)->list[dict]:
    if not points:return []
    stats=_track_stats(points)
    best=preferred_id if preferred_id in stats else max(stats,key=lambda k:(stats[k]["n"],stats[k]["conf"]))
    return [p for p in points if p["track_id"]==best]

def detect_people(path:str,sample_fps:float=3.0,model_name:str="yolo11n.pt")->list[dict]:
    cap=cv2.VideoCapture(path)
    if not cap.isOpened(): raise RuntimeError(f"Unable to open video: {path}")
    fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride=max(1,int(round(fps/max(sample_fps,0.1))))
    model=YOLO(model_name); points=[]; i=0
    try:
        while True:
            ok,frame=cap.read()
            if not ok: break
            if i%stride==0:
                result=model.track(frame,persist=True,classes=[0],conf=0.35,verbose=False)[0]
                if result.boxes is not None and result.boxes.id is not None:
                    for box,tid in zip(result.boxes,result.boxes.id):
                        conf=float(box.conf[0]); x1,y1,x2,y2=[float(v) for v in box.xyxy[0]]
                        points.append({"time":i/fps,"x":(x1+x2)/2,"y":(y1+y2)/2,"confidence":conf,"track_id":int(tid)})
            i+=1
    finally: cap.release()
    return choose_primary_track(points)

def smooth_track(points:list[dict],duration:float,alpha:float=0.22,max_jump:float=140.0,max_gap:float=2.5)->list[dict]:
    if not points:return []
    points=sorted(points,key=lambda p:float(p["time"])); out=[dict(points[0])]
    for p in points[1:]:
        prev=out[-1]; gap=float(p["time"])-float(prev["time"])
        if gap>max_gap:
            out.append({"time":float(p["time"]),"x":float(prev["x"]),"y":float(prev["y"]),"confidence":0.0,"track_id":prev.get("track_id",0),"recovered":True}); continue
        dx=max(-max_jump,min(max_jump,float(p["x"])-float(prev["x"])))
        dy=max(-max_jump,min(max_jump,float(p["y"])-float(prev["y"])))
        out.append({"time":min(duration,max(0,float(p["time"]))),"x":float(prev["x"])+dx*alpha,"y":float(prev["y"])+dy*alpha,"confidence":float(p.get("confidence",1.0)),"track_id":p.get("track_id",prev.get("track_id",0))})
    return out

def recover_track(points:list[dict],duration:float,max_gap:float=2.5)->list[dict]:
    if not points:return []
    points=sorted(points,key=lambda p:float(p["time"])); out=[]
    for a,b in zip(points,points[1:]):
        out.append(a); gap=float(b["time"])-float(a["time"])
        if 0<gap<=max_gap:
            for j in range(1,max(1,int(gap*3))):
                r=j/max(1,int(gap*3)); out.append({"time":float(a["time"])+gap*r,"x":float(a["x"])+(float(b["x"])-float(a["x"]))*r,"y":float(a["y"])+(float(b["y"])-float(a["y"]))*r,"confidence":min(float(a.get("confidence",1)),float(b.get("confidence",1))),"track_id":a.get("track_id",0),"recovered":True})
    out.append(points[-1]); return out
