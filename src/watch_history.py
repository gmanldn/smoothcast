"""Bounded, restart-safe watch-state records (SC-033 #42).

Records are newest-first and capped so a long history cannot grow without
bound. Each entry stores the source, event, position and timestamp plus the
media duration, a cheap file fingerprint, the chosen audio/subtitle tracks and
the watched percentage. Persistence is the caller's atomic config save, so a
crash cannot leave a partially written record.

The fingerprint is a stat identity (size and nanosecond mtime), not a content
hash: it is cheap enough to compute on every start/stop and detects replaced or
truncated files. Content hashing belongs to ``bookmarks.fingerprint`` for the
cases that need move-stable identity.
"""
from __future__ import annotations

import math
import os

import fingerprint as content_identity

EVENTS = frozenset({"start", "stop", "completed", "resumed"})
SOURCES = frozenset({"preview", "cast"})
LIMIT = 200
MAX_PATH = 4096
MAX_FINGERPRINT = 128
MAX_TRACK_TEXT = 64
TRACK_KEYS = ("audio", "subtitle")


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError):
        return None
    return number if math.isfinite(number) else None


def _duration(value: object) -> float | None:
    number = _finite(value)
    if number is None or number <= 0 or number > 1e12:
        return None
    return number


def _fingerprint(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not 0 < len(value) <= MAX_FINGERPRINT:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _track(value: object) -> str | int | None:
    if type(value) is int:
        return value if 0 <= value <= 1024 else None
    if isinstance(value, str):
        text = value.strip()
        if 0 < len(text) <= MAX_TRACK_TEXT and not any(
                ord(char) < 32 or ord(char) == 127 for char in text):
            return text
    return None


def _tracks(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for key in TRACK_KEYS:
        selection = _track(value.get(key))
        if selection is not None:
            cleaned[key] = selection
    return cleaned


def _watched(position: float, duration: float | None) -> float | None:
    if duration is None:
        return None
    return min(1.0, max(0.0, position / duration))


def fingerprint(path: str | os.PathLike[str]) -> str | None:
    """Return a cheap stat identity for a media file, or ``None``.

    The value changes when the file is replaced or its size/mtime changes. It
    follows normal symlinks (media libraries commonly use them) and never
    opens or reads the file.
    """
    try:
        info = os.stat(path)
    except OSError:
        return None
    return f"{info.st_size}:{info.st_mtime_ns}"


def clean_entry(entry: object) -> dict | None:
    """Validate one untrusted history entry, returning a bounded copy."""
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")
    event = entry.get("event")
    source = entry.get("source")
    position = _finite(entry.get("position"))
    at = _finite(entry.get("at"))
    if (not isinstance(path, str) or not 0 < len(path) <= MAX_PATH
            or event not in EVENTS or source not in SOURCES
            or position is None or at is None
            or position < 0 or position > 1e12 or at < 0 or at > 1e12):
        return None
    duration = _duration(entry.get("duration"))
    return {
        "path": path,
        "event": event,
        "position": position,
        "at": at,
        "source": source,
        "duration": duration,
        "fingerprint": _fingerprint(entry.get("fingerprint")),
        "tracks": _tracks(entry.get("tracks")),
        "watched": _watched(position, duration),
        "content_key": content_identity.valid_key(entry.get("content_key")),
    }


def clean(history: object, limit: int = LIMIT) -> list:
    """Return a bounded newest-first list of valid history entries."""
    if not isinstance(history, list):
        return []
    cleaned = []
    for entry in history[:limit * 4]:
        record = clean_entry(entry)
        if record is not None:
            cleaned.append(record)
            if len(cleaned) >= limit:
                break
    return cleaned


def record(history, path, event, position, now, *, source="cast",
           duration=None, fingerprint=None, tracks=None, limit=LIMIT, content_key=None):
    """Return a new bounded history list with one entry prepended.

    Unknown events or a missing path leave the history unchanged. Optional
    duration/tracks/fingerprint are validated; an invalid value is stored as
    ``None``/empty rather than rejecting the event.
    """
    current = list(history or [])
    if event not in EVENTS or not path:
        return current
    position_value = _finite(position)
    at = _finite(now)
    if position_value is None or at is None:
        return current
    position_value = max(0.0, position_value)
    duration_value = _duration(duration)
    entry = {
        "path": str(path),
        "event": event,
        "position": position_value,
        "at": at,
        "source": source if source in SOURCES else "cast",
        "duration": duration_value,
        "fingerprint": _fingerprint(fingerprint),
        "tracks": _tracks(tracks),
        "watched": _watched(position_value, duration_value),
        "content_key": content_identity.valid_key(content_key),
    }
    return ([entry] + current)[:limit]


def latest(history, path, fingerprint=None, content_key=None) -> dict | None:
    """Return the newest valid entry for ``path`` - or, if the file was renamed or
    moved, for the same ``content_key`` - optionally fingerprint-matched."""
    target = str(path)
    key = content_identity.valid_key(content_key)
    for entry in clean(history):
        same_path = entry["path"] == target
        same_content = key is not None and entry.get("content_key") == key
        if not (same_path or same_content):
            continue
        if same_path and not same_content and fingerprint is not None \
                and entry["fingerprint"] != fingerprint:
            continue
        return entry
    return None


def latest_position(history, path, fingerprint=None, content_key=None) -> float | None:
    """Return the newest saved position for ``path`` (or its content), or ``None``."""
    entry = latest(history, path, fingerprint, content_key)
    return None if entry is None else entry["position"]


def saved_position(cfg, path, content_key=None):
    """Return a resumable position from the positions map or watch state."""
    saved = _finite((cfg.get("positions") or {}).get(str(path)))
    if saved is not None:
        return saved
    return latest_position(
        cfg.get("watch_history"), str(path), fingerprint(path), content_key)


def clear():
    """Return an empty history."""
    return []
