"""GTK-free scheduling policy for a low-wakeup desktop window."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TimerPlan:
    seek_ms: int | None
    meter_ms: int | None
    poll_ms: int
    mpris_ms: int
    sleep_ms: int | None
    fade_ms: int | None
    room_ms: int
    watchdog_ms: int | None


def active_deadline(value: object) -> bool:
    """Reject disabled, invalid and non-finite sleep deadlines."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    try:
        deadline = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(deadline) and deadline > 0


def timer_plan(
    *, mapped: bool, playing: bool, monitoring: bool, foreground: bool,
    has_sleep: bool, fade_enabled: bool, fade_active: bool,
    transcoding: bool = False,
) -> TimerPlan:
    """Return intervals in ms; None removes the timer source entirely."""
    foreground_or_playing = playing or (mapped and foreground)
    return TimerPlan(
        seek_ms=500 if mapped and playing else None,
        meter_ms=100 if mapped and playing and monitoring else None,
        poll_ms=4000 if foreground_or_playing else 30000,
        mpris_ms=1000 if foreground_or_playing else 30000,
        sleep_ms=5000 if has_sleep else None,
        fade_ms=3000 if (has_sleep and fade_enabled) or fade_active else None,
        room_ms=1000 if mapped else 15000,
        watchdog_ms=1000 if not mapped and playing and transcoding else None,
    )
