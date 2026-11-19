#!/usr/bin/env python3
"""Subtitle burn-in toggle and live subtitle-delay calibration.

A non-zero delay is applied by FFmpeg, so it always burns captions into the
picture: a Cast receiver cannot time-shift a sidecar track. The delay is saved
per film in the config; ``SessionMixin`` reads it for every cast and restart.
"""
from __future__ import annotations

import subtitle_delay

from cast_widgets import save_config


class SubtitleMixin:
    def _on_burn(self, switch, _param) -> None:
        self.cfg["burn_subs"] = switch.get_active()
        save_config(self.cfg)
        if switch.get_active():
            self.toast("Subtitles will be burned in (slower encode)")


    def _adjust_subtitle_delay(self, direction: int) -> None:
        """Move subtitles 100 ms later (+1) or earlier (-1); 0 resets to none.

        The value is saved per film. A live HLS/DLNA stream is restarted at
        the current film position so the new timing is burned in; the old
        stream stays owned until the replacement is confirmed.
        """
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
        current = subtitle_delay.get(self.cfg, path)
        new = 0 if direction == 0 else subtitle_delay.step(current, direction)
        if new == current:
            self.toast("Subtitle delay already off" if new == 0
                       else f"Subtitle delay limit reached ({subtitle_delay.label(new)})")
            return
        subtitle_delay.put(self.cfg, path, new)
        save_config(self.cfg)
        text = f"Subtitle delay {subtitle_delay.label(new)}"
        if state is None:
            self.toast(text + " — applies when you cast")
            return
        if not (state.subs or state.embedded_subtitle_index >= 0):
            self.toast(text + " — this stream has no subtitles")
            return
        if session.mode == "direct":
            self.toast(text + " — applies the next time you cast")
            return
        self.busy = True
        self._refresh_controls()
        position = self.tracker.value() or 0.0
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        self.tracker.device_update(position, duration)
        self._restart_at(session, position)
        self.toast(text + " — stream restarted")
