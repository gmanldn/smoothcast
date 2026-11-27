"""Probed DRM render nodes for hardware encoding (#703 slice 1). GTK-free, no I/O beyond a listdir.

A machine with an integrated and a discrete GPU may expose ``renderD129`` only;
a fixed ``renderD128`` then disables hardware encode for no reason.
"""
from __future__ import annotations

import os
import re

DRI_DIR = "/dev/dri"
FALLBACK = "/dev/dri/renderD128"
_NODE = re.compile(r"renderD(\d+)\Z")


def render_nodes(dri_dir: str = DRI_DIR) -> list[str]:
    """Render nodes present, lowest number first; empty when none or unreadable."""
    try:
        names = os.listdir(dri_dir)
    except OSError:
        return []
    found = sorted((int(m.group(1)), n) for n in names if (m := _NODE.match(n)))
    return [os.path.join(dri_dir, n) for _, n in found]


def preferred(dri_dir: str = DRI_DIR) -> str:
    """The first render node, or the historical default so behaviour is unchanged."""
    nodes = render_nodes(dri_dir)
    return nodes[0] if nodes else FALLBACK
