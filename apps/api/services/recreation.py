"""Recreation engine: render the user's OWN assets into a reference short's
editing structure.

Reference video -> segments (from /v1/analyze, optionally snapped to beats)
-> mapped user assets -> per-segment render (still images looped, videos
looped when shorter than the segment) -> real transitions (xfade runs) and
concat -> mux the reference audio so the original music/beat timing is
preserved.

Each segment is encoded exactly once; a run of segments joined by real
transitions (fade/zoom/flash/...) is one extra decode+encode pass for that
whole run (still a single transformation pipeline, never per-segment
re-encoding). Geometry is always normalized to 1080x1920, SAR 1:1,
30 fps, yuv420p.
"""

from pathlib import Path
import shutil
import tempfile

from services.media import (
    ENCODER_ARGS,
    FIT_MAX_SOURCE_AR,
    OUT_FPS,
    OUT_H,
    OUT_W,
    RenderError,
    _concat_quote,
    _escape_expr,
    _fit_filtergraph,
    _run,
)


class AssetRenderError(RenderError):
    """Raised when an asset cannot be rendered into a segment."""


# Plan transition kinds -> FFmpeg xfade transition names (Phase 4).
# All values are verified xfade transition names.
_XFADE = {
    "fade": "fade",
    "crossfade": "fade",
    "flash": "fadewhite",
    "zoom": "zoomin",
    "slide": "slideleft",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "wipe": "wipeleft",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "circle": "circleopen",
    "circleopen": "circleopen",
    "radial": "radial",
    "pixelize": "pixelize",
    "rectcrop": "rectcrop",
    "smoothup": "smoothup",
    "blur": "hblur",
    "dissolve": "dissolve",
    "fadeblack": "fadeblack",
}
DEFAULT_TRANSITION_DUR = 0.16

# Per-segment visual effects (Phase 10 slice): post-geometry filter chains
# applied to every frame of the segment. "shake"/"pulse"/"rotate" re-zoom
# slightly so the motion never reveals canvas edges; color effects are pure
# post-filters and cost nothing geometrically.
EFFECTS = ("none", "shake", "pulse", "rotate", "vignette", "brighten", "moody", "bw")


def _xfade_kind(transition: str | None) -> str | None:
    """FFmpeg xfade name for a plan transition, or None for a hard cut."""
    if not transition or transition in ("cut", "none"):
        return None
    return _XFADE.get(str(transition).lower(), "fade")


def _transition_duration(dur_a: float, dur_b: float) -> float:
    """Transition length: 0.16s capped at 40% of the shorter segment."""
    return min(DEFAULT_TRANSITION_DUR, 0.4 * min(dur_a, dur_b))


def _beat_env_expr(beats: list[float] | None) -> str:
    """FFmpeg expression for a beat-energy envelope over local filter time ``t``.

    Returns a value in [0, 1] that peaks at exactly 1 on each (already
    shift-adjusted) beat and falls linearly to 0 at 1/3 s either side, using
    only min/max/abs so it survives older FFmpeg expression parsers. No
    beats -> constant 1.0 (identical to the previous static behavior).
    """
    if not beats:
        return "1.0"
    dist = _escape_expr(f"abs(t-{float(beats[0]):.6f})")
    for b in beats[1:]:
        dist = f"min({dist},{_escape_expr(f'abs(t-{float(b):.6f})')})"
    return _escape_expr(f"max(0,min(1,1-3*({dist})))")


