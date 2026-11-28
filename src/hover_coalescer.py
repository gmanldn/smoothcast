"""GTK-free coalescing of seekbar pointer times: at most one delivery per frame.

Every pointer-motion event used to run the window's whole hover work (labels,
caption lookup with file stats, thumbnail strip, preview scheduling) on the GTK
thread. The knob is drawn from the latest value, so it still tracks the pointer
instantly; only the heavy follow-up is limited to the newest value per frame.
"""
from __future__ import annotations

from collections.abc import Callable

FRAME_MS = 16


class HoverCoalescer:
    def __init__(
        self,
        deliver: Callable[[float], None],
        *,
        schedule: Callable[[int, Callable[[], bool]], int],
        cancel: Callable[[int], object],
        delay_ms: int = FRAME_MS,
    ) -> None:
        self._deliver = deliver
        self._schedule = schedule
        self._cancel = cancel
        self._delay_ms = delay_ms
        self._pending: float | None = None
        self._source = 0

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def push(self, value: float) -> None:
        """Remember the newest value; deliver it on the next frame."""
        self._pending = value
        if not self._source:
            self._source = self._schedule(self._delay_ms, self._flush)

    def flush(self) -> None:
        """Deliver the newest value now (if any) and drop the scheduled frame."""
        self.drop()

    def drop(self) -> None:
        """Forget the pending value without delivering it."""
        if self._source:
            self._cancel(self._source)
            self._source = 0
        self._pending = None

    def _flush(self) -> bool:
        self._source = 0
        value, self._pending = self._pending, None
        if value is not None:
            self._deliver(value)
        return False  # one-shot timer
