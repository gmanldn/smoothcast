"""Adaptive bitrate decision (SC-022, #31): pure, no I/O, no encoder starts.

Chooses a rung of a bitrate ladder from measured throughput and buffer level.
Anti-oscillation: stepping down is quick (one low-buffer sample or sustained
low throughput), stepping up needs sustained headroom, a healthy buffer and a
cool-down since the last change; it moves at most one rung at a time. Each
change implies a re-encode, so ``Decision.change`` is False whenever holding is
acceptable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HEADROOM = 1.4          # throughput must exceed rung bitrate by this factor to step up
SAFETY = 1.1            # throughput must stay above rung bitrate by this factor to hold
LOW_BUFFER_S = 4.0
HIGH_BUFFER_S = 12.0
UP_SAMPLES = 4          # consecutive good samples before stepping up
COOLDOWN_S = 30.0


@dataclass(frozen=True)
class Decision:
    rung: int
    change: bool
    reason: str


@dataclass
class Controller:
    ladder_kbps: list[int]            # ascending bitrates
    rung: int = 0
    _good: int = field(default=0, repr=False)
    _last_change: float = field(default=-1e9, repr=False)

    def __post_init__(self) -> None:
        if not self.ladder_kbps or sorted(self.ladder_kbps) != list(self.ladder_kbps):
            raise ValueError("ladder must be a non-empty ascending list")
        self.rung = max(0, min(self.rung, len(self.ladder_kbps) - 1))

    def observe(self, throughput_kbps: float, buffer_s: float, now: float) -> Decision:
        cur = self.ladder_kbps[self.rung]
        if self.rung > 0 and (buffer_s < LOW_BUFFER_S or throughput_kbps < cur / SAFETY):
            # Step down only as far as the measurement supports (at least one rung).
            target = self.rung - 1
            while target > 0 and self.ladder_kbps[target] * SAFETY > throughput_kbps:
                target -= 1
            return self._move(target, now, "network or buffer too low")
        up_ok = (self.rung + 1 < len(self.ladder_kbps) and buffer_s >= HIGH_BUFFER_S
                 and throughput_kbps >= self.ladder_kbps[self.rung + 1] * HEADROOM)
        self._good = self._good + 1 if up_ok else 0
        if self._good >= UP_SAMPLES and now - self._last_change >= COOLDOWN_S:
            return self._move(self.rung + 1, now, "sustained headroom")
        return Decision(self.rung, False, "holding")

    def _move(self, target: int, now: float, reason: str) -> Decision:
        self._good = 0
        if target == self.rung:
            return Decision(self.rung, False, "holding")
        self.rung, self._last_change = target, now
        return Decision(self.rung, True, reason)