def _effect_filters(
    effect: str | None,
    index: int,
    dur: float,
    beats: list[float] | None = None,
) -> str:
    """Post-geometry filter chain for a named segment effect ("" = none).

    Motion effects (shake/pulse/rotate) scale the canvas up a little first so
    the extra movement never exposes canvas edges, then crop every frame back
    to exactly OUT_W x OUT_H (SAR untouched, so 1:1 is preserved). Color
    effects are pure post-filters. When `beats` (relative to the segment's
    local clock) is present the motion amplitude is multiplied by a beating
    energy envelope, so the rendered motion physically punches on the
    reference music's beats. Expressions containing commas are escaped for
    the filter option parser.
    """
    kind = str(effect or "").lower()
    if not kind or kind == "none":
        return ""
    env = _beat_env_expr(beats)
    amp = f"(0.35+0.65*({env}))"
    if kind == "shake":
        phase = index * 1.7
        x = _escape_expr(
            f"(iw-{OUT_W})/2+{OUT_W * 0.014:.1f}*{amp}"
            f"*sin(2*PI*t*6+{phase:.2f})"
        )
        y = _escape_expr(
            f"(ih-{OUT_H})/2+{OUT_H * 0.014:.1f}*{amp}"
            f"*sin(2*PI*t*5.3+{phase + 1.1:.2f})"
        )
        return (
            "scale=w=trunc(iw*1.06/2)*2:h=trunc(ih*1.06/2)*2:eval=frame,"
            f"crop={OUT_W}:{OUT_H}:{x}:{y}"
        )
    if kind == "pulse":
        # factor stays in [1.0, 1.018] and is scaled by the beat envelope.
        scale = f"1+{amp}*(0.018*(0.5+0.5*sin(2*PI*t*2.4)))"
        return (
            f"scale=w=trunc(iw*({scale})/2)*2:h=trunc(ih*({scale})/2)*2"
            ":eval=frame,"
            f"crop={OUT_W}:{OUT_H}"
        )
    if kind == "rotate":
        return (
            f"rotate=0.05*{amp}*sin(2*PI*t/{max(dur, 0.4):.3f})"
            ":c=black:ow=iw:oh=ih,"
            "scale=w=trunc(iw*1.10/2)*2:h=trunc(ih*1.10/2)*2:eval=frame,"
            f"crop={OUT_W}:{OUT_H}"
        )
    if kind == "vignette":
        return "vignette=angle=PI/5"
    if kind == "brighten":
        return "eq=brightness=0.06:saturation=1.12"
    if kind == "moody":
        return "eq=contrast=1.12:saturation=0.85:brightness=-0.02"
    if kind == "bw":
        return "hue=s=0"
    return ""


def _eased_progress(dur: float) -> str:
    """Smoothstep-eased progress in [0,1] over `dur` seconds (Phase 3).

    Returns an FFmpeg expression: e = clip(t/dur, 0, 1); ease = e*e*(3-2e).
    Commas are escaped for the filter option parser (we never quote values,
    matching the escaping used by crop expressions).
    """
    e = _escape_expr(f"clip(t/{dur:.6f},0,1)")
    return f"({e})*({e})*(3-2*({e}))"


def _drift_axis(axis: str, index: int, dur: float) -> str:
    """Per-frame crop offset for one axis with eased Ken-Burns drift.

    The canvas-sized crop window is centered on the (per-frame) scaled input
    and eased +/- 40% of the available margin on the drifting axis, clamped
    to stay inside the frame at every timestamp.
    """
    margin = f"((iw-{OUT_W})" if axis == "x" else f"((ih-{OUT_H})"
    margin += ")"
    center = f"({margin}/2)"
    sign = "1.0" if index % 4 < 2 else "-1.0"
    drift = f"{center}+0.4*{margin}*{sign}*({_eased_progress(dur)}-0.5)"
    limit = f"iw-{OUT_W}" if axis == "x" else f"ih-{OUT_H}"
    return _escape_expr(f"max(0,min({drift},{limit}))")



def _input_options(is_image: bool) -> list[str]:
    """Input flags: loop a still at the output framerate, loop short videos."""
    if is_image:
        return ["-loop", "1", "-framerate", str(OUT_FPS)]
    return ["-stream_loop", "-1"]


