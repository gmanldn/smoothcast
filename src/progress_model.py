"""Typed models for FFmpeg progress and receiver status (issue #249).

GTK-free and import-light so it is covered by the mypy gate. ``Progress`` is the
immutable snapshot of FFmpeg's ``-progress`` key=value file; ``parse_progress``
is deliberately tolerant (ffmpeg prints ``N/A`` early on, the file may be cut
mid-line, values are untrusted text) and never raises. ``ReceiverInfo`` types
the status dict ``castctl.info()`` returns from catt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, TypedDict


class ReceiverInfo(TypedDict, total=False):
    """Normalized receiver status shared by Catt and PyChromecast backends."""

    title: str
    player_state: str
    current_time: float
    duration: float
    volume_level: float
    volume_muted: bool
    content_id: str
    idle_reason: str
    media_session_id: int
    error_code: int


def _number(raw: object) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _whole(raw: object) -> int | None:
    value = _number(raw)
    return int(value) if value is not None and value >= 0 else None


@dataclass(frozen=True)
class Progress:
    """One snapshot of FFmpeg's progress file; the default means 'nothing yet'."""

    out_time: float = 0.0  # seconds of media encoded so far; never negative
    progress: str = ""  # ffmpeg's "continue" or "end"; "" before the first report
    speed: float | None = None  # encode speed as a multiple of real time
    fps: float | None = None
    frame: int | None = None
    total_size: int | None = None
    bitrate: str = ""
    dup_frames: int | None = None
    drop_frames: int | None = None

    @property
    def done(self) -> bool:
        return self.progress == "end"

    @property
    def speed_text(self) -> str:
        return "—" if self.speed is None else f"{self.speed:g}x"

    @property
    def fps_text(self) -> str:
        return "—" if self.fps is None else f"{self.fps:g}"


EMPTY = Progress()


def _out_time(fields: Mapping[str, str]) -> float:
    micro = _number(fields.get("out_time_us"))
    if micro:
        seconds = micro / 1_000_000
    else:
        milli = _number(fields.get("out_time_ms"))  # ffmpeg labels microseconds "ms"
        seconds = milli / 1_000_000 if milli else 0.0
    return max(0.0, seconds)


def progress_from_fields(fields: Mapping[str, str]) -> Progress:
    speed_text = str(fields.get("speed", "")).strip().rstrip("xX")
    speed = _number(speed_text)
    fps = _number(fields.get("fps"))
    return Progress(
        out_time=_out_time(fields),
        progress=str(fields.get("progress", "")).strip(),
        speed=speed if speed is not None and speed >= 0 else None,
        fps=fps if fps is not None and fps >= 0 else None,
        frame=_whole(fields.get("frame")),
        total_size=_whole(fields.get("total_size")),
        bitrate=str(fields.get("bitrate", "")).strip(),
        dup_frames=_whole(fields.get("dup_frames")),
        drop_frames=_whole(fields.get("drop_frames")),
    )


def parse_progress(text: str) -> Progress:
    """Parse the tail of an ffmpeg progress file; the last value of a key wins."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return progress_from_fields(fields)
