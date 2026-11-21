"""Private, bounded-buffer staging for files uploaded through the LAN portal."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time
import unicodedata
from typing import BinaryIO

import cache_privacy

CHUNK_SIZE = 2 * 1024 * 1024
READ_SIZE = 64 * 1024
MAX_UPLOAD_BYTES = 1 << 40  # 1 TiB; available disk space is the practical limit.
MAX_AUDIO_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 24 * 60 * 60
MAX_ACTIVE_UPLOADS = 3
MIN_FREE_BYTES = 512 * 1024 * 1024
PARTIAL_TTL_SECONDS = 24 * 60 * 60
VIDEO_SUFFIXES = frozenset({
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".ts", ".mpeg", ".mpg", ".wmv",
})
AUDIO_SUFFIXES = frozenset({
    ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aiff", ".aif",
})
# Start casting while a large upload is still arriving, once this much is
# buffered. FFmpeg transcodes with ``-readrate``, so on a LAN the transfer
# stays well ahead of playback and never catches the end of the file.
EARLY_CAST_MIN_BYTES = 16 * 1024 * 1024
_EARLY_CAST_SUFFIXES = frozenset({".mkv", ".ts", ".webm", ".mpeg", ".mpg"})
_INDEXED_SUFFIXES = frozenset({".mp4", ".m4v", ".mov"})
_MP4_SCAN_LIMIT = 64 * 1024 * 1024
_CONTENT_RANGE = re.compile(r"bytes ([0-9]{1,13})-([0-9]{1,13})/([0-9]{1,13})\Z")
_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{32}\Z")


def _mp4_index_at_front(path: Path) -> bool:
    """True when ``moov`` precedes ``mdat`` in a (possibly partial) MP4/MOV.

    Only box headers are read, and the scan stops at the first ``moov`` or
    ``mdat``, so it stays bounded while the file is still being written.
    """
    try:
        with open(path, "rb") as handle:
            scanned = 0
            while scanned < _MP4_SCAN_LIMIT:
                header = handle.read(8)
                if len(header) < 8:
                    return False
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                header_len = 8
                if size == 1:
                    extended = handle.read(8)
                    if len(extended) < 8:
                        return False
                    size = int.from_bytes(extended, "big")
                    header_len = 16
                if size < header_len:
                    return False
                if kind == b"moov":
                    return True
                if kind == b"mdat":
                    return False
                handle.seek(size - header_len, os.SEEK_CUR)
                scanned += size
            return False
    except OSError:
        return False


def is_progressively_castable(name: str, path: Path) -> bool:
    """Whether an incomplete file can start casting before it is fully received.

    Streamable containers keep their headers at the front, so FFmpeg can begin
    reading while the upload continues. Indexed MP4/MOV files qualify only when
    the ``moov`` index precedes the media data (a faststart/progressive file).
    """
    suffix = Path(name).suffix.lower()
    if suffix in _EARLY_CAST_SUFFIXES:
        return True
    if suffix in _INDEXED_SUFFIXES:
        return _mp4_index_at_front(path)
    return False


def _human_rate(value: int) -> str:
    rate = float(max(0, value))
    for unit in ("B/s", "KB/s", "MB/s"):
        if rate < 1024:
            return f"{rate:.0f} {unit}" if unit == "B/s" else f"{rate:.1f} {unit}"
        rate /= 1024
    return f"{rate:.1f} GB/s"


def format_portal_activity(uploads: list[dict]) -> str:
    """One-line summary of LAN client activity for the desktop shared-room card."""
    if not uploads:
        return "No client activity"
    parts = []
    for item in uploads[-3:]:
        name = item.get("name") or "video"
        phase = item.get("phase") or "receiving"
        client = item.get("client") or ""
        prefix = f"{client} · " if client else ""
        percent = int(item.get("percent") or 0)
        if phase in {"complete", "finalizing"}:
            parts.append(f"{prefix}{name}: received")
        elif phase == "casting":
            parts.append(f"{prefix}{name}: casting now ({percent}% received)")
        else:
            parts.append(f"{prefix}{name}: receiving {percent}% "
                         f"({_human_rate(int(item.get('bytes_per_second') or 0))})")
    return "  •  ".join(parts)


def stale_early_casts(casting: dict, *, now: float, busy: bool,
                      now_playing: str | None, grace: float) -> list[str]:
    """Early casts that are neither still starting nor playing, past the grace.

    ``casting`` maps upload id to ``(path, started_monotonic)``. A cast the GUI
    never actually started is reported so the finished file can be cast instead.
    """
    stale = []
    for upload_id, (path, started) in casting.items():
        if busy or now_playing == path or now - started < grace:
            continue
        stale.append(upload_id)
    return stale


class UploadError(ValueError):
    """A safe rejection from the authenticated portal upload protocol."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def default_upload_root() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "cast-control" / "portal-uploads"


