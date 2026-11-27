"""Honest floating-preview capability policy (#124). Pure: environment passed in.

A normal GTK4 toplevel cannot request always-on-top on Wayland; X11 window
managers honour a hint. This returns what may be offered and the plain sentence
to show, so the UI never promises an unsupported behaviour.
"""
from __future__ import annotations


def capability(session_type, desktop="", platform="linux") -> dict:
    """{'floating': small separate window offered, 'always_on_top': bool, 'message': str}."""
    session = str(session_type or "").lower()
    desk = str(desktop or "").lower()
    if platform in ("win32", "darwin"):
        return {"floating": True, "always_on_top": True,
                "message": "The mini preview stays above other windows."}
    if session == "x11":
        return {"floating": True, "always_on_top": True,
                "message": "The mini preview asks your window manager to keep it on top; "
                           "some window managers ignore this."}
    if session == "wayland":
        hint = " In GNOME, right-click the title bar and choose Always on Top." \
            if "gnome" in desk else ""
        return {"floating": True, "always_on_top": False,
                "message": "Wayland does not let apps keep a window on top." + hint}
    return {"floating": True, "always_on_top": False,
            "message": "Always-on-top is not available here; the preview opens as a normal small window."}
