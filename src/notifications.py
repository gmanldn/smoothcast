"""GTK-free policy for in-app playback alerts (#267, #543).

Finished, error and device-lost events remain visible via Adw.Toast and the
activity console. Never post a desktop-shell notification: Ubuntu Dock can
count those as unread badges. The policy needs no GTK or receiver.
"""
from __future__ import annotations

import state_labels

FINISHED = "finished"
ERROR = "error"
DEVICE_LOST = "device_lost"
EVENTS = frozenset({FINISHED, ERROR, DEVICE_LOST})


def enabled(cfg: dict) -> bool:
    """In-app playback notices default on; explicit false disables them."""
    return bool(cfg.get("notifications", True))


def should_notify(cfg: dict, event: str, *, window_active: bool) -> bool:
    """Notify in-app only for permitted background events; never the OS shell."""
    if event not in EVENTS:
        return False
    if not enabled(cfg):
        return False
    return not window_active


def event_title(event: str) -> str:
    """Use the central playback state vocabulary for status notifications."""
    if event == DEVICE_LOST:
        return state_labels.present("OFFLINE").label
    if event == ERROR:
        return state_labels.present("ERROR").label
    return "Playback finished"
