"""#466: the latency benchmark's maths and gate logic (fast, no timing assumptions)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import control_latency_benchmark as clb

ROOT = Path(__file__).resolve().parents[1]


def report(ack=5.0, confirm=50.0, clients="8", scenario="seek"):
    row = {"ack_p50": 2.0, "ack_p95": ack, "confirm_p50": 40.0, "confirm_p95": confirm, "samples": 15}
    return {"schema": 1, "clients": {clients: {scenario: row}}}


def test_percentile_is_nearest_rank():
    data = [float(n) for n in range(1, 21)]
    assert clb.percentile(data, 0.5) == 10.0 and clb.percentile(data, 0.95) == 19.0
    assert clb.percentile([7.0], 0.95) == 7.0 and clb.percentile([3.0, 1.0, 2.0], 1.0) == 3.0


def test_slo_breaches_are_reported_and_slack_scales_them():
    assert clb.evaluate(report(ack=10, confirm=100)) == []
    problems = clb.evaluate(report(ack=150, confirm=1500))
    assert any("ack p95 150" in p for p in problems) and any("confirmed p95 1500" in p for p in problems)
    assert clb.evaluate(report(ack=150, confirm=1500), slack=3.0) == []


def test_regression_gate_is_20_percent_with_an_absolute_floor():
    base = report(ack=40.0, confirm=200.0)
    assert clb.evaluate(report(ack=47.0, confirm=235.0), base) == []              # within +20%
    worse = clb.evaluate(report(ack=70.0, confirm=300.0), base)
    assert any("ack_p95 regressed 40.0 -> 70.0" in p for p in worse)
    assert any("confirm_p95 regressed 200.0 -> 300.0" in p for p in worse)
    tiny = report(ack=4.0, confirm=40.0)
    assert clb.evaluate(report(ack=20.0, confirm=60.0), tiny) == []               # floor: +25 ms is noise
    assert clb.evaluate(report(ack=40.0, confirm=90.0), tiny) != []
    assert clb.evaluate(report(ack=70.0, confirm=300.0), base, slack=3.0) == []   # CI runners are slower


def test_missing_baseline_entries_are_not_failures():
    assert clb.evaluate(report(clients="64"), report(clients="8")) == []


def test_committed_baseline_is_complete_and_inside_the_slos():
    baseline = json.loads((ROOT / "docs/control-latency-baseline.json").read_text(encoding="utf-8"))
    assert baseline["schema"] == clb.SCHEMA and set(baseline["clients"]) == {"1", "8", "32"}
    for count, scenarios in baseline["clients"].items():
        assert set(scenarios) == set(clb.SCENARIOS), count
        assert all(row["samples"] >= 10 for row in scenarios.values())
    assert clb.evaluate(baseline) == []


def test_table_lists_every_scenario():
    text = clb.table(json.loads((ROOT / "docs/control-latency-baseline.json").read_text(encoding="utf-8")))
    assert text.count("\n") == 12 and "play_pause" in text and "volume" in text


def test_a_breach_must_reproduce_to_fail_the_gate(monkeypatch):
    runs = iter([report(ack=500.0), report(ack=5.0)])
    monkeypatch.setattr(clb, "run", lambda *a, **k: next(runs))
    final, problems = clb.run_checked([8], 5, None)
    assert problems == [] and final["clients"]["8"]["seek"]["ack_p95"] == 5.0        # noise: second run is clean
    runs = iter([report(ack=500.0), report(ack=600.0)])
    monkeypatch.setattr(clb, "run", lambda *a, **k: next(runs))
    _final, problems = clb.run_checked([8], 5, None)
    assert any("ack p95 600" in p for p in problems)                                   # persistent: fails
    runs = iter([report(ack=500.0)])
    monkeypatch.setattr(clb, "run", lambda *a, **k: next(runs))
    assert clb.run_checked([8], 5, None, attempts=1)[1] != []
