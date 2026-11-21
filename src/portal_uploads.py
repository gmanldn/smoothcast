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
MAX_ACTIVE_UPLOADS = 3
MIN_FREE_BYTES = 512 * 1024 * 1024
PARTIAL_TTL_SECONDS = 24 * 60 * 60
VIDEO_SUFFIXES = frozenset({
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".ts", ".mpeg", ".mpg", ".wmv",
})
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")
_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{32}\Z")


class UploadError(ValueError):
    """A safe rejection from the authenticated portal upload protocol."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def default_upload_root() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "cast-control" / "portal-uploads"


def _safe_name(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise UploadError(400, "Choose a video file to upload")
    name = unicodedata.normalize("NFC", value.strip()).replace("\\", "/").rsplit("/", 1)[-1]
    if (not name or len(name.encode("utf-8")) > 240
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise UploadError(400, "The selected file name is invalid")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise UploadError(422, "Choose a supported video file")
    return name, suffix


@dataclass
class _Upload:
    upload_id: str
    owner: str
    name: str
    suffix: str
    size: int
    partial_path: Path
    received: int = 0
    complete_path: Path | None = None
    cast_submitted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class UploadManager:
    """Sequential, resumable uploads written directly to private disk files.

    Requests are consumed in 64 KiB reads and each acknowledged chunk is
    fsynced before its offset is advanced. A disconnected chunk is truncated
    back to its starting offset, so a browser can safely retry it.
    """

    def __init__(self, root: Path | None = None, *, disk_usage=shutil.disk_usage,
                 clock=time.time) -> None:
        self.root = Path(root or default_upload_root())
        cache_privacy.ensure_private_directory(self.root)
        self._disk_usage = disk_usage
        self._clock = clock
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

    def create(self, owner: str, name_value: object, size_value: object) -> dict:
        name, suffix = _safe_name(name_value)
        if type(size_value) is not int or not 0 < size_value <= MAX_UPLOAD_BYTES:
            raise UploadError(413, "The selected file size is invalid or too large")
        if not isinstance(owner, str) or not owner:
            raise UploadError(401, "Sign in to upload a file")
        with self._lock:
            pending = [upload for upload in self._uploads.values()
                       if upload.complete_path is None]
            if len(pending) >= MAX_ACTIVE_UPLOADS:
                raise UploadError(429, "Too many uploads are already in progress")
            reserved = sum(upload.size for upload in pending)
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
            upload = _Upload(upload_id, owner_key, name, suffix, size_value, partial)
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

    def status(self, owner: str, upload_id: str) -> dict:
        upload = self._get(owner, upload_id)
        with upload.lock:
            return {"id": upload.upload_id, "name": upload.name, "size": upload.size,
                    "received": upload.received, "complete": upload.complete_path is not None}

    def append(self, owner: str, upload_id: str, content_range: str,
               content_length: int, source: BinaryIO) -> dict:
        upload = self._get(owner, upload_id)
        match = _CONTENT_RANGE.fullmatch(content_range or "")
        if match is None:
            raise UploadError(400, "Use a valid byte range for this upload chunk")
        start, end, total = (int(part) for part in match.groups())
        chunk_length = end - start + 1
        if (total != upload.size or start < 0 or end < start
                or chunk_length != content_length or chunk_length > CHUNK_SIZE):
            raise UploadError(400, "Upload chunk range or size is invalid")
        with upload.lock:
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
            upload.received += written
            return {"id": upload.upload_id, "name": upload.name,
                    "size": upload.size, "received": upload.received,
                    "complete": upload.received == upload.size}

    def finalize(self, owner: str, upload_id: str) -> tuple[Path, str, bool]:
        upload = self._get(owner, upload_id)
        with upload.lock:
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
            should_dispatch = not upload.cast_submitted
            upload.cast_submitted = True
            return upload.complete_path, upload.name, should_dispatch

    def finish_dispatch(self, owner: str, upload_id: str, *, accepted: bool) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if not accepted:
                upload.cast_submitted = False

    def cancel(self, owner: str, upload_id: str) -> None:
        upload = self._get(owner, upload_id)
        with upload.lock:
            if upload.complete_path is not None:
                raise UploadError(409, "A completed upload cannot be cancelled")
            try:
                upload.partial_path.unlink()
            except FileNotFoundError:
                pass
            with self._lock:
                self._uploads.pop(upload_id, None)

    def close(self) -> None:
        """Discard unfinished transfers; keep completed files used by sessions."""
        with self._lock:
            uploads = list(self._uploads.values())
            self._uploads.clear()
        for upload in uploads:
            with upload.lock:
                if upload.complete_path is None:
                    try:
                        upload.partial_path.unlink()
                    except FileNotFoundError:
                        pass
