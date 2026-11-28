"""Private, bounded-buffer staging for files uploaded through the LAN portal."""
from __future__ import annotations

import paths
from dataclasses import dataclass, field
import guest_messages
import hashlib
import hmac
import json
import math
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

# Larger HTTP chunks amortise request and sync costs while 64 KiB reads keep RAM bounded.
# Coalesced durable checkpoint: fsync every N bytes or T seconds instead of per chunk.
# Bytes between committed and received are volatile until the next checkpoint.
CHUNK_SIZE = 8 * 1024 * 1024
READ_SIZE = 64 * 1024
CHECKPOINT_BYTES = 16 * 1024 * 1024
CHECKPOINT_SECONDS = 5.0
MAX_UPLOAD_BYTES = 1 << 40  # 1 TiB; available disk space is the practical limit.
MAX_AUDIO_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 24 * 60 * 60
MAX_ACTIVE_UPLOADS = 3
MIN_FREE_BYTES = 512 * 1024 * 1024
PARTIAL_TTL_SECONDS = 24 * 60 * 60
# Finished uploads neither written nor read (cast) for two weeks are reclaimed
# at start-up; without this the private upload folder grows without bound.
COMPLETED_TTL_SECONDS = 14 * 24 * 60 * 60
_UPLOAD_STEM = re.compile(r"[A-Za-z0-9_-]{32}")
_UPLOAD_META_SUFFIX = ".upload.json"
_UPLOAD_META_VERSION = 1
ANNOUNCE_TTL_SECONDS = 15 * 60
ANNOUNCE_MAX = 100
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
# A busy or slow host (409/503) retries early casting on later chunks this
# many times before it falls back to casting the finished file.
EARLY_CAST_MAX_RETRIES = 6
_EARLY_CAST_SUFFIXES = frozenset({".mkv", ".ts", ".webm", ".mpeg", ".mpg"})
_INDEXED_SUFFIXES = frozenset({".mp4", ".m4v", ".mov"})
_MP4_SCAN_LIMIT = 64 * 1024 * 1024
_CONTENT_RANGE = re.compile(r"bytes ([0-9]{1,13})-([0-9]{1,13})/([0-9]{1,13})\Z")
_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{32}\Z")


@dataclass
class _Mp4IndexCursor:
    """Incremental front-index scan state for one growing upload."""
    offset: int = 0
    pending_end: int | None = None
    pending_is_moov: bool = False
    last_available: int = 0
    headers_read: int = 0


def _mp4_index_state(path: Path, cursor: _Mp4IndexCursor | None = None) -> bool | None:
    """True for complete front index, False for nonprogressive, None for pending bytes."""
    try:
        with open(path, "rb") as handle:
            available = os.fstat(handle.fileno()).st_size
            if cursor is None:
                cursor = _Mp4IndexCursor()
            # A failed append can truncate the partial back to its prior offset.
            # Cached boundaries past that point are no longer trustworthy.
            if available < cursor.last_available:
                cursor.offset = 0
                cursor.pending_end = None
                cursor.pending_is_moov = False
                cursor.headers_read = 0
            cursor.last_available = available
            if cursor.pending_end is not None:
                if cursor.pending_end > available:
                    return None
                cursor.offset = cursor.pending_end
                cursor.pending_end = None
                if cursor.pending_is_moov:
                    cursor.pending_is_moov = False
                    return True
                cursor.pending_is_moov = False
            scanned = cursor.offset
            handle.seek(scanned)
            while scanned < _MP4_SCAN_LIMIT:
                header = handle.read(8)
                cursor.headers_read += 1
                if len(header) < 8:
                    return None
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                header_len = 8
                if kind == b"mdat":
                    return False
                if size == 1:
                    extended = handle.read(8)
                    cursor.headers_read += 1
                    if len(extended) < 8:
                        return None
                    size = int.from_bytes(extended, "big")
                    header_len = 16
                if size < header_len or scanned + size > _MP4_SCAN_LIMIT:
                    return False
                if scanned + size > available:
                    cursor.pending_end = scanned + size
                    cursor.pending_is_moov = kind == b"moov"
                    return None
                if kind == b"moov":
                    return True
                handle.seek(size - header_len, os.SEEK_CUR)
                scanned += size
                cursor.offset = scanned
            return False
    except OSError:
        return False


