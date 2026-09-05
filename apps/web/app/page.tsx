"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Upload,
  WandSparkles,
  Sparkles,
  Scissors,
  Captions,
  SlidersHorizontal,
  CheckCircle2,
  Loader2,
  ImagePlus,
  Play,
  Pause,
  RefreshCw,
  Activity,
} from "lucide-react";
import { readVideoMetadata, makeSmartCrop } from "./lib/video";
import {
  createEditPlan,
  uploadVideo,
  renderEditPlan,
  uploadAssets,
  renderRecreation,
  type UploadedAsset,
  API_BASE,
} from "./lib/api";
type Preset = { id: string; name: string; desc: string; icon: any };
const presets: Preset[] = [
  {
    id: "viral",
    name: "Viral Shorts",
    desc: "Fast cuts · captions · zoom",
    icon: WandSparkles,
  },
  {
    id: "podcast",
    name: "Podcast",
    desc: "Speaker focus · captions",
    icon: Captions,
  },
  {
    id: "cinematic",
    name: "Cinematic",
    desc: "Clean · cinematic motion",
    icon: SlidersHorizontal,
  },
  {
    id: "energy",
    name: "High Energy",
    desc: "Punchy · beat-driven",
    icon: Scissors,
  },
];
const TRANSITIONS = [
  "cut",
  "fade",
  "zoom",
  "flash",
  "slideleft",
  "slideright",
  "slideup",
  "slidedown",
  "wipeleft",
  "wiperight",
  "circleopen",
  "pixelize",
  "rectcrop",
  "smoothup",
  "dissolve",
  "fadeblack",
  "blur",
];
const EFFECTS = [
  "none",
  "shake",
  "pulse",
  "rotate",
  "vignette",
  "brighten",
  "moody",
  "bw",
];
const MIN_SLOT_DUR = 0.4;

// Scene colors used both in the scene cards and the live bit-wave timeline.
const SCENE_COLORS = [
  "#8ec5ff",
  "#ffd166",
  "#7ae2b8",
  "#ff8fa3",
  "#c792ea",
  "#4dd2ff",
];

// Beat energy 0..1 at a playback time: triangular decay pulses after each
// detected beat plus a small pre-beat "swell" so effects anticipate the hit.
// Returns a neutral 0.6 (constant, mildly visible) when the beat wave is off
// or there is no beat data yet.
function beatEnergyAt(beats: number[], t: number, drive: boolean): number {
  if (!drive || !beats.length) return 0.6;
  let e = 0;
  for (let i = beats.length - 1; i >= 0; i--) {
    const d = t - beats[i];
    if (d > 0.8) break;
    if (d >= 0) e += Math.max(0, 1 - d * 2.6);
    else e += Math.max(0, 0.32 * (1 + d * 4));
  }
  return Math.min(1, e);
}

// Live CSS simulation of the selected scene's effect, scaled by beat energy.
// This is what makes the editing section a *live* operation: pick "shake" and
// the monitor instantly starts shaking to the beat wave.
function effectStyles(effect: string, e: number, frame: number) {
  const k = Math.max(0, e);
  switch (effect) {
    case "shake": {
      const x = Math.sin(frame * 0.62) * 11 * k;
      const y = Math.cos(frame * 0.48) * 9 * k;
      return {
        transform: `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) scale(1.05)`,
        filter: "none",
      };
    }
    case "pulse":
      return { transform: `scale(${(1 + 0.045 * k).toFixed(4)})`, filter: "none" };
    case "rotate": {
      const r = Math.sin(frame * 0.19) * 2.6 * k;
      return { transform: `rotate(${r.toFixed(2)}deg) scale(1.08)`, filter: "none" };
    }
    case "vignette":
      return {
        transform: "scale(1.02)",
        filter: `brightness(${(1 + 0.1 * k).toFixed(3)})`,
      };
    case "brighten":
      return {
        transform: "none",
        filter: `brightness(${(1 + 0.3 * k).toFixed(3)}) saturate(${(1 + 0.25 * k).toFixed(3)})`,
      };
    case "moody":
      return {
        transform: "none",
        filter: `contrast(1.12) saturate(${(0.85 - 0.18 * k).toFixed(3)}) brightness(${(1 - 0.14 * k).toFixed(3)})`,
      };
    case "bw":
      return {
        transform: "none",
        filter: `grayscale(1) contrast(${(1.1 + 0.18 * k).toFixed(3)})`,
      };
    default:
      return { transform: "none", filter: "none" };
  }
}

function fmtTime(t: number) {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
}

type WaveDatum = {
  beats: number[];
  segs: any[];
  duration: number;
  playhead: number;
  energy: number;
  selectedId: string | null;
};

