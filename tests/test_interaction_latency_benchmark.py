"""Tests for the native interaction-latency budget (#627)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import interaction_latency_benchmark as bench  # noqa: E402


def _samples(**overrides):
    values = {name: [5.0, 6.0, 7.0, 8.0] for name in bench.SLO_MS}
    values.update(overrides)
    return values


def test_percentile_uses_nearest_rank():
    assert bench.percentile([1, 2, 3, 4], 0.50) == 2
    assert bench.percentile([1, 2, 3, 4], 0.95) == 4
    assert bench.percentile([9], 0.99) == 9


def test_summarize_reports_percentiles_and_skips_empty_scenarios():
    report = bench.summarize({"seek": [1, 2, 3, 4], "volume": []})
    assert report["schema"] == bench.SCHEMA
    assert report["queue_items"] == 1000 and report["phone_pollers"] == 32
    assert report["scenarios"]["seek"] == {"n": 4, "p50": 2.0, "p95": 4.0, "p99": 4.0,
                                           "slo_ms": bench.SLO_MS["seek"]}
    assert "volume" not in report["scenarios"]


def test_evaluate_flags_slo_breaches():
    report = bench.summarize(_samples(seek=[10.0, 30.0]))
    problems = bench.evaluate(report)
    assert any(p.startswith("seek: p95 30.0 ms > SLO") for p in problems), problems
    assert problems == [p for p in problems if "seek" in p]


def test_evaluate_flags_a_p95_regression_beyond_the_noise_floor():
    baseline = bench.summarize(_samples(seek=[10.0, 10.0]))
    within = bench.summarize(_samples(seek=[10.5, 10.5]))       # inside baseline + 1 ms
    assert bench.evaluate(within, baseline) == []
    regressed = bench.summarize(_samples(seek=[10.0, 13.0]))    # beyond floor and tolerance
    problems = bench.evaluate(regressed, baseline)
    assert any("p95 regressed" in p for p in problems), problems


def test_evaluate_reports_missing_scenarios():
    report = bench.summarize({"seek": [1.0]})
    problems = bench.evaluate(report)
    assert any(p == "play_pause: no samples collected" for p in problems)


def test_cli_writes_and_checks_a_baseline(tmp_path):
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps(_samples()), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    assert bench.main(["--samples", str(samples), "--write-baseline", str(baseline)]) == 0
    assert bench.main(["--samples", str(samples), "--check", str(baseline)]) == 0
    slow = tmp_path / "slow.json"
    slow.write_text(json.dumps(_samples(seek=[10.0, 40.0])), encoding="utf-8")
    assert bench.main(["--samples", str(slow), "--check", str(baseline)]) == 1
    assert bench.main(["--samples", str(slow), "--check", str(baseline),
                       "--slack", "10"]) == 0
