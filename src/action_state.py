"""GTK-free availability of transport actions from controller state (issue #458).

The web room must not depend on the desktop's GTK widget sensitivity: a control
that has not been refreshed since the receiver changed state would wrongly
reject (or accept) a remote command. These pure predicates derive availability
from the same state the desktop controls are refreshed from, so the desktop and
the web remote share one source of truth and cannot drift apart.
"""
from __future__ import annotations


def receiver_online(device_state: str) -> bool:
    """A receiver is usable unless it is reported offline."""
    return device_state != "OFFLINE"


def playback_active(session: object, external: bool) -> bool:
    """True while a receiver session or an externally-started cast is live."""
    return bool(session is not None and getattr(session, "state", None) is not None) or bool(external)


def local_preview_ready(preview_path: object, session: object, external: bool) -> bool:
    """True when a local file is open for preview and no receiver owns playback."""
    return preview_path is not None and session is None and not external


def can_play_pause(device_state: str, session: object, external: bool,
                   preview_path: object, busy: bool) -> bool:
    active = playback_active(session, external)
    local = local_preview_ready(preview_path, session, external)
    return not busy and ((receiver_online(device_state) and active) or local)


def can_stop(device_state: str, session: object, external: bool, preview_path: object,
             busy: bool, dlna_cancel: object) -> bool:
    active = playback_active(session, external)
    local = local_preview_ready(preview_path, session, external)
    return (not busy and ((receiver_online(device_state) and active) or local)) or (
        busy and dlna_cancel is not None)


def can_volume(device_state: str, volume_available: bool) -> bool:
    """Volume and mute share one availability rule: online and controllable."""
    return receiver_online(device_state) and bool(volume_available)
