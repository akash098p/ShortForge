def to_ass(groups:list[dict],output:str,font_size:int=72)->None:
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Normal,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,60,60,360,1
Style: Emphasis,Arial,76,&H0000FFB8,&H0000FFB8,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,60,60,360,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    def ts(v):
        h=int(v//3600);m=int(v%3600//60);s=v%60
        return f"{h}:{m:02d}:{s:05.2f}"
    with open(output,"w",encoding="utf-8") as f:
        f.write(header)
        for g in groups:
            words=g.get("words",[])
            if not words:
                f.write(f"Dialogue: 0,{ts(g['start'])},{ts(g['end'])},Normal,,0,0,0,,{g.get('text','')}\n"); continue
            # ASS karaoke tags make each word appear progressively.
            parts=[]
            for w in words:
                dur=max(1,round((float(w["end"])-float(w["start"]))*100))
                text=str(w["text"]).replace("{","").replace("}","")
                tag="\\c&H00FFB8&\\fs76" if w.get("emphasis") else ""
                parts.append(f"{{\\k{dur}{tag}}}{text}")
            f.write(f"Dialogue: 0,{ts(g['start'])},{ts(g['end'])},Normal,,0,0,0,,{' '.join(parts)}\n")