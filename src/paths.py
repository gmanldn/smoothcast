"""One place that decides where SmoothCast keeps files (ARCH-13, #701).

Pure and GTK-free: no I/O except optionally creating a directory on request.
The directory names match the existing layout (``cast-control``), so adopting
this module never moves a user's data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = "cast-control"


def _env_dir(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "")
    # XDG says a relative value must be ignored.
    return Path(value) if value and os.path.isabs(value) else fallback


def config_dir(home: Path | None = None) -> Path:
    home = home or Path.home()
    if sys.platform == "win32":
        return _env_dir("APPDATA", home / "AppData" / "Roaming") / APP_DIR
    return _env_dir("XDG_CONFIG_HOME", home / ".config") / APP_DIR


def cache_dir(home: Path | None = None) -> Path:
    home = home or Path.home()
    if sys.platform == "win32":
        return _env_dir("LOCALAPPDATA", home / "AppData" / "Local") / APP_DIR / "cache"
    return _env_dir("XDG_CACHE_HOME", home / ".cache") / APP_DIR


def data_dir(home: Path | None = None) -> Path:
    home = home or Path.home()
    if sys.platform == "win32":
        return _env_dir("LOCALAPPDATA", home / "AppData" / "Local") / APP_DIR
    return _env_dir("XDG_DATA_HOME", home / ".local" / "share") / APP_DIR


def ensure_private(path: Path) -> Path:
    """Create ``path`` (and parents) with owner-only permissions where supported."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
