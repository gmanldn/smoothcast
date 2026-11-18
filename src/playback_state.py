"""Pure timing and transition decisions for Chromecast playback."""
from __future__ import annotations

import math

PLAYING_STATES = frozenset({"PLAYING", "BUFFERING", "PAUSED"})


def absolute_encoded_position(offset: float, elapsed: float | None, duration: float = 0.0) -> float | None:
    """Convert FFmpeg -progress (relative to -ss) to media-absolute seconds."""
    if elapsed is None or not math.isfinite(elapsed):
        return None
    offset = offset if math.isfinite(offset) else 0.0
    duration = duration if math.isfinite(duration) else 0.0
    position = max(0.0, offset) + max(0.0, elapsed)
    return min(position, duration) if duration > 0 else position


def playback_ended(previous: str, current: str, *, has_session: bool, busy: bool) -> bool:
    """The device, not the encoder/catt CLI, decides playback completion."""
    return has_session and not busy and previous in PLAYING_STATES and current == "IDLE"


def next_media(
    current: str | None, queue: list[str], *,
    repeat_current: bool, auto_next: bool,
) -> str | None:
    """Choose successor after playback: repeat-one overrides auto-next."""
    if not current:
        return None
    if repeat_current:
        return current
    if not auto_next:
        return None
    try:
        index = queue.index(current)
    except ValueError:
        return None
    return queue[index + 1] if index + 1 < len(queue) else None


def sleep_deadline(now: float, minutes: int) -> float:
    """Wall-clock expiry persisted across application restarts."""
    return now + minutes * 60 if minutes > 0 else 0.0


def timer_expired(deadline: object, now: float) -> bool:
    """Treat invalid config values and disabled timers as unarmed."""
    try:
        value = float(deadline)
    except (ValueError, TypeError):
        return False
    return math.isfinite(value) and value > 0 and now >= value
