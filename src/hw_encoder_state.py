"""Remember that hardware (VAAPI) encoding failed, so later launches skip it.

A non-working VAAPI device otherwise costs a 15 s stall on *every* cast before
the software fallback starts (issue #236). The failure is stored in the cache
directory keyed by everything that could change the outcome — ffmpeg binary,
render device, DRM driver and kernel — so an upgrade re-probes automatically.
A record also expires after ``MAX_AGE_SECONDS`` (a transient GPU problem must
not disable hardware encoding forever) and can be cleared by the user with
``smoothcast --reprobe-encoder``.

Pure and GTK-free. Every read is defensive: a missing, corrupt or foreign
record means "not known bad", never an error.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import time

STATE_NAME = "hw_encoder.json"
MAX_AGE_SECONDS = 14 * 24 * 3600
_SCHEMA = 1


def ffmpeg_identity() -> str:
    """Identify the ffmpeg build by its binary: path, size and mtime.

    Replacing ffmpeg (a package upgrade) changes this, so the record is
    re-probed. No process is spawned, so this is cheap and hermetic; it never
    raises.
    """
    try:
        found = shutil.which("ffmpeg")
        if not found:
            return "missing"
        info = os.stat(found)
        return f"{os.path.realpath(found)}|{info.st_size}|{info.st_mtime_ns}"
    except OSError:
        return "unknown"


def drm_driver(device: str) -> str:
    """Kernel DRM driver name behind a render node, or '' when unknown."""
    try:
        link = Path("/sys/class/drm") / Path(device).name / "device" / "driver"
        return os.path.basename(os.readlink(link))
    except OSError:
        return ""


def current_key(device: str) -> dict[str, str]:
    return {
        "ffmpeg": ffmpeg_identity(),
        "device": str(device),
        "driver": drm_driver(device),
        "kernel": platform.release(),
    }


def is_known_bad(path: Path, key: dict[str, str], now: float | None = None) -> bool:
    """True only for a fresh record whose key equals *key* exactly."""
    try:
        record = json.loads(Path(path).read_text("utf-8"))
        failed_at = float(record["failed_at"])
        age = (time.time() if now is None else now) - failed_at
        return (record.get("schema") == _SCHEMA and record["key"] == key
                and 0 <= age <= MAX_AGE_SECONDS)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def record_failure(path: Path, key: dict[str, str], now: float | None = None) -> bool:
    """Atomically persist a failure; returns False if it cannot be written."""
    path = Path(path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": _SCHEMA, "key": key,
                       "failed_at": time.time() if now is None else now}, handle)
        os.replace(temp, path)
        return True
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass
        return False


def clear(path: Path) -> bool:
    """Forget a recorded failure; True if a record existed and was removed."""
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    """``smoothcast --reprobe-encoder``: re-test hardware encoding next cast."""
    from streamer import ROOT
    removed = clear(ROOT / STATE_NAME)
    print("Hardware encoder failure record cleared; VAAPI will be tried again on the next cast."
          if removed else "No hardware encoder failure was recorded; nothing to clear.")
    return 0
