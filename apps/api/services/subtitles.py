from pathlib import Path
import html, re

def _ass_time(seconds:float)->str:
    seconds=max(0,float(seconds)); h=int(seconds//3600); m=int((seconds%3600)//60); s=seconds%60
    return f"{h}:{m:02d}:{s:05.2f}"

def _ass_escape(text:str)->str:
    return text.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")

def to_ass(groups:list[dict],path:str,preset:str="viral")->str:
    styles={
      "viral":("Arial Black",68,"\x1c&H00FFFFFF&","\x1c&H0000D7FF&"),
      "podcast":("Arial",58,"\x1c&H00FFFFFF&","\x1c&H0000FFFF&"),
      "cinematic":("Montserrat",62,"\x1c&H00FFFFFF&","\x1c&H00C8C8C8&"),
      "energy":("Arial Black",72,"\x1c&H00FFFFFF&","\x1c&H0000A5FF&")
    }
    font,size,primary,emph=styles.get(preset,styles["viral"])
    lines=[
      "[Script Info]","ScriptType: v4.00+","PlayResX: 1080","PlayResY: 1920",
      "[V4+ Styles]","Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Alignment, MarginL, MarginR, MarginV, Encoding",
      f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,5,70,70,360,1",
      "[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    for g in groups:
        words=g.get("words",[])
        for i,w in enumerate(words):
            start=float(w["start"]); end=float(w["end"])
            # Display the whole phrase while highlighting the currently spoken word.
            parts=[]
            for j,x in enumerate(words):
                t=_ass_escape(x["text"])
                if j==i:
                    parts.append("{\\c"+emph+"}"+t+"{\\c"+primary+"}")
                else: parts.append(t)
            text=" ".join(parts)
            # Scale pop on the active word.
            active=_ass_escape(w["text"])
            text=text.replace("{\\c"+emph+"}"+active+"{\\c"+primary+"}","{\\c"+emph+"\\fscx108\\fscy108}"+active+"{\\fscx100\\fscy100\\c"+primary+"}")
            lines.append(f"Dialogue: 0,{_ass_time(g['start'])},{_ass_time(g['end'])},Default,,0,0,0,,{{\\an5\\pos(540,1510)}}{text}")
    Path(path).write_text("\n".join(lines),encoding="utf-8")
    return path
