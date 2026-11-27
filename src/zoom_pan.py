"""Zoom/pan and manual crop geometry (#115). Pure; no automatic crop detection.

Coordinates are normalised to the source frame. ``View`` is the visible window at
1x/2x/4x; ``crop_filter`` turns it (or a manual rectangle) into an FFmpeg crop with
even width/height and in-bounds origin, as H.264/yuv420p requires.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ZOOMS = (1, 2, 4)
PAN_STEP = 0.1  # fraction of the visible window per arrow press


@dataclass(frozen=True)
class View:
    zoom: int = 1
    cx: float = 0.5   # centre, normalised
    cy: float = 0.5

    def size(self) -> float:
        return 1.0 / self.zoom


def _clamp_view(zoom: int, cx: float, cy: float) -> View:
    half = 0.5 / zoom
    cx = min(max(cx, half), 1 - half) if math.isfinite(cx) else 0.5
    cy = min(max(cy, half), 1 - half) if math.isfinite(cy) else 0.5
    return View(zoom, cx, cy)


def set_zoom(view: View, zoom: int) -> View:
    return _clamp_view(zoom if zoom in ZOOMS else 1, view.cx, view.cy)


def step_zoom(view: View, direction: int) -> View:
    i = ZOOMS.index(view.zoom) + (1 if direction > 0 else -1)
    return set_zoom(view, ZOOMS[max(0, min(len(ZOOMS) - 1, i))])


def pan(view: View, dx: int, dy: int) -> View:
    """Move by arrow-key steps; always stays inside the frame."""
    s = view.size() * PAN_STEP
    return _clamp_view(view.zoom, view.cx + dx * s, view.cy + dy * s)


def crop_rect(width: int, height: int, view: View) -> tuple[int, int, int, int]:
    """(w, h, x, y) in pixels; w/h even and >=2, origin in bounds."""
    w = max(2, int(width * view.size()) // 2 * 2)
    h = max(2, int(height * view.size()) // 2 * 2)
    x = min(max(0, round(view.cx * width - w / 2)), max(0, width - w)) // 2 * 2
    y = min(max(0, round(view.cy * height - h / 2)), max(0, height - h)) // 2 * 2
    return w, h, x, y


def validate_manual(width: int, height: int, x, y, w, h) -> tuple[int, int, int, int] | None:
    """Manual crop in pixels -> even, in-bounds rect, or None if unusable."""
    try:
        vals = [int(v) for v in (x, y, w, h)]
    except (TypeError, ValueError, OverflowError):
        return None
    x, y, w, h = vals
    if width < 2 or height < 2 or x < 0 or y < 0 or w < 2 or h < 2:
        return None
    if x + w > width or y + h > height:
        return None
    return w // 2 * 2, h // 2 * 2, x // 2 * 2, y // 2 * 2


def crop_filter(width: int, height: int, view: View | None = None, manual=None) -> list[str]:
    """FFmpeg filter fragments; empty for 1x with no manual crop."""
    if manual is not None:
        rect = validate_manual(width, height, *manual)
        return [] if rect is None else ["crop=%d:%d:%d:%d" % rect]
    if view is None or view.zoom == 1:
        return []
    return ["crop=%d:%d:%d:%d" % crop_rect(width, height, view)]
