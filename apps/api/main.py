from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from services.edit_plan import build_plan
from services.analyzer import detect_silences, detect_scenes, build_highlight_windows, detect_beats
from services.transcription import transcribe
from services.captions import CaptionWord, make_caption_groups
from services.subtitles import to_ass
from services.reframe import build_reframe_track
from services.tracking import detect_people, smooth_track, recover_track
from services.broll import find_broll, make_broll_plan
from services.media import apply_transition_metadata
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uuid
import os

app=FastAPI(title="ShortForge API",version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
UPLOAD_DIR=Path("shortforge-uploads"); UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
RENDER_DIR=Path("shortforge-render"); RENDER_DIR.mkdir(parents=True,exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(RENDER_DIR)), name="outputs")

class AnalyzeRequest(BaseModel):
    source_name:str
    source_path:str|None=None
    duration:float=Field(ge=0)
    width:int=Field(ge=1)
    height:int=Field(ge=1)
    fps:float=Field(default=30,gt=0)
    preset:str="viral"
    broll_dir:str|None=None

class RenderPlanRequest(BaseModel):
    source_path:str
    output_path:str
    segments:list[dict]
    captions:list[dict]=[]
    reframe:list[dict]=[]
    preset:str="viral"

@app.get("/health")
def health():
    return {"ok":True,"service":"shortforge-api","version":"1.0.0"}


@app.post("/v1/upload")
async def upload_video(file: UploadFile = File(...)):
    if not file.filename or not Path(file.filename).suffix.lower() in {".mp4",".mov",".mkv",".webm",".m4v",".avi"}:
        raise HTTPException(status_code=400,detail="Unsupported video format")
    name=f"{uuid.uuid4().hex}{Path(file.filename).suffix.lower()}"
    target=UPLOAD_DIR/name
    with target.open("wb") as out:
        while chunk:=await file.read(1024*1024): out.write(chunk)
    return {"source_path":str(target.resolve()),"source_name":file.filename}

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
    assets=find_broll(req.broll_dir) if req.broll_dir else []
    plan["segments"]=make_broll_plan(plan["segments"],assets)
    plan["segments"]=apply_transition_metadata(plan["segments"],beats)
    return {"project":req.model_dump(),"analysis":{"silences":[s.__dict__ for s in silences],"scenes":scenes,"transcript_words":words,"tracking":tracking,"beats":beats},"captions":captions,"segments":plan["segments"],"reframe":reframe,"broll_assets":assets,"status":"ready"}

@app.post("/v1/render-plan")
def render_plan_endpoint(req:RenderPlanRequest):
    try:
        from services.media import render_plan
        subtitle_path=None
        if req.captions:
            subtitle_path=RENDER_DIR/f"{uuid.uuid4().hex}.ass"
            subtitle_path.parent.mkdir(parents=True,exist_ok=True)
            to_ass(req.captions,str(subtitle_path),req.preset)
        output=Path(req.output_path)
        output.parent.mkdir(parents=True,exist_ok=True)
        render_plan(req.source_path,str(output),req.segments,str(subtitle_path) if subtitle_path else None,req.reframe)
        if subtitle_path: subtitle_path.unlink(missing_ok=True)
        return {"status":"complete","output_path":str(output),"size_bytes":os.path.getsize(output),"captions_burned":bool(req.captions)}
    except Exception as e:
        raise HTTPException(status_code=400,detail=str(e))
