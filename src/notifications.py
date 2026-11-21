"""Pure desktop-notification policy for finished, error and device-lost events (#267).

The GUI posts a Gio.Notification for a small allow-list of events when the
window is not focused. Keeping the decision here makes the policy testable
without GTK, a display or a receiver.
"""
from __future__ import annotations

FINISHED = "finished"
ERROR = "error"
DEVICE_LOST = "device_lost"
EVENTS = frozenset({FINISHED, ERROR, DEVICE_LOST})


def enabled(cfg: dict) -> bool:
    """Notifications default to on; only an explicit false disables them."""
    return bool(cfg.get("notifications", True))


def should_notify(cfg: dict, event: str, *, window_active: bool) -> bool:
    """Return True only for a known event when enabled and the window is unfocused."""
    if event not in EVENTS:
        return False
    if not enabled(cfg):
        return False
    return not window_active
