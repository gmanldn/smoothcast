"""Fresh-session and invalid receiver-clock regression tests."""
import math

import pytest

import position_tracker as pt


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(pt.time, "monotonic", lambda: now[0])
    return pt.PositionTracker(), now


def test_new_unknown_duration_does_not_inherit_previous_film(clock):
    tracker, now = clock
    tracker.start(0, 30)
    tracker.start(0, 0)
    now[0] += 45
    assert tracker.duration == 0
    assert tracker.value() == 45


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_invalid_position_sample_does_not_replace_authoritative_clock(clock, bad):
    tracker, now = clock
    tracker.start(0, 100)
    tracker.device_update(20, 100)
    now[0] += 4
    tracker.device_update(bad, 100)
    assert tracker.value() == 24


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0, 0.0])
def test_invalid_poll_metadata_preserves_last_valid_values(clock, bad):
    tracker, now = clock
    tracker.start(0, 100, rate=2)
    tracker.device_update(20, bad, rate=bad)
    now[0] += 3
    assert tracker.duration == 100
    assert tracker.rate == 2
    assert tracker.value() == 26


def test_new_session_sanitises_invalid_initial_values(clock):
    tracker, now = clock
    tracker.start(math.inf, math.nan, rate=math.inf)
    now[0] += 3
    assert tracker.duration == 0
    assert tracker.rate == 1
    assert tracker.value() == 3


def test_missing_poll_duration_keeps_known_duration_and_rebase_keeps_rate(clock):
    tracker, now = clock
    tracker.start(0, 100, rate=2)
    tracker.device_update(20, None)
    tracker.rebase(40)
    now[0] += 5
    assert tracker.duration == 100
    assert tracker.value() == 50
