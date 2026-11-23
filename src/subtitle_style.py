"""Safe, preset-based styling for burned-in plain-text subtitles (SC-025).

Presets map to libass ``force_style`` overrides. Values are in libass's
default SRT script space (288 lines high), so they scale with the picture.

Authored styling is respected: ``force_style`` overrides *every* style in the
file, which would destroy the typesetting of an ASS/SSA script, so a preset is
only ever applied to plain-text formats (SRT, WebVTT, mov_text, ...). For any
other or unknown format the stream is left exactly as before, as it is for the
``default`` preset, which keeps the pre-existing filter graph byte for byte.

Pure module: no GTK, no processes, no network. Presets are a closed set, so no
user text ever reaches the FFmpeg filter string.
"""
from __future__ import annotations

from pathlib import PurePath

DEFAULT = "default"
CONFIG_KEY = "subtitle_style"

# name -> (label, ordered libass style overrides)
PRESETS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    DEFAULT: ("Default", ()),
    "large": ("Large", (("FontSize", "22"), ("Outline", "1.5"))),
    "high-contrast": ("High contrast", (
        ("FontSize", "20"), ("Bold", "1"), ("BorderStyle", "3"),
        ("Outline", "1"), ("Shadow", "0"), ("BackColour", "&H99000000"),
    )),
    "raised": ("Raised", (("FontSize", "18"), ("MarginV", "40"))),
}

# Formats that carry no styling of their own, so overriding them is safe.
PLAIN_CODECS = frozenset({"subrip", "srt", "webvtt", "vtt", "mov_text", "text"})
PLAIN_SUFFIXES = frozenset({".srt", ".vtt"})


def normalize(value: object) -> str:
    """A known preset name, else ``default`` (unusable config never raises)."""
    return value if isinstance(value, str) and value in PRESETS else DEFAULT


def from_config(cfg: object) -> str:
    """The saved preset of a config mapping (``default`` if absent or bad)."""
    return normalize(cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None)


def label(preset: object) -> str:
    return PRESETS[normalize(preset)][0]


def is_plain_text(codec: object = "", path: object = None) -> bool:
    """True only when the source is known to be unstyled plain text."""
    name = str(codec or "").strip().lower()
    if name:
        return name in PLAIN_CODECS
    suffix = PurePath(str(path)).suffix.lower() if path else ""
    return suffix in PLAIN_SUFFIXES


def force_style(preset: object, *, codec: object = "", path: object = None) -> str | None:
    """The ``:force_style='...'`` filter option, or None when nothing applies."""
    items = PRESETS[normalize(preset)][1]
    if not items or not is_plain_text(codec, path):
        return None
    return ":force_style='" + ",".join(f"{k}={v}" for k, v in items) + "'"