// Bit-wave timeline: beat ticks + radiant ripples + ambient waveform + scene
// blocks + playhead, redrawn every animation frame while the preview plays.
function drawTimeline(cv: HTMLCanvasElement, o: WaveDatum) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = Math.max(80, cv.clientWidth || 0);
  const H = cv.clientHeight || 128;
  if (Math.abs(cv.width - Math.round(W * dpr)) > 1) cv.width = Math.round(W * dpr);
  if (Math.abs(cv.height - Math.round(H * dpr)) > 1) cv.height = Math.round(H * dpr);
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const dur = Math.max(o.duration, 1e-6);
  const px = (t: number) => (Math.max(0, Math.min(dur, t)) / dur) * W;
  // Ambient beat-wave envelope across the whole strip.
  const COLS = Math.max(60, Math.min(260, Math.floor(W / 4)));
  const amps = new Array(COLS).fill(0.1);
  for (const b of o.beats) {
    const ci = Math.floor((b / dur) * COLS);
    if (ci >= 0 && ci < COLS) amps[ci] += 0.55;
  }
  // Background grid.
  ctx.fillStyle = "rgba(255,255,255,0.035)";
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  const steps = Math.min(16, Math.max(1, Math.floor(dur / 0.5)));
  for (let i = 0; i <= steps; i++) {
    const x = Math.round(px((i / steps) * dur)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, 8);
    ctx.lineTo(x, H - 16);
    ctx.stroke();
  }
  const mid = H * 0.5;
  // Waveform bars (the "bit wave" ambient shape).
  const barW = W / COLS;
  for (let i = 0; i < COLS; i++) {
    const amp = Math.min(1, amps[i]);
    const h = 3 + amp * 46;
    const x = i * barW + 1;
    ctx.fillStyle = `rgba(184,255,77,${(0.22 + 0.5 * amp).toFixed(2)})`;
    ctx.fillRect(x, mid - h / 2, Math.max(1, barW - 2), h);
    ctx.fillStyle = `rgba(184,255,77,${(0.07 + 0.18 * amp).toFixed(2)})`;
    ctx.fillRect(x, mid + h / 2 - 5, Math.max(1, barW - 2), 5);
  }
  // Beat ticks + radiant ripples near the playhead.
  for (const b of o.beats) {
    const x = px(b);
    const age = o.playhead - b;
    const hot = age >= 0 && age < 0.5 ? Math.max(0, 1 - age * 2.2) * o.energy : 0;
    ctx.strokeStyle = `rgba(184,255,77,${(0.55 + 0.45 * hot).toFixed(2)})`;
    ctx.lineWidth = 1.5 + hot * 1.5;
    ctx.beginPath();
    ctx.moveTo(x, 10);
    ctx.lineTo(x, H * 0.74);
    ctx.stroke();
    if (hot > 0) {
      ctx.strokeStyle = `rgba(184,255,77,${(0.4 * (1 - hot)).toFixed(2)})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, mid, 2 + age * 58, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  // Scene blocks (reference plan) at the bottom.
  const blockY = H - 15;
  o.segs.forEach((s: any, i: number) => {
    const x0 = px(s.start || 0);
    const x1 = px(s.end || 0);
    const color = SCENE_COLORS[i % SCENE_COLORS.length];
    const sel = s.id === o.selectedId;
    ctx.fillStyle = sel ? "rgba(184,255,77,0.22)" : color + "22";
    ctx.strokeStyle = sel ? "#b8ff4d" : color;
    ctx.lineWidth = sel ? 2 : 1;
    const w = Math.max(1, x1 - x0 - 1);
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x0 + 1, blockY, w, 12, 3);
    } else {
      ctx.beginPath();
      ctx.rect(x0 + 1, blockY, w, 12);
    }
    ctx.fill();
    ctx.stroke();
    if (x1 - x0 > 20) {
      ctx.fillStyle = sel ? "#b8ff4d" : "rgba(255,255,255,0.8)";
      ctx.font = "9px Inter, ui-sans-serif, sans-serif";
      ctx.fillText(String(i + 1), x0 + 5, blockY + 9);
    }
  });
  // Playhead.
  const ph = px(o.playhead);
  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(ph, 4);
  ctx.lineTo(ph, H - 4);
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.moveTo(ph - 5, 3);
  ctx.lineTo(ph + 5, 3);
  ctx.lineTo(ph, 10);
  ctx.closePath();
  ctx.fill();
}

// Client-side mirror of the backend auto-spread: the longest scenes are split
// in half until there is a slot for every uploaded asset, then assets are
// dealt onto the slots longest-first (files are reused round-robin when there
// are more slots than files, so every upload always appears at least once).
function distributeAllAssets(
  segments: any[],
  assets: UploadedAsset[],
): { segments: any[]; mapping: Record<string, string> } {
  if (!assets.length || !segments.length) return { segments, mapping: {} };
  const slots = segments.map((s) => ({ ...s }));
  const parts: Record<string, number> = {};
  let guard = 0;
  while (slots.length < assets.length && guard++ < 128) {
    let idx = -1;
    let best = 2 * MIN_SLOT_DUR;
    slots.forEach((s, i) => {
      const d = (s.end || 0) - (s.start || 0);
      if (d > best) {
        best = d;
        idx = i;
      }
    });
    if (idx < 0) break;
    const s = slots[idx];
    const mid = (s.start || 0) + ((s.end || 0) - (s.start || 0)) / 2;
    const n = (parts[s.id] || 0) + 1;
    parts[s.id] = n;
    slots.splice(
      idx,
      1,
      { ...s, end: mid },
      { ...s, start: mid, id: `${s.id}-a${n}`, transition: "cut" },
    );
  }
  const order = slots
    .map((_, i) => i)
    .sort(
      (a, b) =>
        slots[b].end - slots[b].start - (slots[a].end - slots[a].start),
    );
  const mapping: Record<string, string> = {};
  order.forEach((slotIdx, i) => {
    mapping[slots[slotIdx].id] = assets[i % assets.length].id;
  });
  return { segments: slots, mapping };
}

export default function Home() {
  const input = useRef<HTMLInputElement>(null);
  const [video, setVideo] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState<any>(null);
  const [preset, setPreset] = useState("viral");
  const [status, setStatus] = useState("idle");
  const [sourcePath, setSourcePath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [plan, setPlan] = useState<any>(null);
  const [rendered, setRendered] = useState<string | null>(null);
  const assetInput = useRef<HTMLInputElement>(null);
  const [userAssets, setUserAssets] = useState<UploadedAsset[]>([]);
  const [slotAsset, setSlotAsset] = useState<Record<string, string>>({});
  const [autoMap, setAutoMap] = useState(true);
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  const [assetBusy, setAssetBusy] = useState(false);
  const [recreating, setRecreating] = useState(false);
  const [recreation, setRecreation] = useState<string | null>(null);
  const [transOverrides, setTransOverrides] = useState<Record<string, string>>({});
  const [effectSel, setEffectSel] = useState<Record<string, string>>({});
  const [durationEdits, setDurationEdits] = useState<Record<string, string>>({});
  const [splitAt, setSplitAt] = useState<Record<string, boolean>>({});
  const [extraScenes, setExtraScenes] = useState<
    { id: string; dur: number }[]
  >([]);
  // Live editor refs (driven via requestAnimationFrame without re-renders).
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const monitorFxRef = useRef<HTMLDivElement | null>(null);
  const vignetteRef = useRef<HTMLDivElement | null>(null);
  const transOverlayRef = useRef<HTMLDivElement | null>(null);
  const timecodeRef = useRef<HTMLSpanElement | null>(null);
  const beatMeterRef = useRef<HTMLDivElement | null>(null);
  const playheadRef = useRef(0);
  const energyRef = useRef(0.6);
  const frameRef = useRef(0);
  // Transport / live-FX state.
  const [playing, setPlaying] = useState(false);
  const [loopScene, setLoopScene] = useState(false);
  const [beatDrive, setBeatDrive] = useState(true);
  // Latest-state mirrors read by the rAF loop (input to the live preview).
  const latestBeats = useRef<number[]>([]);
  const latestSeqs = useRef<any[]>([]);
  const latestDur = useRef(0);
  const latestSel = useRef<string | null>(null);
  const latestEffect = useRef("none");
  const latestTrans = useRef("cut");
  const latestSeg = useRef<any | null>(null);
  const loopSceneRef = useRef(false);
  const beatDriveRef = useRef(true);
  // Live WYSIWYG timeline: manual splits -> auto-spread of every asset
  // (Auto mode) -> duration edits reflowed cumulatively so scenes stay
  // contiguous. The render call sends exactly these segments + mapping, so
  // what the grid shows is precisely what FFmpeg renders.
  const display = useMemo(() => {
    const base: any[] = plan?.segments || [];
    let segs: any[] = [];
    for (const s of base) {
      const d = (s.end || 0) - (s.start || 0);
      if (splitAt[s.id] && d >= 2 * MIN_SLOT_DUR) {
        const mid = (s.start || 0) + d / 2;
        segs.push({ ...s, end: mid });
        segs.push({ ...s, start: mid, id: `${s.id}-x1`, transition: "cut" });
      } else {
        segs.push({ ...s });
      }
    }
    // Appended scenes ("+ Add scene"): brand-new slots so more of the user's
    // files fit; they start unassigned (engine picks, or the user picks).
    for (const ex of extraScenes) {
      segs.push({ id: ex.id, start: 0, end: ex.dur, transition: "cut" });
    }
    let mapping: Record<string, string> = {};
    if (autoMap) {
      const spread = distributeAllAssets(segs, userAssets);
      segs = spread.segments;
      mapping = spread.mapping;
    } else {
      mapping = { ...slotAsset };
    }
    let t = segs.length ? segs[0].start || 0 : 0;
    segs = segs.map((s) => {
      // Duration edits are stored as raw typing strings and clamped here, so
      // the input never fights the user mid-keystroke.
      const parsed = parseFloat(durationEdits[s.id] ?? "");
      const base = Number.isNaN(parsed)
        ? (s.end || 0) - (s.start || 0)
        : parsed;
      const dur = Math.max(MIN_SLOT_DUR, Math.min(30, base));
      const out = { ...s, start: t, end: t + dur };
      t += dur;
      return out;
    });
    return { segs, mapping };
  }, [
    plan,
    autoMap,
    userAssets,
    slotAsset,
    splitAt,
    durationEdits,
    extraScenes,
  ]);
  const useCount = (assetId: string) =>
    Object.values(display.mapping).filter((id) => id === assetId).length;
  const onFile = async (f?: File) => {
    if (!f?.type.startsWith("video/")) return;
    setFile(f);
    setVideo(URL.createObjectURL(f));
    setMeta(await readVideoMetadata(f));
    setStatus("uploading");
    setError(null);
    try {
      const uploaded = await uploadVideo(f);
      setSourcePath(uploaded.source_path);
      setStatus("ready");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  };
  const autoEdit = async () => {
    if (!meta || !file || !sourcePath) return;
    setStatus("analyzing");
    setError(null);
    try {
      const result = await createEditPlan({
        sourceName: file.name,
        sourcePath,
        ...meta,
        preset,
      });
      setPlan(result);
      // Fresh plan -> drop edits tied to the old plan's segment ids.
      setSlotAsset({});
      setDurationEdits({});
      setSplitAt({});
      setExtraScenes([]);
      setSelectedSlot(null);
      setStatus("complete");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "Analysis failed");
    }
  };
  const renderShort = async () => {
    if (!plan || !sourcePath) return;
    setStatus("rendering");
    setError(null);
    try {
      const result = await renderEditPlan({
        sourcePath,
        segments: plan.segments || [],
        captions: plan.captions || [],
        reframe: plan.reframe || [],
        preset,
      });
      setRendered(
        result.preview_url?.startsWith("http")
          ? result.preview_url
          : "http://localhost:8000" + result.preview_url,
      );
      setStatus("rendered");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "Render failed");
    }
  };
  const onAssetFiles = async (files?: FileList | null) => {
    if (!files?.length) return;
    setAssetBusy(true);
    setError(null);
    try {
      const res = await uploadAssets(Array.from(files));
      const saved = res.assets.map((a) => ({ ...a, url: API_BASE + a.url }));
      setUserAssets((prev) => [...prev, ...saved]);
      // Auto mode ("use every file") is the default: the backend spreads
      // ALL uploaded assets across the timeline. Manual mapping only kicks
      // in when the user clicks specific slots below.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Asset upload failed");
    } finally {
      setAssetBusy(false);
    }
  };
  const recreateShort = async () => {
    if (!plan || !userAssets.length) return;
    setRecreating(true);
    setError(null);
    try {
      const result = await renderRecreation({
        referencePath: sourcePath,
        // WYSIWYG: send exactly the segments/mapping shown in the grid
        // (auto-spread split points, manual picks, duration edits, effects).
        segments: display.segs.map((s: any) => ({
          ...s,
          ...(transOverrides[s.id] ? { transition: transOverrides[s.id] } : {}),
          ...(effectSel[s.id] ? { effect: effectSel[s.id] } : {}),
        })),
        assets: userAssets,
        mapping: Object.keys(display.mapping).length ? display.mapping : null,
      });
      setRecreation(result.preview_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Recreation failed");
    } finally {
      setRecreating(false);
    }
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    onFile(e.dataTransfer.files?.[0]);
  };
  const crop = meta ? makeSmartCrop(meta.width, meta.height) : null;
  const totalDur = display.segs.reduce(
    (acc: number, s: any) => acc + Math.max(0, (s.end || 0) - (s.start || 0)),
    0,
  );
  // Beat data from the analyzer -> the live bit wave + beat-driven effects.
  const beats: number[] = useMemo(
    () =>
      Array.isArray(plan?.analysis?.beats)
        ? ((plan.analysis.beats as number[]) || []).filter(
            (b) => typeof b === "number" && Number.isFinite(b),
          )
        : [],
    [plan],
  );
  const timelineDur =
    meta?.duration ||
    (display.segs.length ? display.segs[display.segs.length - 1].end : 0);
  // The scene bound to the monitor: the user-selected slot, or nothing (raw
  // source clip). Selecting a slot makes its effect/transition live.
  const previewSeg = selectedSlot
    ? display.segs.find((s: any) => s.id === selectedSlot) ?? null
    : null;
  const previewEffect = previewSeg
    ? effectSel[previewSeg.id] || previewSeg.effect || "none"
    : "none";
  const previewTransition = previewSeg
    ? transOverrides[previewSeg.id] || previewSeg.transition || "cut"
    : "cut";
  // Keep the rAF loop reading the freshest UI state without re-renders.
  useEffect(() => {
    latestBeats.current = beats;
    latestSeqs.current = display.segs;
    latestDur.current = timelineDur;
    latestSel.current = selectedSlot;
    latestEffect.current = previewEffect;
    latestTrans.current = previewTransition;
    latestSeg.current = previewSeg;
    loopSceneRef.current = loopScene;
    beatDriveRef.current = beatDrive;
  });
  // Jump the monitor to a selected scene so its transition previews live.
  useEffect(() => {
    const v = videoRef.current;
    if (v && previewSeg && typeof previewSeg.start === "number" && Number.isFinite(previewSeg.start)) {
      v.currentTime = previewSeg.start;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSlot]);
  // The live editor loop: one requestAnimationFrame per frame mutates the
  // monitor + beat wave directly (no React re-renders), syncing effects and
  // transitions to the music's beat energy at the playhead.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      frameRef.current += 1;
      const v = videoRef.current;
      const t = v ? v.currentTime : playheadRef.current;
      if (!Number.isFinite(t)) return;
      playheadRef.current = t;
      const e = beatEnergyAt(latestBeats.current, t, beatDriveRef.current);
      energyRef.current = e;
      // 1) Live effect simulation on the monitor video.
      const fxEl = monitorFxRef.current;
      if (fxEl) {
        const st = effectStyles(latestEffect.current, e, frameRef.current);
        fxEl.style.transform = st.transform;
        fxEl.style.filter = st.filter;
      }
      const vg = vignetteRef.current;
      if (vg) {
        vg.style.opacity =
          latestEffect.current === "vignette" ? String(0.25 + 0.62 * e) : "0";
      }
      // 2) Live transition simulation at the selected scene's boundary.
      const ov = transOverlayRef.current;
      if (ov) {
        const seg = latestSeg.current;
        const moving = !v || !v.paused;
        let vis = false;
        if (seg && moving) {
          const tr = latestTrans.current;
          const segDur = Math.max(0.35, (seg.end || 0) - (seg.start || 0) || 0.35);
          const td = Math.min(0.22, 0.4 * segDur);
          const local = t - (seg.start || 0);
          if (tr !== "cut" && tr !== "none" && local >= 0 && local <= td) {
            const p = local / td;
            const k = Math.max(0, 1 - p);
            vis = true;
            ov.style.transform = "none";
            if (tr.includes("slide") || tr.includes("wipe")) {
              const outRight = tr.endsWith("right") || tr.endsWith("up");
              ov.style.background = "rgba(8,8,10,0.94)";
              ov.style.backdropFilter = "none";
              ov.style.transform = `translateX(${
                outRight ? 100 - k * 100 : -100 + k * 100
              }%)`;
              ov.style.opacity = "1";
            } else if (tr === "blur") {
              ov.style.background = "rgba(0,0,0,0.18)";
              ov.style.backdropFilter = `blur(${(k * 5).toFixed(1)}px)`;
              ov.style.opacity = "1";
            } else if (tr === "zoom") {
              ov.style.background = `radial-gradient(circle at 50% 50%, rgba(0,0,0,0) 55%, rgba(184,255,77,${(
                0.16 * k
              ).toFixed(2)}) 100%)`;
              ov.style.backdropFilter = "none";
              ov.style.opacity = "1";
            } else {
              const white = tr === "flash";
              ov.style.background = white
                ? "rgba(255,255,255,0.92)"
                : "rgba(0,0,0,0.88)";
              ov.style.backdropFilter = "none";
              ov.style.opacity = String((white ? 0.5 : 0.55) * k);
            }
          }
        }
        if (!vis) {
          ov.style.opacity = "0";
          ov.style.backdropFilter = "none";
        }
      }
      // 3) Scene loop + readouts.
      if (loopSceneRef.current && v && !v.paused) {
        const seg = latestSeg.current;
        if (seg && t >= (seg.end || 1e9) - 0.04) v.currentTime = seg.start || 0;
      }
      if (timecodeRef.current) timecodeRef.current.textContent = fmtTime(t);
      if (beatMeterRef.current) {
        const pct = Math.round(e * 100);
        beatMeterRef.current.style.width = pct + "%";
        beatMeterRef.current.style.opacity = String(0.55 + 0.45 * e);
      }
      // 4) Bit-wave timeline redraw.
      const cv = canvasRef.current;
      if (cv) {
        drawTimeline(cv, {
          beats: latestBeats.current,
          segs: latestSeqs.current,
          duration: latestDur.current,
          playhead: t,
          energy: e,
          selectedId: latestSel.current,
        });
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play();
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };
  const seekFromEvent = (clientX: number) => {
    const cv = canvasRef.current;
    if (!cv) return;
    const r = cv.getBoundingClientRect();
    const dur = latestDur.current;
    if (dur <= 0 || r.width <= 0) return;
    const t = Math.max(0, Math.min(dur, ((clientX - r.left) / r.width) * dur));
    playheadRef.current = t;
    const v = videoRef.current;
    if (v) v.currentTime = t;
  };
  const onWavePointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    seekFromEvent(e.clientX);
  };
  const onWavePointerMove = (e: React.PointerEvent) => {
    if (e.buttons & 1) seekFromEvent(e.clientX);
  };
  return (
    <main className="shell">
      <header>
        <div className="brand">
          <div className="logo">S</div>
          <div>
            <b>ShortForge</b>
            <span>AI SHORT-FORM EDITOR</span>
          </div>
        </div>
        <button className="ghost">Projects</button>
      </header>
      <section className="hero">
        <div>
          <p className="eyebrow">CREATE • EDIT • EXPORT</p>
          <h1>
            Turn raw footage into <em>scroll-stopping</em> Shorts.
          </h1>
          <p className="sub">
            Smart cuts, dynamic reframing, captions and motion — built for
            high-quality 9:16 video.
          </p>
          <div className="actions">
            <button className="primary" onClick={() => input.current?.click()}>
              <Upload size={18} /> {file ? "Replace video" : "Upload video"}
            </button>
            {file && (
              <button className="secondary" onClick={autoEdit}>
                {status === "analyzing" ? (
                  <>
                    <Loader2 className="spin" size={17} /> Analyzing…
                  </>
                ) : status === "complete" ? (
                  <>
                    <CheckCircle2 size={17} /> Edit plan ready
                  </>
                ) : status === "rendering" ? (
                  <>
                    <Loader2 className="spin" size={17} /> Rendering…
                  </>
                ) : status === "rendered" ? (
                  <>
                    <CheckCircle2 size={17} /> Render complete
                  </>
                ) : status === "error" ? (
                  <>
                    <Sparkles size={17} /> Retry Auto Edit
                  </>
                ) : (
                  <>
                    <Sparkles size={17} /> Auto Edit
                  </>
                )}
              </button>
            )}
          </div>
          {status === "complete" && (
            <button className="secondary" onClick={renderShort}>
              <Sparkles size={17} /> Render Short
            </button>
          )}
          {status === "complete" && (
            <button
              className="ghost"
              onClick={() => assetInput.current?.click()}
              disabled={assetBusy}
            >
              <ImagePlus size={17} />
              {assetBusy
                ? "Uploading assets…"
                : userAssets.length
                  ? `My assets (${userAssets.length})`
                  : "Add my photos / videos"}
            </button>
          )}
          {status === "complete" && userAssets.length > 0 && (
            <button
              className="primary"
              onClick={recreateShort}
              disabled={recreating}
            >
              {recreating ? (
                <>
                  <Loader2 className="spin" size={18} /> Building your Short…
                </>
              ) : (
                <>
                  <WandSparkles size={18} /> Recreate with my assets
                </>
              )}
            </button>
          )}
          {status === "rendering" && (
            <div className="meta">Rendering your Short…</div>
          )}
          {status === "rendered" && rendered && (
            <div className="result">
              <p className="eyebrow">RESULT</p>
              <h2>Rendered Short</h2>
              <video src={rendered} controls autoPlay playsInline />
              <a
                className="secondary"
                href={rendered}
                download="shortforge-short.mp4"
              >
                Download Short
              </a>
            </div>
          )}
          {recreation && (
            <div className="result">
              <p className="eyebrow">RECREATION</p>
              <h2>Your Short — recreated with my assets</h2>
              <video src={recreation} controls autoPlay playsInline />
              <a
                className="secondary"
                href={recreation}
                download="shortforge-recreation.mp4"
              >
                Download
              </a>
            </div>
          )}
          {error && <div className="meta">{error}</div>}
          <input
            ref={input}
            hidden
            type="file"
            accept="video/*"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          <input
            ref={assetInput}
            hidden
            type="file"
            multiple
            accept="image/*,video/*"
            onChange={(e) => {
              onAssetFiles(e.target.files);
              e.target.value = "";
            }}
          />
          {meta && (
            <div className="meta">
              {Math.round(meta.duration * 10) / 10}s · {meta.width}×
              {meta.height} · 9:16 crop {crop?.width}×{crop?.height}
            </div>
          )}
        </div>
        <div className="stage">
          <div className="monitor">
            <div
              className={"phone dropzone phone-live " + (drag ? "drag" : "")}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={onDrop}
            >
              {video ? (
                <div className="fx-stage" ref={monitorFxRef}>
                  <video
                    ref={videoRef}
                    src={video}
                    autoPlay
                    muted
                    playsInline
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                  />
                  <div className="fx-vignette" ref={vignetteRef} />
                  <div className="fx-flash" ref={transOverlayRef} />
                </div>
              ) : (
                <div className="empty">
                  <WandSparkles size={34} />
                  <strong>Your Short preview</strong>
                  <span>Upload footage to begin</span>
                </div>
              )}
              {video && (
                <div className="monitor-chips">
                  <span className="live-chip live">● Live</span>
                  {previewSeg ? (
                    <>
                      <span className="live-chip fx" title="Live effect preview">
                        fx · {previewEffect}
                      </span>
                      <span
                        className="live-chip tx"
                        title="Live transition preview"
                      >
                        in · {previewTransition}
                      </span>
                    </>
                  ) : (
                    <span className="live-chip tx">full clip</span>
                  )}
                </div>
              )}
            </div>
            {video && (
              <div className="plex-row">
                <button
                  className="plex-btn"
                  onClick={togglePlay}
                  title={playing ? "Pause preview" : "Play preview"}
                >
                  {playing ? <Pause size={15} /> : <Play size={15} />}
                </button>
                <span className="timecode" ref={timecodeRef}>
                  0:00.0
                </span>
                <div className="beat-meter" title="Beat wave energy">
                  <div className="beat-fill" ref={beatMeterRef} />
                </div>
                <button
                  className={"plex-btn " + (loopScene ? "on" : "")}
                  title="Loop the selected scene"
                  disabled={!previewSeg}
                  onClick={() => setLoopScene((v) => !v)}
                >
                  <RefreshCw size={14} />
                </button>
                <button
                  className={"plex-btn " + (beatDrive ? "on" : "")}
                  title="Drive effects with the music's beat wave"
                  onClick={() => setBeatDrive((v) => !v)}
                >
                  <Activity size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
      <section className="workspace">
        <div className="section-head">
          <div>
            <p className="eyebrow">AUTO EDIT</p>
            <h2>Choose a starting style</h2>
          </div>
        </div>
        <div className="presets">
          {presets.map((p) => {
            const Icon = p.icon;
            return (
              <button
                key={p.id}
                className={preset === p.id ? "preset active" : "preset"}
                onClick={() => setPreset(p.id)}
              >
                <div className="preset-icon">
                  <Icon />
                </div>
                <b>{p.name}</b>
                <span>{p.desc}</span>
              </button>
            );
          })}
        </div>
        {plan && userAssets.length > 0 && (
          <>
            <div className="section-head">
              <div>
                <p className="eyebrow">ASSET MAPPING</p>
                <h2>My assets → reference segments</h2>
              </div>
            </div>
            <div className="mode-toggle">
              <button
                className={autoMap ? "chip active" : "chip"}
                onClick={() => {
                  setAutoMap(true);
                  setSelectedSlot(null);
                }}
              >
                Auto (use all {userAssets.length})
              </button>
              <button
                className={!autoMap ? "chip active" : "chip"}
                onClick={() => setAutoMap(false)}
              >
                Manual
              </button>
            </div>
            <p className="hint">
              {autoMap
                ? `Every uploaded file is dealt across the timeline automatically (long scenes split to make room) — the grid below shows exactly what will render. Total: ${totalDur.toFixed(1)}s`
                : "Click a scene to pick its image or video — reuse any file as many times as you want, set its duration, split it, or use “+ Add scene” below for extra layers."}
            </p>
            <div className="asset-strip">
              {userAssets.map((a) => (
                <div
                  key={a.id}
                  className="asset-chip clickable"
                  role="button"
                  tabIndex={0}
                  title={selectedSlot ? "Assign this asset to the selected scene" : "Select a scene below, then click an asset"}
                  onClick={() => {
                    if (selectedSlot) {
                      setAutoMap(false);
                      setSlotAsset((m) => ({ ...m, [selectedSlot]: a.id }));
                    }
                  }}
                >
                  {a.kind === "image" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={a.url} alt={a.name} />
                  ) : (
                    <video src={a.url} muted playsInline />
                  )}
                  <small>
                    {a.kind}
                    {useCount(a.id) > 0 ? ` ×${useCount(a.id)}` : ""}
                  </small>
                </div>
              ))}
            </div>
            <div className="slot-grid">
              {display.segs.map((s: any, i: number) => {
                const dur = Math.max(0, (s.end || 0) - (s.start || 0));
                const asset = userAssets.find(
                  (x) => x.id === display.mapping[s.id],
                );
                const pickable = !autoMap && selectedSlot === s.id;
                const canSplit =
                  !autoMap &&
                  dur >= 2 * MIN_SLOT_DUR &&
                  !/-[ax]\d+$/.test(s.id);
                return (
                  <div
                    key={s.id || i}
                    className={"slot-card" + (selectedSlot === s.id ? " sel" : "")}
                    onClick={() =>
                      setSelectedSlot(s.id === selectedSlot ? null : s.id)
                    }
                  >
                    <div className="slot-thumb">
                      {asset ? (
                        asset.kind === "image" ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={asset.url} alt={asset.name} />
                        ) : (
                          <video src={asset.url} muted playsInline />
                        )
                      ) : (
                        <span>auto</span>
                      )}
                      <b>#{i + 1}</b>
                    </div>
                    {pickable && (
                      <div
                        className="slot-picker"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {userAssets.map((a) => (
                          <button
                            key={a.id}
                            className="mini-asset"
                            title={a.name}
                            onClick={() =>
                              setSlotAsset((m) => ({ ...m, [s.id]: a.id }))
                            }
                          >
                            {a.kind === "image" ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={a.url} alt={a.name} />
                            ) : (
                              <video src={a.url} muted playsInline />
                            )}
                          </button>
                        ))}
                        <button
                          className="mini-clear"
                          title="Let the engine choose for this scene"
                          onClick={() =>
                            setSlotAsset((m) => {
                              const next = { ...m };
                              delete next[s.id];
                              return next;
                            })
                          }
                        >
                          clear
                        </button>
                      </div>
                    )}
                    <div className="slot-meta">
                      <span>
                        {dur.toFixed(1)}s
                        {s.role === "person" ? " person" : s.role === "scene" ? " scene" : ""}
                      </span>
                      <span
                        className="beat-tag"
                        title="Beat energy of this scene (0–100)"
                      >
                        <i
                          style={{
                            width: `${Math.round(
                              Math.min(1, Number(s.beat_intensity) || 0) * 100,
                            )}%`,
                          }}
                        />
                      </span>
                      <label
                        className="slot-timing"
                        title="How long this scene stays on screen"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="text"
                          inputMode="decimal"
                          placeholder={dur.toFixed(1)}
                          value={durationEdits[s.id] ?? dur.toFixed(1)}
                          onChange={(e) =>
                            setDurationEdits((m) => ({
                              ...m,
                              [s.id]: e.target.value.replace(/[^0-9.]/g, ""),
                            }))
                          }
                        />
                        <span>s</span>
                      </label>
                      {canSplit && (
                        <button
                          className="slot-split"
                          title="Cut this scene in half so another asset can fit"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSplitAt((m) => ({ ...m, [s.id]: !m[s.id] }));
                          }}
                        >
                          {splitAt[s.id] ? "unsplit" : "split"}
                        </button>
                      )}
                      {s.id.startsWith("ext-") && (
                        <button
                          className="slot-split"
                          title="Remove this added scene"
                          onClick={(e) => {
                            e.stopPropagation();
                            setExtraScenes((xs) =>
                              xs.filter((x) => x.id !== s.id),
                            );
                          }}
                        >
                          remove
                        </button>
                      )}
                      <select
                        className="trans-select"
                        title="Transition into this scene"
                        value={transOverrides[s.id] || s.transition || "cut"}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => {
                          setSelectedSlot(s.id);
                          setTransOverrides((m) => ({
                            ...m,
                            [s.id]: e.target.value,
                          }));
                        }}
                      >
                        {TRANSITIONS.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      <select
                        className="trans-select"
                        title="Visual effect for this scene"
                        value={effectSel[s.id] || "none"}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => {
                          setSelectedSlot(s.id);
                          setEffectSel((m) => ({ ...m, [s.id]: e.target.value }));
                        }}
                      >
                        {EFFECTS.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                );
              })}
            </div>
            <button
              className="add-scene"
              title="Append a brand-new scene to the end of the timeline"
              onClick={() =>
                setExtraScenes((xs) => [
                  ...xs,
                  { id: `ext-${Date.now()}`, dur: 2 },
                ])
              }
            >
              + Add scene (2s)
            </button>
          </>
        )}
        <div className="timeline">
          <div className="timeline-top">
            <span>Timeline · beat wave</span>
            <span>
              {presets.find((p) => p.id === preset)?.name}
              {beats.length > 0 && <> · {beats.length} beats mapped</>}
            </span>
          </div>
          <div
            className="wave-shell"
            onPointerDown={onWavePointerDown}
            onPointerMove={onWavePointerMove}
          >
            <canvas ref={canvasRef} className="wave-canvas" />
            {!file && (
              <div className="wave-empty">
                Upload a video to see its beat wave
              </div>
            )}
          </div>
          <div className="track">
            {file ? (
              <div className="clip" style={{ width: "100%" }}>
                <span>SOURCE FOOTAGE</span>
                {status === "complete" && <small>AUTO EDIT PLAN READY</small>}
              </div>
            ) : (
              <div className="track-empty">
                Upload a video to populate the timeline
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
