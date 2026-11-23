"""Seekbar and volume spoken values without GTK (#449)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import slider_accessibility as sa  # noqa: E402


class _Gtk:
    class AccessibleProperty:
        VALUE_MIN = "min"
        VALUE_MAX = "max"
        VALUE_NOW = "now"
        VALUE_TEXT = "text"


class _Widget:
    def __init__(self):
        self.calls = []

    def update_property(self, names, values):
        assert len(names) == len(values)
        self.calls.append(dict(zip(names, values)))


@pytest.mark.parametrize(("position", "duration", "text"), [
    (3723, 7500, "1:02:03 of 2:05:00"),
    (5, 59, "0:05 of 0:59"),
    (0, 3600, "0:00 of 1:00:00"),
    (9999, 60, "1:00 of 1:00"),        # position beyond the end is clamped
    (-5, 60, "0:00 of 1:00"),          # negative clamps to the start
    (10, 0, "No media playing"),       # unknown length
    (None, None, "No media playing"),
    (10, math.nan, "No media playing"),
    (math.inf, 60, "0:00 of 1:00"),    # non-finite position is not spoken
])
def test_position_text(position, duration, text):
    assert sa.position_text(position, duration) == text


def test_seekbar_publishes_range_value_and_text():
    bar = _Widget()
    sa.sync_position(bar, _Gtk, 3723.4, 7500.0)
    assert bar.calls == [{"min": 0.0, "max": 7500.0, "now": 3723.4,
                          "text": "1:02:03 of 2:05:00"}]


def test_seekbar_unchanged_text_is_not_republished():
    bar = _Widget()
    sa.sync_position(bar, _Gtk, 10.2, 100.0)
    sa.sync_position(bar, _Gtk, 10.7, 100.0)   # same spoken second
    assert len(bar.calls) == 1
    sa.sync_position(bar, _Gtk, 11.0, 100.0)
    assert len(bar.calls) == 2


def test_seekbar_reset_after_stop_is_published():
    bar = _Widget()
    sa.sync_position(bar, _Gtk, 30.0, 100.0)
    sa.sync_position(bar, _Gtk, 0.0, 0.0)
    assert bar.calls[-1] == {"min": 0.0, "max": 0.0, "now": 0.0,
                             "text": "No media playing"}


def test_volume_text_and_clamp():
    scale = _Widget()
    sa.sync_percent(scale, _Gtk, 50)
    sa.sync_percent(scale, _Gtk, 50.0)          # duplicate: no call
    sa.sync_percent(scale, _Gtk, 140)
    sa.sync_percent(scale, _Gtk, -3)
    assert [c["text"] for c in scale.calls] == [
        "50 percent", "100 percent", "0 percent"]
    assert all(set(c) == {"text"} for c in scale.calls)  # GTK owns the range


def test_widgets_are_wired_to_the_helpers():
    widgets = (ROOT / "src/cast_widgets.py").read_text()
    assert "accessible_role=Gtk.AccessibleRole.SLIDER" in widgets
    assert '["Playback position"]' in widgets
    assert "slider_accessibility.sync_position(self, Gtk, self.position" in widgets
    assert "slider_accessibility.sync_percent(scale, Gtk, value)" in (
        ROOT / "src/cast_av.py").read_text()
    assert "slider_accessibility.sync_percent(self.volume_scale, Gtk, 50)" in (
        ROOT / "src/cast_ui.py").read_text()