def _portrait_cover_filter(
    w: int, h: int, zoom: float, index: int, dur: float
) -> str:
    """Cover-crop chain for portrait-ish assets (AR <= FIT_MAX_SOURCE_AR).

    Phase 3 motion: when a zoom is planned, the asset scale is animated
    per-frame (eval=frame) from cover to zoom-times cover (zoom-in) or the
    reverse (zoom-out) along a smoothstep ease, while a canvas-sized crop
    window drifts on one axis (alternating by segment index) through the
    available margin. SAR is normalized last.
    """
    z = max(1.0, min(float(zoom or 1.0), 1.2))
    if z <= 1.0001:
        return (
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase"
            ":force_divisible_by=2,"
            f"crop={OUT_W}:{OUT_H},"
            "setsar=1"
        )

    zoom_in = index % 2 == 0
    # Base scale S0 takes the asset to canvas cover; the eased factor only
    # animates the RELATIVE zoom (1.0 -> z, or z -> 1.0), so the scaled frame
    # is always at least canvas size and the crop window stays valid.
    s0 = max(OUT_W / w, OUT_H / h)
    grow = f"(1+({z - 1:.4f})*{_eased_progress(dur)})"
    shrink = f"(1+({z - 1:.4f})*(1-{_eased_progress(dur)}))"
    factor = grow if zoom_in else shrink
    x_expr = _drift_axis("x", index, dur) if zoom_in else f"((iw-{OUT_W})/2)"
    y_expr = _drift_axis("y", index, dur) if not zoom_in else f"((ih-{OUT_H})/2)"
    return (
        f"scale=w=ceil(iw*{s0:.6f}*{factor}/2)*2"
        f":h=ceil(ih*{s0:.6f}*{factor}/2)*2"
        ":flags=lanczos:eval=frame,"
        f"crop={OUT_W}:{OUT_H}:{x_expr}:{y_expr},"
        "setsar=1"
    )


