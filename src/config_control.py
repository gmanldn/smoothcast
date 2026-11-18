"""Pure, bounded validation of untrusted JSON preferences before GTK uses them.

Never mutate caller defaults or retain their nested list/dict identities.
One malformed value must not discard other valid settings.
"""
from __future__ import annotations

from copy import deepcopy
import math


_OPTIONS = {
    "quality": frozenset({"high", "balanced", "saver"}),
    "audio": frozenset({"original", "dialogue", "night"}),
    "subs": frozenset({"off", "auto", "pick", "embedded"}),
    "color_scheme": frozenset({"default", "force-light", "prefer-dark"}),
}
_LIMITED_MAPS = frozenset({
    "positions", "audio_track_by_file", "subtitle_track_by_file",
})
_MAX_PATH = 4096
_MAX_ITEMS = 512


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def sanitise_config(raw: object, defaults: dict) -> dict:
    """Return an independent validated settings map.

    Corrupt/unknown individual keys revert to defaults, not the whole file.
    Small bounded collections prevent hostile JSON from blocking the GTK
    thread when the user launches the application.
    """
    cfg = deepcopy(defaults)
    if not isinstance(raw, dict):
        return cfg
    for key, value in raw.items():
        if key not in defaults:
            continue
        baseline = defaults[key]
        if key in _OPTIONS:
            if isinstance(value, str) and value in _OPTIONS[key]:
                cfg[key] = value
        elif key in {"recents", "cast_targets"}:
            if isinstance(value, list):
                limit = 8 if key == "recents" else 32
                cfg[key] = [
                    item for item in value[:_MAX_ITEMS]
                    if isinstance(item, str) and 0 < len(item) <= _MAX_PATH
                ][:limit]
        elif key in _LIMITED_MAPS:
            if isinstance(value, dict):
                clean: dict = {}
                for path, selection in list(value.items())[:_MAX_ITEMS]:
                    if not isinstance(path, str) or not 0 < len(path) <= _MAX_PATH:
                        continue
                    if key == "positions":
                        if _number(selection) and 0 <= selection <= 1e9:
                            clean[path] = float(selection)
                    elif type(selection) is int and -1 <= selection <= 1024:
                        clean[path] = selection
                cfg[key] = clean
        elif type(baseline) is bool:
            if type(value) is bool:
                cfg[key] = value
        elif key == "rotation":
            if type(value) is int and value in (0, 90, 180, 270):
                cfg[key] = value
        elif type(baseline) is int:
            lo, hi = (-100000, 100000) if key in {"window_x", "window_y"} else (
                (0, 1440) if key == "sleep_timer_minutes" else (1, 10000)
            )
            if type(value) is int and lo <= value <= hi:
                cfg[key] = value
        elif type(baseline) is float:
            bounds = {
                "audio_gain": (0, 24),
                "playback_speed": (0.5, 2),
                "sleep_timer_deadline": (0, 1e12),
            }
            lo, hi = bounds.get(key, (-1e12, 1e12))
            if _number(value) and lo <= value <= hi:
                cfg[key] = float(value)
        elif isinstance(baseline, str):
            if isinstance(value, str) and len(value) <= _MAX_PATH and (
                key != "device" or value.strip()
            ):
                cfg[key] = value
    return cfg
