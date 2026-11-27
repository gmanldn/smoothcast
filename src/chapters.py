"""Chapter list parsing and navigation from ffprobe ``-show_chapters`` JSON (#39). Pure."""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    index: int
    start: float
    end: float
    title: str


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def parse(probe: dict, duration: float | None = None) -> list[Chapter]:
    """Valid chapters sorted by start; malformed, empty or reversed entries are dropped.

    Titles fall back to ``Chapter N``. End times are clamped to ``duration`` when known.
    """
    raw = probe.get("chapters") if isinstance(probe, dict) else None
    found: list[tuple[float, float, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        start, end = _num(item.get("start_time")), _num(item.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
        title = str(tags.get("title") or "").strip()[:120]
        if duration and start >= duration:
            continue
        found.append((start, min(end, duration) if duration else end, title))
    found.sort(key=lambda c: c[0])
    return [Chapter(i, s, e, t or f"Chapter {i + 1}") for i, (s, e, t) in enumerate(found)]


def current(chapters: list[Chapter], position: float) -> Chapter | None:
    """Chapter containing ``position`` (the last one started), or None before the first."""
    if not chapters or not isinstance(position, (int, float)) or not math.isfinite(position):
        return None
    i = bisect.bisect_right([c.start for c in chapters], position) - 1
    return chapters[i] if i >= 0 else None


def jump(chapters: list[Chapter], position: float, direction: int, restart_after: float = 3.0):
    """Start time for next (+1) or previous (-1); previous restarts the current
    chapter when more than ``restart_after`` seconds in. None when there is nowhere to go."""
    if not chapters:
        return None
    here = current(chapters, position)
    if direction > 0:
        nxt = [c for c in chapters if c.start > position + 1e-6]
        return nxt[0].start if nxt else None
    if here is None:
        return None
    if position - here.start > restart_after or here.index == 0:
        return here.start if position > here.start + 1e-6 else None
    return chapters[here.index - 1].start


def clock(seconds: float) -> str:
    """``m:ss`` or ``h:mm:ss`` for a chapter start; never raises."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        return "0:00"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def rows(chapters: list[Chapter], position: float | None = None) -> list[dict]:
    """Display rows ``{index, title, start, at, current}`` for a chapter picker."""
    here = current(chapters, position) if position is not None else None
    return [{"index": c.index, "title": c.title or f"Chapter {c.index + 1}", "start": c.start,
             "at": clock(c.start), "current": here is not None and here.index == c.index}
            for c in chapters]


def source_to_stream(chapter_start: float, stream_offset: float = 0.0) -> float:
    """Exact stream time for a chapter when the stream was started at a source offset
    (restart-at-offset seeks): chapter start minus the offset, floored at 0."""
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (chapter_start, stream_offset)):
        return 0.0
    return max(0.0, float(chapter_start) - float(stream_offset))
