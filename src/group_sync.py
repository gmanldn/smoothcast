"""Multi-room sync maths (SC-037, #46): pure, no receiver I/O.

``plan`` turns measured per-receiver latency (ms from command to audible output)
into the extra delay each receiver needs so all sound together, and rejects
measurements too noisy or too far apart to trust. ``group_volume`` applies a
shared volume change per room with a per-room ceiling so one loud room is
never raised past its own safe limit.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

MAX_SKEW_MS = 2000.0     # beyond this the group cannot be aligned by delay alone
MAX_JITTER_MS = 150.0    # spread of repeated samples above this is untrustworthy


@dataclass(frozen=True)
class RoomPlan:
    room: str
    delay_ms: int
    trusted: bool
    reason: str = ""


def _clean(samples: object) -> list[float]:
    if not isinstance(samples, (list, tuple)):
        return []
    return [float(s) for s in samples
            if isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and s >= 0]


def plan(measurements: dict[str, list[float]]) -> list[RoomPlan]:
    """Delay each room to match the slowest trusted one; untrusted rooms get 0."""
    medians: dict[str, float] = {}
    out: dict[str, RoomPlan] = {}
    for room, raw in measurements.items():
        samples = _clean(raw)
        if len(samples) < 3:
            out[room] = RoomPlan(room, 0, False, "needs at least 3 latency samples")
        elif max(samples) - min(samples) > MAX_JITTER_MS:
            out[room] = RoomPlan(room, 0, False, "latency too unsteady to calibrate")
        else:
            medians[room] = statistics.median(samples)
    if medians:
        slowest = max(medians.values())
        for room, value in medians.items():
            delay = slowest - value
            if delay > MAX_SKEW_MS:
                out[room] = RoomPlan(room, 0, False, "out of range for delay alignment")
            else:
                out[room] = RoomPlan(room, int(round(delay)), True)
    return [out[room] for room in measurements]


def group_volume(current: dict[str, float], target: float, ceilings: dict[str, float] | None = None) -> dict[str, float]:
    """Per-room volume (0..1) moving toward ``target`` but never above a room's ceiling."""
    if not isinstance(target, (int, float)) or isinstance(target, bool) or not math.isfinite(target):
        return dict(current)
    target = max(0.0, min(1.0, float(target)))
    limits = ceilings or {}
    return {room: round(min(target, max(0.0, min(1.0, limits.get(room, 1.0)))), 3) for room in current}
