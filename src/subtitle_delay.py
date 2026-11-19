"""Bounded, per-film subtitle delay and the FFmpeg timing shift it needs.

A positive delay shows each cue *later*; a negative delay shows it earlier.
The value is whole milliseconds, clamped to +/-30 s and stored per film so it
survives restarts. This module is pure (no GTK, no processes, no network).

Burn-in timing: libass draws a cue when the frame timestamp it sees falls in
the cue interval. The ``subtitles`` filter sees timestamps relative to the
start of the *encode*, so a stream started with ``-ss`` needs the seek offset
added back, and the user delay subtracted. Both are folded into one
``setpts`` pair wrapped around the filter, which keeps every other frame
timestamp (and therefore A/V sync) unchanged.
"""
from __future__ import annotations

import math
from collections.abc import MutableMapping

STEP_MS = 100
LIMIT_MS = 30_000
CONFIG_KEY = "subtitle_delay_by_file"
MAX_ENTRIES = 512


def normalize(value: object) -> int:
    """Return a safe whole-millisecond delay; unusable input means no delay."""
    if type(value) is bool or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return max(-LIMIT_MS, min(LIMIT_MS, int(round(value))))


def step(current: object, direction: int) -> int:
    """Move one 100 ms step later (direction > 0) or earlier (< 0)."""
    value = normalize(current)
    if direction == 0:
        return value
    return normalize(value + (STEP_MS if direction > 0 else -STEP_MS))


def label(delay_ms: object) -> str:
    """Short human label such as ``+0.3 s`` or ``-1.5 s``; ``Off`` at zero."""
    ms = normalize(delay_ms)
    if ms == 0:
        return "Off"
    text = f"{ms / 1000:+.3f}".rstrip("0").rstrip(".")
    return f"{text.replace('-', chr(0x2212))} s"


def filter_shift(offset_s: float, delay_ms: object) -> tuple[str, str] | None:
    """Return the (before, after) ``setpts`` filters around ``subtitles``.

    ``offset_s`` is the ``-ss`` start of the encode in source seconds. Returns
    None when no shift is needed, so an unchanged stream keeps its exact
    pre-existing filter graph.
    """
    try:
        offset = float(offset_s)
    except (TypeError, ValueError):
        offset = 0.0
    if not math.isfinite(offset) or offset < 0:
        offset = 0.0
    shift = offset - normalize(delay_ms) / 1000
    if abs(shift) < 0.0005:
        return None
    return f"setpts=PTS{shift:+.3f}/TB", f"setpts=PTS{-shift:+.3f}/TB"


def get(cfg: object, path: object) -> int:
    """Saved delay for a film (0 when none or when the stored value is bad)."""
    saved = cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None
    if not isinstance(saved, dict):
        return 0
    return normalize(saved.get(str(path), 0))


def put(cfg: MutableMapping, path: object, delay_ms: object) -> int:
    """Store (or clear, at zero) a film's delay; returns the stored value."""
    ms = normalize(delay_ms)
    current = cfg.get(CONFIG_KEY)
    saved = dict(current) if isinstance(current, dict) else {}
    key = str(path)
    if ms == 0:
        saved.pop(key, None)
    else:
        saved.pop(key, None)  # re-insert so the newest entry is kept last
        while len(saved) >= MAX_ENTRIES:
            saved.pop(next(iter(saved)))
        saved[key] = ms
    cfg[CONFIG_KEY] = saved
    return ms
