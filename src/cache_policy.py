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
import sys
from contextlib import contextmanager
from typing import Any, IO, Iterator

try:
    import fcntl
except ImportError:  # Windows/non-POSIX
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None  # type: ignore[assignment]

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
    Windows FFmpeg receives the lease handle through STARTUPINFO.handle_list.
    If neither platform's locking primitive is available, cleanup fails closed.
    """
    if fcntl is None and msvcrt is None:
        return None
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(directory / SCRATCH_LEASE_NAME, flags, 0o600)
    try:
        # msvcrt.locking requires a byte range; a one-byte marker also makes
        # empty, hand-created files fail closed during the abandoned sweep.
        os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return os.fdopen(fd, "r+b", buffering=0)
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def encoder_lease_kwargs(lease: IO[bytes] | int | None) -> Iterator[dict[str, Any]]:
    """Yield subprocess options that keep a scratch lease through FFmpeg.

    Windows can inherit only explicitly listed OS handles. Use a temporary
    duplicate so concurrent process launches cannot inherit the app's handle.
    """
    if lease is None:
        yield {}
        return
    fd = lease if isinstance(lease, int) else lease.fileno()
    if fcntl is not None:
        yield {"pass_fds": (fd,)}
        return
    if msvcrt is None:
        yield {}
        return
    import subprocess

    duplicate_fd = os.dup(fd)
    try:
        handle = msvcrt.get_osfhandle(duplicate_fd)
        os.set_handle_inheritable(handle, True)
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [handle]}
        yield {"startupinfo": startup}
    finally:
        os.close(duplicate_fd)


def claim_abandoned_scratch(directory: Path) -> IO[bytes] | None:
    """Return a held reaper lock only when no live process owns the scratch.

    A missing, symlinked, foreign-owned or already locked marker is *not*
    evidence of abandonment. Never infer ownership from directory age alone.
    Keep this descriptor open while deleting on POSIX. Windows closes it only
    immediately before an atomic directory rename, which an inherited live
    lease handle prevents.
    """
    if fcntl is None and msvcrt is None:
        return None
    marker = directory / SCRATCH_LEASE_NAME
    try:
        before = marker.lstat()
        if not stat.S_ISREG(before.st_mode) or marker.is_symlink():
            return None
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(marker, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or (hasattr(info, "st_uid") and hasattr(os, "getuid")
                    and info.st_uid != os.getuid())
                or info.st_nlink != 1
                or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
                or info.st_size != 1):
            os.close(fd)
            return None
        os.lseek(fd, 0, os.SEEK_SET)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return os.fdopen(fd, "rb", buffering=0)
    except (OSError, ValueError):
        os.close(fd)
        return None


def current_user_temp_root(path: Path) -> bool:
    """Whether *path* is the current Windows user's private Temp directory.

    Windows does not expose POSIX ``st_uid`` ownership. Only sweep its usual
    per-user LocalAppData Temp root; custom/shared roots fail closed.
    """
    if not sys.platform.startswith("win"):
        return True
    if msvcrt is None:
        return False
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return False
    try:
        expected = Path(local_app_data, "Temp").resolve(strict=True)
        actual = path.resolve(strict=True)
    except OSError:
        return False
    return os.path.normcase(str(actual)) == os.path.normcase(str(expected))


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
