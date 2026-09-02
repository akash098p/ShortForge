def to_ass(groups:list[dict], output:str, font_size:int=72)->None:
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Shorts,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,60,60,360,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    def ts(v):
        h=int(v//3600); m=int(v%3600//60); s=v%60
        return f"{h}:{m:02d}:{s:05.2f}"
    with open(output,"w",encoding="utf-8") as f:
        f.write(header)
        for g in groups:
            text=str(g.get("text","")).replace("{","").replace("}","")
            f.write(f"Dialogue: 0,{ts(float(g['start']))},{ts(float(g['end']))},Shorts,,0,0,0,,{text}\n")