from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from services.edit_plan import build_plan
from services.analyzer import detect_silences, detect_scenes, build_highlight_windows
from services.transcription import transcribe
from services.captions import CaptionWord, make_caption_groups

app=FastAPI(title="ShortForge API",version="0.4.0")

class RenderPlanRequest(BaseModel):\n    source_path:str\n    output_path:str\n    segments:list[dict]\n\n@app.post("/v1/render-plan")\ndef render_plan_endpoint(req:RenderPlanRequest):\n    try:\n        from services.media import render_plan\n        render_plan(req.source_path,req.output_path,req.segments)\n        return {"status":"complete","output_path":req.output_path}\n    except Exception as e:\n        raise HTTPException(status_code=400,detail=str(e))\n\nclass AnalyzeRequest(BaseModel):
    source_name:str
    source_path:str|None=None
    duration:float=Field(ge=0)
    width:int=Field(ge=1)
    height:int=Field(ge=1)
    fps:float=Field(default=30,gt=0)
    preset:str="viral"

@app.get("/health")
def health(): return {"ok":True,"service":"shortforge-api","version":"0.4.0"}

@app.post("/v1/analyze")
def analyze(req:AnalyzeRequest):
    silences=[]; scenes=[]; words=[]
    if req.source_path:
        try:
            silences=detect_silences(req.source_path)
            scenes=detect_scenes(req.source_path)
            words=transcribe(req.source_path)
        except Exception as e:
            raise HTTPException(status_code=400,detail=f"media analysis failed: {e}")
    active=build_highlight_windows(req.duration,silences)
    plan=build_plan(req.duration,req.preset,active or None)
    captions=make_caption_groups([CaptionWord(w["text"],float(w["start"]),float(w["end"])) for w in words])
    return {"project":req.model_dump(),"analysis":{"silences":[s.__dict__ for s in silences],"scenes":scenes,"transcript_words":words},"captions":captions,"segments":plan["segments"],"status":"ready"}