"""Bounded, cancellable pre-probe/prewarm planning for queue transitions (#48). Pure.

``Prewarm`` tracks one warm-up for the *next* queue item. A token ties results to
the item they were started for, so a result that arrives after the queue changed,
the user skipped, or playback stopped is discarded rather than applied.
"""
from __future__ import annotations

from dataclasses import dataclass

LEAD_S = 45.0          # begin warming this long before the current item ends
MIN_REMAINING_S = 5.0  # too close to the end: skip, the normal start path is as fast
MAX_AGE_S = 120.0      # a warm result older than this is not trusted


@dataclass(frozen=True)
class Warm:
    token: int
    item: str
    started: float
    probe: object = None


class Prewarm:
    def __init__(self) -> None:
        self._token = 0
        self._active: Warm | None = None
        self._ready: Warm | None = None

    def should_start(self, duration, position, next_item) -> bool:
        """Warm only when there is a next item, enough time and nothing in flight for it."""
        if not next_item or not _real(duration) or not _real(position):
            return False
        remaining = duration - position
        if remaining < MIN_REMAINING_S or remaining > LEAD_S:
            return False
        held = self._active or self._ready
        return held is None or held.item != next_item

    def begin(self, item: str, now: float) -> int:
        """Start (and supersede any earlier) warm-up; returns the token to report back with."""
        self._token += 1
        self._active = Warm(self._token, item, now)
        self._ready = None
        return self._token

    def finish(self, token: int, probe) -> bool:
        """Accept a result only if its token is still current."""
        if self._active is None or self._active.token != token:
            return False
        a = self._active
        self._ready, self._active = Warm(a.token, a.item, a.started, probe), None
        return True

    def take(self, item: str, now: float):
        """Consume a fresh warm result for exactly ``item``; otherwise None."""
        r = self._ready
        self._ready = None
        if r and r.item == item and now - r.started <= MAX_AGE_S:
            return r.probe
        return None

    def cancel(self) -> None:
        """Invalidate everything in flight (skip, queue edit, stop)."""
        self._token += 1
        self._active = self._ready = None


def _real(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")
