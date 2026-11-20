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


class AudioSyncMixin:
    def _adjust_audio_delay(self, direction: int) -> None:
        """Move the soundtrack 50 ms later (+1) or earlier (-1); 0 resets to none."""
        session = self.session
        state = session.state if session is not None else None
        if state is not None:
            path = state.file
        elif self.media is not None:
            path = str(self.media.path)
        else:
            path = self._preview_path
        if not path:
            self.toast("Open a video first")
            return
        if state is not None and self.busy:
            self.toast("Hold on — finishing the last command")
            return
        current = audio_delay.get(self.cfg, path)
        new = 0 if direction == 0 else audio_delay.step(current, direction)
        if new == current:
            self.toast("Audio delay already off" if new == 0
                       else f"Audio delay limit reached ({audio_delay.label(new)})")
            return
        audio_delay.put(self.cfg, path, new)
        save_config(self.cfg)
        text = f"Audio delay {audio_delay.label(new)}"
        if state is None:
            self.toast(text + " — applies when you cast")
            return
        if session.mode == "direct":
            self.toast(text + " — applies the next time you cast (direct play cannot be shifted)")
            return
        self.busy = True
        self._refresh_controls()
        position = self.tracker.value() or 0.0
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        self.tracker.device_update(position, duration)
        self._restart_at(session, position)
        self.toast(text + " — stream restarted")
