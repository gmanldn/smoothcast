"""Pure timing and transition decisions for Chromecast playback."""
from __future__ import annotations

import math

PLAYING_STATES = frozenset({"PLAYING", "BUFFERING", "PAUSED"})


def absolute_encoded_position(
    offset: float, elapsed: float | None, duration: float = 0.0,
    speed: float = 1.0,
) -> float | None:
    """Map HLS presentation seconds back to the source-file timeline.

    The stream starts at source offset `-ss` but its clock restarts at zero.
    For playback at 2×, ten seconds of HLS represents twenty seconds of source.
    """
    if elapsed is None or not math.isfinite(elapsed):
        return None
    if not math.isfinite(speed) or speed <= 0:
        return None
    offset = offset if math.isfinite(offset) else 0.0
    duration = duration if math.isfinite(duration) else 0.0
    position = max(0.0, offset) + max(0.0, elapsed) * speed
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


def direct_session_matches(info: dict | None, saved_title: str) -> bool:
    """Only restore a saved direct cast when the TV still reports playback.

    catt can exit successfully after initiating a cast, so checking its PID
    cannot establish whether playback is ongoing after an app restart.
    """
    if not isinstance(info, dict):
        return False
    state = str(info.get("player_state") or "").upper()
    if state not in PLAYING_STATES:
        return False
    # Some Chromecast receivers omit titles. Reject a known mismatch rather
    # than attaching our media controls to another app's unrelated stream.
    current_title = str(info.get("title") or "").strip()
    saved_title = str(saved_title or "").strip()
    if current_title and saved_title and current_title.casefold() != saved_title.casefold():
        return False
    return True


def hls_session_matches(info: dict | None, saved_url: str, saved_title: str) -> bool:
    """Do not adopt an unrelated cast after the HLS encoder has exited.

    A friendly title or open HLS port is insufficient; only the exact
    content URL reported by the receiver establishes our ownership.
    """
    if not isinstance(info, dict) or not saved_url:
        return False
    if str(info.get("player_state") or "").upper() not in PLAYING_STATES:
        return False
    if str(info.get("content_id") or "").strip() != saved_url:
        return False
    current_title = str(info.get("title") or "").strip()
    if current_title and saved_title and current_title.casefold() != saved_title.strip().casefold():
        return False
    return True


def start_offset(requested: float | None, saved: object = None) -> float:
    """Resolve source timeline start without confusing explicit 0 with resume.

    None requests a remembered resume position; any explicit number, including
    0.0, overrides it. Treat malformed saved configuration as zero.
    """
    candidate = saved if requested is None else requested
    try:
        value = float(candidate)
    except (ValueError, TypeError, OverflowError):
        return 0.0
    return max(0.0, value) if math.isfinite(value) else 0.0
