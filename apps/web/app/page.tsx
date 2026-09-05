"use client";
import { useMemo, useRef, useState } from "react";
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
          <div
            className={"phone dropzone " + (drag ? "drag" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
          >
            {video ? (
              <video src={video} controls autoPlay muted />
            ) : (
              <div className="empty">
                <WandSparkles size={34} />
                <strong>Your Short preview</strong>
                <span>Upload footage to begin</span>
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
                        onChange={(e) =>
                          setTransOverrides((m) => ({ ...m, [s.id]: e.target.value }))
                        }
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
                        onChange={(e) =>
                          setEffectSel((m) => ({ ...m, [s.id]: e.target.value }))
                        }
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
            <span>Timeline</span>
            <span>{presets.find((p) => p.id === preset)?.name}</span>
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
