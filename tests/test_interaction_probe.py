"""Tests for the interaction probe core (#627)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import interaction_latency_benchmark as bench  # noqa: E402
import interaction_probe as probe  # noqa: E402


def test_measure_records_each_interaction_until_the_frame_spins():
    clock = iter([0.0, 0.010, 1.0, 1.004])  # 10 ms, then 4 ms
    calls = []
    samples = probe.measure({"play_pause": lambda: calls.append("play")},
                            spin=lambda: calls.append("spin"),
                            now=lambda: next(clock), rounds=2)
    assert calls == ["play", "spin", "play", "spin"]
    assert samples == {"play_pause": [10.0, 4.0]}


def test_measure_keeps_every_scenario_and_always_takes_a_round():
    samples = probe.measure({"a": lambda: None, "b": lambda: None},
                            spin=lambda: None, now=lambda: 0.0, rounds=0)
    assert sorted(samples) == ["a", "b"]
    assert samples["a"] == [0.0]


def test_poll_pressure_counts_the_simulated_phones():
    polls = []
    assert probe.poll_pressure(lambda: polls.append(1), pollers=32, rounds=2) == 64
    assert len(polls) == 64
    assert probe.poll_pressure(lambda: None, pollers=0) == 0


def test_write_samples_round_trips_through_the_budget_script(tmp_path):
    samples = {name: [4.0, 5.0] for name in bench.SLO_MS}
    path = probe.write_samples(tmp_path / "samples.json", samples)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == probe.SCHEMA
    assert payload["load"] == {"queue_items": 1000, "phone_pollers": 32}
    assert payload["seek"] == [4.0, 5.0]
    baseline = tmp_path / "baseline.json"
    assert bench.main(["--samples", str(path), "--write-baseline", str(baseline)]) == 0
    assert bench.main(["--samples", str(path), "--check", str(baseline)]) == 0


def test_require_isolated_refuses_a_real_desktop(monkeypatch):
    import gui_test_safety

    monkeypatch.setattr(gui_test_safety, "is_isolated_gui_test", lambda env=None: False)
    with pytest.raises(RuntimeError, match="only collected in the isolated Xvfb job"):
        probe.require_isolated()
    monkeypatch.setattr(gui_test_safety, "is_isolated_gui_test", lambda env=None: True)
    assert probe.require_isolated() is None
