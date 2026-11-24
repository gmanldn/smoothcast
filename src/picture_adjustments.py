"""Bounded colour adjustments for encoded video (SC-103).

Pure functions: do not import GTK, start an encoder or read user media.
All four controls are neutral by default, so existing pictures stay unchanged.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

CONFIG_KEY = "picture_by_file"

DEFAULTS = {
    "picture_brightness": 0.0,
    "picture_contrast": 1.0,
    "picture_saturation": 1.0,
    "picture_hue": 0.0,
}

BOUNDS = {
    "picture_brightness": (-0.5, 0.5),
    "picture_contrast": (0.5, 1.5),
    "picture_saturation": (0.0, 2.0),
    "picture_hue": (-180.0, 180.0),
}


def validated(key: str, value: object) -> float:
    """Normalise hostile settings to the neutral value, never clamp silently."""
    default = DEFAULTS[key]
    if type(value) not in (int, float):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    lower, upper = BOUNDS[key]
    return number if math.isfinite(number) and lower <= number <= upper else default


def settings(config: Mapping[str, object] | None) -> dict[str, float]:
    """Return a fresh, safely normalised picture configuration."""
    values = config if isinstance(config, Mapping) else {}
    return {key: validated(key, values.get(key, default))
            for key, default in DEFAULTS.items()}


def active(config: Mapping[str, object] | None) -> bool:
    values = settings(config)
    return any(value != DEFAULTS[key] for key, value in values.items())


def for_path(config: Mapping[str, object] | None, path: object | None) -> dict[str, float]:
    """Return effective settings for one film, overriding the global values.

    A per-film preset is optional; missing keys fall back to the global
    controls, so an old preset never freezes unrelated settings.
    """
    values = settings(config)
    if path is None or not isinstance(config, Mapping):
        return values
    presets = config.get(CONFIG_KEY)
    preset = presets.get(str(path)) if isinstance(presets, Mapping) else None
    if isinstance(preset, Mapping):
        for key in DEFAULTS:
            if key in preset:
                values[key] = validated(key, preset[key])
    return values


def filters(config: Mapping[str, object] | None) -> list[str]:
    """Generate argument-safe FFmpeg filters; no shell interpolation.

    FFmpeg eq uses brightness (-1..1), contrast and saturation;
    hue=h uses degrees. Place this chain before subtitle overlays so
    captions retain their intended colours.
    """
    values = settings(config)
    if not active(values):
        return []
    brightness = values["picture_brightness"]
    contrast = values["picture_contrast"]
    saturation = values["picture_saturation"]
    hue = values["picture_hue"]
    chain: list[str] = []
    if (brightness, contrast, saturation) != (0.0, 1.0, 1.0):
        chain.append(
            f"eq=brightness={brightness:g}:contrast={contrast:g}:saturation={saturation:g}"
        )
    if hue != 0.0:
        chain.append(f"hue=h={hue:g}")
    return chain
