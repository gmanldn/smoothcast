"""Pure preference choices shared by the GTK Preferences window and headless tests.

The order of playback options intentionally matches the existing in-player
Gtk.DropDown controls, so preferences delegate to their established handlers.
"""
from __future__ import annotations

import accent
import density

OPTIONS: dict[str, tuple[tuple[str, str | int], ...]] = {
    "quality": (("High", "high"), ("Balanced", "balanced"), ("Data saver", "saver")),
    "audio": (("Original", "original"), ("Dialogue auto-fix", "dialogue"), ("Night mode", "night")),
    "rotation": (("No rotation", 0), ("90°", 90), ("180°", 180), ("270°", 270)),
    "subs": (("Off", "off"), ("Automatic", "auto"), ("Choose a file…", "pick"), ("Embedded text", "embedded")),
    "color_scheme": (("Follow system", "default"), ("Light", "force-light"), ("Dark", "prefer-dark")),
    "accent": tuple((label, preset_id) for preset_id, label, _hex in accent.PRESETS),
    "density": tuple((label, preset_id) for preset_id, label, _scale in density.PRESETS),
}


def labels(key: str) -> list[str]:
    return [label for label, _value in OPTIONS[key]]


def selected_index(key: str, current: object) -> int:
    for index, (_label, value) in enumerate(OPTIONS[key]):
        if type(value) is type(current) and value == current:
            return index
    return 0


def selected_value(key: str, index: int) -> str | int:
    choices = OPTIONS[key]
    if type(index) is not int or not 0 <= index < len(choices):
        raise ValueError(f"Invalid {key} preference choice: {index!r}")
    return choices[index][1]
