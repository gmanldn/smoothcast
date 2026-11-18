"""Safe, bounded FFmpeg frame capture, independent from GTK."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import math
import subprocess
import uuid


class CaptureError(RuntimeError):
    """A screenshot could not be captured."""


def capture_frame(
    source: Path, position: float, directory: Path, *, timeout: int = 30,
) -> Path:
    """Capture one source frame without overwriting an existing picture.

    Called from a worker thread. Never call this on the GTK event loop.
    """
    source = Path(source).expanduser()
    directory = Path(directory).expanduser()
    if not source.is_file():
        raise CaptureError(f"Source video is missing: {source.name}")
    if not math.isfinite(position):
        raise CaptureError("Invalid video position")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CaptureError(f"Cannot create screenshot directory: {exc}") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"smoothcast_{stamp}_{uuid.uuid4().hex[:8]}.png"
    args = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-ss", str(max(0.0, position)), "-i", str(source),
        "-frames:v", "1", str(target),
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise CaptureError(f"FFmpeg exceeded {timeout}s") from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise CaptureError(f"Cannot start FFmpeg: {exc}") from exc
    if result.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()
        raise CaptureError((detail[-1] if detail else "FFmpeg produced no image")[-240:])
    return target
