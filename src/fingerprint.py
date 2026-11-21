"""Cheap, stable media identity that survives rename and move (issue #366).

``content_key`` is SHA-256 over (size, first/middle/last 4 MiB). It costs a few
reads even for huge files, so watched state, resume points and replicas can key
on the *content* instead of the path.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

CHUNK = 4 * 1024 * 1024
PREFIX = "qh:"


def quick_hash(path: str | os.PathLike[str]) -> str:
    """Return ``qh:<32 hex>`` for a regular file; raises OSError on read failure."""
    path = Path(path)
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        hasher.update(str(size).encode("ascii"))
        if size <= 3 * CHUNK:
            hasher.update(handle.read())
        else:
            for offset in (0, (size - CHUNK) // 2, size - CHUNK):
                handle.seek(offset)
                hasher.update(handle.read(CHUNK))
    return PREFIX + hasher.hexdigest()[:32]
