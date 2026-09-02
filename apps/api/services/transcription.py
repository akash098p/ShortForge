from pathlib import Path
import json, shutil, subprocess


def transcribe(path: str) -> list[dict]:
    whisper = shutil.which("whisper")
    if not whisper:
        return []
    out = Path("/tmp/shortforge-transcripts")
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            whisper,
            path,
            "--model",
            "turbo",
            "--output_format",
            "json",
            "--output_dir",
            str(out),
        ],
        check=True,
    )
    result = out / (Path(path).stem + ".json")
    if not result.exists():
        return []
    data = json.loads(result.read_text())
    words = []
    for segment in data.get("segments", []):
        # Local Whisper builds often expose segment timing but not word timing.
        for w in segment.get("words", []) or []:
            words.append(
                {
                    "text": w.get("word", "").strip(),
                    "start": float(w.get("start", segment.get("start", 0))),
                    "end": float(w.get("end", segment.get("end", 0))),
                }
            )
        if not segment.get("words"):
            text = segment.get("text", "").strip()
            if text:
                words.append(
                    {
                        "text": text,
                        "start": float(segment.get("start", 0)),
                        "end": float(segment.get("end", 0)),
                    }
                )
    return words
