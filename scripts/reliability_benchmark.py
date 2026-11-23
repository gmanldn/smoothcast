#!/usr/bin/env python3
"""Measure protocol command-to-PLAYING latency against loopback FakeCast."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pychromecast

from fakecast import FakeCastReceiver
from castctl import ReceiverInfo
from pychromecast_backend import PyChromecastBackend
import low_end_policy

SCHEMA = 1
TOLERANCE = 1.0  # A 100% margin tolerates hosted-runner noise; tune after baselines.


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def one_trial() -> float:
    """Return command-to-confirmed-PLAYING time on the loopback CASTV2 fake."""
    with FakeCastReceiver() as receiver:
        cast = pychromecast.get_chromecast_from_host(
            (receiver.host, receiver.port, uuid.uuid4(), "benchmark", "SLO fake"),
            tries=1, retry_wait=0.1, timeout=1,
        )

        def discover(*, callback, **_kwargs):
            callback(cast)
            return type("Browser", (), {"stop_discovery": lambda _self: None})()

        backend = PyChromecastBackend(discover=discover)
        statuses: list[ReceiverInfo] = []
        try:
            backend.scan(timeout=0)
            cast.wait(timeout=2)
            cast.start_app("CC1AD845")
            unsubscribe = backend.subscribe("SLO fake", statuses.append)
            try:
                start = time.perf_counter()
                accepted, message = backend.command(
                    "SLO fake", "cast", "http://127.0.0.1/reliability.mp4",
                )
                if not accepted:
                    raise RuntimeError(f"FakeCast rejected the benchmark cast: {message}")
                if not _wait(lambda: any(row.get("player_state") == "PLAYING" for row in statuses)):
                    raise RuntimeError("FakeCast did not confirm PLAYING within 3 seconds")
                return (time.perf_counter() - start) * 1000.0
            finally:
                if unsubscribe is not None:
                    unsubscribe()
        finally:
            backend.close()


def profile() -> dict[str, str]:
    return {
        "runner": os.environ.get(
            "SMOOTHCAST_BENCHMARK_RUNNER", f"{platform.system().lower()}-{platform.machine()}",
        ),
        "machine": platform.machine(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def compare(result: dict, baseline: dict | None) -> dict:
    if not isinstance(baseline, dict):
        return {"status": "baseline-pending", "tolerance": TOLERANCE}
    expected = baseline.get("profile")
    if expected != result["profile"]:
        return {"status": "profile-mismatch", "tolerance": TOLERANCE}
    median = baseline.get("median_playing_ms")
    if not isinstance(median, (int, float)) or median <= 0:
        return {"status": "baseline-invalid", "tolerance": TOLERANCE}
    allowed = median * (1.0 + TOLERANCE)
    return {
        "status": "pass" if result["median_playing_ms"] <= allowed else "regression",
        "baseline_median_playing_ms": median,
        "allowed_median_playing_ms": round(allowed, 3),
        "tolerance": TOLERANCE,
    }


def measure(iterations: int, *, runner=one_trial, runner_profile=None) -> dict:
    values = [round(float(runner()), 3) for _ in range(iterations)]
    if any(value < 0 for value in values):
        raise ValueError("benchmark values cannot be negative")
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile() if runner_profile is None else runner_profile,
        "measurement": "CASTV2 command dispatch to fake receiver PLAYING confirmation",
        "iterations": iterations,
        "playing_ms": values,
        "median_playing_ms": round(statistics.median(values), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    if not 3 <= args.iterations <= 31:
        parser.error("--iterations must be between 3 and 31")
    try:
        result = measure(args.iterations)
        baseline = (json.loads(args.baseline.read_text(encoding="utf-8"))
                    if args.baseline and args.baseline.is_file() else None)
        result["comparison"] = compare(result, baseline)
        # Informational scenario: never present a CI runner as physical hardware.
        result["low_end_reference"] = low_end_policy.budget()
        encoded = json.dumps(result, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 1 if result["comparison"]["status"] == "regression" else 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"reliability benchmark failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
