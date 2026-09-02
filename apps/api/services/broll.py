from pathlib import Path
import json, subprocess, tempfile, shutil

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def find_broll(folder: str) -> list[str]:
    root = Path(folder)
    if not root.exists():
        return []
    return [str(p) for p in sorted(root.rglob("*")) if p.suffix.lower() in VIDEO_EXT]


def make_broll_plan(
    segments: list[dict], assets: list[str], coverage: float = 0.28
) -> list[dict]:
    if not assets:
        return segments
    out = []
    ai = 0
    for i, s in enumerate(segments):
        d = float(s["end"]) - float(s["start"])
        if d < 2.5 or (i % 3) != 1:
            out.append(dict(s))
            continue
        length = min(max(0.8, d * coverage), 2.2)
        start = float(s["start"]) + (d - length) / 2
        x = dict(s)
        x["broll"] = {
            "asset": assets[ai % len(assets)],
            "start": round(start, 3),
            "end": round(start + length, 3),
            "mode": "cutaway",
        }
        ai += 1
        out.append(x)
    return out


def render_broll(
    source: str, asset: str, output: str, start: float, end: float
) -> None:
    dur = max(0.1, end - start)
    work = Path(tempfile.mkdtemp(prefix="shortforge-broll-"))
    try:
        fg = work / "fg.mp4"
        # Fit source B-roll to the exact vertical canvas with high-quality scaling.
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-i",
                asset,
                "-t",
                str(dur),
                "-vf",
                vf,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(fg),
            ],
            check=True,
        )
        # Output is a standalone cutaway clip; main timeline compositor can insert it at the planned time.
        shutil.copy2(fg, output)
    finally:
        shutil.rmtree(work, ignore_errors=True)
