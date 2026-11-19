"""Private, crash-safe local cache storage without desktop dependencies.

The cache contains film paths, logs and staged media. A normal umask is not
sufficient to protect it from other local accounts. POSIX metadata and writes
must not follow a symlink in place of the cache directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


def ensure_private_directory(path: Path) -> None:
    """Create/tighten a cache directory to POSIX 0700, without deleting data.

    Reject a symlink or directory belonging to another user instead of
    chmod-ing an unrelated target. Use a directory descriptor so fchmod does
    not follow a path swapped between inspection and permission update.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        # POSIX permission bits do not express Windows ACLs. The default
        # per-user home directory ACL remains the OS-level boundary.
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(f"SmoothCast cache is not a directory: {path}")
        if metadata.st_uid != os.getuid():
            raise PermissionError(f"SmoothCast cache is owned by another user: {path}")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def write_private_json_atomic(path: Path, data: Any) -> None:
    """Atomically replace session state using a fresh private 0600 temp file.

    Never truncate the previous session before a complete new JSON document is
    fsynced. The temporary file uses O_EXCL, and failures remove only that
    temporary file; an existing session is retained.
    """
    ensure_private_directory(path.parent)
    payload = json.dumps(data)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp",
                                dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if os.name != "nt":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except BaseException:
        # The original session remains untouched when serialization, fsync or
        # the atomic replacement fails. Never unlink the destination here.
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise
