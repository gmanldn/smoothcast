"""Per-receiver guest volume ceiling, step mode and rate limit (#330). Pure.

Keyed by a stable receiver id (never a display name). ``Guard.decide`` is called
at dispatch, right before a command is sent: hosts pass through; guests are
clamped to the receiver's ceiling and to ``max_step`` from the last known level,
and limited to ``RATE_N`` changes per ``RATE_WINDOW_S`` per receiver+actor.
Unknown current volume makes steps conservative (no jump above the ceiling's half).
"""
from __future__ import annotations

DEFAULT_CEILING = 0.6
DEFAULT_STEP = 0.05
RATE_N, RATE_WINDOW_S = 5, 5.0


class Guard:
    def __init__(self) -> None:
        self._ceiling: dict[str, float] = {}
        self._hits: dict[tuple[str, str], list[float]] = {}

    def set_ceiling(self, receiver_id: str, ceiling: float) -> bool:
        if not receiver_id or not isinstance(ceiling, (int, float)) or not 0.0 <= ceiling <= 1.0:
            return False
        self._ceiling[receiver_id] = float(ceiling)
        return True

    def ceiling(self, receiver_id: str) -> float:
        return self._ceiling.get(receiver_id, DEFAULT_CEILING)

    def decide(self, receiver_id: str, actor: str, role: str, requested: float,
               current: float | None, now: float, max_step: float = DEFAULT_STEP) -> tuple[float | None, str]:
        """(volume to send or None, reason). Host is never clamped."""
        if not receiver_id or not isinstance(requested, (int, float)) or requested != requested:
            return None, "Invalid volume."
        requested = max(0.0, min(1.0, float(requested)))
        if role == "host":
            return requested, ""
        hits = [t for t in self._hits.get((receiver_id, actor), []) if now - t < RATE_WINDOW_S]
        if len(hits) >= RATE_N:
            self._hits[(receiver_id, actor)] = hits
            return None, "Too many volume changes. Wait a moment."
        hits.append(now)
        self._hits[(receiver_id, actor)] = hits
        cap = self.ceiling(receiver_id)
        level = min(requested, cap)
        if current is not None:
            level = max(current - max_step, min(current + max_step, level)) if current <= cap else min(level, current)
        else:
            level = min(level, cap / 2)
        return max(0.0, level), ("Limited by the host." if level < requested else "")
