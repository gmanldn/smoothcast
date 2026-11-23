"""Cheap, stable media identity that survives rename and move (issue #366).

``content_key`` is SHA-256 over (size, first/middle/last 4 MiB). It costs a few
reads even for huge files, so watched state, resume points and replicas can key
on the *content* instead of the path.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

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


KEY_PATTERN = re.compile(r"qh:[0-9a-f]{32}")


def valid_key(value: object) -> str | None:
    return value if isinstance(value, str) and KEY_PATTERN.fullmatch(value) else None


class KeyCache:
    """Non-blocking path -> content key lookups.

    ``get`` never reads media on the caller's thread (GTK's): it answers from a
    stat-validated cache, or returns None and hashes once on a background
    worker so the *next* call has the key. Bounded, thread-safe, and any read
    error simply means "no key yet".
    """

    def __init__(self, hasher=quick_hash, limit: int = 512) -> None:
        self._hasher, self._limit = hasher, limit
        self._cache: OrderedDict[str, tuple[tuple[int, int], str]] = OrderedDict()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="content-key")

    @staticmethod
    def _identity(path: str) -> tuple[int, int] | None:
        try:
            info = os.stat(path)
        except OSError:
            return None
        return info.st_size, info.st_mtime_ns

    def get(self, path: str | os.PathLike[str]) -> str | None:
        name = os.fspath(path)
        ident = self._identity(name)
        if ident is None:
            return None
        with self._lock:
            hit = self._cache.get(name)
            if hit and hit[0] == ident:
                self._cache.move_to_end(name)
                return hit[1]
            if name in self._pending:
                return None
            self._pending.add(name)
        self._pool.submit(self._compute, name, ident)
        return None

    def _compute(self, name: str, ident: tuple[int, int]) -> None:
        try:
            key = self._hasher(name)
        except OSError:
            key = None
        with self._lock:
            self._pending.discard(name)
            if key is not None and self._identity(name) == ident:
                self._cache[name] = (ident, key)
                self._cache.move_to_end(name)
                while len(self._cache) > self._limit:
                    self._cache.popitem(last=False)

    def wait(self) -> None:
        """Block until queued hashing is done (tests and shutdown only)."""
        self._pool.submit(lambda: None).result()


KEYS = KeyCache()
