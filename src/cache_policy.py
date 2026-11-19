"""Disk-use limits for SmoothCast's scratch data (issue #277).

Pure and GTK-free. The only large, crash-prone scratch data is the temporary
MP4 a DLNA cast converts before playback (``smoothcast-dlna-*`` in the system
temp directory, roughly twice the source size). HLS segments are already
deleted on stop and at startup.

The cap is the ``cache_cap_mb`` setting in config.json: megabytes of scratch a
single conversion may need; ``0`` disables the cap. It is read without any side
effect (no migration, no backups) so conversion code can call it cheaply.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:  # Windows: startup cleanup deliberately skips scratch sweeping.
    fcntl = None  # type: ignore[assignment]

DEFAULT_CAP_MB = 8192
MAX_CAP_MB = 1_000_000
SCRATCH_PREFIX = "smoothcast-dlna-"
SCRATCH_LEASE_NAME = ".smoothcast-active.lock"
# A scratch directory younger than this may belong to a conversion that is
# still being prepared; only older ones are treated as crash debris.
MIN_STALE_AGE_SECONDS = 600.0
MB = 1024 * 1024

def hold_scratch_lease(directory: Path) -> IO[bytes] | None:
    """Hold an exclusive kernel lock until this DLNA session has fully stopped.

    POSIX FFmpeg children inherit the locked descriptor via pass_fds: if the
    GUI crashes during conversion, cleanup must wait for FFmpeg to exit too.
    On platforms without safe POSIX locking the startup sweep is disabled.
    """
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        return None
    fd = os.open(
        directory / SCRATCH_LEASE_NAME,
        os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(fd, "r+b", buffering=0)
    except BaseException:
        os.close(fd)
        raise


def claim_abandoned_scratch(directory: Path) -> IO[bytes] | None:
    """Return a held reaper lock only when no live process owns the scratch.

    A missing, symlinked, foreign-owned or already locked marker is *not*
    evidence of abandonment. Never infer ownership from directory age alone.
    Keep this descriptor open until the scratch directory has been removed.
    """
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        return None
    try:
        fd = os.open(directory / SCRATCH_LEASE_NAME, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            os.close(fd)
            return None
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(fd, "rb", buffering=0)
    except (OSError, ValueError):
        os.close(fd)
        return None


def valid_cap_mb(value: object) -> int | None:
    """Return a validated cap in MB (0 = unlimited) or None if unusable."""
    if type(value) is int and 0 <= value <= MAX_CAP_MB:
        return value
    return None


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cast-control" / "config.json"


def configured_cap_mb(path: Path | None = None) -> int:
    """The user's cap in MB, falling back to the default on any problem."""
    try:
        raw = json.loads((path or config_path()).read_text())
        cap = valid_cap_mb(raw.get("cache_cap_mb")) if isinstance(raw, dict) else None
    except (OSError, ValueError, RuntimeError):
        cap = None
    return DEFAULT_CAP_MB if cap is None else cap


def conversion_blocker(needed_bytes: int, cap_mb: int, in_use_bytes: int = 0) -> str | None:
    """Explain why a conversion must not start, or None if it fits the cap.

    *in_use_bytes* is scratch already held by this app (other temp conversions).
    """
    if cap_mb <= 0:
        return None
    cap = cap_mb * MB
    if needed_bytes + max(0, in_use_bytes) <= cap:
        return None
    need_mb = -(-needed_bytes // MB)
    return (
        f"Preparing this film for DLNA needs about {need_mb} MB of temporary space, "
        f"above the SmoothCast cache limit of {cap_mb} MB. Raise 'cache_cap_mb' in "
        "config.json (0 = no limit), or cast it to a Chromecast instead."
    )


def directory_size(path: Path) -> int:
    """Total bytes of regular files below *path*, never following symlinks."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += directory_size(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def scratch_in_use(temp_root: Path) -> int:
    """Bytes currently held by SmoothCast's DLNA scratch directories."""
    try:
        return sum(directory_size(p) for p in temp_root.glob(SCRATCH_PREFIX + "*")
                   if p.is_dir() and not p.is_symlink())
    except OSError:
        return 0
