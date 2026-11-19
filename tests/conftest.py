"""Fail-closed test environment: never connect GTK to the user's session.

Ordinary pytest is entirely headless. Clear inherited display/session channels
*before* collection, so even an accidental direct PyGObject import cannot
connect to the user's running Wayland/X11 desktop or D-Bus session.

Only the separate opt-in scripts/test_gui_isolated.py may create GTK windows,
and it supplies its own disposable Xvfb session and credentials.
"""
from __future__ import annotations

import os
import tempfile

os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"
# Never read or write a developer's real home: settings (hls_port, cache_cap_mb),
# the cache dir (session.json, server.log) and the error log all live under HOME.
# Set before any test imports modules that compute paths from Path.home().
_HOME = tempfile.mkdtemp(prefix="smoothcast-test-home-")
os.environ["HOME"] = _HOME
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, ".config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_HOME, ".cache")
os.environ["XDG_DATA_HOME"] = os.path.join(_HOME, ".local", "share")
os.environ["GDK_BACKEND"] = "x11"  # No X11 server without DISPLAY.
for name in (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
    "SMOOTHCAST_GUI_TEST_ISOLATED",
):
    os.environ.pop(name, None)
