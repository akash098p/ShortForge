from dataclasses import dataclass

@dataclass
class CaptionWord:
    text: str
    start: float
    end: float
    emphasis: bool=False

def make_caption_groups(words: list[CaptionWord], max_words: int=4) -> list[dict]:
    groups=[]
    for i in range(0,len(words),max_words):
        chunk=words[i:i+max_words]
        if not chunk: continue
        groups.append({"start":chunk[0].start,"end":chunk[-1].end,"text":" ".join(w.text for w in chunk),"emphasis":[w.text for w in chunk if w.emphasis]})
    return groups