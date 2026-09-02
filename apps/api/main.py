from fastapi import FastAPI
from pydantic import BaseModel, Field

app=FastAPI(title="ShortForge API",version="0.1.0")

class AnalyzeRequest(BaseModel):
    source_name:str
    duration:float=Field(ge=0)
    width:int=Field(ge=1)
    height:int=Field(ge=1)
    fps:float=Field(default=30,gt=0)
    preset:str="viral"

@app.get("/health")
def health():
    return {"ok":True,"service":"shortforge-api"}

@app.post("/v1/analyze")
def analyze(req:AnalyzeRequest):
    # Phase 2 contract: deterministic edit plan first; AI workers plug in later.
    segment={"id":"segment-1","start":0,"end":req.duration,"zoom":1.0,"reason":"initial source segment"}
    return {"project":{"source_name":req.source_name,"duration":req.duration,"width":req.width,"height":req.height,"fps":req.fps,"preset":req.preset},"segments":[segment],"status":"ready"}