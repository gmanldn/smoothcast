#!/usr/bin/env python3
"""Live lip-sync (audio delay) adjustment for the active or selected film (#113).

The delay is saved per film in the config and read by ``SessionMixin`` for every
cast and restart (see ``audio_delay``). FFmpeg applies it, so direct play cannot
be shifted: a non-zero delay makes the next cast a transcode, and a live
transcode is restarted at the current film position so the new timing starts
exactly where you were.
"""
from __future__ import annotations

import audio_delay

from cast_widgets import save_config


class AudioSyncController:
    """Composition replacement for AudioSyncMixin (#691): drives the window, owns no widgets."""

    def __init__(self, window, save=save_config) -> None:
        self.w = window
        self.save = save

    def adjust(self, direction: int) -> None:
        """Move the soundtrack 50 ms later (+1) or earlier (-1); 0 resets to none."""
        w = self.w
        session = w.session
        state = session.state if session is not None else None
        if state is not None:
            path = state.file
        elif w.media is not None:
            path = str(w.media.path)
        else:
            path = w._preview_path
        if not path:
            w.toast("Open a video first")
            return
        if state is not None and w.busy:
            w.toast("Hold on — finishing the last command")
            return
        current = audio_delay.get(w.cfg, path)
        new = 0 if direction == 0 else audio_delay.step(current, direction)
        if new == current:
            w.toast("Audio delay already off" if new == 0
                       else f"Audio delay limit reached ({audio_delay.label(new)})")
            return
        audio_delay.put(w.cfg, path, new)
        self.save(w.cfg)
        text = f"Audio delay {audio_delay.label(new)}"
        if state is None:
            w.toast(text + " — applies when you cast")
            return
        if session.mode == "direct":
            w.toast(text + " — applies the next time you cast (direct play cannot be shifted)")
            return
        w.busy = True
        w._refresh_controls()
        position = w.tracker.value() or 0.0
        duration = w.tracker.duration or (w.media.duration if w.media else 0.0)
        w.tracker.device_update(position, duration)
        w._restart_at(session, position)
        w.toast(text + " — stream restarted")
