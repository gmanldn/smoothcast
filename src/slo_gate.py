"""Regression gate for reliability SLIs (#206): pure comparison of runs to a baseline.

Each metric has a direction (lower or higher is better) and a relative
tolerance. Runs are reduced to a median of N to damp CI-runner noise. A missing
or malformed measurement is a FAIL, never a silent pass.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

# metric -> (direction, relative tolerance); wide at first, tighten over time.
POLICY: dict[str, tuple[str, float]] = {
    "time_to_first_frame_s": ("lower", 0.50),
    "stall_ratio": ("lower", 0.50),
    "success_rate": ("higher", 0.10),
}


@dataclass(frozen=True)
class Verdict:
    metric: str
    ok: bool
    baseline: float | None
    observed: float | None
    detail: str


def _median(values: object) -> float | None:
    if not isinstance(values, (list, tuple)):
        return None
    clean = [float(v) for v in values
             if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    return statistics.median(clean) if clean else None


def compare(baseline: dict[str, float], runs: dict[str, list[float]],
            policy: dict[str, tuple[str, float]] | None = None) -> list[Verdict]:
    out: list[Verdict] = []
    for metric, (direction, tol) in (policy or POLICY).items():
        base = baseline.get(metric)
        if not isinstance(base, (int, float)) or isinstance(base, bool) or not math.isfinite(base):
            out.append(Verdict(metric, False, None, None, "no usable baseline"))
            continue
        seen = _median(runs.get(metric))
        if seen is None:
            out.append(Verdict(metric, False, float(base), None, "no usable measurement"))
            continue
        limit = base * (1 + tol) if direction == "lower" else base * (1 - tol)
        ok = seen <= limit if direction == "lower" else seen >= limit
        out.append(Verdict(metric, ok, float(base), seen,
                           "within tolerance" if ok else f"regressed beyond {tol:.0%} (limit {limit:.4g})"))
    return out


def passed(verdicts: list[Verdict]) -> bool:
    return bool(verdicts) and all(v.ok for v in verdicts)