def _mp4_index_at_front(path: Path) -> bool:
    """Only a fully received front index is safe for progressive playback."""
    return _mp4_index_state(path) is True


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

    def __init__(self, status: int, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def default_upload_root() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / paths.APP_DIR / "portal-uploads"


def _safe_name(value: object) -> tuple[str, str, bool]:
    if not isinstance(value, str):
        raise UploadError(400, "Choose an audio or video file to upload")
    name = unicodedata.normalize("NFC", value.strip()).replace("\\", "/").rsplit("/", 1)[-1]
    if (not name or len(name.encode("utf-8")) > 240
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise UploadError(400, "Rename this file and try uploading it again.")
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
    committed: int = 0
    complete_path: Path | None = None
    cast_submitted: bool = False
    dispatch_pending: bool = False
    dispatch_queue_only: bool | None = None
    # "idle" -> "requested" -> "active"/"declined"; early casting state.
    early_cast: str = "idle"
    early_retries: int = 0
    mp4_index_cursor: _Mp4IndexCursor = field(default_factory=_Mp4IndexCursor)
    keep_partial: bool = False
    queue_only: bool = False
    audio_only: bool = False
    cast_target: str | None = None
    batch_index: int = 0
    batch_total: int = 0
    media_validated: bool = False
    # A successful rename and directory fsync are separate steps. If fsync
    # fails, retain the final path and retry durability without re-uploading.
    directory_synced: bool = False
    # Last monotonic time a durable checkpoint was taken; bounds staleness.
    last_checkpoint: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class UploadManager:
    """Sequential, resumable uploads written directly to private disk files.

    Requests are consumed in 64 KiB reads. Bytes are acknowledged as received
    immediately but only become durable at coalesced checkpoints (bounded by
    bytes or time). A disconnected chunk is truncated back to its starting
    committed offset, so a browser can safely retry it. After a crash, resume
    from the last committed (fsynced) offset, never from volatile bytes.
    """

    def __init__(self, root: Path | None = None, *, disk_usage=shutil.disk_usage,
                 clock=time.time, early_cast_min_bytes: int = EARLY_CAST_MIN_BYTES) -> None:
        self.root = Path(root or default_upload_root())
        cache_privacy.ensure_private_directory(self.root)
        self._disk_usage = disk_usage
        self._clock = clock
        self._early_cast_min_bytes = max(0, int(early_cast_min_bytes))
        self._uploads: dict[str, _Upload] = {}
        # owner key -> (expires_at, [{name,size,audio,queue}]) for files a guest
        # has chosen but not yet reserved, so the whole batch is visible.
        self._announced: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.RLock()
        self._remove_expired_partials()
        self._remove_stale_completed()
        self._recover_uploads()

    def _metadata_path(self, upload_id: str) -> Path:
        return self.root / f"{upload_id}{_UPLOAD_META_SUFFIX}"

    def _sync_directory(self) -> None:
        if os.name == "nt":
            return
        fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _remove_metadata(self, upload_id: str) -> None:
        for path in (self._metadata_path(upload_id),
                     self.root / f".{upload_id}.upload.tmp"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_metadata(self, upload: _Upload) -> None:
        """Atomically checkpoint only the fsynced offset and its owner-bound recipe."""
        metadata = {
            "version": _UPLOAD_META_VERSION,
            "id": upload.upload_id,
            "owner": upload.owner,
            "name": upload.name,
            "suffix": upload.suffix,
            "size": upload.size,
            "committed": upload.committed,
            "created_at": upload.created_at,
            "last_at": upload.last_at,
            "queue_only": upload.queue_only,
            "audio_only": upload.audio_only,
            "batch_index": upload.batch_index,
            "batch_total": upload.batch_total,
        }
        raw = json.dumps(metadata, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        temp = self.root / f".{upload.upload_id}.upload.tmp"
        target = self._metadata_path(upload.upload_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temp, flags, 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while storing upload checkpoint")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, target)
        self._sync_directory()

    def _recover_uploads(self) -> None:
        """Recover queue-only uploads at their last durable checkpoint, never volatile bytes."""
        try:
            for temp in self.root.glob(".*.upload.tmp"):
                if temp.is_symlink() or temp.is_file():
                    temp.unlink(missing_ok=True)
            metadata_paths = tuple(self.root.glob(f"*{_UPLOAD_META_SUFFIX}"))
        except OSError:
            return
        now = self._clock()
        for meta_path in metadata_paths:
            upload_id = meta_path.name[:-len(_UPLOAD_META_SUFFIX)]
            if not _UPLOAD_ID.fullmatch(upload_id):
                continue
            try:
                meta_info = meta_path.lstat()
                if (not stat.S_ISREG(meta_info.st_mode) or meta_path.is_symlink()
                        or meta_info.st_size > 4096):
                    raise ValueError("unsafe upload metadata")
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or data.get("version") != _UPLOAD_META_VERSION
                        or data.get("id") != upload_id
                        or not isinstance(data.get("owner"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", data["owner"])):
                    raise ValueError("invalid upload metadata identity")
                name, suffix, audio_only = _safe_name(data.get("name"))
                size, committed = data.get("size"), data.get("committed")
                created_at, last_at = data.get("created_at"), data.get("last_at")
                if (type(created_at) not in (int, float) or type(last_at) not in (int, float)
                        or not math.isfinite(created_at) or not math.isfinite(last_at)
                        or created_at > last_at or last_at > now
                        or now - last_at > PARTIAL_TTL_SECONDS):
                    raise ValueError("expired or invalid upload metadata timestamps")
                if (type(size) is not int or not 0 < size <= MAX_UPLOAD_BYTES
                        or type(committed) is not int or not 0 <= committed <= size
                        or suffix != data.get("suffix")
                        or type(data.get("queue_only")) is not bool
                        or data.get("queue_only") is not True
                        or type(data.get("audio_only")) is not bool
                        or data.get("audio_only") != audio_only):
                    raise ValueError("invalid upload metadata fields")
                partial = self.root / f"{upload_id}.partial"
                info = partial.lstat()
                if partial.is_symlink() or not stat.S_ISREG(info.st_mode):
                    raise ValueError("unsafe partial upload")
                if info.st_size < committed or info.st_size > size:
                    raise ValueError("partial does not contain its committed prefix")
                if info.st_size != committed:
                    fd = os.open(partial, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        os.ftruncate(fd, committed)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                upload = _Upload(
                    upload_id, data["owner"], name, suffix, size, partial,
                    created_at=float(created_at), last_at=float(last_at), received=committed,
                    committed=committed, queue_only=True, audio_only=audio_only,
                    last_checkpoint=float(last_at),
                    batch_index=(data.get("batch_index") if type(data.get("batch_index")) is int else 0),
                    batch_total=(data.get("batch_total") if type(data.get("batch_total")) is int else 0),
                )
                with self._lock:
                    if len(self._uploads) < MAX_ACTIVE_UPLOADS:
                        self._uploads[upload_id] = upload
            except FileNotFoundError:
                # A finalized or cancelled upload may have lost its partial
                # before its sidecar cleanup; it is not a resumable transfer.
                try:
                    meta_path.unlink(missing_ok=True)
                except OSError:
                    pass
            except (OSError, UnicodeError, ValueError, TypeError, UploadError):
                # Torn or malformed metadata never authorizes an arbitrary path
                # or byte range. Leave its file for the TTL sweep.
                try:
                    meta_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _remove_stale_completed(self) -> None:
        cutoff = self._clock() - COMPLETED_TTL_SECONDS
        try:
            paths = list(self.root.iterdir())
        except OSError:
            return
        for path in paths:
            if (path.suffix.lower() not in VIDEO_SUFFIXES | AUDIO_SUFFIXES
                    or not _UPLOAD_STEM.fullmatch(path.stem)):
                continue
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and max(info.st_mtime, info.st_atime) < cutoff:
                    path.unlink()
                    self._remove_metadata(path.stem)
            except OSError:
                continue

    def _remove_expired_partials(self) -> None:
        cutoff = self._clock() - PARTIAL_TTL_SECONDS
        for path in self.root.glob("*.partial"):
            try:
                info = path.lstat()
                if path.is_file() and not path.is_symlink() and info.st_mtime < cutoff:
                    path.unlink()
                    self._remove_metadata(path.stem.removesuffix(".partial"))
            except OSError:
                continue

    def _expire_uploads(self) -> None:
        # Called under the manager lock. An active chunk owns its upload lock.
        cutoff = self._clock() - PARTIAL_TTL_SECONDS
        for upload_id, upload in list(self._uploads.items()):
            if not upload.lock.acquire(blocking=False):
                continue
            try:
                if upload.cancelled:
                    # Rejected media has already been discarded. Do not let
                    # dead records consume one of the three active slots.
                    self._uploads.pop(upload_id, None)
                    continue
                # A pending/active progressive cast still owns this path.
                # Reclaim it only after the receiver outcome is reconciled.
                if (upload.complete_path is None and upload.last_at <= cutoff
                        and upload.early_cast not in {"requested", "active"}):
                    try:
                        upload.partial_path.unlink(missing_ok=True)
                    except OSError:
                        continue
                    self._remove_metadata(upload_id)
                    upload.cancelled = True
                    self._uploads.pop(upload_id)
            finally:
                upload.lock.release()

    def create(self, owner: str, name_value: object, size_value: object,
               client: str = "", *, queue_only: bool = False,
               cast_target: str | None = None, batch: tuple[int, int] | None = None) -> dict:
        name, suffix, audio_only = _safe_name(name_value)
        if type(size_value) is not int or not 0 < size_value <= MAX_UPLOAD_BYTES:
            raise UploadError(413, "The selected file size is invalid or too large")
        if audio_only and size_value > MAX_AUDIO_UPLOAD_BYTES:
            raise UploadError(413, "Audio uploads are limited to 512 MiB")
        if not isinstance(owner, str) or not owner:
            raise UploadError(401, "Sign in to upload a file")
        with self._lock:
            self._expire_uploads()
            # The first overlapping Play now request owns the ingress cast lane.
            # Later arrivals can transfer immediately, but may never replace it
            # merely because their upload finishes faster.
            now = self._clock()
            cast_reserved = any(
                not row.cancelled and not row.queue_only
                and not (row.cast_submitted and row.directory_synced)
                and (row.early_cast in {"requested", "active"}
                     or row.dispatch_pending
                     or now - row.last_at <= PARTIAL_TTL_SECONDS)
                for row in self._uploads.values()
            )
            queue_only = bool(queue_only or audio_only or cast_reserved)
            pending = [upload for upload in self._uploads.values()
                       if not upload.cancelled and upload.complete_path is None]
            if len(pending) >= MAX_ACTIVE_UPLOADS:
                raise UploadError(429, "Too many uploads are already in progress", code="room.rate_limited")
            reserved = sum(upload.size - upload.received for upload in pending)
            free = self._disk_usage(self.root).free
            if free - reserved - size_value < MIN_FREE_BYTES:
                raise UploadError(507, "Not enough free space to receive this file", code="upload.disk_full")
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
                             last_checkpoint=now,
                             queue_only=bool(queue_only or audio_only),
                             audio_only=audio_only, cast_target=cast_target if not (queue_only or audio_only) else None)
            if batch and 1 <= batch[0] <= batch[1] <= 500:
                upload.batch_index, upload.batch_total = batch
            try:
                self._write_metadata(upload)
            except OSError:
                self._remove_metadata(upload_id)
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                raise UploadError(507, "The host could not save the upload checkpoint") from None
            self._uploads[upload_id] = upload
            held = self._announced.get(owner_key)
            if held:
                for index, row in enumerate(held[1]):
                    if row["name"] == name and row["size"] == size_value:
                        del held[1][index]
                        break
                if not held[1]:
                    self._announced.pop(owner_key, None)
                else:
                    self._announced[owner_key] = (now + ANNOUNCE_TTL_SECONDS, held[1])
        return {"id": upload_id, "name": name, "size": size_value,
                "received": 0, "chunk_size": CHUNK_SIZE, "queue_only": upload.queue_only}

    def _get(self, owner: str, upload_id: str) -> _Upload:
        if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
            raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
        with self._lock:
            upload = self._uploads.get(upload_id)
        owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        if upload is None or not hmac.compare_digest(upload.owner, owner_key):
            raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
        return upload

    def is_queue_only(self, owner: str, upload_id: str) -> bool:
        """Whether this upload was created with early casting disabled."""
        return self._get(owner, upload_id).queue_only

    def cast_target(self, owner: str, upload_id: str) -> str | None:
        """Immutable server-side destination consent, including resumed uploads."""
        return self._get(owner, upload_id).cast_target

    def recovery_target(self, upload_id: str, path: str) -> str | None:
        """Internal retry consent; never expose this token to room status."""
        with self._lock:
            upload = self._uploads.get(upload_id)
            if (upload is None or upload.cancelled or upload.queue_only
                    or upload.dispatch_pending or upload.dispatch_queue_only is True
                    or not upload.directory_synced or upload.complete_path is None
                    or str(upload.complete_path) != path):
                return None
            return upload.cast_target

    def is_audio_only(self, owner: str, upload_id: str) -> bool:
        """Whether a validated source is audio-only and must never early-cast."""
        return self._get(owner, upload_id).audio_only

    def status(self, owner: str, upload_id: str) -> dict:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
            return {"id": upload.upload_id, "name": upload.name, "size": upload.size,
                    "received": upload.received, "committed": upload.committed,
                    "complete": upload.complete_path is not None and upload.directory_synced,
                    "queue_only": upload.queue_only,
                    "ready_to_cast": upload.early_cast in {"requested", "active"},
                    "dispatch_state": ("accepted" if upload.cast_submitted else
                                       "pending" if upload.dispatch_pending else "not_submitted")}

    def _summary(self, upload: _Upload, now: float) -> dict:
        """Best-effort display only; never wait for a network chunk on GTK.

        The immutable file identity and published, fsynced offset are safe to
        sample independently. Capture the offset once so all displayed values
        agree. Authoritative status, cancellation and mutations retain locks.
        """
        received = upload.received
        committed = upload.committed
        complete = upload.complete_path is not None and (
            upload.keep_partial or upload.directory_synced)
        if complete:
            phase = "complete"
        elif upload.early_cast in {"requested", "active"}:
            phase = "casting"
        elif received >= upload.size:
            phase = "finalizing"
        else:
            phase = "receiving"
        elapsed = max(0.001, now - upload.created_at)
        return {
            "id": upload.upload_id, "name": upload.name, "size": upload.size,
            "received": received, "committed": committed,
            "complete": complete,
            "client": upload.client, "phase": phase,
            "percent": (100 * received // upload.size) if upload.size else 0,
            "bytes_per_second": int(received / elapsed),
        }

    def by_id(self, upload_id: str) -> dict | None:
        """Display snapshot for one upload without an owner check (internal)."""
        with self._lock:
            upload = self._uploads.get(upload_id)
        if upload is None:
            return None
        return self._summary(upload, self._clock())

    def snapshot(self) -> list[dict]:
        """Every tracked upload, newest last, for the desktop activity display."""
        now = self._clock()
        with self._lock:
            uploads = list(self._uploads.values())
        return [self._summary(upload, now) for upload in uploads]

    def room_transfers(self) -> list[dict]:
        """Authenticated room projection of submitted, not-yet-delivered media.

        Never expose the upload handle, owner, IP, path or target consent token.
        Read published offsets without waiting on a network writer's file lock.
        Completed accepted actions belong to the actual queue/playback status.
        """
        now = self._clock()
        rows = []
        with self._lock:
            for upload in reversed(self._uploads.values()):
                if upload.cancelled or (upload.cast_submitted and upload.directory_synced):
                    continue
                if now - upload.last_at > PARTIAL_TTL_SECONDS:
                    continue
                received = upload.received
                if upload.dispatch_pending:
                    stage = "submitting"
                elif upload.early_cast in {"requested", "active"} and received < upload.size:
                    stage = "buffering"
                elif received >= upload.size:
                    stage = "verifying" if not upload.directory_synced else "awaiting_acceptance"
                else:
                    stage = "receiving"
                rows.append({
                    "id": hashlib.sha256(("room-transfer:" + upload.upload_id).encode()).hexdigest()[:24],
                    "title": upload.name,
                    "media_kind": "audio" if upload.audio_only else "video",
                    "received": received,
                    "size": upload.size,
                    "intent": "queue" if upload.queue_only else "cast",
                    "stage": stage,
                    **({"batch_index": upload.batch_index, "batch_total": upload.batch_total}
                       if upload.batch_total > 1 else {}),
                })
                if len(rows) >= 24:
                    break
            rows = list(reversed(rows))
            for owner_key, (expires, held) in list(self._announced.items()):
                if expires < now:
                    self._announced.pop(owner_key, None)
                    continue
                for index, row in enumerate(held):
                    if len(rows) >= 24:
                        break
                    rows.append({
                        "id": hashlib.sha256(f"room-wait:{owner_key}:{index}:{row['name']}".encode()).hexdigest()[:24],
                        "title": row["name"],
                        "media_kind": "audio" if row["audio"] else "video",
                        "received": 0,
                        "size": row["size"],
                        "intent": "queue" if (row["queue"] or row["audio"]) else "cast",
                        "stage": "waiting",
                    })
            return rows

    def announce(self, owner: str, items: object) -> int:
        """Record a guest's not-yet-started batch files (names and sizes only)."""
        if not isinstance(owner, str) or not owner:
            raise UploadError(401, "Sign in to upload a file")
        key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        rows: list[dict] = []
        if isinstance(items, list):
            for item in items[:ANNOUNCE_MAX]:
                if not isinstance(item, dict):
                    continue
                size = item.get("size")
                if type(size) is not int or not 0 < size <= MAX_UPLOAD_BYTES:
                    continue
                try:
                    name, _suffix, audio = _safe_name(item.get("name"))
                except UploadError:
                    continue
                rows.append({"name": name, "size": size, "audio": audio,
                             "queue": bool(item.get("queue", True))})
        with self._lock:
            if rows:
                self._announced[key] = (self._clock() + ANNOUNCE_TTL_SECONDS, rows)
            else:
                self._announced.pop(key, None)
        return len(rows)

    def mark_early_cast(self, upload_id: str, *, accepted: bool,
                        transient: bool = False) -> None:
        """Record whether the GUI accepted an early-cast request for an upload.

        ``transient`` (host busy or slow) re-arms the request for the next
        acknowledged chunk, a bounded number of times, instead of declining.
        """
        with self._lock:
            upload = self._uploads.get(upload_id)
        if upload is None:
            return
        with upload.lock:
            if (not accepted and transient and upload.early_cast == "requested"
                    and upload.early_retries < EARLY_CAST_MAX_RETRIES):
                upload.early_retries += 1
                upload.early_cast = "idle"
            elif upload.early_cast == "requested":
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
                raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
            if upload.complete_path is not None:
                raise UploadError(409, "This upload is already complete")
            if start != upload.received:
                raise UploadError(409, f"Upload expects byte offset {upload.received}")
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(upload.partial_path, flags)
            written = 0
            rollback_safe = False
            previous_received = upload.received
            previous_committed = upload.committed
            previous_checkpoint = upload.last_checkpoint
            previous_last_at = upload.last_at
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size < start:
                    raise UploadError(409, "The partial upload is unavailable; restart it")
                # Never extend a missing acknowledged prefix during rollback.
                rollback_safe = True
                if info.st_size != start:
                    os.ftruncate(fd, start)
                os.lseek(fd, start, os.SEEK_SET)
                while written < chunk_length:
                    limit = min(READ_SIZE, chunk_length - written)
                    block = source.read(limit)
                    if len(block) > limit:
                        raise UploadError(400, "Upload chunk exceeds its declared size")
                    if not block:
                        raise UploadError(400, "Upload chunk ended early; retry from the current offset")
                    view = memoryview(block)
                    while view:
                        amount = os.write(fd, view)
                        if amount <= 0:
                            raise OSError("short write while storing upload")
                        view = view[amount:]
                    written += len(block)
                received = start + written
                # Coalesced durable checkpoint: fsync when bounded bytes or
                # time have elapsed since the last durable offset.
                now = self._clock()
                if (received - upload.committed >= CHECKPOINT_BYTES
                        or now - upload.last_checkpoint >= CHECKPOINT_SECONDS):
                    os.fsync(fd)
                    upload.committed = received
                    upload.last_checkpoint = now
                    upload.last_at = now
                    self._write_metadata(upload)
                upload.received = received
            except BaseException:  # noqa: BLE001 - roll back the in-memory append then re-raise
                # The append is one in-memory transaction too: never report
                # bytes that rollback removed from the partial file.
                upload.received = previous_received
                upload.committed = previous_committed
                upload.last_checkpoint = previous_checkpoint
                upload.last_at = previous_last_at
                if rollback_safe:
                    try:
                        # External truncation must not turn lost bytes into zeros.
                        if os.fstat(fd).st_size >= start:
                            os.ftruncate(fd, start)
                            os.fsync(fd)
                    except OSError:
                        pass
                raise
            finally:
                os.close(fd)
            if upload.cancelled:
                raise UploadError(401, guest_messages.ACCESS_REMOVED_DURING_UPLOAD)
            upload.last_at = self._clock()
            ready = self._maybe_start_early_cast(upload)
            return {"id": upload.upload_id, "name": upload.name,
                    "size": upload.size, "received": upload.received,
                    "committed": upload.committed,
                    "complete": upload.received == upload.size,
                    "ready_to_cast": ready,
                    "cast_path": str(upload.partial_path) if ready else None,
                    "client": upload.client}

    def _maybe_start_early_cast(self, upload: _Upload) -> bool:
        """Decide whether this upload can cast before it finishes arriving.

        Called with ``upload.lock`` held. Returns True on the single append that
        has enough buffered bytes and a complete progressive container index.
        """
        if (upload.audio_only or upload.queue_only or upload.early_cast != "idle"
                or upload.received < self._early_cast_min_bytes
                or upload.received >= upload.size):
            return False
        ready = (_mp4_index_state(upload.partial_path, upload.mp4_index_cursor)
                 if upload.suffix in _INDEXED_SUFFIXES
                 else is_progressively_castable(upload.name, upload.partial_path))
        if ready is None:
            # The durable prefix has not reached a complete index. Recheck
            # after the next acknowledged chunk rather than abandoning early cast.
            return False
        if not ready:
            upload.early_cast = "declined"
            return False
        upload.early_cast = "requested"
        upload.keep_partial = True
        return True

    def finalize(self, owner: str, upload_id: str, *,
                 queue_only: bool | None = None) -> tuple[Path, str, bool]:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
            intent = upload.queue_only or bool(queue_only)
            if intent and upload.early_cast in {"requested", "active"}:
                # A progressive cast owns this source. Queue validation can
                # discard unreadable media, so never change the action here.
                raise UploadError(409, "Casting has already been requested for this upload")
            if upload.dispatch_pending:
                raise UploadError(409, "The host is still processing this upload. Retry shortly.")
            if upload.cast_submitted and upload.dispatch_queue_only != intent:
                raise UploadError(409, "This upload already has a different accepted room action.")
            if upload.complete_path is None and upload.received != upload.size:
                raise UploadError(409, f"Upload is incomplete at byte {upload.received}")
            if upload.complete_path is None:
                # Ensure all received bytes are durable before completion.
                if upload.received > upload.committed:
                    fd = os.open(upload.partial_path,
                                 os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        os.fsync(fd)
                        upload.committed = upload.received
                        upload.last_checkpoint = self._clock()
                        self._write_metadata(upload)
                    finally:
                        os.close(fd)
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
                    upload.directory_synced = True
                else:
                    destination = self.root / f"{upload.upload_id}{upload.suffix}"
                    os.replace(upload.partial_path, destination)
                    upload.complete_path = destination
            if not upload.directory_synced:
                # Persist the rename before acknowledging finalisation. If a
                # directory sync fails, retry this step at the existing path.
                try:
                    dir_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError:
                    if os.name != "nt":
                        raise
                upload.directory_synced = True
            # Complete uploads no longer need a partial-transfer checkpoint.
            self._remove_metadata(upload_id)
            if intent and not upload.media_validated:
                try:
                    import streamer
                    media = streamer.ffprobe(upload.complete_path)
                except Exception as exc:  # noqa: BLE001 - an unprobeable upload is discarded
                    if upload.complete_path != upload.partial_path:
                        upload.complete_path.unlink(missing_ok=True)
                    upload.complete_path = None
                    upload.cancelled = True
                    upload.partial_path.unlink(missing_ok=True)
                    message = ("The uploaded file is not readable audio" if upload.audio_only
                               else "The uploaded file is not readable media")
                    raise UploadError(422, message) from exc
                duration_valid = math.isfinite(media.duration) and media.duration > 0
                playable = bool(media.audio_streams or media.has_video)
                audio_valid = (not upload.audio_only or (
                    media.is_audio_only and bool(media.audio_streams)
                    and duration_valid and media.duration <= MAX_AUDIO_DURATION_SECONDS
                ))
                if not playable or not duration_valid or not audio_valid:
                    if upload.complete_path != upload.partial_path:
                        upload.complete_path.unlink(missing_ok=True)
                    upload.complete_path = None
                    upload.cancelled = True
                    upload.partial_path.unlink(missing_ok=True)
                    message = (
                        "Choose a readable audio file up to 24 hours long"
                        if upload.audio_only else
                        "Choose a readable audio or video file with a playable track"
                    )
                    raise UploadError(422, message)
                upload.media_validated = True
            should_dispatch = not upload.cast_submitted
            if should_dispatch:
                upload.dispatch_pending = True
                upload.dispatch_queue_only = intent
            return upload.complete_path, upload.name, should_dispatch

    def finish_dispatch(self, owner: str, upload_id: str, *, accepted: bool) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
            if upload.dispatch_pending:
                upload.dispatch_pending = False
                upload.cast_submitted = accepted
                if not accepted:
                    upload.dispatch_queue_only = None

    def cancel(self, owner: str, upload_id: str) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.cancelled:
                raise UploadError(404, "Upload not found. Choose the file again.", code="upload.not_found")
            if (upload.cast_submitted or upload.dispatch_pending
                    or upload.early_cast in {"requested", "active"}):
                raise UploadError(409, "Casting has already been requested for this upload")
            try:
                (upload.complete_path or upload.partial_path).unlink()
            except FileNotFoundError:
                pass
            self._remove_metadata(upload_id)
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
            for key in owner_keys:
                self._announced.pop(key, None)
            targets = []
            for upload_id, upload in list(self._uploads.items()):
                if upload.owner in owner_keys:
                    upload.cancelled = True
                    targets.append(upload)
                    self._uploads.pop(upload_id, None)
        for upload in targets:
            if upload.cast_submitted or upload.dispatch_pending or upload.keep_partial:
                continue  # May be in use by a locally owned receiver session.
            if not upload.lock.acquire(blocking=False):
                continue
            try:
                try:
                    (upload.complete_path or upload.partial_path).unlink(missing_ok=True)
                except OSError:
                    pass  # Do not break room revocation over disk cleanup.
                self._remove_metadata(upload.upload_id)
            finally:
                upload.lock.release()
        return len(targets)

    def close(self) -> None:
        """Discard unfinished transfers not owned by a progressive cast."""
        with self._lock:
            uploads = list(self._uploads.values())
            self._uploads.clear()
        for upload in uploads:
            with upload.lock:
                upload.cancelled = True
                if (upload.complete_path is None
                        and upload.early_cast not in {"requested", "active"}):
                    try:
                        upload.partial_path.unlink()
                    except OSError:
                        # A locked or inaccessible partial must not prevent
                        # cleanup of the remaining transfers. Startup expiry
                        # can reclaim it once the filesystem permits removal.
                        continue
                    self._remove_metadata(upload.upload_id)
