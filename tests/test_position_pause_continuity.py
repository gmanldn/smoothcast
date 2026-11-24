"""Source-time continuity between authoritative receiver polls (#336)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import position_tracker as pt  # noqa: E402


@pytest.fixture
def timeline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(pt.time, "monotonic", lambda: now[0])
    return pt.PositionTracker(), now


@pytest.mark.parametrize("rate", [0.5, 1.0, 2.0])
def test_pause_freezes_extrapolated_device_position(timeline, rate):
    tracker, now = timeline
    tracker.start(0, 100, rate=rate)
    tracker.device_update(20, 100, rate)
    now[0] += 4
    before = tracker.value()
    tracker.set_state(False)
    assert tracker.value() == before == 20 + 4 * rate
    now[0] += 30
    assert tracker.value() == before
    tracker.set_state(True)
    assert tracker.value() == before
    now[0] += 2
    assert tracker.value() == before + 2 * rate


def test_pause_clamps_to_duration(timeline):
    tracker, now = timeline
    tracker.start(0, 30)
    tracker.device_update(29, 30)
    now[0] += 5
    tracker.set_state(False)
    assert tracker.value() == 30


def test_new_authoritative_sample_overrides_paused_estimate(timeline):
    tracker, now = timeline
    tracker.start(0, 100)
    tracker.device_update(20, 100)
    now[0] += 5
    tracker.set_state(False)
    tracker.device_update(22, 100)
    now[0] += 12
    assert tracker.value() == 22
    tracker.set_state(True)
    now[0] += 1
    assert tracker.value() == 23


def test_estimated_clock_preserves_pause_continuity(timeline):
    tracker, now = timeline
    tracker.start(10, 100)
    now[0] += 4
    tracker.set_state(False)
    now[0] += 10
    assert tracker.value() == 14
    tracker.set_state(True)
    now[0] += 3
    assert tracker.value() == 17
