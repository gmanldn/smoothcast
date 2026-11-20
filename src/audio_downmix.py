"""Dialogue-first surround-to-stereo downmix (a pure FFmpeg ``pan`` builder).

FFmpeg's default ``-ac 2`` matrix (measured with FFmpeg 7) puts a 5.1 centre
channel 3 dB *below* the front pair and no louder than the surrounds, so
dialogue, which lives in the centre, is the weakest part of the mix. For the
``dialogue`` and ``night`` audio profiles the centre is lifted about 5 dB
relative to that default and the fronts and surrounds are lowered.

Safety properties, all covered by tests:

* the LFE channel is never mixed in (as with FFmpeg's default; it overloads
  small speakers and a stereo stream gets no bass management);
* each output's coefficients sum to at most 1.0, so even fully correlated,
  full-scale input cannot clip before the limiter;
* only layouts whose channel order is known are handled; anything else
  returns ``None`` and the stream keeps the previous ``-ac 2`` behaviour;
* ``pan`` uses input channel *indices*, so the mix depends only on FFmpeg's
  fixed native channel order for the named layout, not on the file's tags;
* it is a plain per-sample matrix: no delay, no resampling, no buffering, so
  A/V sync is untouched.

This module has no GTK, process or network dependency.
"""
from __future__ import annotations

import math

DOWNMIX_PROFILES = frozenset({"dialogue", "night"})

# Weights (before normalisation): front L/R, centre, surround/back.
_FRONT = 0.6
_CENTRE = 1.0
_SURROUND = 0.35

# FFmpeg native channel order per layout name -> role of each input index.
# F = front left/right (side of the output it feeds), C = centre,
# S = surround/back left/right, M = mono-surround centre back (both sides),
# X = low-frequency effects (dropped).
_LAYOUTS: dict[str, str] = {
    "5.0": "FFCSS", "5.0(side)": "FFCSS",
    "5.1": "FFCXSS", "5.1(side)": "FFCXSS",
    "6.1": "FFCXMSS", "6.1(back)": "FFCXSSM",
    "7.1": "FFCXSSSS",
    "quad": "FFSS", "quad(side)": "FFSS", "4.0": "FFCM",
}
_CHANNELS = {name: len(roles) for name, roles in _LAYOUTS.items()}


def _floor4(value: float) -> float:
    """Round *down* so the printed coefficients can never sum above 1.0."""
    return math.floor(value * 10000) / 10000


def known_layout(layout: object, channels: object) -> str | None:
    """Return the canonical layout name if *layout* matches *channels*."""
    name = str(layout or "").strip().lower()
    if name in _LAYOUTS and _CHANNELS[name] == channels:
        return name
    return None


def _side_roles(roles: str, side: int) -> list[tuple[int, str]]:
    """Input index/role pairs that feed one output side (0=left, 1=right).

    Roles alternate left/right in FFmpeg's native order, so the n-th F or S
    belongs to the left output when n is even. C and M feed both sides.
    """
    result: list[tuple[int, str]] = []
    seen = {"F": 0, "S": 0}
    for index, role in enumerate(roles):
        if role in ("C", "M"):
            result.append((index, role))
        elif role in seen:
            if seen[role] % 2 == side:
                result.append((index, role))
            seen[role] += 1
    return result


def downmix_filter(channels: object, layout: object, profile: object) -> str | None:
    """Return the ``pan=stereo|...`` filter, or ``None`` to keep ``-ac 2``.

    ``None`` is returned for the ``original`` profile (unchanged behaviour),
    for mono/stereo sources and for any layout whose order is not known.
    """
    if profile not in DOWNMIX_PROFILES or type(channels) is not int or channels <= 2:
        return None
    name = known_layout(layout, channels)
    if name is None:
        return None
    roles = _LAYOUTS[name]
    weight = {"F": _FRONT, "C": _CENTRE, "S": _SURROUND, "M": _SURROUND}
    outputs = []
    for side, label in enumerate(("FL", "FR")):
        terms = _side_roles(roles, side)
        total = sum(weight[role] for _, role in terms)
        outputs.append(f"{label}=" + "+".join(
            f"{_floor4(weight[role] / total):.4f}*c{index}" for index, role in terms
        ))
    return "pan=stereo|" + "|".join(outputs)
