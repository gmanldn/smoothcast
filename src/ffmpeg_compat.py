"""Bounded FFmpeg release guard for HLS encoding and preflight.

FFmpeg 5.0 is the minimum supported release: -readrate was introduced after
4.4 (July 2021), and scale:force_divisible_by is present in 5.0. Both options
are used by SmoothCast's playback and preflight pipelines. A distro build
suffix is allowed; an undated git snapshot without a release number is not
assumed compatible.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from async_jobs import UserFacingError
import media_tools


MINIMUM = (5, 0)
_HEADER = re.compile(
    r"^ffmpeg version n?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)"
    r"(?:\.[0-9]+)?(?:[-+~][^\s]+)?(?:\s|$)",
    re.IGNORECASE,
)


# A loaded host can take seconds to start ffmpeg; the answer for one binary
# never changes, so a good result is remembered per (path, mtime, size).
VERSION_TIMEOUT = 15
_verified: dict[tuple, tuple[int, int]] = {}


class FFmpegVersionError(UserFacingError):
    """FFmpeg is missing, too old or reports an unrecognised build version."""


def parse_version(output: str) -> tuple[int, int] | None:
    """Read the actual binary banner; never guess from a filename or package."""
    if not isinstance(output, str):
        return None
    first = output.splitlines()[0].strip() if output.splitlines() else ""
    match = _HEADER.match(first)
    return (int(match["major"]), int(match["minor"])) if match else None


def require_supported_ffmpeg(*, run=None) -> tuple[int, int]:
    """Query once before a cast starts an encoder; no GUI/network interaction."""
    command = [media_tools.resolve_media_tool("ffmpeg"), "-version"]
    cacheable = run is None
    run = run or subprocess.run
    key = None
    if cacheable:
        try:
            real = shutil.which(command[0]) or command[0]
            st = os.stat(real)
            key = (real, st.st_mtime_ns, st.st_size)
        except OSError:
            pass
        if key in _verified:
            return _verified[key]
    try:
        result = run(
            command, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=VERSION_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegVersionError(
            "FFmpeg version check timed out because this computer is very busy; try the cast again",
            code="ffmpeg.missing",
        ) from exc
    except OSError as exc:
        raise FFmpegVersionError(
            "FFmpeg is unavailable or cannot start; install FFmpeg 5.0 or newer",
            code="ffmpeg.missing",
        ) from exc
    if result.returncode != 0:
        raise FFmpegVersionError(
            "FFmpeg version check failed; install FFmpeg 5.0 or newer",
            code="ffmpeg.missing",
        )
    version = parse_version(result.stdout)
    if version is None:
        raise FFmpegVersionError(
            "Could not determine the FFmpeg release; install FFmpeg 5.0 or newer "
            "with -readrate and scale:force_divisible_by support",
            code="ffmpeg.too_old",
        )
    if version < MINIMUM:
        raise FFmpegVersionError(
            f"FFmpeg {version[0]}.{version[1]} is too old: "
            "SmoothCast requires FFmpeg 5.0 or newer (-readrate and "
            "scale:force_divisible_by)",
            code="ffmpeg.too_old",
        )
    if key is not None:
        _verified[key] = version
    return version
