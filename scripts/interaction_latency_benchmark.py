"""Native GTK interaction latency budget (#627).

The isolated-Xvfb harness collects, per scenario, the milliseconds between a
synthetic interaction and the frame that acknowledges it, plus the worst
main-loop stall. This script turns those samples into p50/p95/p99, checks them
against the per-scenario SLOs and a stored baseline (a p95 more than 20 % over
the baseline, beyond a 1 ms noise floor), and can write the baseline.

    python3 scripts/interaction_latency_benchmark.py --samples samples.json \
        --check docs/interaction-latency-baseline.json
    python3 scripts/interaction_latency_benchmark.py --samples samples.json \
        --write-baseline docs/interaction-latency-baseline.json

Only the authorised isolated-Xvfb job produces samples; never measure with the
real desktop or a real receiver.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SLO_MS = {
    "play_pause": 16.0,
    "seek": 16.0,
    "volume": 16.0,
    "queue_rebuild_1000": 150.0,
    "stall_worst": 250.0,
}
TOLERANCE = 0.20  # allowed p95 regression against the baseline
FLOOR_MS = 1.0    # ...but never tighter than baseline + 1 ms: below that is timer noise
SCHEMA = 1
QUEUE_ITEMS = 1000
PHONE_POLLERS = 32


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summarize(samples: dict[str, list[float]]) -> dict:
    """Report with p50/p95/p99 per scenario; unknown scenarios keep their samples."""
    scenarios = {}
    for name, values in sorted(samples.items()):
        if not isinstance(values, list):   # e.g. the probe's "load" metadata
            continue
        numbers = [float(value) for value in values]
        if not numbers:
            continue
        scenarios[name] = {"n": len(numbers),
                           "p50": round(percentile(numbers, 0.50), 2),
                           "p95": round(percentile(numbers, 0.95), 2),
                           "p99": round(percentile(numbers, 0.99), 2),
                           "slo_ms": SLO_MS.get(name)}
    return {"schema": SCHEMA, "queue_items": QUEUE_ITEMS,
            "phone_pollers": PHONE_POLLERS, "scenarios": scenarios}


def evaluate(report: dict, baseline: dict | None = None, *, slack: float = 1.0) -> list[str]:
    """Problems: SLO breaches, and p95 regressions over the baseline."""
    problems = []
    scenarios = report.get("scenarios") or {}
    for name, row in sorted(scenarios.items()):
        slo = row.get("slo_ms")
        if slo is not None and row["p95"] > slo * slack:
            problems.append(f"{name}: p95 {row['p95']} ms > SLO {slo * slack:.0f} ms")
        old = ((baseline or {}).get("scenarios") or {}).get(name)
        limit = max(old["p95"] * (1 + TOLERANCE), old["p95"] + FLOOR_MS) * slack if old else None
        if limit is not None and row["p95"] > limit:
            problems.append(f"{name}: p95 regressed {old['p95']} -> {row['p95']} ms "
                            f"(limit +{TOLERANCE:.0%} above baseline)")
    for name in sorted(SLO_MS):
        if name not in scenarios:
            problems.append(f"{name}: no samples collected")
    return problems


def table(report: dict) -> str:
    lines = [f"{'scenario':22} {'n':>5} {'p50':>8} {'p95':>8} {'p99':>8} {'SLO':>8}"]
    for name, row in sorted((report.get("scenarios") or {}).items()):
        slo = "-" if row.get("slo_ms") is None else f"{row['slo_ms']:.0f}"
        lines.append(f"{name:22} {row['n']:>5} {row['p50']:>8} {row['p95']:>8} "
                     f"{row['p99']:>8} {slo:>8}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--samples", type=Path, required=True,
                        help='JSON: {"scenario": [ms, ...], ...}')
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--check", type=Path, help="fail on an SLO breach or a >20%% p95 regression")
    parser.add_argument("--slack", type=float, default=1.0,
                        help="multiply the SLOs and baseline limits (quiet host tuning)")
    args = parser.parse_args(argv)

    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    report = summarize(samples)
    print(table(report))
    if args.write_baseline:
        args.write_baseline.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
        print(f"baseline written to {args.write_baseline}")
    if not args.check:
        return 0
    baseline = json.loads(args.check.read_text(encoding="utf-8"))
    problems = evaluate(report, baseline, slack=args.slack)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
