from dataclasses import dataclass

@dataclass
class CropPoint:
    time: float
    x: float
    y: float

def center_crop(width: int, height: int) -> dict:
    target = 9 / 16
    if width / height >= target:
        crop_width = height * target
        return {"x": (width - crop_width) / 2, "y": 0, "width": crop_width, "height": height}
    crop_height = width / target
    return {"x": 0, "y": (height - crop_height) / 2, "width": width, "height": crop_height}

def build_reframe_track(width: int, height: int, duration: float, points: list[dict] | None = None) -> list[dict]:
    crop = center_crop(width, height)
    if points:
        return [{"time": float(p["time"]), "x": float(p["x"]), "y": float(p["y"])} for p in points]
    cx = crop["x"] + crop["width"] / 2
    cy = crop["y"] + crop["height"] / 2
    return [{"time": 0.0, "x": cx, "y": cy}, {"time": float(duration), "x": cx, "y": cy}]
