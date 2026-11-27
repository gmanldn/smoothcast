"""Sparse thumbnail strip and frame stepping for instant scrub previews (#40). GTK-free.

One bounded ffmpeg run writes every thumbnail for a file, so hovering the scrubber
looks frames up from disk instead of spawning a decoder per mouse move.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
import tempfile
from pathlib import Path

import media_tools

MAX_THUMBS = 120
MIN_INTERVAL = 5.0
WIDTH = 160


def interval_for(duration: float) -> float:
    """Seconds between thumbnails: at least MIN_INTERVAL, at most MAX_THUMBS frames."""
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return MIN_INTERVAL
    return max(MIN_INTERVAL, math.ceil(duration / MAX_THUMBS))


def nearest_index(position: float, interval: float, count: int) -> int:
    """Index of the thumbnail covering ``position``; clamped, NaN-safe."""
    if count <= 0:
        return 0
    if not isinstance(position, (int, float)) or not math.isfinite(position):
        return 0
    return min(count - 1, max(0, int(position // interval)))


def step_position(position: float, direction: int, fps: float, duration: float) -> float:
    """Position one frame forward (+1) or back (-1), clamped to the media."""
    step = 1.0 / fps if isinstance(fps, (int, float)) and math.isfinite(fps) and fps > 0 else 1 / 25
    target = position + (1 if direction >= 0 else -1) * step
    return min(max(0.0, target), max(0.0, duration))


def cache_dir(root: Path, source: Path, interval: float) -> Path:
    """Per-file directory keyed by path, size, mtime and interval (stale-proof)."""
    info = Path(source).stat()
    key = f"{Path(source).resolve()}|{info.st_size}|{int(info.st_mtime)}|{interval}"
    return Path(root) / "thumbs" / hashlib.sha256(key.encode()).hexdigest()[:20]


def build_strip(source: Path, duration: float, root: Path, *, timeout: int = 90) -> list[Path]:
    """Return cached thumbnail paths in order, generating them once. Worker thread only."""
    interval = interval_for(duration)
    out = cache_dir(root, source, interval)
    done = out / "done"
    if done.is_file():
        return sorted(out.glob("t*.jpg"))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=out.name + ".", dir=out.parent))
    command = [media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-nostdin",
               "-loglevel", "error", "-skip_frame", "nokey", "-i", str(source), "-an", "-sn",
               "-vf", f"fps=1/{interval:g},scale={WIDTH}:-2", "-q:v", "6",
               str(tmp / "t%04d.jpg")]
    try:
        subprocess.run(command, capture_output=True, timeout=timeout, check=True)
    except (subprocess.SubprocessError, OSError):
        _discard(tmp)
        return []
    frames = sorted(tmp.glob("t*.jpg"))
    if not frames:
        _discard(tmp)
        return []
    (tmp / "done").write_text("ok")
    try:
        tmp.rename(out)
    except OSError:  # a concurrent worker finished first
        _discard(tmp)
    return sorted(out.glob("t*.jpg")) if done.is_file() else []


def _discard(path: Path) -> None:
    for item in path.glob("*"):
        item.unlink(missing_ok=True)
    path.rmdir()
