"""Fade receiver volume out before the sleep timer stops playback (issue #270).

GTK-free: all I/O is injected so the state machine is tested with fakes and no
receiver. ``SleepFader.tick`` is called every few seconds from the GUI thread
and never blocks; receiver commands go through ``run(work, done)``.

Per sleep-timer deadline: when the remaining time enters the fade window the
current receiver volume is read once, then lowered linearly towards zero. The
original volume is restored afterwards: at once if the timer is cancelled or
re-armed, or once the cast has stopped after expiry (never while the stream is
still playing, which would blast the room). A receiver whose volume cannot be
read is left alone, and a change of selected device abandons the fade without
touching the new device.
"""
from __future__ import annotations

from typing import Callable

import castctl

SETTING = "sleep_fade_seconds"
DEFAULT_SECONDS = 30
MAX_SECONDS = 600
RESTORE_ATTEMPTS = 3
RESTORE_MAX_WAIT = 90.0  # seconds after expiry before restoring regardless


def valid_seconds(value: object) -> int | None:
    """A bounded fade length in whole seconds (0 disables), else None."""
    if type(value) is int and 0 <= value <= MAX_SECONDS:
        return value
    return None


def fade_level(start: int, remaining: float, fade_seconds: float) -> int:
    """Linear volume for *remaining* seconds of a *fade_seconds* fade."""
    if fade_seconds <= 0 or remaining >= fade_seconds:
        return start
    return max(0, min(start, round(start * max(remaining, 0.0) / fade_seconds)))


class SleepFader:
    def __init__(self, read_volume: Callable[[str], int | None],
                 set_volume: Callable[[str, int], bool],
                 run: Callable[[Callable[[], object], Callable[[object], None]], object]) -> None:
        self._read, self._set, self._run = read_volume, set_volume, run
        self._reset()
        self._given_up: float | None = None  # deadline whose volume was unreadable

    def _reset(self) -> None:
        self.phase: str | None = None  # None | "starting" | "fading" | "await_stop"
        self.device = ""
        self.start = 0
        self.deadline = 0.0
        self._level: int | None = None
        self._inflight = False
        self._attempts = 0

    # -- helpers ---------------------------------------------------------
    def _submit(self, work, done) -> None:
        self._inflight = True

        def finished(result):
            self._inflight = False
            done(result)
        self._run(work, finished)

    def _restore(self) -> None:
        if self._inflight:
            return
        device, start = self.device, self.start
        self._attempts += 1

        def done(ok):
            if ok is True or self._attempts >= RESTORE_ATTEMPTS:
                self._reset()
        self._submit(lambda: self._set(device, start), done)

    # -- public ----------------------------------------------------------
    def tick(self, *, now: float, deadline: object, fade_seconds: object,
             device: str, active: bool) -> None:
        try:
            deadline = float(deadline)
        except (TypeError, ValueError):
            deadline = 0.0
        fade = fade_seconds if valid_seconds(fade_seconds) is not None else 0
        remaining = deadline - now
        in_window = (deadline > 0 and fade > 0 and active and device
                     and 0 < remaining <= fade)

        if self.phase is None:
            if in_window and not self._inflight and self._given_up != deadline:
                self._begin(device, deadline)
            return
        if self.phase == "starting":
            return  # waiting for the volume read
        if device != self.device:
            self._reset()  # never touch a different receiver
            return
        if self.phase == "fading":
            if in_window and deadline == self.deadline:
                level = fade_level(self.start, remaining, fade)
                if (self._level is None or level < self._level) and not self._inflight:
                    self._level = level
                    self._submit(lambda: self._set(self.device, level), lambda _ok: None)
                return
            expired = deadline <= 0 and now >= self.deadline - 1.0
            if expired and active:
                self.phase = "await_stop"
                return
            self._restore()  # cancelled, re-armed or the cast ended early
            return
        if self.phase == "await_stop":
            if not active or now - self.deadline > RESTORE_MAX_WAIT:
                self._restore()

    def _begin(self, device: str, deadline: float) -> None:
        self.phase, self.device, self.deadline = "starting", device, deadline

        def done(volume):
            if type(volume) is int and volume > 0:
                self.start, self.phase = volume, "fading"
            else:
                self._given_up = deadline  # unreadable or already silent
                self._reset()
        self._submit(lambda: self._read(device), done)


def make_fader(run_async: Callable[..., object]) -> SleepFader:
    """Wire a fader to Cast receivers through the GUI's background workers."""
    def run(work, done):
        run_async(work, done=done, failed=lambda _message: done(None), domain="transport")
    return SleepFader(
        lambda device: castctl.volume_percent(castctl.info(device)),
        lambda device, percent: bool(castctl.volume(device, percent)[0]),
        run,
    )