def _safe_name(value: object) -> tuple[str, str, bool]:
    if not isinstance(value, str):
        raise UploadError(400, "Choose an audio or video file to upload")
    name = unicodedata.normalize("NFC", value.strip()).replace("\\", "/").rsplit("/", 1)[-1]
    if (not name or len(name.encode("utf-8")) > 240
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise UploadError(400, "The selected file name is invalid")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES | AUDIO_SUFFIXES:
        raise UploadError(422, "Choose a supported audio or video file")
    return name, suffix, suffix in AUDIO_SUFFIXES


@dataclass
class _Upload:
    upload_id: str
    owner: str
    name: str
    suffix: str
    size: int
    partial_path: Path
    client: str = ""
    created_at: float = 0.0
    last_at: float = 0.0
    cancelled: bool = False
    received: int = 0
    complete_path: Path | None = None
    cast_submitted: bool = False
    # "idle" -> "requested" -> "active"/"declined"; early casting state.
    early_cast: str = "idle"
    keep_partial: bool = False
    queue_only: bool = False
    audio_only: bool = False
    audio_validated: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class UploadManager:
    """Sequential, resumable uploads written directly to private disk files.

    Requests are consumed in 64 KiB reads and each acknowledged chunk is
    fsynced before its offset is advanced. A disconnected chunk is truncated
    back to its starting offset, so a browser can safely retry it.
    """

    def __init__(self, root: Path | None = None, *, disk_usage=shutil.disk_usage,
                 clock=time.time, early_cast_min_bytes: int = EARLY_CAST_MIN_BYTES) -> None:
        self.root = Path(root or default_upload_root())
        cache_privacy.ensure_private_directory(self.root)
        self._disk_usage = disk_usage
        self._clock = clock
        self._early_cast_min_bytes = max(0, int(early_cast_min_bytes))
        self._uploads: dict[str, _Upload] = {}
        self._lock = threading.RLock()
        self._remove_expired_partials()

    def _remove_expired_partials(self) -> None:
        cutoff = self._clock() - PARTIAL_TTL_SECONDS
        for path in self.root.glob("*.partial"):
            try:
                info = path.lstat()
                if path.is_file() and not path.is_symlink() and info.st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def _expire_uploads(self) -> None:
        # Called under the manager lock. An active chunk owns its upload lock.
        cutoff = self._clock() - PARTIAL_TTL_SECONDS
        for upload_id, upload in list(self._uploads.items()):
            if not upload.lock.acquire(blocking=False):
                continue
            try:
                if upload.complete_path is None and upload.last_at <= cutoff:
                    try:
                        upload.partial_path.unlink(missing_ok=True)
                    except OSError:
                        continue
                    upload.cancelled = True
                    self._uploads.pop(upload_id)
            finally:
                upload.lock.release()

    def create(self, owner: str, name_value: object, size_value: object,
               client: str = "", *, queue_only: bool = False) -> dict:
        name, suffix, audio_only = _safe_name(name_value)
        if type(size_value) is not int or not 0 < size_value <= MAX_UPLOAD_BYTES:
            raise UploadError(413, "The selected file size is invalid or too large")
        if audio_only and size_value > MAX_AUDIO_UPLOAD_BYTES:
            raise UploadError(413, "Audio uploads are limited to 512 MiB")
        if not isinstance(owner, str) or not owner:
            raise UploadError(401, "Sign in to upload a file")
        with self._lock:
            self._expire_uploads()
            pending = [upload for upload in self._uploads.values()
                       if upload.complete_path is None]
            if len(pending) >= MAX_ACTIVE_UPLOADS:
                raise UploadError(429, "Too many uploads are already in progress")
            reserved = sum(upload.size - upload.received for upload in pending)
            free = self._disk_usage(self.root).free
            if free - reserved - size_value < MIN_FREE_BYTES:
                raise UploadError(507, "Not enough free space to receive this file")
            for _ in range(4):
                upload_id = secrets.token_urlsafe(24)
                partial = self.root / f"{upload_id}.partial"
                try:
                    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
                except FileExistsError:
                    continue
                os.close(fd)
                break
            else:
                raise UploadError(503, "Could not reserve a private upload file")
            owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
            now = self._clock()
            upload = _Upload(upload_id, owner_key, name, suffix, size_value, partial,
                             client=str(client or "")[:64], created_at=now, last_at=now,
                             queue_only=bool(queue_only or audio_only),
                             audio_only=audio_only)
            self._uploads[upload_id] = upload
        return {"id": upload_id, "name": name, "size": size_value,
                "received": 0, "chunk_size": CHUNK_SIZE}

    def _get(self, owner: str, upload_id: str) -> _Upload:
        if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
            raise UploadError(404, "Upload not found")
        with self._lock:
            upload = self._uploads.get(upload_id)
        owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        if upload is None or not hmac.compare_digest(upload.owner, owner_key):
            raise UploadError(404, "Upload not found")
        return upload

    def is_queue_only(self, owner: str, upload_id: str) -> bool:
        """Whether this upload was created with early casting disabled."""
        return self._get(owner, upload_id).queue_only

    def is_audio_only(self, owner: str, upload_id: str) -> bool:
        """Whether a validated source is audio-only and must never early-cast."""
        return self._get(owner, upload_id).audio_only

    def status(self, owner: str, upload_id: str) -> dict:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found")
            return {"id": upload.upload_id, "name": upload.name, "size": upload.size,
                    "received": upload.received, "complete": upload.complete_path is not None,
                    "ready_to_cast": upload.early_cast in {"requested", "active"}}

    def _summary(self, upload: _Upload, now: float) -> dict:
        """A display-only snapshot of one upload; caller holds ``upload.lock``."""
        complete = upload.complete_path is not None
        if complete:
            phase = "complete"
        elif upload.early_cast in {"requested", "active"}:
            phase = "casting"
        elif upload.received >= upload.size:
            phase = "finalizing"
        else:
            phase = "receiving"
        elapsed = max(0.001, now - upload.created_at)
        return {
            "id": upload.upload_id, "name": upload.name, "size": upload.size,
            "received": upload.received, "complete": complete,
            "client": upload.client, "phase": phase,
            "percent": (100 * upload.received // upload.size) if upload.size else 0,
            "bytes_per_second": int(upload.received / elapsed),
        }

    def by_id(self, upload_id: str) -> dict | None:
        """Display snapshot for one upload without an owner check (internal)."""
        with self._lock:
            upload = self._uploads.get(upload_id)
        if upload is None:
            return None
        with upload.lock:
            return self._summary(upload, self._clock())

    def snapshot(self) -> list[dict]:
        """Every tracked upload, newest last, for the desktop activity display."""
        now = self._clock()
        with self._lock:
            uploads = list(self._uploads.values())
        summaries = []
        for upload in uploads:
            with upload.lock:
                summaries.append(self._summary(upload, now))
        return summaries

    def mark_early_cast(self, upload_id: str, *, accepted: bool) -> None:
        """Record whether the GUI accepted an early-cast request for an upload."""
        with self._lock:
            upload = self._uploads.get(upload_id)
        if upload is None:
            return
        with upload.lock:
            if upload.early_cast == "requested":
                upload.early_cast = "active" if accepted else "declined"
            elif upload.early_cast == "active" and not accepted:
                upload.early_cast = "declined"

    def append(self, owner: str, upload_id: str, content_range: str,
               content_length: int, source: BinaryIO) -> dict:
        upload = self._get(owner, upload_id)
        match = _CONTENT_RANGE.fullmatch(content_range or "")
        if match is None:
            raise UploadError(400, "Use a valid byte range for this upload chunk")
        start, end, total = (int(part) for part in match.groups())
        chunk_length = end - start + 1
        if (total != upload.size or start < 0 or end >= total or end < start
                or chunk_length != content_length or chunk_length > CHUNK_SIZE):
            raise UploadError(400, "Upload chunk range or size is invalid")
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found")
            if upload.complete_path is not None:
                raise UploadError(409, "This upload is already complete")
            if start != upload.received:
                raise UploadError(409, f"Upload expects byte offset {upload.received}")
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(upload.partial_path, flags)
            written = 0
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size < start:
                    raise UploadError(409, "The partial upload is unavailable; restart it")
                if info.st_size != start:
                    os.ftruncate(fd, start)
                os.lseek(fd, start, os.SEEK_SET)
                while written < chunk_length:
                    block = source.read(min(READ_SIZE, chunk_length - written))
                    if not block:
                        raise UploadError(400, "Upload chunk ended early; retry from the current offset")
                    view = memoryview(block)
                    while view:
                        amount = os.write(fd, view)
                        if amount <= 0:
                            raise OSError("short write while storing upload")
                        view = view[amount:]
                    written += len(block)
                os.fsync(fd)
            except BaseException:
                try:
                    os.ftruncate(fd, start)
                    os.fsync(fd)
                except OSError:
                    pass
                raise
            finally:
                os.close(fd)
            if upload.cancelled:
                raise UploadError(401, "Room access was revoked during this upload")
            upload.received += written
            upload.last_at = self._clock()
            ready = self._maybe_start_early_cast(upload)
            return {"id": upload.upload_id, "name": upload.name,
                    "size": upload.size, "received": upload.received,
                    "complete": upload.received == upload.size,
                    "ready_to_cast": ready,
                    "cast_path": str(upload.partial_path) if ready else None,
                    "client": upload.client}

    def _maybe_start_early_cast(self, upload: _Upload) -> bool:
        """Decide once whether this upload can cast before it finishes arriving.

        Called with ``upload.lock`` held. Returns True on the single append that
        crosses the buffer threshold for a progressively castable container.
        """
        if (upload.audio_only or upload.queue_only or upload.early_cast != "idle"
                or upload.received < self._early_cast_min_bytes
                or upload.received >= upload.size):
            return False
        if not is_progressively_castable(upload.name, upload.partial_path):
            upload.early_cast = "declined"
            return False
        upload.early_cast = "requested"
        upload.keep_partial = True
        return True

    def finalize(self, owner: str, upload_id: str) -> tuple[Path, str, bool]:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found")
            if upload.complete_path is None:
                if upload.received != upload.size:
                    raise UploadError(409, f"Upload is incomplete at byte {upload.received}")
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(upload.partial_path, flags)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size != upload.size:
                        raise UploadError(409, "The completed upload size did not match")
                finally:
                    os.close(fd)
                if upload.keep_partial:
                    # A progressive cast may still be reading this exact path
                    # (and Windows refuses to rename an open file), so keep it
                    # stable instead of moving it to the final name.
                    upload.complete_path = upload.partial_path
                else:
                    destination = self.root / f"{upload.upload_id}{upload.suffix}"
                    os.replace(upload.partial_path, destination)
                    try:
                        dir_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    except OSError:
                        if os.name != "nt":
                            raise
                    upload.complete_path = destination
            if upload.audio_only and not upload.audio_validated:
                try:
                    import streamer
                    media = streamer.ffprobe(upload.complete_path)
                except Exception as exc:
                    if upload.complete_path != upload.partial_path:
                        upload.complete_path.unlink(missing_ok=True)
                    upload.complete_path = None
                    upload.cancelled = True
                    upload.partial_path.unlink(missing_ok=True)
                    raise UploadError(422, "The uploaded file is not readable audio") from exc
                if (not media.is_audio_only or not media.audio_streams
                        or not 0 < media.duration <= MAX_AUDIO_DURATION_SECONDS):
                    if upload.complete_path != upload.partial_path:
                        upload.complete_path.unlink(missing_ok=True)
                    upload.complete_path = None
                    upload.cancelled = True
                    upload.partial_path.unlink(missing_ok=True)
                    raise UploadError(
                        422, "Choose a readable audio file up to 24 hours long",
                    )
                upload.audio_validated = True
            should_dispatch = not upload.cast_submitted
            upload.cast_submitted = True
            return upload.complete_path, upload.name, should_dispatch

    def finish_dispatch(self, owner: str, upload_id: str, *, accepted: bool) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found")
            if not accepted:
                upload.cast_submitted = False

    def cancel(self, owner: str, upload_id: str) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found")
            if upload.cast_submitted:
                raise UploadError(409, "Casting has already been requested for this upload")
            try:
                (upload.complete_path or upload.partial_path).unlink()
            except FileNotFoundError:
                pass
            upload.cancelled = True
            with self._lock:
                self._uploads.pop(upload_id, None)

    def revoke_owner_keys(self, owner_keys: set[str]) -> int:
        """Cancel a revoked guest's uploads without touching media in playback.

        Owner keys are SHA-256 cookie digests already held by the portal, never
        raw session secrets. In-flight writes may hold their per-upload lock;
        mark them cancelled immediately and leave that partial for the normal
        crash/expiry sweep rather than deleting a file still being written.
        """
        with self._lock:
            targets = []
            for upload_id, upload in list(self._uploads.items()):
                if upload.owner in owner_keys:
                    upload.cancelled = True
                    targets.append(upload)
                    self._uploads.pop(upload_id, None)
        for upload in targets:
            if upload.cast_submitted or upload.keep_partial:
                continue  # May be in use by a locally owned receiver session.
            if not upload.lock.acquire(blocking=False):
                continue
            try:
                try:
                    (upload.complete_path or upload.partial_path).unlink(missing_ok=True)
                except OSError:
                    pass  # Do not break room revocation over disk cleanup.
            finally:
                upload.lock.release()
        return len(targets)

    def close(self) -> None:
        """Discard unfinished transfers; keep completed files used by sessions."""
        with self._lock:
            uploads = list(self._uploads.values())
            self._uploads.clear()
        for upload in uploads:
            with upload.lock:
                upload.cancelled = True
                if upload.complete_path is None:
                    try:
                        upload.partial_path.unlink()
                    except FileNotFoundError:
                        pass
