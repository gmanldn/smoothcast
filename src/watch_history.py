"""Pure, bounded watch-history records (SC-114 #123).

Records are newest-first and capped so a long-running library cannot grow the
config without bound. Each entry stores whether it came from the local preview
or a full cast, so the two are distinguishable, plus the start/stop/completed/
resumed event and the source position at that moment.
"""
from __future__ import annotations

EVENTS = frozenset({"start", "stop", "completed", "resumed"})
SOURCES = frozenset({"preview", "cast"})
LIMIT = 200


def record(history, path, event, position, now, *, source="cast", limit=LIMIT):
    """Return a new bounded history list with one entry prepended.

    Unknown events or a missing path leave the history unchanged.
    """
    current = list(history or [])
    if event not in EVENTS or not path:
        return current
    entry = {
        "path": str(path),
        "event": event,
        "position": float(max(0.0, position or 0.0)),
        "at": float(now),
        "source": source if source in SOURCES else "cast",
    }
    return ([entry] + current)[:limit]


def clear():
    """Return an empty history."""
    return []
