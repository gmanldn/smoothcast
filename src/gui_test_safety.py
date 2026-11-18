"""Fail-closed guard for GTK self-tests: never test against the user's desktop.

Only scripts/test_gui_isolated.py sets up the dedicated Xvfb display, private
XDG directories and disconnected session bus. Normal pytest never starts GTK.
"""
from __future__ import annotations

import os
import hmac
from pathlib import Path
from typing import Mapping


def is_isolated_gui_test(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    if values.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        return False
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
    if not authority or not Path(authority).is_file():
        return False
    # A boolean flag alone is insufficient: it can leak into a developer
    # shell. Require a one-use capability written in the isolated temporary
    # XDG runtime directory by scripts/test_gui_isolated.py.
    token = values.get("SMOOTHCAST_GUI_TEST_TOKEN", "")
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        return False
    runtime = Path(values["XDG_RUNTIME_DIR"])
    marker = runtime / ".smoothcast-gui-test-token"
    try:
        if marker.is_symlink() or not marker.is_file():
            return False
        return hmac.compare_digest(marker.read_text(encoding="ascii"), token)
    except (OSError, UnicodeError, ValueError):
        return False


def refusal() -> str:
    return (
        "Refusing SmoothCast GUI self-test on an unisolated desktop. "
        "Run: python3 scripts/test_gui_isolated.py "
        "(requires Xvfb/xvfb-run/xauth)."
    )
