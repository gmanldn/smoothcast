"""Bounded FFmpeg release guard for HLS encoding and preflight.

FFmpeg 5.0 is the minimum supported release: -readrate was introduced after
4.4 (July 2021), and scale:force_divisible_by is present in 5.0. Both options
are used by SmoothCast's playback and preflight pipelines. A distro build
suffix is allowed; an undated git snapshot without a release number is not
assumed compatible.
"""
from __future__ import annotations

import re
import subprocess

from async_jobs import UserFacingError
import media_tools


MINIMUM = (5, 0)
_HEADER = re.compile(
    r"^ffmpeg version n?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)"
    r"(?:\.[0-9]+)?(?:[-+~][^\s]+)?(?:\s|$)",
    re.IGNORECASE,
)


class FFmpegVersionError(UserFacingError):
    """FFmpeg is missing, too old or reports an unrecognised build version."""


def parse_version(output: str) -> tuple[int, int] | None:
    """Read the actual binary banner; never guess from a filename or package."""
    if not isinstance(output, str):
        return None
    first = output.splitlines()[0].strip() if output.splitlines() else ""
    match = _HEADER.match(first)
    return (int(match["major"]), int(match["minor"])) if match else None


def require_supported_ffmpeg(*, run=subprocess.run) -> tuple[int, int]:
    """Query once before a cast starts an encoder; no GUI/network interaction."""
    command = [media_tools.resolve_media_tool("ffmpeg"), "-version"]
    try:
        result = run(
            command, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=4, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegVersionError(
            "FFmpeg version check timed out; install FFmpeg 5.0 or newer",
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
    return version
