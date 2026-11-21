"""Sanitized Google Cast media capabilities for deterministic fake receivers.

The entries summarize the per-device codec limits in Google's Supported Media
documentation. They guide fake rejection tests; the Cast SDK notes that actual
support varies with receiver hardware and display, so these are not qualification
results.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodecLimit:
    codec: str
    profile: str | None
    max_level: tuple[int, int] | None
    max_width: int
    max_height: int
    max_fps: int


@dataclass(frozen=True)
class ReceiverProfile:
    name: str
    codecs: tuple[CodecLimit, ...]


def _limit(
    codec: str,
    profile: str | None,
    level: tuple[int, int] | None,
    width: int,
    height: int,
    fps: int,
) -> CodecLimit:
    return CodecLimit(codec, profile, level, width, height, fps)


PROFILES: dict[str, ReceiverProfile] = {
    "generic": ReceiverProfile("generic", ()),
    "chromecast-gen2": ReceiverProfile("chromecast-gen2", (
        _limit("h264", "high", (4, 1), 1280, 720, 60),
        _limit("h264", "high", (4, 1), 1920, 1080, 30),
        _limit("vp8", None, None, 1280, 720, 60),
        _limit("vp8", None, None, 1920, 1080, 30),
    )),
    "chromecast-gen3": ReceiverProfile("chromecast-gen3", (
        _limit("h264", "high", (4, 2), 1920, 1080, 60),
        _limit("vp8", None, None, 1280, 720, 60),
        _limit("vp8", None, None, 1920, 1080, 30),
    )),
    "chromecast-ultra": ReceiverProfile("chromecast-ultra", (
        _limit("h264", "high", (4, 2), 1920, 1080, 60),
        _limit("vp8", None, None, 3840, 2160, 30),
        _limit("h265", "main", (5, 1), 3840, 2160, 60),
        _limit("h265", "main10", (5, 1), 3840, 2160, 60),
        _limit("vp9", "0", (5, 1), 3840, 2160, 60),
        _limit("vp9", "2", (5, 1), 3840, 2160, 60),
    )),
    "chromecast-with-google-tv": ReceiverProfile("chromecast-with-google-tv", (
        _limit("h264", "high", (5, 1), 3840, 2160, 30),
        _limit("h265", "main", (5, 1), 3840, 2160, 60),
        _limit("h265", "main10", (5, 1), 3840, 2160, 60),
        _limit("vp9", "2", None, 3840, 2160, 60),
    )),
    "google-tv-streamer": ReceiverProfile("google-tv-streamer", (
        _limit("h264", "high", (5, 2), 3840, 2160, 60),
        _limit("h265", "main", (5, 1), 3840, 2160, 60),
        _limit("h265", "main10", (5, 1), 3840, 2160, 60),
        _limit("vp9", "2", None, 3840, 2160, 60),
        _limit("av1", "main", (5, 1), 3840, 2160, 60),
    )),
}


def level_tuple(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        major, minor = str(value).split(".", maxsplit=1)
        return int(major), int(minor)
    except (ValueError, TypeError):
        return None


def supports(profile: str, stream: object) -> bool:
    """Return whether an explicit test stream fits a documented profile."""
    capabilities = PROFILES.get(profile)
    if capabilities is None:
        return False
    if profile == "generic":
        return True
    if not isinstance(stream, dict):
        return False
    codec = str(stream.get("codec", "")).lower()
    video_profile = str(stream.get("profile", "")).lower()
    level = level_tuple(stream.get("level"))
    width = stream.get("width")
    height = stream.get("height")
    fps = stream.get("fps")
    if not all(isinstance(value, int) and value > 0 for value in (width, height, fps)):
        return False
    for limit in capabilities.codecs:
        if codec != limit.codec:
            continue
        if limit.profile is not None and video_profile != limit.profile:
            continue
        if limit.max_level is not None and (level is None or level > limit.max_level):
            continue
        if width <= limit.max_width and height <= limit.max_height and fps <= limit.max_fps:
            return True
    return False
