"""Compact mini-player layout policy (#118). Pure; the GTK layer applies the result.

Decides which controls stay visible at a given window width. Essential transport,
output and subtitle controls are never hidden; only decoration is dropped. No
always-on-top promise is made (Wayland cannot honour it).
"""
from __future__ import annotations

COMPACT_MAX_WIDTH = 520
TINY_MAX_WIDTH = 340
ESSENTIAL = ("play_pause", "seek", "output", "subtitles", "volume")
EXTRAS = ("thumbnail", "title", "queue", "next_prev", "audio_track", "time_labels")


def is_compact(width) -> bool:
    return isinstance(width, (int, float)) and 0 < width <= COMPACT_MAX_WIDTH


def layout(width, user_enabled: bool = False) -> dict:
    """Visible controls and arrangement for ``width``; mini mode if enabled or narrow."""
    compact = bool(user_enabled) or is_compact(width)
    if not compact:
        return {"mode": "full", "visible": ESSENTIAL + EXTRAS, "orientation": "wide"}
    tiny = isinstance(width, (int, float)) and 0 < width <= TINY_MAX_WIDTH
    extras = ("time_labels",) if tiny else ("thumbnail", "title", "next_prev", "time_labels")
    return {"mode": "mini", "visible": ESSENTIAL + extras,
            "orientation": "stacked" if tiny else "row"}


def essentials_always_present(width, user_enabled=False) -> bool:
    return all(c in layout(width, user_enabled)["visible"] for c in ESSENTIAL)
