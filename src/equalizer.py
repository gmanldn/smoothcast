"""10-band graphic equaliser model and FFmpeg filter builder (#111). Pure: no GTK or I/O.

Gains are clamped to +/-12 dB. A flat curve emits no filter so the default audio
chain is byte-identical to before. A negative preamp offsets boosts to avoid clipping.
"""
from __future__ import annotations

import math

BANDS_HZ = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
MAX_GAIN_DB = 12.0
DEFAULT = "flat"

PRESETS: dict[str, tuple[str, tuple[float, ...]]] = {
    "flat": ("Flat", (0,) * 10),
    "bass": ("Bass boost", (6, 5, 4, 2, 0, 0, 0, 0, 0, 0)),
    "treble": ("Treble boost", (0, 0, 0, 0, 0, 1, 2, 4, 5, 6)),
    "voice": ("Speech clarity", (-3, -2, -1, 0, 2, 4, 4, 2, 0, -2)),
    "loudness": ("Loudness", (5, 4, 1, 0, -1, 0, 0, 1, 4, 5)),
}


def clamp(gains) -> tuple[float, ...]:
    """Ten finite gains within range; anything malformed becomes flat."""
    try:
        values = [float(g) for g in gains]
    except (TypeError, ValueError):
        return PRESETS[DEFAULT][1]
    if len(values) != len(BANDS_HZ) or not all(math.isfinite(v) for v in values):
        return PRESETS[DEFAULT][1]
    return tuple(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, v)) for v in values)


def normalize(mode) -> str:
    return mode if isinstance(mode, str) and mode in PRESETS else DEFAULT


def gains_for(mode, custom=None) -> tuple[float, ...]:
    """Preset gains, or the user's ``custom`` curve when mode is ``custom``."""
    if mode == "custom":
        return clamp(custom)
    return clamp(PRESETS[normalize(mode)][1])


def filter_args(mode=DEFAULT, custom=None) -> list[str]:
    """FFmpeg ``-af`` filter fragments; empty when the curve is flat."""
    gains = gains_for(mode, custom)
    if not any(abs(g) >= 0.05 for g in gains):
        return []
    preamp = -max(0.0, max(gains))
    chain = [f"volume={preamp:.1f}dB"] if preamp else []
    chain += [f"equalizer=f={hz}:t=o:w=1:g={g:.1f}"
              for hz, g in zip(BANDS_HZ, gains) if abs(g) >= 0.05]
    return chain
