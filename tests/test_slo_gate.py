import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import slo_gate as g

BASE = {"time_to_first_frame_s": 2.0, "stall_ratio": 0.01, "success_rate": 0.98}


def test_within_tolerance_passes_and_median_damps_one_noisy_run():
    runs = {"time_to_first_frame_s": [2.1, 9.0, 2.2], "stall_ratio": [0.012], "success_rate": [0.97, 0.99, 0.97]}
    assert g.passed(g.compare(BASE, runs))


def test_regressions_in_either_direction_fail():
    slow = {"time_to_first_frame_s": [4.0] * 3, "stall_ratio": [0.01], "success_rate": [0.98]}
    assert [v.metric for v in g.compare(BASE, slow) if not v.ok] == ["time_to_first_frame_s"]
    flaky = {"time_to_first_frame_s": [2.0], "stall_ratio": [0.01], "success_rate": [0.8]}
    assert [v.metric for v in g.compare(BASE, flaky) if not v.ok] == ["success_rate"]


def test_missing_or_hostile_data_fails_closed():
    bad = {"time_to_first_frame_s": [float("nan"), True], "stall_ratio": "x"}
    verdicts = g.compare(BASE, bad)
    assert not g.passed(verdicts) and all(not v.ok for v in verdicts)
    assert not g.passed(g.compare({}, {}))
    assert not g.passed([])