def snap_segments_to_beats(
    segments: list[dict], beats: list[float] | None, tol: float = 0.12
) -> list[dict]:
    """Phase 6: snap internal cut points to detected beats.

    Contiguous boundaries (end of segment i == start of segment i+1) move to
    the nearest beat within `tol` seconds so visual cuts land exactly on the
    reference's music/beat timing. First/last edges stay fixed and segment
    durations remain valid (>= 0.2s).
    """
    if not beats:
        return segments
    beats_sorted = sorted(float(b) for b in beats)
    out = [dict(s) for s in segments]
    for i in range(len(out) - 1):
        try:
            end = float(out[i]["end"])
            start_next = float(out[i + 1]["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(end - start_next) > 0.001:
            continue  # not a contiguous boundary; leave it alone
        near = [b for b in beats_sorted if abs(b - end) <= tol]
        if not near:
            continue
        beat = min(near, key=lambda b: abs(b - end))
        try:
            start = float(out[i].get("start", 0.0))
            end_next = float(out[i + 1].get("end", end + 0.5))
        except (TypeError, ValueError):
            continue
        if beat - start >= 0.2 and end_next - beat >= 0.2:
            out[i]["end"] = round(beat, 6)
            out[i + 1]["start"] = round(beat, 6)
    return out


def assign_segment_roles(
    segments: list[dict], tracking: list[dict] | None
) -> list[dict]:
    """Level-5-lite: label each segment with a semantic role.

    "person" when the primary tracked subject is present somewhere inside the
    segment window (any tracking sample), "scene" otherwise. Roles drive
    orientation-aware asset mapping (portrait assets for people, wide assets
    for scenery).
    """
    points = [p for p in (tracking or []) if p.get("time") is not None]
    out = []
    for seg in segments:
        item = dict(seg)
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            item["role"] = "scene"
            out.append(item)
            continue
        present = any(start - 0.15 <= float(p["time"]) <= end + 0.15 for p in points)
        item["role"] = "person" if present else "scene"
        out.append(item)
    return out


def _default_mapping(
    segments: list[dict], assets: list[dict]
) -> dict[str, str]:
    """Phase 5/7-lite: automatic asset assignment when the user has not
    chosen one.

    Rules: ultra-short segments (< 0.6s) prefer still images (a video has no
    time to register), "person" segments prefer portrait assets and "scene"
    segments prefer wide ones, the same asset never repeats on consecutive
    segments while alternatives exist, and everything else round-robins.
    """
    mapping: dict[str, str] = {}
    prev_id: str | None = None
    for i, seg in enumerate(segments):
        try:
            dur = float(seg["end"]) - float(seg["start"])
        except (KeyError, TypeError, ValueError):
            dur = 1.0
        seg_id = str(seg.get("id", i))
        pool = list(assets or [])
        if dur < 0.6:
            images = [a for a in pool if a.get("kind") == "image"]
            if images:
                pool = images
        if seg.get("role") == "person":
            portrait = [a for a in pool if a.get("height", 0) > a.get("width", 0)]
            if portrait:
                pool = portrait
        elif seg.get("role") == "scene":
            wide = [a for a in pool if a.get("width", 0) >= a.get("height", 0)]
            if wide:
                pool = wide
        pick = next((a for a in pool if a.get("id") != prev_id), None)
        if pick is None:
            pick = pool[i % len(pool)] if pool else None
        if pick is not None:
            mapping[seg_id] = pick["id"]
            prev_id = pick["id"]
    return mapping


def distribute_all_assets(
    segments: list[dict], assets: list[dict], min_part: float = 0.4
) -> tuple[list[dict], dict[str, str]]:
    """Auto mode: guarantee EVERY uploaded asset appears at least once.

    When the user uploads more assets than the reference has segments, the
    longest segments are split equally (never below `min_part`) until there
    are at least as many slots as assets; assets are then round-robined in
    upload order. Split parts inherit zoom/effect/role, enter with a hard
    cut, and the first part keeps the original segment id. Ultra-short slots
    swap a still in for a video when one is available later in the timeline.
    Returns (expanded_segments, mapping).
    """
    segs = [dict(s) for s in segments]
    if not assets:
        return segs, {}

    def _dur(s: dict) -> float:
        try:
            return float(s["end"]) - float(s["start"])
        except (KeyError, TypeError, ValueError):
            return 1.0

    guard = 0
    while len(segs) < len(assets) and guard < 256:
        guard += 1
        best_i = -1
        best_dur = 0.0
        for i, s in enumerate(segs):
            d = _dur(s)
            if d > best_dur and d >= 2 * min_part:
                best_i, best_dur = i, d
        if best_i < 0:
            break  # nothing splittable left; some assets stay unused
        s = segs[best_i]
        mid = (float(s["start"]) + float(s["end"])) / 2
        second = dict(s)
        s["end"] = round(mid, 6)
        second["start"] = round(mid, 6)
        second["id"] = f"{s.get('id', best_i)}-p{guard}"
        second["transition"] = "cut"
        segs.insert(best_i + 1, second)

    mapping = {
        str(s.get("id", i)): assets[i % len(assets)]["id"]
        for i, s in enumerate(segs)
    }
    # Prefer stills on ultra-short slots: swap with a later video slot.
    for i, s in enumerate(segs):
        if _dur(s) >= 0.6:
            continue
        sid = str(s.get("id", i))
        a = next((x for x in assets if x["id"] == mapping[sid]), None)
        if not a or a.get("kind") != "video":
            continue
        for j in range(i + 1, len(segs)):
            if _dur(segs[j]) < 0.6:
                continue
            jid = str(segs[j].get("id", j))
            ja = next((x for x in assets if x["id"] == mapping[jid]), None)
            if ja and ja.get("kind") == "image":
                mapping[sid], mapping[jid] = mapping[jid], mapping[sid]
                break
    return segs, mapping


def render_asset_segment(
    asset: dict,
    duration: float,
    zoom: float,
    index: int,
    out: Path,
    effect: str | None = None,
    beats: list[float] | None = None,
    seg_start: float = 0.0,
) -> None:
    """Render one mapped asset as a single normalized 1080x1920 segment.

    Images are looped stills; videos loop when shorter than the segment
    (-stream_loop) and are trimmed when longer. Audio is never taken from
    assets - the reference audio is muxed afterwards. Wide assets go through
    the blur-pad fit graph so their full composition stays visible; portrait
    assets get eased zoom/drift motion (Phase 3). Per-segment effects
    (shake/pulse/rotate/vignette/brighten/moody/bw) are appended after the
    geometry chain. Transitions between parts are applied later at join time
    (xfade), not here.
    """
    dur = max(0.2, float(duration))
    w = int(asset.get("width") or 0) or OUT_W
    h = int(asset.get("height") or 0) or OUT_H
    path = str(asset.get("path") or "")
    if not path or not Path(path).exists():
        raise AssetRenderError(f"asset file missing: {path!r}")
    is_image = asset.get("kind") == "image"
    # Stills get a gentle default zoom so segments never sit static; videos
    # honor the plan zoom (extracted from the reference's own motion).
    if is_image:
        z = max(1.0, min(max(float(zoom or 1.0), 1.08), 1.2))
    else:
        z = max(1.0, min(float(zoom or 1.0), 1.2))
    fx = _effect_filters(effect, index, dur, _local_beats(beats, seg_start, dur))
    cmd = ["ffmpeg", "-y", "-v", "error"] + _input_options(is_image) + ["-i", path]

    if w / h > FIT_MAX_SOURCE_AR:
        graph = _fit_filtergraph(w, h, z)
        if fx:
            graph = graph[: -len("[vout]")] + "," + fx + "[vout]"
        cmd += [
            "-t", f"{dur:.6f}",
            "-filter_complex", graph,
            "-map", "[vout]",
        ]
    else:
        vf = _portrait_cover_filter(w, h, z, index, dur)
        if fx:
            vf += "," + fx
        cmd += ["-t", f"{dur:.6f}", "-vf", vf]

    cmd += ["-r", str(OUT_FPS), *ENCODER_ARGS, "-an", str(out)]
    try:
        _run(cmd)
    except RenderError as e:
        raise AssetRenderError(
            f"failed to render asset '{asset.get('name', path)}' "
            f"({w}x{h} {asset.get('kind', '?')}): {e}"
        ) from e


def _local_beats(
    beats: list[float] | None, seg_start: float, dur: float
) -> list[float] | None:
    """Shift reference beats into a segment's local clock (with a halo).

    Returns None when there is no beat data so effects keep their static
    amplitude; otherwise returns beats within [start-0.7, end+0.7] relative
    to the segment start (the halo keeps the envelope from clipping at the
    segment edges).
    """
    if not beats:
        return None
    start = float(seg_start)
    return [float(b) - start for b in beats if start - 0.7 <= float(b) <= start + float(dur) + 0.7]


def _join_run(work: Path, group: list) -> Path:
    """Join one run of parts with real xfade transitions (Phase 4).

    A run is a maximal sequence of segments whose entry transitions are
    xfade-able (fade/zoom/flash/slide/wipe/blur/dissolve). All parts of the
    run go into ONE ffmpeg command as separate inputs and are blended in a
    single filter_complex chain, so a whole run costs exactly one extra
    encode (never per-segment re-encoding). Each xfade overlaps its inputs,
    shortening the timeline; the caller trims the final mux to the plan
    length. A single-entry run is returned as-is (hard cut, zero encodes).
    """
    if len(group) == 1:
        return group[0][0]
    inputs: list[str] = []
    for entry in group:
        inputs += ["-i", str(entry[0])]
    chains: list[str] = []
    acc = float(group[0][1])
    prev_label = "0:v"
    for n, entry in enumerate(group[1:], start=1):
        dur = float(entry[1])
        td = _transition_duration(acc, dur)
        offset = max(0.0, acc - td)
        label = "vout" if n == len(group) - 1 else f"x{n}"
        chains.append(
            f"[{prev_label}][{n}:v]xfade=transition={_xfade_kind(entry[2])}"
            f":duration={td:.3f}:offset={offset:.3f}[{label}]"
        )
        acc = acc + dur - td
        prev_label = label
    out = work / f"run-{group[0][0].stem}.mp4"
    _run(
        ["ffmpeg", "-y", "-v", "error"]
        + inputs
        + [
            "-filter_complex", ";".join(chains),
            "-map", "[vout]",
            "-r", str(OUT_FPS),
            *ENCODER_ARGS,
            "-movflags", "+faststart",
            str(out),
        ]
    )
    return out


def render_recreation(
    reference: str | None,
    segments: list[dict],
    assets: list[dict],
    mapping: dict[str, str] | None,
    output: str,
    beats: list[float] | None = None,
) -> None:
    """Build the user's short: reference structure + mapped user assets.

    Phase 6: internal cut points are snapped to detected beats first (when
    `beats` is provided). mapping maps segment id -> asset id; unmapped
    segments fall back to the smart default assignment so a render always
    succeeds. The reference's audio track is muxed onto the final cut
    (music/beat timing preserved); without a reference the output is silent.
    """
    if not segments:
        raise ValueError("No segments to render")
    if not assets:
        raise ValueError("No user assets provided")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if reference and not Path(reference).exists():
        raise ValueError(f"reference video missing: {reference}")
    segments = snap_segments_to_beats(segments, beats)
    work = Path(tempfile.mkdtemp(prefix="shortforge-recreation-"))
    try:
        total = 0.0
        # 1) Render every segment from its mapped user asset.
        runs: list[list] = []  # entries: [part_path, duration, transition_in]
        for i, seg in enumerate(segments):
            try:
                start = float(seg["start"])
                end = float(seg["end"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"segment {i + 1} is missing valid start/end")
            dur = end - start
            if dur <= 0.05:
                continue
            asset_id = (mapping or {}).get(str(seg.get("id", "")))
            asset = next((a for a in assets if a.get("id") == asset_id), None)
            if asset is None:
                asset = assets[i % len(assets)]
            part = work / f"part-{i:04d}.mp4"
            render_asset_segment(
                asset,
                dur,
                float(seg.get("zoom", 1.0) or 1.0),
                i,
                part,
                effect=seg.get("effect"),
                beats=beats or None,
                seg_start=start,
            )
            runs.append([part, dur, str(seg.get("transition") or "cut")])
            total += dur
        if not runs:
            raise ValueError("No renderable segments")
        # 2) Join transition-runs (real xfades inside a run, cuts between).
        # A segment's `transition` describes how it ENTERS (the join between
        # it and the previous part), so a segment with an xfade-able
        # transition extends the current run; a cut/none segment starts a
        # new run after flushing the previous one.
        pieces: list[Path] = []
        group: list = []
        for entry in runs:
            if group and entry[2] in _XFADE:
                group.append(entry)
                continue
            if group:
                pieces.append(_join_run(work, group))
            group = [entry]
        if group:
            pieces.append(_join_run(work, group))
        # 3) Concat pieces (identical codec params -> stream copy), then mux
        # the reference audio over the visuals (no video re-encode). -t
        # trims the xfade overlaps back to the plan length; -shortest ends
        # the output with the (slightly shorter) visual stream.
        if len(pieces) == 1:
            final_visual = pieces[0]
        else:
            concat = work / "concat.txt"
            concat.write_text(
                "\n".join(_concat_quote(p) for p in pieces), encoding="utf-8"
            )
            final_visual = work / "joined.mp4"
            _run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", str(final_visual),
                ]
            )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(final_visual)]
        if reference:
            cmd += ["-i", str(reference)]
        cmd += ["-map", "0:v:0"]
        if reference:
            cmd += ["-map", "1:a:0?"]
        cmd += [
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-t", f"{total:.6f}",
            "-movflags", "+faststart",
        ]
        if reference:
            cmd += ["-shortest"]
        cmd += [str(out)]
        _run(cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)



