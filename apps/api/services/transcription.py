from pathlib import Path
import json, shutil, subprocess

def transcribe(path: str) -> list[dict]:
    """Optional Whisper adapter. Returns [] when no local Whisper binary is configured."""
    whisper=shutil.which("whisper")
    if not whisper: return []
    out=Path("/tmp/shortforge-transcripts"); out.mkdir(parents=True,exist_ok=True)
    cmd=[whisper,path,"--model","turbo","--output_format","json","--output_dir",str(out)]
    subprocess.run(cmd,check=True)
    result=out/(Path(path).stem+".json")
    if not result.exists(): return []
    data=json.loads(result.read_text())
    words=[]
    for segment in data.get("segments",[]):
        text=segment.get("text","").strip()
        if not text: continue
        words.append({"text":text,"start":segment.get("start",0),"end":segment.get("end",0)})
    return words