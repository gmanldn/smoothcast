"""Headless regression tests for the bounded buffer-health history (#133)."""
from pathlib import Path

import buffer_health

ROOT = Path(__file__).resolve().parents[1]


def test_samples_are_bounded_and_sanitised():
    history = buffer_health.BufferHealth(limit=3)
    history.sample(12.5, 4)
    history.sample(float("nan"), -2)
    history.sample(float("inf"), "not-a-number")
    history.sample(-7.25, 2, stalled=True)

    assert len(history.samples) == 3
    assert history.samples[0] == (None, 0, False)
    assert history.samples[1] == (None, 0, False)
    assert history.samples[2] == (-7.25, 2, True)


def test_ahead_values_are_finite_and_bounded():
    history = buffer_health.BufferHealth(limit=4)
    history.sample(-10_000, 1)
    history.sample(10_000, 1)
    history.sample("6.5", 1)
    history.sample(None, 1)

    assert history.ahead_series() == (
        -buffer_health.MAX_AHEAD_SECONDS,
        buffer_health.MAX_AHEAD_SECONDS,
        6.5,
        None,
    )


def test_clear_starts_a_new_session():
    history = buffer_health.BufferHealth()
    history.sample(1.0, 2, stalled=True)
    assert history.active
    assert history.stall_count == 1

    history.clear()

    assert not history.active
    assert history.samples == ()
    assert history.stall_count == 0
    assert history.latest() is None


def test_summary_and_series_match_the_measurements():
    history = buffer_health.BufferHealth()
    history.sample(9.0, 3)
    history.sample(-4.5, 1, stalled=True)

    assert history.segment_series() == (3, 1)
    assert history.stall_positions() == (1,)
    assert "4.5 s behind" in history.summary()
    assert "1 HLS segment available" in history.summary()
    assert "1 watchdog restart" in history.summary()


def test_summary_before_any_sample():
    history = buffer_health.BufferHealth()
    assert "No measured HLS buffer history" in history.summary()


def test_limit_must_be_positive():
    for limit in (0, -1, True, 1.5, "3"):
        try:
            buffer_health.BufferHealth(limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError(f"limit {limit!r} should be rejected")


def test_graph_is_wired_into_the_diagnostics_card():
    widgets = (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")

    assert "class BufferHealthGraph(Gtk.DrawingArea)" in widgets
    assert "SeekBar._rounded(cr, 0, 0, width, height, 8)" in widgets
    assert "self._buffer_health = buffer_health.BufferHealth()" in ui
    assert "self.buffer_graph = BufferHealthGraph()" in ui
    assert "self._buffer_health.sample(ahead, seg_count, stalled=stalled)" in ui
    assert "self.buffer_graph.set_health(self._buffer_health)" in ui
