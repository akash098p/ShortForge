def _merge_windows(windows:list[dict],gap:float=0.12)->list[dict]:
    if not windows:return []
    items=sorted(windows,key=lambda x:x["start"]); out=[dict(items[0])]
    for w in items[1:]:
        if w["start"]-out[-1]["end"]<=gap: out[-1]["end"]=max(out[-1]["end"],w["end"])
        else: out.append(dict(w))
    return out

def _nearest_beat(beats:list[float],target:float,lo:float,hi:float):
    choices=[b for b in beats if lo<=b<=hi]
    return min(choices,key=lambda b:abs(b-target)) if choices else None

def build_plan(duration:float,preset:str,active_windows:list[dict]|None=None,scene_cuts:list[float]|None=None,words:list[dict]|None=None,beats:list[float]|None=None)->dict:
    if duration<=0:return {"segments":[]}
    limits={"viral":(2.0,7.0),"podcast":(4.0,16.0),"cinematic":(3.0,12.0),"energy":(1.5,5.0)}
    min_clip,max_clip=limits.get(preset,limits["viral"])
    source=_merge_windows(active_windows or [{"start":0.0,"end":duration}])
    cuts=sorted(set([0.0,duration]+[float(x) for x in (scene_cuts or []) if 0<float(x)<duration]))
    beats=sorted(float(x) for x in (beats or []) if 0<float(x)<duration)
    segments=[]; index=0
    for w in source:
        cursor=float(w["start"]); end_limit=float(w["end"])
        while cursor<end_limit-0.05:
            target=min(end_limit,cursor+max_clip)
            beat=_nearest_beat(beats,target,cursor+min_clip,target+0.45)
            candidates=[c for c in cuts if cursor+min_clip<=c<=target+0.15]
            end=min(candidates,key=lambda c:abs(c-target)) if candidates else target
            if beat is not None and abs(beat-target)<0.45: end=beat
            if end-cursor<min_clip and target<end_limit: end=min(end_limit,target)
            if end-cursor>=0.5:
                nearby_words=[x for x in (words or []) if float(x.get("start",0))<end and float(x.get("end",0))>cursor]
                density=min(1.0,len(nearby_words)/max(1.0,(end-cursor)*3.0))
                beat_sync=beat is not None and abs(end-beat)<0.03
                segments.append({"id":f"segment-{index+1}","start":round(cursor,3),"end":round(end,3),"zoom":1.06 if preset in {"viral","energy"} and index%3==0 else 1.0,"speech_density":round(density,3),"beat_sync":beat_sync,"beat":round(beat,3) if beat is not None else None,"reason":"silence-aware, scene-aware, beat-aligned pacing"})
                index+=1
            cursor=end
    return {"segments":segments}
