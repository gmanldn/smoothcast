"""Canonical user-facing media states (distinct from protocol wire values).

Keep receiver enums raw in JSON and diagnostics; UI surfaces consume these
labels. MPRIS has its own required D-Bus status vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatePresentation:
    label: str
    short: str
    accessible: str
    icon: str
    mpris: str


STATES = {
    "PLAYING": StatePresentation("Playing", "Playing", "Media is playing on the receiver", "media-playback-start-symbolic", "Playing"),
    "PAUSED": StatePresentation("Paused", "Paused", "Playback is paused", "media-playback-pause-symbolic", "Paused"),
    "BUFFERING": StatePresentation("Buffering…", "Buffering", "Waiting for enough media to continue playback", "view-refresh-symbolic", "Playing"),
    "IDLE": StatePresentation("Ready", "Ready", "Receiver is ready for playback", "media-playback-stop-symbolic", "Stopped"),
    "OFFLINE": StatePresentation("Receiver offline", "Offline", "The selected receiver cannot be reached", "network-offline-symbolic", "Stopped"),
    "UNKNOWN": StatePresentation("State unavailable", "Unknown", "Receiver did not report a reliable playback state", "dialog-question-symbolic", "Stopped"),
    "ERROR": StatePresentation("Playback error", "Error", "Playback could not continue", "dialog-error-symbolic", "Stopped"),
    "PREPARING": StatePresentation("Preparing…", "Preparing", "Preparing the next media source", "content-loading-symbolic", "Stopped"),
    "EXTERNAL": StatePresentation("External playback", "External", "Another application owns receiver playback", "media-playback-start-symbolic", "Playing"),
    "LOCAL_PLAYING": StatePresentation("Playing locally", "Playing", "Media is playing in the local preview", "media-playback-start-symbolic", "Playing"),
    "LOCAL_PAUSED": StatePresentation("Preview paused", "Paused", "The local preview is paused", "media-playback-pause-symbolic", "Paused"),
}


def present(value: str | None) -> StatePresentation:
    """Unknown protocol values are *not* displayed as raw enumerations."""
    return STATES.get(str(value or "").upper(), STATES["UNKNOWN"])
