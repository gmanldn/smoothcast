"""Local-to-receiver handoff accuracy (#41). Pure: no GTK, network or clock reads.

Records how far the receiver's first reported position landed from the intended
one, keeps a robust per-receiver latency estimate, and returns the start offset
that compensates for it within a bounded range.
"""
from __future__ import annotations

import math
import statistics

TOLERANCE_S = 1.0
MAX_COMPENSATION_S = 8.0
KEEP = 9
MIN_SAMPLES = 3


def _ok(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def error(intended: float, first_reported: float) -> float | None:
    """Signed start error in seconds (positive = receiver started late/behind)."""
    if not (_ok(intended) and _ok(first_reported)):
        return None
    return float(intended) - float(first_reported)


def record(history: dict, receiver: str, err) -> list[float]:
    """Add one measurement; implausible errors (beyond +/-30 s) are discarded."""
    samples = history.setdefault(str(receiver), [])
    if _ok(err) and abs(err) <= 30:
        samples.append(float(err))
        del samples[:-KEEP]
    return samples


def compensation(history: dict, receiver: str) -> float:
    """Seconds to add to the requested start so playback lands on target.

    Median of recent errors (robust to one bad handoff), clamped, and zero until
    enough samples exist or while the typical error is already within tolerance.
    """
    samples = history.get(str(receiver)) or []
    if len(samples) < MIN_SAMPLES:
        return 0.0
    med = statistics.median(samples)
    if abs(med) <= TOLERANCE_S / 4:
        return 0.0
    return max(-MAX_COMPENSATION_S, min(MAX_COMPENSATION_S, med))


def within_tolerance(err) -> bool:
    return _ok(err) and abs(err) <= TOLERANCE_S
