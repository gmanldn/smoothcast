"""Safe, bounded FFmpeg frame capture, independent from GTK."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
import math
import stat
import subprocess
import uuid


class SparseFrameCache:
    """Bounded GTK-thread-owned LRU: only quantised hover previews, never frame steps."""

    def __init__(self, interval: float = 10.0, max_entries: int = 96):
        if not math.isfinite(interval) or interval <= 0 or max_entries < 1:
            raise ValueError("Invalid thumbnail cache limits")
        self.interval = interval
        self.max_entries = max_entries
        self._images: OrderedDict[tuple[str, int, int, int], bytes] = OrderedDict()

    def bucket(self, position: float) -> int:
        if not isinstance(position, (int, float)) or not math.isfinite(position):
            return 0
        return min(10_000_000, int(max(0.0, position) // self.interval))

    def key(self, path: str, generation: int, stream: int, position: float) -> tuple[str, int, int, int]:
        return str(path), generation, stream, self.bucket(position)

    def sample(self, position: float) -> float:
        return self.bucket(position) * self.interval

    def get(self, key: tuple[str, int, int, int]) -> bytes | None:
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
        return image

    def put(self, key: tuple[str, int, int, int], image: bytes) -> None:
        if not isinstance(image, bytes) or not image.startswith(b"\xff\xd8"):
            return
        self._images[key] = image
        self._images.move_to_end(key)
        while len(self._images) > self.max_entries:
            self._images.popitem(last=False)


class CaptureError(RuntimeError):
    """A screenshot could not be captured."""


class FramePositionError(CaptureError):
    """A controlled explanation of why the visible frame cannot be located."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def owned_frame_time(
    source: Path, *, session: object | None, external: bool, tracker: object,
    local_video_path: str | None, local_stream: object | None,
    preview_path: str | None, preview_position: float,
) -> float:
    """Choose the timestamp of the *owned* visible film, never an unrelated row."""
    if external:
        raise FramePositionError("Cannot capture another application's TV stream")
    if session is not None:
        state = getattr(session, "state", None)
        if state is None or Path(getattr(state, "file", "")) != source:
            raise FramePositionError("Active film and media metadata do not match")
        position = tracker.value()
        if position is None:
            raise FramePositionError("Cannot capture: receiver position is unknown")
    elif local_video_path == str(source):
        try:
            stream = local_stream() if callable(local_stream) else local_stream
            timestamp = stream.get_timestamp() if stream is not None else -1
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            raise FramePositionError("Cannot capture: local playback position is unknown") from exc
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
            if preview_path != str(source):
                raise FramePositionError("Cannot capture: local playback position is unknown")
            position = preview_position
        else:
            position = timestamp / 1_000_000
    elif preview_path == str(source):
        position = preview_position
    else:
        raise FramePositionError("Select and preview a film before capturing")
    if (isinstance(position, bool) or not isinstance(position, (int, float))
            or not math.isfinite(position) or position < 0):
        raise FramePositionError("Cannot capture: playback position is invalid")
    return float(position)


def capture_frame(
    source: Path, position: float, directory: Path, *, timeout: int = 30,
    video_stream_index: int = 0,
) -> Path:
    """Capture one source frame without overwriting an existing picture.

    Called from a worker thread. Never call this on the GTK event loop.
    """
    source = Path(source).expanduser()
    directory = Path(directory).expanduser()
    # Verify filesystem metadata directly. Apart from avoiding TOCTOU-prone
    # path predicates, this remains correct when unrelated tests monkeypatch
    # Path.is_file globally.
    try:
        source_stat = source.stat()
    except OSError as exc:
        raise CaptureError(f"Source video is missing: {source.name}") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise CaptureError(f"Source is not a regular video file: {source.name}")
    if not math.isfinite(position):
        raise CaptureError("Invalid video position")
    if type(video_stream_index) is not int or video_stream_index < 0:
        raise CaptureError("Invalid video stream index")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CaptureError(f"Cannot create screenshot directory: {exc}") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"smoothcast_{stamp}_{uuid.uuid4().hex[:8]}.png"
    args = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-ss", str(max(0.0, position)), "-i", str(source),
        "-map", f"0:{video_stream_index}", "-frames:v", "1", str(target),
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
    try:
        output_stat = target.stat()
    except OSError:
        output_stat = None
    # FFmpeg can return 0 yet leave a zero-byte output or no file at all.
    # A bare Path.is_file() check isn't sufficient for that case.
    if (
        result.returncode != 0
        or output_stat is None
        or not stat.S_ISREG(output_stat.st_mode)
        or output_stat.st_size == 0
    ):
        target.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()
        raise CaptureError((detail[-1] if detail else "FFmpeg produced no image")[-240:])
    return target


def cover_art(source: Path, *, timeout: int = 8) -> bytes:
    """Extract a small JPEG of a track's embedded artwork, in memory only.

    Runs in a worker thread. Raises CaptureError when the file has no
    attached picture; it never reads a motion-video stream (#64).
    """
    source = Path(source).expanduser()
    try:
        info = source.stat()
    except OSError as exc:
        raise CaptureError(f"Source is missing: {source.name}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CaptureError(f"Source is not a regular file: {source.name}")
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-frames:v", "1", "-vf", "scale=480:480:force_original_aspect_ratio=decrease",
        "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise CaptureError("Cover art extraction timed out") from exc
    except OSError as exc:
        raise CaptureError(f"Cannot start FFmpeg: {exc}") from exc
    if result.returncode or not result.stdout.startswith(b"\xff\xd8"):
        raise CaptureError("No embedded cover art")
    return result.stdout


def preview_frame(source: Path, position: float, *, timeout: int = 12,
                  video_stream_index: int = 0) -> bytes:
    """Decode a small JPEG frame for the pre-cast scrubber, without writing files.

    This runs only in a worker thread. A bounded output resolution and timeout
    avoid decoding a full-resolution film frame on the GTK event loop.
    """
    source = Path(source).expanduser()
    try:
        info = source.stat()
    except OSError as exc:
        raise CaptureError(f"Source video is missing: {source.name}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CaptureError(f"Source is not a regular video file: {source.name}")
    if not isinstance(position, (int, float)) or not math.isfinite(position):
        raise CaptureError("Invalid preview position")
    if type(video_stream_index) is not int or video_stream_index < 0:
        raise CaptureError("Invalid video stream index")
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", str(max(0.0, position)), "-i", str(source),
        "-map", f"0:{video_stream_index}",
        "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", "scale=640:360:force_original_aspect_ratio=decrease",
        "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise CaptureError("Frame preview timed out") from exc
    except OSError as exc:
        raise CaptureError(f"Cannot start FFmpeg: {exc}") from exc
    if result.returncode or not result.stdout or not result.stdout.startswith(b"\xff\xd8"):
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise CaptureError((detail[-1] if detail else "No preview frame available")[-240:])
    return result.stdout
