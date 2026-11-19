"""Recover an owned Cast HLS session after its live segment window rolls over.

This module is GTK-free: it only decides whether to schedule the existing
asynchronous restart path. A short pause retains normal receiver play/pause.
"""
from __future__ import annotations

import math

import streamer


def resume_from_long_pause(window, session, device, renderer, want_play: bool) -> bool:
    """Restart at the frozen source clock; never cast to a foreign receiver.

    Returns True only after scheduling a serialised recovery. Caller must
    retain normal transport handling for short pauses, DLNA and direct play.
    """
    if (
        not want_play
        or renderer is not None
        or session is None
        or session.mode != "transcode"
        or window.device_state != "PAUSED"
        or window.external
        or window._closing
        or getattr(session.state, "device", None) != device
        or not window.tracker.known
        or window.tracker.playing
        or window.tracker.paused_for() < streamer.HLS_PAUSE_RESTART_AFTER
    ):
        return False

    # No fabricated zero-second restart if the receiver clock is unknown.
    position = window.tracker.value()
    if not isinstance(position, (float, int)) or not math.isfinite(position):
        return False
    if position < 0:
        return False
    window.busy = True
    window._refresh_controls()
    window._restart_at(session, float(position), resume_after_pause=True)
    return True
