from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from services.edit_plan import build_plan
from services.analyzer import detect_silences, detect_scenes, build_highlight_windows, detect_beats
from services.transcription import transcribe
from services.captions import CaptionWord, make_caption_groups
from services.subtitles import to_ass
from services.reframe import build_reframe_track
from services.tracking import detect_people, smooth_track, recover_track
from pathlib import Path
import uuid

app=FastAPI(title="ShortForge API",version="0.8.0")

class AnalyzeRequest(BaseModel):
    source_name:str
    source_path:str|None=None
    duration:float=Field(ge=0)
    width:int=Field(ge=1)
    height:int=Field(ge=1)
    fps:float=Field(default=30,gt=0)
    preset:str="viral"

@app.get("/health")
def health(): return {"ok":True,"service":"shortforge-api","version":"0.8.0"}

@app.post("/v1/analyze")
def analyze(req:AnalyzeRequest):
    silences=[]; scenes=[]; words=[]; tracking=[]; beats=[]
    if req.source_path:
        try:
            silences=detect_silences(req.source_path)
            scenes=detect_scenes(req.source_path)
            words=transcribe(req.source_path)
            tracking=recover_track(smooth_track(detect_people(req.source_path),req.duration),req.duration)
            beats=detect_beats(req.source_path)
        except Exception as e:
            raise HTTPException(status_code=400,detail=f"media analysis failed: {e}")
    active=build_highlight_windows(req.duration,silences)
    captions=make_caption_groups([CaptionWord(w["text"],float(w["start"]),float(w["end"])) for w in words])
    reframe=build_reframe_track(req.width,req.height,req.duration,tracking or None)
    plan=build_plan(req.duration,req.preset,active or None,scenes,words,beats)
    return {"project":req.model_dump(),"analysis":{"silences":[s.__dict__ for s in silences],"scenes":scenes,"transcript_words":words,"tracking":tracking,"beats":beats},"captions":captions,"segments":plan["segments"],"reframe":reframe,"status":"ready"}

class RenderPlanRequest(BaseModel):
    source_path:str
    output_path:str
    segments:list[dict]
    captions:list[dict]=[]

@app.post("/v1/render-plan")
def render_plan_endpoint(req:RenderPlanRequest):
    try:
        from services.media import render_plan
        subtitle=None; subtitle_path=None
        if req.captions:
            subtitle_path=Path("/tmp/shortforge-render")/f"{uuid.uuid4().hex}.ass"
            subtitle_path.parent.mkdir(parents=True,exist_ok=True)
            to_ass(req.captions,str(subtitle_path)); subtitle=str(subtitle_path)
        render_plan(req.source_path,req.output_path,req.segments,subtitle,req.reframe)
        if subtitle_path: subtitle_path.unlink(missing_ok=True)
        return {"status":"complete","output_path":req.output_path,"captions_burned":bool(req.captions)}
    except Exception as e:
        raise HTTPException(status_code=400,detail=str(e))