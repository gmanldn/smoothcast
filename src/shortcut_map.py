"""One shared, declarative shortcuts guide for GTK desktop and web room.

The browser is sent only these predefined bindings; input focus and receiver
permissions are enforced at each frontend's invocation boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    desktop: str
    browser: str
    label: str
    action: str


SHARED = (
    Shortcut("space", " ", "Play or pause", "play_pause"),
    Shortcut("Left", "ArrowLeft", "Skip back 10 seconds", "seek_back"),
    Shortcut("Right", "ArrowRight", "Skip forward 10 seconds", "seek_forward"),
    Shortcut("Up", "ArrowUp", "Volume up 5%", "volume_up"),
    Shortcut("Down", "ArrowDown", "Volume down 5%", "volume_down"),
    Shortcut("m", "m", "Toggle mute", "mute"),
    Shortcut("n", "n", "Next in queue", "next"),
    Shortcut("p", "p", "Previous in queue", "previous"),
    Shortcut("question", "?", "Keyboard shortcuts", "help"),
)


def desktop_labels() -> list[tuple[str, str]]:
    return [(item.desktop, item.label) for item in SHARED]


def browser_json() -> str:
    """Safe HTML script literal: only static predefined values, never user data."""
    return json.dumps([{
        "key": item.browser, "label": item.desktop, "description": item.label,
        "action": item.action,
    } for item in SHARED], ensure_ascii=True, separators=(",", ":"))
