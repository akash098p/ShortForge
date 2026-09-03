export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function uploadVideo(file: File) {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(API_BASE + "/v1/upload", { method: "POST", body });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ source_path: string; source_name: string }>;
}
export async function createEditPlan(input: {
  sourceName: string;
  sourcePath: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  preset: string;
}) {
  const r = await fetch(API_BASE + "/v1/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_name: input.sourceName,
      source_path: input.sourcePath,
      duration: input.duration,
      width: input.width,
      height: input.height,
      fps: input.fps,
      preset: input.preset,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function renderEditPlan(input: {
  sourcePath: string;
  segments: any[];
  captions: any[];
  reframe: any[];
  preset: string;
}) {
  const filename = `short-${Date.now()}.mp4`;
  const r = await fetch(API_BASE + "/v1/render-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_path: input.sourcePath,
      output_path: "shortforge-render/" + filename,
      segments: input.segments,
      captions: input.captions,
      reframe: input.reframe,
      preset: input.preset,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  return { ...data, preview_url: API_BASE + "/outputs/" + filename };
}

export type UploadedAsset = {
  id: string;
  name: string;
  path: string;
  kind: "image" | "video";
  width: number;
  height: number;
  duration: number;
  url: string;
};

export async function uploadAssets(files: File[]) {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  const r = await fetch(API_BASE + "/v1/assets", { method: "POST", body });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; assets: UploadedAsset[] }>;
}

export async function renderRecreation(input: {
  referencePath: string | null;
  segments: any[];
  assets: UploadedAsset[];
  mapping: Record<string, string>;
}) {
  const filename = `recreation-${Date.now()}.mp4`;
  const r = await fetch(API_BASE + "/v1/render-recreation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reference_path: input.referencePath,
      output_path: "shortforge-render/" + filename,
      segments: input.segments,
      assets: input.assets,
      mapping: input.mapping,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  return { ...data, preview_url: API_BASE + "/outputs/" + filename };
}
