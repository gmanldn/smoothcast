"""Fail-closed test environment: never connect GTK to the user's session.

Ordinary pytest is entirely headless. Clear inherited display/session channels
*before* collection, so even an accidental direct PyGObject import cannot
connect to the user's running Wayland/X11 desktop or D-Bus session.

Only the separate opt-in scripts/test_gui_isolated.py may create GTK windows,
and it supplies its own disposable Xvfb session and credentials.
"""
from __future__ import annotations

import os

os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"
os.environ["GDK_BACKEND"] = "x11"  # No X11 server without DISPLAY.
for name in (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
    "SMOOTHCAST_GUI_TEST_ISOLATED",
):
    os.environ.pop(name, None)
