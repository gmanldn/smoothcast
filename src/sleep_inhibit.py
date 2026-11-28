"""Bounded sleep/shutdown inhibitor (#426). Pure core; OS backends are injected.

``Inhibitor`` holds at most 15 s and releases exactly once on every path (done, error, timeout, ``with`` exit).
``NoopBackend`` is the fallback where the OS has no inhibitor API.
"""
from __future__ import annotations

MAX_HOLD_S = 15.0


class NoopBackend:
    def acquire(self, why: str):
        return None

    def release(self, token) -> None:
        return None


class Inhibitor:
    def __init__(self, backend=None, clock=None, max_hold: float = MAX_HOLD_S) -> None:
        import time
        self.backend, self.clock = backend or NoopBackend(), clock or time.monotonic
        self.max_hold, self.token, self.held, self.t0 = min(float(max_hold), MAX_HOLD_S), None, False, 0.0

    def acquire(self, why: str = "SmoothCast is handing over playback") -> bool:
        if self.held:
            return True
        try:
            self.token = self.backend.acquire(why[:120])
        except Exception:  # noqa: BLE001 - no inhibitor: proceed; the drain deadline still applies
            return False                                 # no inhibitor: proceed, the drain deadline still bounds us
        self.held, self.t0 = True, self.clock()
        return True

    def remaining(self) -> float:
        return max(0.0, self.max_hold - (self.clock() - self.t0)) if self.held else 0.0

    def expired(self) -> bool:
        return self.held and self.clock() - self.t0 >= self.max_hold

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        try:
            self.backend.release(self.token)
        except Exception:  # noqa: BLE001 - best-effort release
            pass
        self.token = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False
