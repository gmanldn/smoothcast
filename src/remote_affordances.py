"""One capability view that drives every remote control (#337). Pure.

Each control is ``{"state": enabled|unsupported|busy|unknown|unauthorised,
"reason": str}``. The same ``check`` backs both the snapshot the phone renders
and server-side rejection, so a disabled control and a crafted request agree.
Unknown or offline never reads as supported.
"""
from __future__ import annotations

ENABLED, UNSUPPORTED, BUSY, UNKNOWN, UNAUTHORISED = (
    "enabled", "unsupported", "busy", "unknown", "unauthorised")
CONTROLS = {                       # control -> (capability flag, role permission)
    "play": ("can_pause", "control"), "pause": ("can_pause", "control"),
    "stop": ("can_stop", "control"), "seek": ("can_seek", "seek"),
    "volume": ("can_set_volume", "volume"), "tracks": ("can_change_tracks", "change_tracks"),
    "output": ("can_switch_output", "host"),
}
WHY = {"can_seek": "This TV can't skip within this film.",
       "can_set_volume": "This TV's volume can't be set from here.",
       "can_change_tracks": "Tracks can't be changed on this TV.",
       "can_pause": "This TV can't pause.", "can_stop": "This TV can't be stopped from here.",
       "can_switch_output": "Only the host can change the TV."}


def view(caps: dict | None, perms: set[str], *, online: bool = True, busy: bool = False,
         transcode_changes: set[str] | None = None) -> dict[str, dict]:
    """Per-control state. ``caps`` None or offline -> unknown (never 'enabled')."""
    out = {}
    for name, (flag, perm) in CONTROLS.items():
        if perm not in perms and "host" not in perms:
            out[name] = {"state": UNAUTHORISED, "reason": "You don't have permission for this."}
        elif caps is None or not online:
            out[name] = {"state": UNKNOWN, "reason": "Waiting for the TV to respond."}
        elif caps.get(flag) is None:
            out[name] = {"state": UNKNOWN, "reason": "Not known for this TV yet."}
        elif not caps[flag]:
            reason = WHY.get(flag, "Not supported.")
            if transcode_changes and name in transcode_changes:
                reason += " Transcoding may enable it."
            out[name] = {"state": UNSUPPORTED, "reason": reason}
        elif busy:
            out[name] = {"state": BUSY, "reason": "The TV is busy. Try again in a moment."}
        else:
            out[name] = {"state": ENABLED, "reason": ""}
    return out


def check(control: str, caps: dict | None, perms: set[str], **kw) -> tuple[bool, str]:
    """Server-side gate for a crafted request: (allowed, reason)."""
    item = view(caps, perms, **kw).get(control)
    if item is None:
        return False, "Unknown control."
    return item["state"] == ENABLED, item["reason"]


def changed(old: dict, new: dict) -> list[str]:
    """Controls whose state differs, so the UI updates only what moved."""
    return [k for k in new if old.get(k, {}).get("state") != new[k]["state"]]
