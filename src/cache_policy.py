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
from pathlib import Path

DEFAULT_CAP_MB = 8192
MAX_CAP_MB = 1_000_000
SCRATCH_PREFIX = "smoothcast-dlna-"
# A scratch directory younger than this may belong to a conversion that is
# still being prepared; only older ones are treated as crash debris.
MIN_STALE_AGE_SECONDS = 600.0
MB = 1024 * 1024


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
