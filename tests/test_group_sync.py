import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import group_sync as gs


def test_faster_rooms_are_delayed_to_match_the_slowest():
    p = {r.room: r for r in gs.plan({"a": [100, 102, 98], "b": [300, 301, 299], "c": [200, 200, 200]})}
    assert (p["a"].delay_ms, p["b"].delay_ms, p["c"].delay_ms) == (200, 0, 100)
    assert all(r.trusted for r in p.values())


def test_sparse_or_noisy_rooms_are_not_trusted_and_not_delayed():
    p = {r.room: r for r in gs.plan({"a": [100, 100, 100], "few": [50], "noisy": [10, 400, 90], "bad": "x"})}
    assert p["a"].trusted and p["a"].delay_ms == 0
    assert not p["few"].trusted and not p["noisy"].trusted and not p["bad"].trusted
    assert p["few"].delay_ms == p["noisy"].delay_ms == 0


def test_hostile_numbers_are_ignored():
    p = gs.plan({"a": [float("nan"), True, -5, 1, 2, 3]})
    assert p[0].trusted


def test_huge_skew_is_refused_not_applied():
    p = {r.room: r for r in gs.plan({"a": [10, 10, 10], "b": [5000, 5000, 5000]})}
    assert not p["a"].trusted and p["b"].trusted


def test_group_volume_respects_each_rooms_ceiling_and_bad_targets():
    assert gs.group_volume({"a": 0.2, "b": 0.2}, 0.9, {"b": 0.5}) == {"a": 0.9, "b": 0.5}
    assert gs.group_volume({"a": 0.2}, float("nan")) == {"a": 0.2}
    assert gs.group_volume({"a": 0.2}, 7) == {"a": 1.0}
