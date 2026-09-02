from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from services.edit_plan import build_plan
from services.analyzer import detect_silences, detect_scenes, build_highlight_windows

app=FastAPI(title="ShortForge API",version="0.3.0")

class AnalyzeRequest(BaseModel):
    source_name:str
    source_path:str|None=None
    duration:float=Field(ge=0)
    width:int=Field(ge=1)
    height:int=Field(ge=1)
    fps:float=Field(default=30,gt=0)
    preset:str="viral"

@app.get("/health")
def health(): return {"ok":True,"service":"shortforge-api","version":"0.3.0"}

@app.post("/v1/analyze")
def analyze(req:AnalyzeRequest):
    silences=[]; scenes=[]
    if req.source_path:
        try:
            silences=detect_silences(req.source_path)
            scenes=detect_scenes(req.source_path)
        except Exception as e:
            raise HTTPException(status_code=400,detail=f"media analysis failed: {e}")
    active=build_highlight_windows(req.duration,silences)
    plan=build_plan(req.duration,req.preset,active or None)
    return {"project":req.model_dump(),"analysis":{"silences":[s.__dict__ for s in silences],"scenes":scenes},"segments":plan["segments"],"status":"ready"}