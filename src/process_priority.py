"""Run encoders at below-normal priority so the desktop stays responsive (#247).

GTK-free. ``launch_kwargs`` gives extra ``subprocess.Popen`` arguments (Windows
priority class); ``lower`` applies the POSIX nice value right after spawn, which
avoids ``preexec_fn`` (unsafe in a threaded GUI process). The opt-out is the
``lower_ffmpeg_priority`` setting in config.json (default on); it is read
without side effects, like ``cache_policy``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SETTING = "lower_ffmpeg_priority"
NICE_VALUE = 10  # POSIX: noticeably lower than the default 0, not idle-starved.
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000  # Windows process creation flag.


def config_path() -> Path:
    import paths  # one place decides where config lives (#701)
    return paths.config_dir() / "config.json"


def enabled(path: Path | None = None) -> bool:
    """True unless the user explicitly set the option to false."""
    try:
        raw = json.loads((path or config_path()).read_text())
    except (OSError, ValueError, RuntimeError):
        return True
    return not (isinstance(raw, dict) and raw.get(SETTING) is False)


def launch_kwargs(is_enabled: bool | None = None, *, platform: str | None = None) -> dict:
    """Extra Popen keyword arguments; only Windows needs one at spawn time."""
    if is_enabled is None:
        is_enabled = enabled()
    if is_enabled and (platform or sys.platform).startswith("win"):
        return {"creationflags": BELOW_NORMAL_PRIORITY_CLASS}
    return {}


def lower(proc: subprocess.Popen, is_enabled: bool | None = None, *,
          platform: str | None = None) -> bool:
    """Apply the POSIX nice value to a spawned child; never raises."""
    if is_enabled is None:
        is_enabled = enabled()
    if not is_enabled or (platform or sys.platform).startswith("win"):
        return False
    setpriority = getattr(os, "setpriority", None)
    pid = getattr(proc, "pid", None)
    if setpriority is None or not isinstance(pid, int):
        return False
    try:
        setpriority(os.PRIO_PROCESS, pid, NICE_VALUE)
    except (OSError, ValueError):
        return False
    return True
