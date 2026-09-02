from dataclasses import dataclass
import subprocess, json, re


@dataclass
class Silence:
    start: float
    end: float


def detect_silences(
    path: str, noise_db: int = -32, min_duration: float = 0.35
) -> list[Silence]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        path,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    p = subprocess.run(cmd, text=True, capture_output=True)
    text = p.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    return [Silence(s, e) for s, e in zip(starts, ends)]


def detect_scenes(path: str, threshold: float = 0.35) -> list[float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-f",
        "lavfi",
        f"movie={path},select=gt(scene\,{threshold})",
        "-show_entries",
        "frame=pts_time",
        "-of",
        "csv=p=0",
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        return [float(x) for x in out.splitlines() if x.strip()]
    except Exception:
        return []


def build_highlight_windows(
    duration: float, silences: list[Silence], max_gap: float = 0.15
) -> list[dict]:
    if duration <= 0:
        return []
    blocked = [
        (max(0, s.start - max_gap), min(duration, s.end + max_gap)) for s in silences
    ]
    windows = []
    cursor = 0.0
    for a, b in blocked:
        if a > cursor:
            windows.append({"start": round(cursor, 3), "end": round(a, 3)})
        cursor = max(cursor, b)
    if cursor < duration:
        windows.append({"start": round(cursor, 3), "end": round(duration, 3)})
    return [w for w in windows if w["end"] - w["start"] >= 0.5]


def detect_beats(path: str, min_bpm: int = 70, max_bpm: int = 180) -> list[float]:
    """Estimate musical beat timestamps from an audio/video source.
    Uses FFmpeg to extract mono PCM, then a lightweight energy/onset detector.
    """
    import wave, audioop, math, tempfile, os
    import numpy as np

    wav = None
    try:
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-c:a",
                "pcm_s16le",
                wav,
            ],
            check=True,
        )
        with wave.open(wav, "rb") as f:
            rate = f.getframerate()
            raw = f.readframes(f.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if len(audio) < rate // 2:
            return []
        hop = 256
        win = 1024
        rms = []
        for i in range(0, max(1, len(audio) - win), hop):
            rms.append(float(np.sqrt(np.mean(audio[i : i + win] ** 2) + 1e-9)))
        env = np.asarray(rms)
        diff = np.maximum(0, np.diff(env, prepend=env[:1]))
        threshold = float(np.mean(diff) + 1.25 * np.std(diff))
        min_gap = 60.0 / max_bpm
        beats = []
        last = -1e9
        for i, v in enumerate(diff):
            t = i * hop / rate
            if v > threshold and t - last >= min_gap:
                beats.append(round(t, 3))
                last = t
        return beats
    except Exception:
        return []
    finally:
        if wav:
            try:
                os.remove(wav)
            except OSError:
                pass
