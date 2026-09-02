from dataclasses import dataclass
import re


@dataclass
class CaptionWord:
    text: str
    start: float
    end: float
    emphasis: bool = False


EMPHASIS = {
    "you",
    "your",
    "best",
    "new",
    "never",
    "always",
    "why",
    "how",
    "secret",
    "free",
    "important",
    "wow",
    "stop",
    "wait",
    "now",
}


def score_emphasis(text: str) -> bool:
    word = re.sub(r"[^a-zA-Z0-9']", "", text).lower()
    return word in EMPHASIS or text.isupper() or len(word) >= 9


def make_caption_groups(
    words: list[CaptionWord], max_words: int = 4, max_duration: float = 2.0
) -> list[dict]:
    groups = []
    chunk = []
    for word in words:
        if not word.text.strip():
            continue
        if chunk and (
            len(chunk) >= max_words or word.end - chunk[0].start > max_duration
        ):
            groups.append(_group(chunk))
            chunk = []
        chunk.append(word)
    if chunk:
        groups.append(_group(chunk))
    return groups


def _group(chunk: list[CaptionWord]) -> dict:
    return {
        "start": round(chunk[0].start, 3),
        "end": round(chunk[-1].end, 3),
        "text": " ".join(w.text for w in chunk),
        "words": [
            {
                "text": w.text,
                "start": w.start,
                "end": w.end,
                "emphasis": w.emphasis or score_emphasis(w.text),
            }
            for w in chunk
        ],
    }
