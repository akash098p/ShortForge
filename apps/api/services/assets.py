"""User asset registry for the recreation engine.

Assets are the user's OWN photos/videos that get mapped into the segments of
a reference short ("recreate this viral short using my assets"). Files live
in apps/api/shortforge-assets/ (git-ignored) and are served by the /assets
static mount so the web UI can show previews.
"""

from pathlib import Path
import uuid

from services.media import ffprobe

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


class AssetError(ValueError):
    """Raised for unsupported or unreadable asset uploads."""


def classify(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    raise AssetError(f"Unsupported asset format: '{ext or filename}'")


def save_asset(filename: str, data: bytes, asset_dir: Path) -> dict:
    """Store one uploaded asset and return its probe descriptor."""
    kind = classify(filename)
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    target.write_bytes(data)
    return probe_asset(target, kind)


def probe_asset(path: Path, kind: str | None = None) -> dict:
    """Descriptor for one asset file (dimensions/duration best-effort)."""
    if kind is None:
        kind = "image" if path.suffix.lower() in IMAGE_EXTS else "video"
    width = height = 0
    duration = 0.0
    try:
        info = ffprobe(str(path))
        width, height, duration = info.width, info.height, info.duration
    except Exception:
        pass  # keep zeros rather than failing a whole listing upload
    return {
        "id": path.stem,
        "name": path.name,
        "path": str(path.resolve()),
        "kind": kind,
        "width": int(width),
        "height": int(height),
        "duration": float(duration),
        "url": f"/assets/{path.name}",
    }


def list_assets(asset_dir: Path) -> list[dict]:
    if not asset_dir.exists():
        return []
    out = []
    for p in sorted(asset_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
            out.append(probe_asset(p))
    return out
