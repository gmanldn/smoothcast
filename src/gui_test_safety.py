"""Fail-closed guard for GTK self-tests: never test against the user's desktop.

Only scripts/test_gui_isolated.py sets up the dedicated Xvfb display, private
XDG directories and disconnected session bus. Normal pytest never starts GTK.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def is_isolated_gui_test(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    if values.get("SMOOTHCAST_GUI_TEST_ISOLATED") != "1":
        return False
    if values.get("GDK_BACKEND") != "x11" or not values.get("DISPLAY"):
        return False
    # A genuine Wayland session or DBus address could activate/focus the
    # user's primary application or use desktop portals.
    if values.get("WAYLAND_DISPLAY") or values.get("DBUS_SESSION_BUS_ADDRESS"):
        return False
    if not all(values.get(k) for k in (
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    )):
        return False
    authority = values.get("XAUTHORITY")
    return bool(authority and Path(authority).is_file())


def refusal() -> str:
    return (
        "Refusing SmoothCast GUI self-test on an unisolated desktop. "
        "Run: python3 scripts/test_gui_isolated.py "
        "(requires Xvfb/xvfb-run/xauth)."
    )
