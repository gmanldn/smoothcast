"""Measured stream-health aggregate (SC-040, #49): pure, bounded, no I/O.

Feed it observed facts (segment served/failed, recovery, throughput and latency
samples, decoder state reported by the receiver). ``snapshot`` reports only what
was measured: anything never observed is ``None``/"unknown", never inferred OK.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from collections import deque
from dataclasses import dataclass, field

WINDOW = 60                # samples kept per series
EVENT_WINDOW = 200         # events kept
DECODER_STATES = ("unknown", "idle", "buffering", "playing", "paused", "error")


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


@dataclass
class StreamHealth:
    clock: object = time.monotonic
    _throughput: deque = field(default_factory=lambda: deque(maxlen=WINDOW), repr=False)
    _latency: deque = field(default_factory=lambda: deque(maxlen=WINDOW), repr=False)
    _events: deque = field(default_factory=lambda: deque(maxlen=EVENT_WINDOW), repr=False)
    decoder: str = "unknown"
    segments_ok: int = 0
    segments_failed: int = 0
    recoveries: int = 0

    def throughput(self, kbps: object) -> None:
        if (v := _num(kbps)) is not None:
            self._throughput.append(v)

    def latency(self, ms: object) -> None:
        if (v := _num(ms)) is not None:
            self._latency.append(v)

    def segment(self, ok: bool, name: str = "") -> None:
        if ok:
            self.segments_ok += 1
        else:
            self.segments_failed += 1
            self._events.append((self.clock(), "segment_failed", str(name)[:80]))

    def recovered(self, what: str = "") -> None:
        self.recoveries += 1
        self._events.append((self.clock(), "recovered", str(what)[:80]))

    def decoder_state(self, state: object) -> None:
        self.decoder = state if state in DECODER_STATES else "unknown"
        if self.decoder == "error":
            self._events.append((self.clock(), "decoder_error", ""))

    def snapshot(self) -> dict:
        def stat(series: deque) -> dict | None:
            if not series:
                return None
            ordered = sorted(series)
            return {"last": series[-1], "median": statistics.median(series),
                    "p95": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], "samples": len(series)}
        total = self.segments_ok + self.segments_failed
        return {"throughput_kbps": stat(self._throughput), "latency_ms": stat(self._latency),
                "decoder": self.decoder, "segments_ok": self.segments_ok,
                "segments_failed": self.segments_failed,
                "failure_rate": (self.segments_failed / total) if total else None,
                "recoveries": self.recoveries,
                "recent_events": [{"t": t, "kind": k, "detail": d} for t, k, d in list(self._events)[-10:]]}


SNAPSHOT_NAME = "stream_health.json"
SNAPSHOT_MAX_AGE = 15.0     # seconds; older data is stale, not "healthy"


def write_snapshot(directory, snapshot: dict, *, now: float | None = None) -> None:
    """Best-effort atomic publish for another process; never raises."""
    try:
        target = os.path.join(os.fspath(directory), SNAPSHOT_NAME)
        tmp = f"{target}.{os.getpid()}.tmp"
        payload = {"at": time.time() if now is None else now, "snapshot": snapshot}
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, target)
    except (OSError, TypeError, ValueError):
        pass


def read_snapshot(directory, *, now: float | None = None) -> dict | None:
    """Fresh published snapshot, or None when missing, corrupt or stale."""
    try:
        with open(os.path.join(os.fspath(directory), SNAPSHOT_NAME), encoding="utf-8") as handle:
            data = json.load(handle)
        age = (time.time() if now is None else now) - float(data["at"])
        snap = data["snapshot"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return snap if isinstance(snap, dict) and 0 <= age <= SNAPSHOT_MAX_AGE else None
