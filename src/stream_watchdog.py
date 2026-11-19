"""Bounded, receiver-safe HLS playback stall classification.

Pure state machine: call from the GUI's existing half-second tick with already
cached local progress/receiver status; never probe networks or spawn processes.
An interrupted session, paused film or unverified receiver cannot restart.
"""
from __future__ import annotations

import math
import time

import playback_state
import progress_model


class StreamWatchdog:
    """Differentiate encoder and receiver stalls with at most one recovery.

    `observe` returns "encoder_stalled", "receiver_stalled" or
    "recovery_exhausted" for a confirmed owned, playing HLS stream. Any
    returned stall name grants exactly one restart; later stalls are reported
    without restarting. Ended, paused, busy and foreign streams are ignored.
    """

    def __init__(
        self, *, encoder_timeout: float = 24.0,
        receiver_timeout: float = 36.0, max_restarts: int = 1,
    ) -> None:
        self.encoder_timeout = encoder_timeout
        self.receiver_timeout = receiver_timeout
        self.max_restarts = max_restarts
        self.reset()

    def reset(self) -> None:
        self._session = None
        self._epoch = None
        self._encoder_value: float | None = None
        self._encoder_advanced_at: float | None = None
        self._receiver_value: float | None = None
        self._receiver_advanced_at: float | None = None
        self.restarts = 0
        self._exhausted_reported = False

    @staticmethod
    def _seconds(value: object) -> float | None:
        if type(value) not in (int, float):
            return None
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None

    def observe(
        self, *, session: object | None, epoch: object, now: float,
        receiver_state: str, owned: bool, busy: bool,
        encoder_seconds: object, receiver_seconds: object,
        encoder_done: bool = False, seconds_remaining: float | None = None,
    ) -> str | None:
        if session is None:
            self.reset()
            return None
        if session is not self._session:
            self.reset()
            self._session = session
        if epoch != self._epoch:
            self._epoch = epoch
            # FFmpeg restarts at zero, but total recovery allowance belongs
            # to the original session and survives a seek/restart generation.
            self._encoder_value = self._receiver_value = None
            self._encoder_advanced_at = self._receiver_advanced_at = now

        encoded = self._seconds(encoder_seconds)
        received = self._seconds(receiver_seconds)
        if encoded is not None and (
            self._encoder_value is None or encoded > self._encoder_value + 0.25
        ):
            self._encoder_advanced_at = now
            self._encoder_value = encoded
        if received is not None and (
            self._receiver_value is None or received > self._receiver_value + 0.25
        ):
            self._receiver_advanced_at = now
            self._receiver_value = received

        # The TV's actual media URL is the ownership authority. Never
        # restart playback merely because something is visible on the port.
        if (not owned or busy or receiver_state not in {"PLAYING", "BUFFERING"}
                or encoder_done or
                (seconds_remaining is not None and seconds_remaining <= 8)):
            # Resume from pause/network loss without counting those seconds
            # as lost frames. Keep the session-level retry budget.
            self._encoder_advanced_at = self._receiver_advanced_at = now
            return None

        encoder_stalled = (
            self._encoder_value is not None and
            self._encoder_advanced_at is not None and
            now - self._encoder_advanced_at >= self.encoder_timeout
        )
        receiver_stalled = (
            self._receiver_value is not None and
            self._receiver_advanced_at is not None and
            self._encoder_value is not None and
            self._encoder_advanced_at is not None and
            now - self._encoder_advanced_at < self.encoder_timeout / 2 and
            now - self._receiver_advanced_at >= self.receiver_timeout and
            not encoder_stalled
        )
        if not (encoder_stalled or receiver_stalled):
            return None
        if self.restarts >= self.max_restarts:
            if self._exhausted_reported:
                return None
            self._exhausted_reported = True
            return "recovery_exhausted"
        self.restarts += 1
        self._encoder_advanced_at = self._receiver_advanced_at = now
        return "encoder_stalled" if encoder_stalled else "receiver_stalled"


def recover_window(window, snapshot: progress_model.Progress, position: float | None) -> None:
    """Apply pure health verdicts to the current GTK window without blocking."""
    session = window.session
    state = session.state if session is not None else None
    if (session is None or session.mode != "transcode" or state is None):
        window._stream_watchdog.reset()
        return
    info = window.device_info
    owned = playback_state.hls_session_matches(
        info, state.stream_url, state.title,
    )
    remaining = (
        max(0.0, state.duration - position)
        if state.duration and position is not None else None
    )
    outcome = window._stream_watchdog.observe(
        session=session, epoch=state.started_at, now=time.monotonic(),
        receiver_state=window.device_state,
        owned=owned, busy=window.busy or window._closing or window._cast_starting,
        encoder_seconds=snapshot.out_time,
        receiver_seconds=info.get("current_time") if info else None,
        encoder_done=snapshot.done,
        seconds_remaining=remaining,
    )
    if outcome in {"encoder_stalled", "receiver_stalled"}:
        # Restart is local/async and only permitted while the receiver
        # reports our *exact* HLS URL. Never hijack unrelated TV content.
        window.busy = True
        window._refresh_controls()
        reason = ("FFmpeg stopped advancing" if outcome == "encoder_stalled"
                  else "the receiver stopped consuming HLS media")
        window.toast("Playback stalled; attempting one safe restart", error=True)
        window._console(f"Watchdog: {reason}; restarting owned HLS stream once")
        target = max(0.0, position if position is not None else state.offset)
        window._restart_at(session, target)
    elif outcome == "recovery_exhausted":
        window.toast("Playback remains stalled — automatic retries exhausted", error=True)
        window._console("Watchdog: one restart already attempted; manual diagnosis required")


