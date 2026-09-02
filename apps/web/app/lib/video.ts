export function readVideoMetadata(
  file: File,
): Promise<{ duration: number; width: number; height: number; fps: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file),
      v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => {
      const fps = 30;
      resolve({
        duration: v.duration,
        width: v.videoWidth,
        height: v.videoHeight,
        fps,
      });
      URL.revokeObjectURL(url);
    };
    v.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Unable to read video metadata"));
    };
    v.src = url;
  });
}
export function makeSmartCrop(width: number, height: number) {
  const target = 9 / 16,
    source = width / height;
  if (source > target) {
    const cropWidth = Math.round(height * target);
    return {
      width: cropWidth,
      height,
      x: Math.round((width - cropWidth) / 2),
      y: 0,
    };
  }
  const cropHeight = Math.round(width / target);
  return {
    width,
    height: cropHeight,
    x: 0,
    y: Math.round((height - cropHeight) / 2),
  };
}
