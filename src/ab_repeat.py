"""Source-time A/B loop marks with one outstanding boundary seek."""
from __future__ import annotations

import math


class ABRepeat:
    def __init__(self) -> None:
        self.start: float | None = None
        self.end: float | None = None
        self._seek_pending = False

    def mark_start(self, position: float, duration: float) -> bool:
        if not self._valid(position, duration) or position >= duration:
            return False
        self.start = position
        self.end = None
        self._seek_pending = False
        return True

    def mark_end(self, position: float, duration: float) -> bool:
        if (self.start is None or not self._valid(position, duration)
                or not self.start < position <= duration):
            return False
        self.end = position
        self._seek_pending = False
        return True

    def boundary_target(self, position: float, *, playing: bool) -> float | None:
        if self.start is None or self.end is None or not playing:
            return None
        if self._seek_pending:
            if playing and position <= self.start + 0.75:
                self._seek_pending = False
            return None
        if position >= self.end:
            self._seek_pending = True
            return self.start
        return None

    def manual_seek(self, position: float) -> None:
        if self.start is not None and abs(position - self.start) > 0.75:
            self._seek_pending = False

    def clear(self) -> None:
        self.start = self.end = None
        self._seek_pending = False

    @staticmethod
    def _valid(position: float, duration: float) -> bool:
        return (isinstance(position, (int, float)) and math.isfinite(position)
                and position >= 0 and isinstance(duration, (int, float))
                and math.isfinite(duration) and duration > 0)
