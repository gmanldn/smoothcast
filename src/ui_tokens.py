"""Shared geometry tokens for the GTK app and the web room (#708 slice 1).

One scale for corner radii; colours live in `design_tokens` (web) and
libadwaita (GTK). GTK-free. The web page declares ``--r-sm/md/lg`` and the GTK
stylesheet is snapped to the same scale, so a card has the same corners on both
surfaces. `tests/test_ui_tokens.py` fails when either surface drifts.
"""
from __future__ import annotations

import re

RADIUS = {"sm": 10, "md": 14, "lg": 22, "pill": 999}
_STEPS = sorted(v for k, v in RADIUS.items() if k != "pill")


def snap(px: int) -> int:
    """Nearest token radius; 0 stays square (flush panels), 99+ is a pill."""
    if px <= 0:
        return 0
    if px >= 99:
        return RADIUS["pill"]
    return min(_STEPS, key=lambda v: (abs(v - px), v))


def snap_gtk_radii(css: bytes) -> bytes:
    """Rewrite every ``border-radius: Npx`` in a GTK stylesheet onto the scale."""
    def one(match: re.Match[bytes]) -> bytes:
        return match.group(1) + str(snap(int(match.group(2)))).encode() + b"px"
    return re.sub(rb"(border-radius:\s*)(\d+)px", one, css)
