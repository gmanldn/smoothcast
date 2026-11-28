#!/usr/bin/env python3
"""Subtitle burn-in toggle and live subtitle-delay calibration.

A non-zero delay is applied by FFmpeg, so it always burns captions into the
picture: a Cast receiver cannot time-shift a sidecar track. The delay is saved
per film in the config; ``SessionMixin`` reads it for every cast and restart.
"""
from __future__ import annotations

import subtitle_delay

from cast_widgets import save_config


class SubtitleController:
    """Composition replacement for SubtitleMixin (#691): drives the window, owns no widgets."""

    def __init__(self, window, save=save_config) -> None:
        self.w = window
        self.save = save

    def _on_burn(self, switch, _param) -> None:
        w = self.w
        if w._syncing:
            return
        w.cfg["burn_subs"] = switch.get_active()
        self.save(w.cfg)
        if switch.get_active():
            w.toast("Subtitles will be burned in (slower encode)")


    def _adjust_subtitle_delay(self, direction: int) -> None:
        """Move subtitles 100 ms later (+1) or earlier (-1); 0 resets to none.

        The value is saved per film. A live HLS/DLNA stream is restarted at
        the current film position so the new timing is burned in; the old
        stream stays owned until the replacement is confirmed.
        """
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
        current = subtitle_delay.get(w.cfg, path)
        new = 0 if direction == 0 else subtitle_delay.step(current, direction)
        if new == current:
            w.toast("Subtitle delay already off" if new == 0
                       else f"Subtitle delay limit reached ({subtitle_delay.label(new)})")
            return
        subtitle_delay.put(w.cfg, path, new)
        self.save(self.w.cfg)
        text = f"Subtitle delay {subtitle_delay.label(new)}"
        if state is None:
            w.toast(text + " — applies when you cast")
            return
        if not (state.subs or state.embedded_subtitle_index >= 0):
            w.toast(text + " — this stream has no subtitles")
            return
        if session.mode == "direct":
            w.toast(text + " — applies the next time you cast")
            return
        w.busy = True
        w._refresh_controls()
        position = w.tracker.value() or 0.0
        duration = w.tracker.duration or (w.media.duration if w.media else 0.0)
        w.tracker.device_update(position, duration)
        w._restart_at(session, position)
        w.toast(text + " — stream restarted")
