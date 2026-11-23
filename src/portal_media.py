"""Authenticated media delivery from the host to a room screen.

Two routes, both GTK-free and both bounded:

* **direct** — ranged ``GET``/``HEAD`` of a regular file the browser can decode;
* **transcode** — a progressive fragmented-MP4 stream produced by the host's
  FFmpeg for formats the browser cannot decode. The child process is killed the
  moment the client goes away, at most ``MAX_TRANSCODES`` run at once and they
  run at below-normal priority so the desktop stays responsive.

The caller has already authenticated the participant and resolved an opaque
queue ID to a path on the GTK thread. This module re-validates the file at
open time (regular file, no symlink swap) and never reveals the path.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
from typing import BinaryIO, Callable

import process_priority

CHUNK = 64 * 1024
MAX_STREAMS = 8
MAX_TRANSCODES = 2
MAX_START_SECONDS = 24 * 60 * 60
_RANGE = re.compile(r"^bytes=(\d{0,18})-(\d{0,18})$")
_streams = threading.BoundedSemaphore(MAX_STREAMS)
_transcodes = threading.BoundedSemaphore(MAX_TRANSCODES)


class MediaError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def can_transcode() -> bool:
    return ffmpeg_path() is not None


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return inclusive ``(first, last)`` for a single satisfiable byte range.

    ``None`` means "no Range header, send everything". Raises ``MediaError(416)``
    for a malformed, multi-part or unsatisfiable range.
    """
    if header is None or not header.strip():
        return None
    match = _RANGE.fullmatch(header.strip())
    if match is None:
        raise MediaError(416, "Unsupported range")
    first_text, last_text = match.groups()
    if not first_text and not last_text:
        raise MediaError(416, "Unsupported range")
    if not first_text:                      # suffix range: last N bytes
        count = int(last_text)
        if count <= 0 or size <= 0:
            raise MediaError(416, "Range not satisfiable")
        return max(0, size - count), size - 1
    first = int(first_text)
    last = int(last_text) if last_text else size - 1
    if first >= size or last < first:
        raise MediaError(416, "Range not satisfiable")
    return first, min(last, size - 1)


def open_regular(path: str | os.PathLike[str]) -> tuple[BinaryIO, int]:
    """Open *path* read-only, refusing symlinks, devices and directories."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError:
        raise MediaError(404, "That media is no longer available") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MediaError(404, "That media is no longer available")
        return os.fdopen(fd, "rb", buffering=0), info.st_size
    except BaseException:
        os.close(fd)
        raise


class _Slot:
    """Context manager for a non-blocking semaphore acquisition."""

    def __init__(self, semaphore: threading.BoundedSemaphore, busy: str) -> None:
        self._semaphore = semaphore
        self._busy = busy

    def __enter__(self) -> "_Slot":
        if not self._semaphore.acquire(blocking=False):
            raise MediaError(503, self._busy)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._semaphore.release()


def stream_slot() -> _Slot:
    return _Slot(_streams, "The host is serving as many streams as it can")


def transcode_slot() -> _Slot:
    return _Slot(_transcodes, "The host is already converting the maximum number "
                              "of streams")


def file_generation(info: os.stat_result) -> str:
    """Opaque, cheap change detector for one open file; not a content digest.

    fstat rather than path.stat ties identity to the descriptor being served.
    The file may still change in place without reliable timestamps on unusual
    filesystems; a full digest is intentionally not computed on the hot path.
    """
    identity = (info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)
    return hashlib.sha256(repr(identity).encode("ascii")).hexdigest()


def serve_direct(handler, path: str | os.PathLike[str], mime: str, *,
                 head: bool = False,
                 mesh_generation: bool = False,
                 write_headers: Callable[[int, dict], None]) -> None:
    """Send one file (or one byte range of it) to *handler*'s socket."""
    file, size = open_regular(path)
    with file:
        try:
            span = parse_range(handler.headers.get("Range"), size)
        except MediaError as exc:
            write_headers(exc.status, {"Content-Range": f"bytes */{size}",
                                       "Content-Length": "0"})
            return
        if span is None:
            first, last, status = 0, size - 1, 200
        else:
            (first, last), status = span, 206
        length = max(0, last - first + 1) if size else 0
        headers = {"Content-Type": mime, "Content-Length": str(length),
                   "Accept-Ranges": "bytes"}
        if mesh_generation:
            headers["X-SmoothCast-Generation"] = file_generation(os.fstat(file.fileno()))
        if status == 206:
            headers["Content-Range"] = f"bytes {first}-{last}/{size}"
        write_headers(status, headers)
        if head or length == 0:
            return
        file.seek(first)
        remaining = length
        while remaining > 0:
            chunk = file.read(min(CHUNK, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except OSError:
                return
            remaining -= len(chunk)


def ffmpeg_command(ffmpeg: str, path: str, kind: str, start: float) -> list[str]:
    """Argument list for a progressive fragmented-MP4 stream on stdout."""
    start = min(max(0.0, float(start)), MAX_START_SECONDS)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start:
        command += ["-ss", f"{start:.3f}"]
    # "file:" pins FFmpeg to the local filesystem, whatever the name looks like.
    command += ["-i", "file:" + os.path.abspath(str(path))]
    if kind == "video":
        command += [
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-vf", "scale='min(1280,iw)':-2", "-profile:v", "main",
            "-c:a", "aac", "-ac", "2", "-b:a", "160k",
        ]
    else:
        command += ["-vn", "-sn", "-dn", "-map", "0:a:0",
                    "-c:a", "aac", "-ac", "2", "-b:a", "192k"]
    command += ["-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", "pipe:1"]
    return command


def serve_transcode(handler, path: str | os.PathLike[str], kind: str,
                    start: float, mime: str, *,
                    write_headers: Callable[[int, dict], None],
                    head: bool = False,
                    popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
    """Stream FFmpeg output; the child never outlives the client connection."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise MediaError(503, "The host cannot convert media (FFmpeg is missing)")
    # Validate the source exactly as direct play does, then hand FFmpeg the
    # already-checked path rather than any client-supplied string.
    file, _size = open_regular(path)
    file.close()
    # Unknown total length, so no Content-Length: the connection closes at end.
    headers = {"Content-Type": mime, "X-Accel-Buffering": "no"}
    if head:
        write_headers(200, {"Content-Type": mime})
        return
    with transcode_slot():
        proc = popen(
            ffmpeg_command(ffmpeg, str(path), kind, start),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True,
            **process_priority.launch_kwargs())
        process_priority.lower(proc)
        try:
            assert proc.stdout is not None
            first = proc.stdout.read(CHUNK)
            if not first:
                raise MediaError(502, "The host could not convert that media")
            write_headers(200, headers)
            chunk = first
            while chunk:
                try:
                    handler.wfile.write(chunk)
                except OSError:
                    return
                chunk = proc.stdout.read(CHUNK)
        finally:
            _reap(proc)


def _reap(proc: subprocess.Popen) -> None:
    """Terminate and collect a child; never leave a zombie or an encoder."""
    try:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def safe_suffix(path: str | os.PathLike[str]) -> str:
    return Path(os.fspath(path)).suffix.lower()
