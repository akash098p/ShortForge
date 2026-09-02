def build_plan(duration: float, preset: str, active_windows: list[dict]|None=None) -> dict:
    if duration <= 0: return {"segments":[]}
    max_clip={"viral":8.0,"podcast":18.0,"cinematic":14.0,"energy":5.0}.get(preset,8.0)
    source=active_windows or [{"start":0.0,"end":duration}]
    segments=[]; index=0
    for window in source:
        cursor=float(window["start"]); end_limit=float(window["end"])
        while cursor<end_limit:
            end=min(end_limit,cursor+max_clip)
            zoom=1.06 if preset in {"viral","energy"} and index%2==0 else 1.0
            segments.append({"id":f"segment-{index+1}","start":round(cursor,3),"end":round(end,3),"zoom":zoom,"reason":"speech-active pacing"})
            cursor=end; index+=1
    return {"segments":segments}