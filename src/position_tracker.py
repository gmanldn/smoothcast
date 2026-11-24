"""Playback position estimation.

Tracks the current playback position from a start base plus elapsed time,
accounting for pause/resume.  When the device reports an authoritative
``current_time`` (via :meth:`device_update`), that takes precedence so the
seekbar stays synced with the player instead of drifting while paused.

No GUI toolkit dependencies: safe to import and test on any machine.
"""
from __future__ import annotations

import math
import time


class PositionTracker:
    def __init__(self) -> None:
        self.known = False
        self.duration = 0.0
        self.rate = 1.0
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

    def start(self, base: float, duration: float, playing: bool = True, rate: float = 1.0) -> None:
        self.known = True
        # A new source must never inherit the previous source's duration.
        self.duration = duration if math.isfinite(duration) and duration > 0 else 0.0
        self.rate = max(0.05, float(rate)) if math.isfinite(rate) and rate > 0 else 1.0
        self._base = max(0.0, base) if math.isfinite(base) else 0.0
        now = time.monotonic()
        self._epoch = now
        self._playing = playing
        self._paused_accum = 0.0
        # A restarted receiver may already be PAUSED. Without an initial
        # pause timestamp estimated source time drifts while paused.
        self._pause_started = None if playing else now
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
            if self._device_pos is not None:
                # While paused, the device reports a fixed position. Rebase
                # extrapolation on resume rather than counting paused seconds.
                self._device_epoch = now
        else:
            if self._device_pos is not None:
                # Freeze the extrapolated position before disabling playback.
                self._device_pos = self.value(now)
                self._device_epoch = now
            self._pause_started = now
        self._playing = playing

    def device_update(
        self, current: float, duration: float | None, rate: float | None = None,
    ) -> None:
        if not math.isfinite(current):
            return  # An invalid sample must not overwrite the last good clock.
        self.known = True
        if duration is not None and math.isfinite(duration) and duration > 0:
            self.duration = duration
        if rate is not None and math.isfinite(rate) and rate > 0:
            self.rate = max(0.05, float(rate))
        # Record the device's authoritative position; play state governs whether
        # it advances between polls so a paused stream does not creep forward.
        self._device_pos = max(0.0, current)
        self._device_epoch = time.monotonic()

    def rebase(self, value: float) -> None:
        self.start(value, self.duration, self._playing, self.rate)

    def value(self, now: float | None = None) -> float | None:
        if not self.known:
            return None
        now = time.monotonic() if now is None else now
        if self._device_pos is not None:
            value = self._device_pos
            if self._playing:
                value += (now - self._device_epoch) * self.rate
            if self.duration:
                value = min(value, self.duration)
            return max(0.0, value)
        # Estimated mode: base + elapsed, adjusted for paused time.
        paused = self._paused_accum
        if self._pause_started is not None:
            paused += now - self._pause_started
        value = self._base + (now - self._epoch - paused) * self.rate
        if self.duration:
            value = min(value, self.duration)
        return max(0.0, value)

    def paused_for(self, now: float | None = None) -> float:
        """Elapsed wall-clock pause time; zero when playing or unknown."""
        if not self.known or self._playing or self._pause_started is None:
            return 0.0
        now = time.monotonic() if now is None else now
        return max(0.0, now - self._pause_started)

    def clear(self) -> None:
        self.known = False
        self.duration = 0.0
        self.rate = 1.0
        self._playing = False
        self._paused_accum = 0.0
        self._pause_started = None
        self._device_pos = None
        self._device_epoch = 0.0

    @property
    def playing(self) -> bool:
        """True while the tracker extrapolates; False while paused or unknown."""
        return self._playing
