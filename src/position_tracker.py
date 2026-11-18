"""Playback position estimation.

Tracks the current playback position from a start base plus elapsed time,
accounting for pause/resume.  When the device reports an authoritative
``current_time`` (via :meth:`device_update`), that takes precedence so the
seekbar stays synced with the player instead of drifting while paused.

No GUI toolkit dependencies: safe to import and test on any machine.
"""
from __future__ import annotations

import time


class PositionTracker:
    def __init__(self) -> None:
        self.known = False
        self.duration = 0.0
        self._base = 0.0
        self._epoch = time.monotonic()
        self._playing = False
        self._paused_accum = 0.0
        self._pause_started: float | None = None
        # Device-authoritative position (current_time from the player). When set
        # it takes precedence over the estimated base/epoch model so the seekbar
        # stays synced with the device instead of drifting while paused.
        self._device_pos: float | None = None
        self._device_epoch: float = 0.0

    def start(self, base: float, duration: float, playing: bool = True) -> None:
        self.known = True
        self.duration = duration or self.duration
        self._base = max(0.0, base)
        self._epoch = time.monotonic()
        self._playing = playing
        self._paused_accum = 0.0
        self._pause_started = None
        # Clearing device position falls back to the estimated model.
        self._device_pos = None
        self._device_epoch = 0.0

    def set_state(self, playing: bool) -> None:
        if playing == self._playing:
            return
        now = time.monotonic()
        if playing:
            if self._pause_started is not None:
                self._paused_accum += now - self._pause_started
                self._pause_started = None
        else:
            self._pause_started = now
        self._playing = playing

    def device_update(self, current: float, duration: float | None) -> None:
        self.known = True
        self.duration = duration or self.duration
        # Record the device's authoritative position; play state governs whether
        # it advances between polls so a paused stream does not creep forward.
        self._device_pos = max(0.0, current)
        self._device_epoch = time.monotonic()

    def rebase(self, value: float) -> None:
        self.start(value, self.duration, self._playing)

    def value(self, now: float | None = None) -> float | None:
        if not self.known:
            return None
        now = now or time.monotonic()
        if self._device_pos is not None:
            value = self._device_pos
            if self._playing:
                value += now - self._device_epoch
            if self.duration:
                value = min(value, self.duration)
            return max(0.0, value)
        # Estimated mode: base + elapsed, adjusted for paused time.
        paused = self._paused_accum
        if self._pause_started is not None:
            paused += now - self._pause_started
        value = self._base + (now - self._epoch - paused)
        if self.duration:
            value = min(value, self.duration)
        return max(0.0, value)

    def clear(self) -> None:
        self.known = False
        self.duration = 0.0
        self._playing = False
        self._paused_accum = 0.0
        self._pause_started = None
        self._device_pos = None
        self._device_epoch = 0.0
