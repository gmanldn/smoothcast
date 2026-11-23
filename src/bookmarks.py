"""Move-stable, named playback bookmarks with bounded private metadata."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import stat
import unicodedata

LIMIT = 64
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
HASH_CHUNK = 1024 * 1024
MAX_LABEL = 100


class BookmarkError(ValueError):
    """A media file could not be safely identified for a bookmark."""


def fingerprint(path: str | os.PathLike[str]) -> str:
    """Hash file contents with bounded memory, independent of path and mtime.

    Reject links, non-files and media that changes while being read. Call from
    a worker for large media files.
    """
    if Path(path).is_symlink():
        raise BookmarkError("Bookmarks do not follow symbolic links")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BookmarkError("Could not read this media file") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise BookmarkError("Bookmarks require a regular media file")
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, HASH_CHUNK)
            if not block:
                break
            digest.update(block)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise BookmarkError("This media file changed while it was being identified")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize("NFC", value.strip())
    if (not value or len(value) > MAX_LABEL
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    return value


def clean(value: object) -> list[dict]:
    """Validate bookmarks loaded from user-controlled configuration JSON."""
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:LIMIT * 4]:
        if not isinstance(item, dict):
            continue
        digest = item.get("fingerprint")
        name, media = _label(item.get("name")), _label(item.get("media"))
        position, created = item.get("position"), item.get("created")
        if (not isinstance(digest, str) or HASH_RE.fullmatch(digest) is None
                or name is None or media is None
                or type(position) not in (int, float) or not math.isfinite(position)
                or not 0 <= position <= 1e12
                or type(created) not in (int, float) or not math.isfinite(created)
                or not 0 <= created <= 1e12):
            continue
        result.append({
            "fingerprint": digest, "name": name, "media": media,
            "position": float(position), "created": float(created),
        })
        if len(result) >= LIMIT:
            break
    return result


def add(value: object, digest: str, name: object, media: object,
        position: object, created: object) -> list[dict]:
    """Return a new bounded list with one validated marker at the front."""
    record = clean([{
        "fingerprint": digest, "name": name, "media": media,
        "position": position, "created": created,
    }])
    if not record:
        raise ValueError("Enter a name and use a valid media position")
    return (record + clean(value))[:LIMIT]


def at(value: object, index: int) -> dict | None:
    """Read a menu item safely even if config changed after menu creation."""
    records = clean(value)
    return records[index] if type(index) is int and 0 <= index < len(records) else None
