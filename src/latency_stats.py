"""Local latency histograms and correlation ids (#698). Bounded, pure, no network; persists via store.Store.

Fixed buckets keep memory constant however many samples arrive. Percentiles are bucket upper bounds (never under-reported).
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from bisect import bisect_left

BOUNDS_MS = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)
MAX_METRICS = 32
_NAME = re.compile(r"[a-z][a-z0-9_.]{0,47}\Z")
_CID = re.compile(r"[0-9a-f]{12}\Z")


def new_correlation_id(rng=None) -> str:
    """12 hex chars: one id follows a user action through log lines to the receiver result."""
    return (rng or (lambda: secrets.token_hex(6)))()


def valid_correlation_id(value) -> bool:
    return isinstance(value, str) and bool(_CID.match(value))


class Stats:
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._h: dict[str, list[int]] = {}
        self._lock = threading.Lock()

    def record(self, name: str, ms) -> bool:
        if not isinstance(name, str) or not _NAME.match(name) or isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms != ms or ms < 0:
            return False
        with self._lock:
            row = self._h.get(name)
            if row is None:
                if len(self._h) >= MAX_METRICS:
                    return False
                row = self._h[name] = [0] * (len(BOUNDS_MS) + 1)
            row[bisect_left(BOUNDS_MS, ms)] += 1
        return True

    def timer(self, name: str):
        stats = self

        class _T:
            def __enter__(self_):
                self_.t0 = stats.clock()
                return self_

            def __exit__(self_, *exc):
                stats.record(name, (stats.clock() - self_.t0) * 1000.0)
                return False

        return _T()

    def percentile(self, name: str, p: float) -> float | None:
        with self._lock:
            row = list(self._h.get(name) or [])
        total = sum(row)
        if not total:
            return None
        need, seen = max(1, -(-total * p // 100)), 0
        for i, n in enumerate(row):
            seen += n
            if seen >= need:
                return float(BOUNDS_MS[i]) if i < len(BOUNDS_MS) else float("inf")
        return None

    def snapshot(self) -> dict:
        with self._lock:
            return {"bounds_ms": list(BOUNDS_MS), "metrics": {k: list(v) for k, v in sorted(self._h.items())}}

    def summary(self) -> dict:
        return {k: {"count": sum(v), **{f"p{p}": self.percentile(k, p) for p in (50, 95, 99)}} for k, v in self.snapshot()["metrics"].items()}

    def restore(self, data) -> None:
        """Load a persisted snapshot; anything malformed or from different bounds is ignored."""
        if not isinstance(data, dict) or data.get("bounds_ms") != list(BOUNDS_MS) or not isinstance(data.get("metrics"), dict):
            return
        with self._lock:
            for k, v in list(data["metrics"].items())[:MAX_METRICS]:
                if _NAME.match(str(k)) and isinstance(v, list) and len(v) == len(BOUNDS_MS) + 1 and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in v):
                    self._h.setdefault(k, [0] * len(v))
                    self._h[k] = [a + b for a, b in zip(self._h[k], v)]


_SHARED = Stats()
FILE_NAME = "latency.json"


def shared() -> Stats:
    """Process-wide recorder: call sites record here, the app saves it, diagnostics read it."""
    return _SHARED


def save(stats: Stats, directory) -> bool:
    """Atomically write the snapshot to ``directory/latency.json``; False when the disk refuses."""
    import json
    import os
    from pathlib import Path
    target = Path(directory) / FILE_NAME
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(stats.snapshot()), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        return False
    return True


def load(directory) -> Stats:
    """A fresh Stats restored from ``directory/latency.json``; missing or corrupt files give an empty one."""
    import json
    from pathlib import Path
    stats = Stats()
    try:
        stats.restore(json.loads((Path(directory) / FILE_NAME).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return stats


def record_shutdown(report: dict, directory) -> bool:
    """Fold one shutdown report into the persisted histograms (``app.shutdown`` plus ``shutdown.<step>``).

    Merges with what earlier runs saved, so the p95 grows across sessions; False when the disk refuses.
    """
    stats = load(directory)
    stats.record("app.shutdown", report.get("total_ms"))
    for step in report.get("steps") or ():
        if isinstance(step, dict):
            stats.record("shutdown." + str(step.get("name", "")), step.get("ms"))
    return save(stats, directory)
