"""Installed, GTK-free access to SmoothCast's bundled application artwork.

Native wheels are expanded by pip into site-packages; keeping the icon
alongside this package means its location is independent of the Git checkout.
"""
from __future__ import annotations

from pathlib import Path


ICON_NAME = "local.cast-control"


def icon_path() -> Path:
    """Return the shipped GTK icon file; no system theme or GUI import."""
    return Path(__file__).resolve().parent / f"{ICON_NAME}.png"
