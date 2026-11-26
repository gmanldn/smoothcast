"""Main-loop jank detector (#442): the GTK-free core.

The wired build posts :meth:`JankWatchdog.beat` from the GTK main loop and runs
:meth:`JankWatchdog.poll` from a monitor thread. A gap between heartbeats longer
than the threshold counts one stall per rate-limit window, keeps a bounded,
privacy-scrubbed stack sample, and maintains a p99 lag figure for diagnostics
and reliability metrics. Nothing here imports GTK or starts a thread.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time
from typing import Callable, Iterable

DEFAULT_THRESHOLD_MS = 100.0
DEFAULT_RATE_LIMIT_S = 1.0
MAX_SAMPLES = 200
_LONG_ID = re.compile(r"\b[0-9a-f]{24,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class Stall:
    """One detected main-loop stall."""

    at: float
    lag_ms: float
    stack: tuple[str, ...]


def scrub_frames(frames: Iterable[str], *, home: str | None = None) -> tuple[str, ...]:
    """Drop the user's home prefix and opaque identifiers from frame names."""
    prefix = os.path.expanduser("~") if home is None else home
    cleaned = []
    for frame in frames:
        text = str(frame)
        if prefix and prefix not in ("", "~"):
            text = text.replace(prefix, "~")
        cleaned.append(_LONG_ID.sub("<id>", text))
    return tuple(cleaned)


class JankWatchdog:
    """Detect main-loop stalls from heartbeat gaps; never blocks or raises."""

    def __init__(self, *, threshold_ms: float = DEFAULT_THRESHOLD_MS,
                 rate_limit_s: float = DEFAULT_RATE_LIMIT_S,
                 max_samples: int = MAX_SAMPLES,
                 clock: Callable[[], float] = time.monotonic,
                 capture_stack: Callable[[], Iterable[str]] | None = None,
                 scrub: Callable[..., tuple[str, ...]] = scrub_frames,
                 home: str | None = None,
                 on_stall: Callable[[Stall], None] | None = None) -> None:
        self.threshold_ms = float(threshold_ms)
        self.rate_limit_s = float(rate_limit_s)
        self.max_samples = max(1, int(max_samples))
        self._clock = clock
        self._capture_stack = capture_stack
        self._scrub = scrub
        self._home = home
        self._on_stall = on_stall
        self._last_beat = clock()
        self._last_stall_at: float | None = None
        self._count = 0
        self._lags: list[float] = []
        self._samples: list[Stall] = []

    def beat(self, now: float | None = None) -> None:
        """Called from the main loop; records that the loop is still moving."""
        self._last_beat = self._clock() if now is None else float(now)

    def poll(self, now: float | None = None) -> Stall | None:
        """Called from the monitor; returns the stall when one is recorded."""
        moment = self._clock() if now is None else float(now)
        lag_ms = (moment - self._last_beat) * 1000.0
        if lag_ms < self.threshold_ms:
            return None
        if (self._last_stall_at is not None
                and moment - self._last_stall_at < self.rate_limit_s):
            return None
        self._last_stall_at = moment
        self._count += 1
        self._lags.append(lag_ms)
        stall = Stall(at=moment, lag_ms=lag_ms, stack=self._capture(moment))
        self._samples.append(stall)
        del self._samples[:-self.max_samples]
        del self._lags[:-self.max_samples]
        if self._on_stall is not None:
            try:
                self._on_stall(stall)
            except Exception:
                # A counter hook must never break the loop either.
                pass
        return stall

    def reset(self) -> None:
        """Re-arm after a scripted journey (counts preserved only if asked)."""
        self._lags.clear()
        self._samples.clear()
        self._last_stall_at = None
        self._last_beat = self._clock()

    @property
    def count(self) -> int:
        return self._count

    @property
    def samples(self) -> tuple[Stall, ...]:
        return tuple(self._samples)

    @property
    def p99_ms(self) -> float:
        return _percentile(self._lags, 0.99)

    def stats(self) -> dict[str, float | int]:
        last = self._lags[-1] if self._lags else 0.0
        return {"stalls": self._count, "p99_ms": round(self.p99_ms, 1),
                "last_lag_ms": round(last, 1), "threshold_ms": self.threshold_ms}

    def summary(self) -> dict[str, float | int | bool]:
        """Diagnostics view of this watchdog."""
        return {"enabled": True, **self.stats()}

    def _capture(self, moment: float) -> tuple[str, ...]:
        if self._capture_stack is None:
            return ()
        try:
            frames = tuple(self._capture_stack())
            try:
                return self._scrub(frames, home=self._home)
            except TypeError:
                return tuple(self._scrub(frames))
        except Exception:
            # A detector must never break the loop it is watching.
            return ()


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile (no interpolation), 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(fraction * len(ordered) + 0.9999) - 1))
    return ordered[index]


_CURRENT: "JankWatchdog | None" = None


def install(watchdog: "JankWatchdog | None") -> "JankWatchdog | None":
    """Make *watchdog* the process-wide instance diagnostics report on."""
    global _CURRENT
    previous, _CURRENT = _CURRENT, watchdog
    return previous


def current() -> "JankWatchdog | None":
    return _CURRENT


def diagnostics_summary() -> dict[str, float | int | bool]:
    """Jank snapshot for the diagnostics bundle; disabled when unwired."""
    watchdog = _CURRENT
    if watchdog is None:
        return {"enabled": False, "stalls": 0, "p99_ms": 0.0, "last_lag_ms": 0.0,
                "threshold_ms": DEFAULT_THRESHOLD_MS}
    return watchdog.summary()
