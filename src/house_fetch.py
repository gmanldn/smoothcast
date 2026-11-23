"""Fetch a house file from another computer into a verified local cache (#414, #424).

A queued item is always a local path, so media on another node is first copied
over the LAN (``GET /mesh/file/<content_key>``): resumable with ``Range``,
verified against its content key, size-checked against free disk, and kept in
a budget-limited cache. GTK-free.
"""
from __future__ import annotations

from http.client import HTTPConnection
import os
from pathlib import Path
import re
import shutil
import time
from typing import Callable
from urllib.parse import urlsplit

import fingerprint
import lan_guard

CHUNK = 1024 * 1024
TIMEOUT = 10.0
MIN_FREE_BYTES = 1024 * 1024 * 1024
_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,5}")


class FetchError(Exception):
    """A user-presentable reason the file could not be fetched."""


def cache_path(dest_dir: Path, key: str, suffix: str) -> Path:
    if not re.fullmatch(r"qh:[0-9a-f]{32}", key):
        raise FetchError("That item's identity is not valid.")
    suffix = suffix if _SAFE_SUFFIX.fullmatch(suffix or "") else ".bin"
    return Path(dest_dir) / f"{key[3:]}{suffix.lower()}"


def cached(dest_dir: Path, key: str, suffix: str) -> Path | None:
    """The verified cached copy, or None (a corrupt copy is removed)."""
    path = cache_path(dest_dir, key, suffix)
    if not path.is_file():
        return None
    try:
        if fingerprint.quick_hash(path) == key:
            os.utime(path)                       # recently used survives eviction longest
            return path
    except OSError:
        pass
    path.unlink(missing_ok=True)
    return None


def fetch(url: str, key: str, dest_dir: Path, *, suffix: str = ".bin",
          progress: Callable[[int, int], None] | None = None,
          cancelled: Callable[[], bool] = lambda: False,
          connect=HTTPConnection, min_free: int = MIN_FREE_BYTES) -> Path:
    """Copy ``key`` from the peer at ``url`` into ``dest_dir``; return the verified path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = cached(dest_dir, key, suffix)
    if existing is not None:
        return existing
    final = cache_path(dest_dir, key, suffix)
    part = final.with_name(final.name + ".part")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not lan_guard.is_lan_address(host):
        raise FetchError("That computer is not on your home network.")
    have = part.stat().st_size if part.exists() else 0
    for attempt in range(4):
        try:
            conn = connect(host, parts.port or 80, timeout=TIMEOUT)
            headers = {"Host": f"{host}:{parts.port}", "X-SmoothCast-Hop": "1"}
            if have:
                headers["Range"] = f"bytes={have}-"
            conn.request("GET", f"/mesh/file/{key}", headers=headers)
            reply = conn.getresponse()
            if reply.status == 416 and have:       # stale/oversized partial: start over
                part.unlink(missing_ok=True)
                have = 0
                conn.close()
                continue
            if reply.status not in (200, 206):
                raise FetchError("The other computer no longer has that file.")
            if reply.status == 200 and have:        # server ignored Range: restart cleanly
                part.unlink(missing_ok=True)
                have = 0
            total = int(reply.getheader("Content-Length") or 0) + have
            match = _RANGE.fullmatch(reply.getheader("Content-Range") or "")
            if match:
                total = int(match.group(3))
            if shutil.disk_usage(dest_dir).free < total - have + min_free:
                raise FetchError("There isn't enough free disk space to copy that file.")
            with open(part, "ab") as out:
                while True:
                    if cancelled():
                        raise FetchError("Cancelled.")
                    chunk = reply.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    have += len(chunk)
                    if progress:
                        progress(have, total)
            conn.close()
            if total and have < total:
                raise OSError("connection dropped")
            break
        except (OSError, ValueError) as exc:
            if attempt == 3:
                raise FetchError("The copy was interrupted; try again when the other "
                                 "computer is reachable.") from exc
            have = part.stat().st_size if part.exists() else 0
            time.sleep(0)
    try:
        if fingerprint.quick_hash(part) != key:
            part.unlink(missing_ok=True)
            raise FetchError("The file changed on the other computer; search again.")
    except OSError as exc:
        raise FetchError("The copied file could not be read.") from exc
    os.replace(part, final)
    return final


def evict(dest_dir: Path, budget_bytes: int, keep: set[str] | None = None) -> list[str]:
    """Delete least-recently-used cached files until under budget; never those in ``keep``."""
    keep = {os.path.realpath(p) for p in (keep or set())}
    files = [p for p in Path(dest_dir).glob("*") if p.is_file() and not p.name.endswith(".part")]
    total = sum(p.stat().st_size for p in files)
    removed = []
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= budget_bytes:
            break
        if os.path.realpath(path) in keep:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size
        removed.append(path.name)
    return removed
