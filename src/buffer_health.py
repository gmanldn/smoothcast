"""Bounded time-series buffer-health history for the diagnostics graph (#133).

The GUI already measures buffer-ahead seconds and the HLS segment count once
per tick. This module keeps a small, fixed-size history of those measurements
so the diagnostics view can show a real time series instead of a single
instantaneous value. It is pure: no GTK, no disk, no network and no polling.
"""
from __future__ import annotations

from collections import deque
import math

MAX_SAMPLES = 120  # Two minutes at the GUI's half-second tick.
MAX_AHEAD_SECONDS = 3600.0


def _ahead(value) -> float | None:
    """A finite, bounded buffer-ahead value, or ``None`` when unavailable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(-MAX_AHEAD_SECONDS, min(MAX_AHEAD_SECONDS, number))


def _segments(value) -> int:
    """A non-negative segment count; malformed values become zero."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


class BufferHealth:
    """A bounded history of measured HLS buffer health.

    Each sample is ``(ahead_seconds, segments, stalled)``. ``ahead_seconds`` is
    signed: positive means the encoder is ahead of the receiver, negative means
    the receiver is ahead. ``None`` means that tick had no usable measurement.
    ``stalled`` marks a tick where the watchdog restarted the owned stream.
    """

    def __init__(self, limit: int = MAX_SAMPLES) -> None:
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        self._samples: deque[tuple[float | None, int, bool]] = deque(
            maxlen=min(limit, MAX_SAMPLES)
        )
        self._stalls = 0

    def sample(self, ahead, segments, *, stalled: bool = False) -> None:
        """Append one tick's measurement; invalid values are sanitised."""
        is_stalled = bool(stalled)
        if is_stalled:
            self._stalls += 1
        self._samples.append((_ahead(ahead), _segments(segments), is_stalled))

    def clear(self) -> None:
        """Forget the previous session so a new cast starts clean."""
        self._samples.clear()
        self._stalls = 0

    @property
    def samples(self) -> tuple[tuple[float | None, int, bool], ...]:
        """The bounded history, oldest first."""
        return tuple(self._samples)

    @property
    def stall_count(self) -> int:
        """Number of watchdog restarts recorded in this history."""
        return self._stalls

    @property
    def active(self) -> bool:
        """Whether any samples have been recorded."""
        return bool(self._samples)

    def latest(self) -> tuple[float | None, int, bool] | None:
        """The most recent sample, or ``None`` before the first tick."""
        return self._samples[-1] if self._samples else None

    def ahead_series(self) -> tuple[float | None, ...]:
        """Buffer-ahead values only, oldest first."""
        return tuple(ahead for ahead, _segments, _stalled in self._samples)

    def segment_series(self) -> tuple[int, ...]:
        """HLS segment counts only, oldest first."""
        return tuple(segments for _ahead, segments, _stalled in self._samples)

    def stall_positions(self) -> tuple[int, ...]:
        """Indices of ticks marked as a watchdog restart."""
        return tuple(
            index for index, (_ahead, _segments, stalled) in enumerate(self._samples)
            if stalled
        )

    def summary(self) -> str:
        """Plain-language summary for the diagnostics caption."""
        if not self._samples:
            return "No measured HLS buffer history yet."
        ahead, segments, _stalled = self._samples[-1]
        if ahead is None:
            position = "buffer unavailable"
        elif ahead >= 0:
            position = f"{ahead:.1f} s ahead"
        else:
            position = f"{abs(ahead):.1f} s behind"
        return (
            f"Latest {position}; {segments} HLS segment"
            f"{'s' if segments != 1 else ''} available; "
            f"{self._stalls} watchdog restart{'s' if self._stalls != 1 else ''}."
        )
