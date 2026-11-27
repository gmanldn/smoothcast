"""Pure timing and transition decisions for Chromecast playback."""
from __future__ import annotations

import math
import random

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
    repeat_all: bool = False, order: list[str] | None = None,
) -> str | None:
    """Choose the successor after playback.

    Precedence: repeat-one, then (unless auto-next is off) the next entry in the
    play order; ``repeat_all`` wraps the last entry back to the first. ``order``
    lets a shuffled play order drive auto-advance while ``queue`` keeps the
    displayed order.
    """
    if not current:
        return None
    if repeat_current:
        return current
    if not auto_next:
        return None
    sequence = list(order) if order else list(queue)
    try:
        index = sequence.index(current)
    except ValueError:
        return None
    if index + 1 < len(sequence):
        return sequence[index + 1]
    return sequence[0] if repeat_all and sequence else None


def shuffle_order(queue: list[str], seed: int) -> list[str]:
    """Return a deterministic permutation of *queue* for a given *seed*.

    Pure and reproducible: the same queue and seed always yield the same order,
    so a shuffled play order can be rebuilt and tested.
    """
    items = list(queue)
    random.Random(int(seed)).shuffle(items)
    return items


def frame_step_delta(fps: object) -> float:
    """Seconds for one source frame, or 1.0 s when the frame rate is unknown.

    Uses the average frame duration (1/fps), which is the documented
    approximation for variable-frame-rate sources. Never returns zero, so a
    frame step always moves.
    """
    try:
        value = float(fps)
    except (TypeError, ValueError):
        return 1.0
    return 1.0 / value if value > 0 else 1.0


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


def url_cast_matches(info: dict | None, saved_url: str) -> bool:
    """Return True only while the receiver still plays the URL we sent.

    A URL cast has no local ``Session`` to prove ownership. Store the exact URL
    we handed to the receiver and require both an active player state and an
    identical content id before the sleep timer stops it; otherwise another app
    that replaced our stream must be left playing.
    """
    if not isinstance(info, dict) or not saved_url:
        return False
    if str(info.get("player_state") or "").upper() not in PLAYING_STATES:
        return False
    return str(info.get("content_id") or "").strip() == str(saved_url).strip()


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


MAX_EXTERNAL_RUNTIME = 7 * 24 * 3600.0


def external_runtime(info: dict | None) -> tuple[float, float] | None:
    """Return ``(position, total runtime)`` seconds for media we did not start.

    The receiver is the only source for an external stream's length. A live or
    unknown-length stream reports no usable duration, so it yields ``None``
    (the guest sees an unknown runtime, never a made-up one).
    """
    if not isinstance(info, dict):
        return None
    try:
        total = float(info.get("duration") or 0.0)
        position = float(info.get("current_time") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(total) and 0 < total <= MAX_EXTERNAL_RUNTIME):
        return None
    if not math.isfinite(position) or position < 0:
        position = 0.0
    return min(position, total), total


def external_display_clock(info: dict | None, state: str):
    """Receiver-only display clock; never grants ownership or seek capability.

    Position and duration are independent: live streams may report a position
    but no length; some receivers report a length before the first position.
    """
    from position_tracker import PositionTracker

    def seconds(key):
        if not isinstance(info, dict) or isinstance(info.get(key), bool):
            return None
        try:
            value = float(info.get(key))
        except (TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) and 0 <= value <= MAX_EXTERNAL_RUNTIME else None

    tracker = PositionTracker()
    total = seconds("duration") or 0.0
    position = seconds("current_time")
    if position is not None:
        tracker.start(min(position, total) if total else position, total,
                      playing=state == "PLAYING")
    else:
        tracker.duration = total
    return tracker


def _external_title(fields: dict) -> str:
    meta = fields.get("media_metadata")
    meta = meta if isinstance(meta, dict) else {}
    for value in (fields.get("title"), meta.get("title"), meta.get("subtitle"),
                  meta.get("artist")):
        if isinstance(value, str) and value.strip():
            return value.strip()[:256]
    return ""


_FORMAT_NAMES = {
    "application/x-mpegurl": "HLS stream", "application/vnd.apple.mpegurl": "HLS stream",
    "application/dash+xml": "DASH stream", "video/mp4": "MP4 video", "video/webm": "WebM video",
    "video/x-matroska": "MKV video", "audio/mpeg": "MP3 audio", "audio/mp4": "AAC audio",
    "audio/flac": "FLAC audio", "audio/ogg": "Ogg audio", "audio/wav": "WAV audio",
}


def external_details(info: dict | None) -> str:
    """One-line "what is this" for media we did not start: format, kind, length, source.

    Metadata only; the content URL is reduced to a public host name (never a
    LAN address, path or query) and is never fetched.
    """
    if not isinstance(info, dict):
        return ""
    parts: list[str] = []
    ctype = info.get("content_type")
    if isinstance(ctype, str) and ctype.strip():
        key = ctype.split(";")[0].strip().lower()
        parts.append(_FORMAT_NAMES.get(key) or key.replace("x-", "").replace("/", " ").upper()[:40])
    meta = info.get("media_metadata")
    meta = meta if isinstance(meta, dict) else {}
    width, height = meta.get("width"), meta.get("height")
    if type(width) is int and type(height) is int and width > 0 and height > 0:
        parts.append(f"{width}×{height}")
    runtime = external_runtime(info)
    stream = str(info.get("stream_type") or "").upper()
    if stream == "LIVE" and runtime is None:
        parts.append("Live")
    elif runtime is not None:
        total = int(runtime[1])
        h, rest = divmod(total, 3600)
        parts.append(f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}")
    else:
        parts.append("Length unknown")
    app = info.get("display_name")
    if isinstance(app, str) and app.strip():
        parts.append(app.strip()[:40])
    source = info.get("content_id")
    if isinstance(source, str) and "://" in source:
        from urllib.parse import urlsplit
        host = (urlsplit(source).hostname or "").lower()
        if host and not host.replace(".", "").isdigit() and ":" not in host:
            parts.append(host[:60])
    return " · ".join(parts)


def external_media_labels(info: dict | None) -> tuple[str, str]:
    """Use reported metadata only; never fetch a foreign content URL."""
    fields = info if isinstance(info, dict) else {}
    title = _external_title(fields)
    size = fields.get("size_bytes")
    if isinstance(size, str) and size.isascii() and size.isdecimal() and len(size) <= 19:
        size = int(size)
    if type(size) is not int or not 0 < size < 2**63:
        return title or "External stream", "Size unavailable"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB", "EB"):
        if size < 1000 or unit == "EB":
            return title or "External stream", f"{size:.2f} {unit}" if unit != "B" else f"{size} B"
        size /= 1000
    return title or "External stream", "Size unavailable"
