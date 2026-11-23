"""User-selectable accent colour presets with computed text contrast (issue #135 / SC-126).

GTK-free and standard library only. A small, fixed set of presets keeps the
choice bounded and accessible: every preset is checked (by tests and by
``text_on``) so button text reaches WCAG AA contrast (4.5:1) on the accent and
on its hover shade, and the accent itself reaches 3:1 against the app surfaces.

The result is an extra application-level CSS provider that overrides only the
accent-coloured rules of SmoothCast's own stylesheet; the user's GTK theme is
never edited, and choosing "Default" removes the override entirely.
"""
from __future__ import annotations

import re

DARK_TEXT = "#0c1c2b"
LIGHT_TEXT = "#ffffff"
SURFACES = ("#151f2d", "#0b111b")  # cards and canvas the accent must stand out against
DEFAULT_ID = "default"

# (id, label, accent). The default is SmoothCast's built-in blue and adds no override.
PRESETS: tuple[tuple[str, str, str], ...] = (
    (DEFAULT_ID, "Default blue", "#79baff"),
    ("teal", "Teal", "#4fd1c5"),
    ("green", "Green", "#6fd08c"),
    ("amber", "Amber", "#ffc857"),
    ("orange", "Orange", "#ff9f68"),
    ("rose", "Rose", "#ff8fab"),
    ("violet", "Violet", "#b79cff"),
)
IDS = frozenset(preset_id for preset_id, _label, _hex in PRESETS)
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


def normalize(value: object) -> str:
    """A valid preset id, or ``default`` for anything else (never raises)."""
    return value if isinstance(value, str) and value in IDS else DEFAULT_ID


def _rgb(colour: str) -> tuple[int, int, int]:
    if not _HEX.fullmatch(colour):
        raise ValueError(f"not a #rrggbb colour: {colour!r}")
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _channel(value: int) -> float:
    unit = value / 255
    return unit / 12.92 if unit <= 0.03928 else ((unit + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    """WCAG 2.x relative luminance of a ``#rrggbb`` colour."""
    red, green, blue = _rgb(colour)
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio, from 1 (identical) to 21 (black on white)."""
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def mix(first: str, second: str, amount: float) -> str:
    """Blend *first* towards *second* by *amount* (0..1), as ``#rrggbb``."""
    amount = max(0.0, min(1.0, amount))
    a, b = _rgb(first), _rgb(second)
    return "#" + "".join(f"{round(x * (1 - amount) + y * amount):02x}" for x, y in zip(a, b))


def text_on(background: str) -> str:
    """The readable text colour (dark or white) with the higher contrast on *background*."""
    if contrast_ratio(background, DARK_TEXT) >= contrast_ratio(background, LIGHT_TEXT):
        return DARK_TEXT
    return LIGHT_TEXT


def accent_hex(preset: object) -> str:
    return next(h for pid, _label, h in PRESETS if pid == normalize(preset))


def css_for(preset: object) -> str:
    """Override CSS for *preset*; empty for the default (no override at all)."""
    preset_id = normalize(preset)
    if preset_id == DEFAULT_ID:
        return ""
    accent = accent_hex(preset_id)
    hover = mix(accent, LIGHT_TEXT, 0.18)
    border = mix(accent, LIGHT_TEXT, 0.35)
    text = text_on(accent)
    return f"""
button.suggested-action, button.primary-action, button.big-play {{
    color: {text};
    background-color: {accent};
    border-color: {border};
}}
button.suggested-action:hover, button.primary-action:hover, button.big-play:hover {{
    background-color: {hover};
}}
scale highlight {{
    background-color: {accent};
}}
scale slider {{
    background-color: {accent};
    border-color: {border};
}}
switch:checked {{
    background-color: {accent};
}}
.queue-row.current .queue-title {{
    color: {hover};
}}
"""
