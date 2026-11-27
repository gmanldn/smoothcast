"""Now-playing art source selection (#130). Pure; opt-out respected.

Attached pictures (cover art) are image streams flagged ``attached_pic``; they are
never counted as the motion-video stream. Prefers embedded art, then a
representative frame at ~10% of duration (clamped), else nothing.
"""
from __future__ import annotations

import math


def _attached(stream: dict) -> bool:
    disp = stream.get("disposition")
    return isinstance(disp, dict) and disp.get("attached_pic") == 1


def streams(probe: dict) -> list[dict]:
    raw = probe.get("streams") if isinstance(probe, dict) else None
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


def motion_video_index(probe: dict) -> int | None:
    """First real video stream, ignoring attached artwork."""
    for s in streams(probe):
        if s.get("codec_type") == "video" and not _attached(s) and isinstance(s.get("index"), int):
            return s["index"]
    return None


def embedded_art_index(probe: dict) -> int | None:
    for s in streams(probe):
        if s.get("codec_type") == "video" and _attached(s) and isinstance(s.get("index"), int):
            return s["index"]
    return None


def frame_position(duration) -> float:
    """Representative frame time: 10% in, between 1 s and 120 s, never past the end."""
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return 0.0
    return min(max(duration * 0.1, 1.0), 120.0, max(0.0, duration - 0.5))


def choose(probe: dict, duration, enabled: bool = True) -> dict | None:
    """{'kind': 'embedded'|'frame', ...} or None (opted out / nothing usable)."""
    if not enabled:
        return None
    art = embedded_art_index(probe)
    if art is not None:
        return {"kind": "embedded", "stream": art}
    video = motion_video_index(probe)
    if video is not None:
        return {"kind": "frame", "stream": video, "position": frame_position(duration)}
    return None
