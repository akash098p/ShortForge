from dataclasses import dataclass
from pathlib import Path
import math, subprocess, json, shutil, tempfile

OUT_W, OUT_H = 1080, 1920
OUT_FPS = 30

# Sources wider than this aspect ratio (w/h) are contain-fitted into the
# 9:16 canvas with a blurred fill instead of cover-cropped, so landscape /
# square footage is never blown up into a narrow, over-zoomed sliver.
FIT_MAX_SOURCE_AR = 0.70

# Single-pass encoding target shared by every renderer (video quality rules:
# one transformation pipeline, H.264 1080x1920 @30fps, CRF ~20, faststart).
ENCODER_ARGS = [
    "-pix_fmt", "yuv420p",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "20",
    "-c:a", "aac",
    "-b:a", "160k",
    "-movflags", "+faststart",
]


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float


class RenderError(RuntimeError):
    """Raised when an FFmpeg command fails; message carries the FFmpeg log."""


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run an FFmpeg/ffprobe command in list form (no shell) and capture output.

    Windows-safe: every argument is passed as its own list element, so filter
    expressions and file paths are never reparsed by a shell. On a non-zero
    exit, raise a RenderError whose message contains the real FFmpeg stderr so
    the API can surface a useful error to the frontend. `cwd` is only used so
    the subtitles filter can resolve a relative filename (FFmpeg's
    filtergraph parser unescapes drive-letter colons inside option values, so
    an absolute Windows path in `subtitles=` is unreliable across builds).
    """
    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd
    )
    if p.returncode != 0:
        tail = (p.stderr or "").strip()
        if len(tail) > 2000:
            tail = "..." + tail[-2000:]
        brief = " ".join(str(x) for x in cmd[:4])
        raise RenderError(
            f"FFmpeg command failed (exit {p.returncode}): {brief}\n{tail}"
        )
    return p


def ffprobe(path: str) -> MediaInfo:
    if not shutil.which("ffprobe"):
        raise RenderError("ffprobe is not installed")
    try:
        p = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=width,height,r_frame_rate",
                "-of",
                "json",
                path,
            ]
        )
    except RenderError as e:
        raise RenderError(f"Could not read media file '{path}':\n{e}") from e
    data = json.loads(p.stdout)
    stream = next(s for s in data["streams"] if "width" in s)
    n, d = stream.get("r_frame_rate", "30/1").split("/")
    fps = float(n) / float(d) if float(d) != 0 else float(OUT_FPS)
    raw_dur = (data.get("format") or {}).get("duration")
    try:
        duration = float(raw_dur) if raw_dur else 0.0
    except (TypeError, ValueError):
        duration = 0.0  # still images report no duration
    return MediaInfo(
        duration,
        int(stream["width"]),
        int(stream["height"]),
        fps,
    )


def _escape_expr(expr: str) -> str:
    """Escape FFmpeg filtergraph specials inside an expression/value.

    FFmpeg's filter parser treats an unescaped comma as a filter separator and
    an unescaped semicolon as a chain separator, so the commas used by
    functions such as if() and clip() must be escaped whenever the expression
    is embedded in a filter option. Colons separate option values and must
    also be escaped (same technique used for Windows drive letters). Any
    backslash must be doubled so av_get_token does not consume the next char.
    """
    return (
        expr.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace(":", "\\:")
    )


def _escaped_filter_path(path: str) -> str:
    """Turn a filesystem path into a value safe to embed in a filter option."""
    return _escape_expr(Path(path).as_posix())


def _sanitize_track(
    track: list[dict] | None,
    width: int,
    height: int,
    duration: float,
    min_conf: float = 0.1,
) -> list[dict] | None:
    """Validate/normalize a tracking point list; None means "no reliable track".

    Graceful-fallback layer for the "not enough matching points" case: points
    that are non-finite, out of bounds, or low-confidence are dropped; if
    nothing usable remains we return None so the renderer falls back to a
    stable centered crop instead of emitting a broken animated expression.
    """
    if not track:
        return None
    out: list[dict] = []
    for p in track:
        try:
            t = float(p["time"])
            x = float(p["x"])
            y = float(p["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (t, x, y)):
            continue
        if not (0.0 <= t <= max(0.0, float(duration))):
            continue
        if not (0.0 <= x <= float(width)) or not (0.0 <= y <= float(height)):
            continue
        conf = float(p.get("confidence", 1.0))
        if conf < min_conf:
            continue
        out.append(
            {
                "time": t,
                "x": x,
                "y": y,
                "confidence": conf,
                "track_id": p.get("track_id", 0),
            }
        )
    if not out:
        return None
    out.sort(key=lambda q: q["time"])
    dedup: list[dict] = []
    for q in out:
        if dedup and abs(q["time"] - dedup[-1]["time"]) < 1e-6:
            dedup[-1] = q
        else:
            dedup.append(q)
    return dedup


def _tracked_crop_filter(
    width: int, height: int, track: list[dict] | None
) -> tuple[str, int, int]:
    """Build a safe 9:16 crop filter for the source geometry.

    Returns (crop_filter_str, crop_width, crop_height). The crop rectangle is
    always kept fully inside the source frame. When track is None the crop is
    the stable centered 9:16 window; otherwise the crop rectangle follows the
    tracked point through piecewise-linear keyframes (clamped before the first
    and after the last keyframe so we never extrapolate).
    """
    target = 9 / 16
    if width / height >= target:
        cw_f = height * target
        ch_f = height
    else:
        cw_f = width
        ch_f = width / target
    cw = max(2, min(width, int(round(cw_f))))
    ch = max(2, min(height, int(round(ch_f))))
    if cw < width and cw % 2 == 1:
        cw -= 1
    if ch < height and ch % 2 == 1:
        ch -= 1
    max_x = max(0, width - cw)
    max_y = max(0, height - ch)

    if not track:
        return f"crop={cw}:{ch}:{max_x // 2}:{max_y // 2}", cw, ch

    def expr(axis: str, limit: int, crop_size: int) -> str:
        vals: list[tuple[float, float]] = []
        for p in track:
            t = float(p["time"])
            center = float(p[axis])
            raw = center - crop_size / 2  # center -> top-left corner
            start = max(0.0, min(float(limit), raw))
            vals.append((t, start))
        if len(vals) == 1:
            v = vals[0][1]
            return _escape_expr(f"clip({v:.3f},0,{float(limit):.3f})")
        e = f"clip({vals[-1][1]:.3f},0,{float(limit):.3f})"
        for i in range(len(vals) - 1, 0, -1):
            t0, v0 = vals[i - 1]
            t1, v1 = vals[i]
            dt = t1 - t0
            if dt <= 0:
                continue
            interp = f"clip({v0:.3f}+({v1 - v0:.3f})*(t-{t0:.6f})/{dt:.6f},0,{float(limit):.3f})"
            e = f"if(lt(t,{t1:.6f}),{interp},{e})"
        # Clamp before the first keyframe: segments may start before
        # tracking data becomes available.
        t0, v0 = vals[0]
        e = f"if(lte(t,{t0:.6f}),clip({v0:.3f},0,{float(limit):.3f}),{e})"
        return _escape_expr(e)

    x_expr = expr("x", max_x, cw)
    y_expr = expr("y", max_y, ch)
    return f"crop={cw}:{ch}:{x_expr}:{y_expr}", cw, ch


def _fit_filtergraph(width: int, height: int, zoom: float = 1.0) -> str:
    """Complex filtergraph that normalizes wide footage into 9:16.

    The full frame is contain-fitted inside the 1080x1920 canvas
    (force_original_aspect_ratio=decrease) and centered over a blurred,
    cover-scaled copy of itself, so landscape/square sources keep their
    whole composition instead of being cover-cropped into an over-zoomed
    sliver. An optional zoom is a gentle centered punch-in on the sharp
    foreground only; the blurred background stays stable.
    """
    z = max(1.0, min(float(zoom or 1.0), 1.14))
    fg = "[fg]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if z > 1.0001:
        fg += f",scale=trunc(iw*{z:.4f}/2)*2:trunc(ih*{z:.4f}/2)*2:flags=lanczos"
    fg += ",setsar=1[fgs]"
    return (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=270:480:force_original_aspect_ratio=increase:force_divisible_by=2,"
        "crop=270:480,gblur=sigma=6,scale=1080:1920:flags=bilinear,setsar=1[bgb];"
        f"{fg};"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]"
    )


def _build_vertical_filter(
    width: int,
    height: int,
    track: list[dict] | None,
    zoom: float = 1.0,
    subtitle_file: str | None = None,
) -> tuple[str, bool]:
    """Filtergraph for one normalized 9:16 segment.

    Returns (filtergraph, is_complex). Two geometry modes:

    * Portrait-ish sources (w/h <= FIT_MAX_SOURCE_AR): single-chain `-vf`
      graph — 9:16 tracked crop -> optional centered zoom -> scale canvas ->
      setsar=1 (always LAST so rounding inside scale never reintroduces a
      non-1:1 sample aspect ratio). Upscaling here is plain output-size
      normalization, not an extra framing zoom.

    * Wider sources (3:4, 4:5, 1:1, 16:9 ...): complex graph from
      `_fit_filtergraph` — the whole frame is contain-fitted and centered on
      a blurred fill, avoiding the destructive cover-crop that made rendered
      shorts look hugely zoomed-in ("too big for screen").

    Optional subtitles (the ASS canvas is already 1080x1920) are appended to
    the final chain in both modes.
    """
    if width / height > FIT_MAX_SOURCE_AR:
        graph = _fit_filtergraph(width, height, zoom)
        if subtitle_file:
            suffix = f",subtitles={_escaped_filter_path(subtitle_file)}"
            graph = graph[: -len("[vout]")] + suffix + "[vout]"
        return graph, True

    crop_vf, cw, ch = _tracked_crop_filter(width, height, track)
    filters = [crop_vf]
    z = max(1.0, min(float(zoom or 1.0), 1.14))
    if z > 1.0001:
        filters.append(
            f"scale=trunc({cw}*{z:.4f}/2)*2:trunc({ch}*{z:.4f}/2)*2:flags=lanczos,"
            f"crop={cw}:{ch}"
        )
    filters.append(f"scale={OUT_W}:{OUT_H}:flags=lanczos")
    filters.append("setsar=1")
    vf = ",".join(filters)
    if subtitle_file:
        vf += f",subtitles={_escaped_filter_path(subtitle_file)}"
    return vf, False


def render_vertical(
    source: str,
    output: str,
    start: float = 0,
    end: float | None = None,
    zoom: float = 1.0,
    subtitle_file: str | None = None,
    track: list[dict] | None = None,
) -> None:
    """Render one segment of the source to a normalized 1080x1920 vertical clip."""
    info = ffprobe(source)
    t = (
        _sanitize_track(track, info.width, info.height, info.duration)
        if track
        else None
    )
    sub_name = None
    sub_cwd = None
    if subtitle_file:
        # Reference the ASS by relative name and run ffmpeg from its folder:
        # an absolute Windows path inside the subtitles filter option is not
        # reliably parseable across FFmpeg builds (see _run docstring).
        sub_abs = Path(subtitle_file).resolve()
        sub_name = sub_abs.name
        sub_cwd = str(sub_abs.parent)
    vf, is_complex = _build_vertical_filter(info.width, info.height, t, zoom, sub_name)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.6f}", "-i", source]
    if end is not None:
        cmd += ["-t", f"{max(0.0, end - start):.6f}"]
    if is_complex:
        # Blur-pad fit mode: multi-chain graph -> map its output label; keep
        # source audio when present ("?" makes the audio map optional).
        cmd += ["-filter_complex", vf, "-map", "[vout]", "-map", "0:a?"]
    else:
        cmd += ["-vf", vf]
    cmd += ["-r", str(OUT_FPS), *ENCODER_ARGS, output]
    _run(cmd, cwd=sub_cwd)


def _concat_quote(posix_path: str) -> str:
    """One entry for the concat demuxer file list (names are our own temp files)."""
    return f"file '{posix_path}'"


def render_plan(
    source: str,
    output: str,
    segments: list[dict],
    subtitle_file: str | None = None,
    track: list[dict] | None = None,
) -> None:
    """Render consecutive segments of `source` into a single vertical MP4.

    Each segment is rendered exactly once (decoded from source and encoded to
    its final form), then the parts are concatenated with stream copy, so no
    content is re-encoded repeatedly. Temporary files are cleaned up even when
    FFmpeg fails, and any FFmpeg error escapes as a RenderError with the log.
    """
    if not segments:
        raise ValueError("No segments to render")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="shortforge-render-"))
    parts: list[Path] = []
    try:
        ffprobe(source)  # fail fast with a useful RenderError (missing source)
        for i, s in enumerate(segments):
            try:
                st = float(s["start"])
                en = float(s["end"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"segment {i + 1} is missing valid start/end")
            if en <= st:
                continue
            part = work / f"part-{i:04d}.mp4"
            local = None
            if track:
                local = []
                for p in track:
                    try:
                        t = float(p["time"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if st <= t <= en:
                        q = dict(p)
                        q["time"] = round(t - st, 6)
                        local.append(q)
            try:
                z = float(s.get("zoom", 1.0) or 1.0)
            except (TypeError, ValueError):
                z = 1.0
            render_vertical(source, str(part), st, en, z, subtitle_file, local)
            parts.append(part)
        if not parts:
            raise ValueError("No renderable segments after validation")
        if len(parts) == 1:
            shutil.copy2(parts[0], out)
            return
        concat = work / "concat.txt"
        concat.write_text(
            "\n".join(_concat_quote(p.as_posix()) for p in parts), encoding="utf-8"
        )
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def transition_filter(kind: str, duration: float = 0.18) -> str:
    d = max(0.08, min(0.5, float(duration)))
    if kind == "fade":
        return f"fade=t=in:st=0:d={d}"
    if kind == "flash":
        return "eq=brightness=0.04"
    if kind == "zoom":
        return "scale=1120:1992:flags=lanczos,crop=1080:1920"
    return "null"


def _segment_beat_intensity(
    beats: list[float], start: float, end: float
) -> float:
    """0..1 music-energy score for a segment derived from its beat window.

    Counts beats inside the window (with a small halo either side) and
    rewards a beat landing exactly on the cut point, so punchy segments
    score high and quiet stretches score ~0. This is the "bit wave" datum
    the frontend uses to drive its live preview.
    """
    if not beats:
        return 0.0
    dur = max(0.2, float(end) - float(start))
    inside = [b for b in beats if start - 0.15 <= b <= end + 0.15]
    if not inside:
        return 0.0
    density = (len(inside) - 1) / max(1.0, dur * 1.6)
    on_cut = min(1.0, max(0.0, 1.0 - min(abs(b - start) for b in inside) * 4.0))
    return round(min(1.0, 0.3 * on_cut + 0.7 * min(1.0, density)), 3)


def _auto_effect(preset: str, index: int, seg: dict) -> str:
    """Auto AI visual effect for a segment, tuned to the chosen preset.

    Beat-aligned segments get motion effects (pulse/shake/bw) so the punch
    of the music is visible; quiet speech stretches get gentle color
    treatments. First segment stays clean.
    """
    kind = preset.lower()
    speech = float(seg.get("speech_density", 0) or 0)
    if index == 0:
        return "none"
    if seg.get("beat_sync"):
        if kind == "energy":
            return ("shake", "bw", "pulse")[index % 3]
        if kind == "cinematic":
            return "pulse"
        if kind == "podcast":
            return "vignette"
        return ("pulse", "shake")[index % 2]
    if kind == "energy":
        return "pulse" if speech < 0.5 else "shake"
    if kind == "cinematic":
        return "moody" if speech >= 0.35 else "vignette"
    if kind == "podcast":
        return "brighten"
    return "brighten" if speech < 0.35 else "pulse"


def _auto_transition(preset: str, index: int, seg: dict, intensity: float) -> str:
    """Auto AI transition into a segment, driven by beats + speech density."""
    if index == 0:
        return "none"
    if seg.get("beat_sync"):
        if intensity >= 0.75:
            return "flash"
        if intensity >= 0.45:
            return "zoom"
        return "pixelize" if preset.lower() == "energy" else "fade"
    if float(seg.get("speech_density", 0) or 0) < 0.35:
        return "fadeblack" if preset.lower() == "cinematic" else "fade"
    if intensity >= 0.5:
        return "flash"
    return "cut"


def apply_transition_metadata(
    segments: list[dict],
    beats: list[float] | None = None,
    preset: str = "viral",
) -> list[dict]:
    """Auto-editor pass: AI transitions, effects and beat intensity.

    The first segment enters from black (no punch). Beat-aligned segments
    get zoom/flash + motion effects, quiet segments fade, low-energy cuts
    stay hard cuts, and every segment carries a 0..1 ``beat_intensity``
    score that the web preview's live bit-wave and the recreation engine's
    beat-synced effects both consume.
    """
    beats = beats or []
    result = []
    for i, segment in enumerate(segments):
        item = dict(segment)
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start + 1.0))
        except (TypeError, ValueError):
            start, end = 0.0, 1.0
        intensity = _segment_beat_intensity(beats, start, end)
        item["transition"] = _auto_transition(preset, i, item, intensity)
        item["transition_duration"] = 0.16 if item["transition"] != "cut" else 0.0
        if not item.get("effect") or item.get("effect") == "none":
            item["effect"] = _auto_effect(preset, i, item)
        item["beat_intensity"] = intensity
        result.append(item)
    return result
