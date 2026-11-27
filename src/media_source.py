"""MediaSource: the only way request data becomes a readable local path (#702 slice).

Handlers name a *validated source* (upload id under the upload root, library file
under a shared folder) and never open a path from request data. Containment uses
fully resolved paths, so ``..`` segments and symlinks cannot escape the root.
Pure stdlib; raises ``SourceError`` with a guest-safe message.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


class SourceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_under(root: Path | str | None, candidate: Path | str) -> Path:
    """A readable regular file that really lives inside ``root`` (symlinks rejected)."""
    if root is None:
        raise SourceError("Media storage is unavailable", 503)
    real_root = Path(root).resolve()
    raw = Path(candidate)
    try:
        if raw.is_symlink():
            raise SourceError("Media is unavailable")
        real = raw.resolve(strict=True)
        info = real.lstat()
    except (OSError, RuntimeError):
        raise SourceError("Media is unavailable") from None
    if not _inside(real, real_root):
        raise SourceError("Media is unavailable")
    if not stat.S_ISREG(info.st_mode) or not os.access(real, os.R_OK):
        raise SourceError("Media is unavailable")
    return real


def upload_source(upload_root, name: str) -> Path:
    """An upload addressed by file name only; separators and dot-names are refused."""
    if upload_root is None:
        raise SourceError("Media storage is unavailable", 503)
    if (not isinstance(name, str) or not name or name in (".", "..")
            or "/" in name or "\\" in name or "\0" in name):
        raise SourceError("Media is unavailable")
    return resolve_under(upload_root, Path(upload_root) / name)


def library_source(roots: list, path: Path | str) -> Path:
    """A library file that sits inside one of the shared library folders."""
    for root in roots:
        try:
            return resolve_under(root, path)
        except SourceError:
            continue
    raise SourceError("That file is no longer available.", 404)
