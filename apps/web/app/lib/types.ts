export type EditPresetId = "viral" | "podcast" | "cinematic" | "energy";
export type EditSegment = {
  id: string;
  start: number;
  end: number;
  zoom: number;
  reason: string;
};
export type ProjectAnalysis = {
  duration: number;
  width: number;
  height: number;
  fps: number;
  segments: EditSegment[];
};
export type AutoEditRequest = {
  preset: EditPresetId;
  sourceName: string;
  duration: number;
};
