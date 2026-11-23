"""Source-time A/B repeat boundary and lifecycle behavior."""
import math

from ab_repeat import ABRepeat


def test_marks_loop_at_exact_source_time_and_rearm_after_seek():
    loop = ABRepeat()
    assert loop.mark_start(1.234, 100)
    assert loop.mark_end(5.678, 100)
    assert loop.boundary_target(5.677, playing=True) is None
    assert loop.boundary_target(5.678, playing=True) == 1.234
    # No duplicate seek while the receiver is still reporting the old point.
    assert loop.boundary_target(5.9, playing=True) is None
    assert loop.boundary_target(1.234, playing=True) is None
    assert loop.boundary_target(5.678, playing=True) == 1.234


def test_pause_preserves_marks_and_invalid_or_eof_marks_are_rejected():
    loop = ABRepeat()
    assert loop.mark_start(4.25, 20)
    assert loop.mark_end(9.75, 20)
    assert loop.boundary_target(12, playing=False) is None
    assert loop.boundary_target(12, playing=True) == 4.25
    for value in (-1, float("nan"), float("inf")):
        assert not loop.mark_start(value, 20)
    assert not loop.mark_start(20, 20)
    assert not loop.mark_end(4.25, 20)
    assert not loop.mark_end(math.nan, 20)


def test_manual_seek_releases_failed_boundary_guard_and_clear_resets():
    loop = ABRepeat()
    assert loop.mark_start(2.0, 20)
    assert loop.mark_end(6.0, 20)
    assert loop.boundary_target(6.0, playing=True) == 2.0
    assert loop.boundary_target(6.1, playing=True) is None
    # A paused or busy seek cannot acknowledge an optimistic local position.
    assert loop.boundary_target(2.0, playing=False) is None
    assert loop.boundary_target(6.0, playing=True) is None
    assert loop.boundary_target(2.0, playing=True) is None
    assert loop.boundary_target(6.0, playing=True) == 2.0
    loop.manual_seek(10.0)
    assert loop.end == 6.0  # User seeks do not erase the marks.
    assert loop.boundary_target(6.0, playing=True) == 2.0
    loop.clear()
    assert loop.boundary_target(20.0, playing=True) is None
