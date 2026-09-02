def build_plan(duration: float, preset: str) -> dict:
    # Deterministic baseline. AI scoring and transcript-aware cuts are added next.
    if duration <= 0: return {"segments":[]}
    max_clip={"viral":8.0,"podcast":18.0,"cinematic":14.0,"energy":5.0}.get(preset,8.0)
    segments=[]
    cursor=0.0; index=0
    while cursor < duration:
        end=min(duration,cursor+max_clip)
        zoom=1.06 if preset in {"viral","energy"} and index%2 else 1.0
        segments.append({"id":f"segment-{index+1}","start":round(cursor,3),"end":round(end,3),"zoom":zoom,"reason":"baseline pacing"})
        cursor=end; index+=1
    return {"segments":segments}