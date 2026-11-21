"""Headless timer-policy and ownership regression checks for issue #443."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from idle_timers import active_deadline, timer_plan


@pytest.mark.parametrize("bad", [None, 0, -5, True, "bad", float("inf"), float("nan")])
def test_no_sleep_wakeup_for_invalid_deadline(bad):
    assert not active_deadline(bad)


def test_valid_deadline_is_recognised():
    assert active_deadline(123.0)
    assert active_deadline("125")


def test_simulated_minute_hidden_idle_has_at_most_one_callback_per_second():
    plan = timer_plan(
        mapped=False, playing=False, monitoring=False, foreground=False,
        has_sleep=False, fade_enabled=False, fade_active=False,
    )
    assert plan.seek_ms is None and plan.meter_ms is None
    assert plan.sleep_ms is None and plan.fade_ms is None
    # Two existing 15-second LAN probes and the ten-minute theme check remain.
    periods = [plan.poll_ms, plan.room_ms, 15_000, 15_000, 600_000]
    callback_count = sum(60_000 // ms for ms in periods)
    assert callback_count <= 60


def test_seek_and_meter_run_at_full_rate_only_when_mapped_and_playing():
    args = dict(foreground=True, has_sleep=False, fade_enabled=False, fade_active=False)
    visible = timer_plan(mapped=True, playing=True, monitoring=True, **args)
    assert (visible.seek_ms, visible.meter_ms, visible.poll_ms) == (500, 100, 4000)
    hidden = timer_plan(mapped=False, playing=True, monitoring=True, **args)
    assert hidden.seek_ms is None and hidden.meter_ms is None
    assert hidden.poll_ms == 4000
    paused = timer_plan(mapped=True, playing=False, monitoring=True, **args)
    assert paused.seek_ms is None and paused.meter_ms is None


def test_sleep_fader_restores_after_cancellation():
    args = dict(mapped=False, playing=False, monitoring=False, foreground=False)
    restore = timer_plan(has_sleep=False, fade_enabled=False, fade_active=True, **args)
    assert restore.sleep_ms is None and restore.fade_ms == 3000
    disabled = timer_plan(has_sleep=True, fade_enabled=False, fade_active=False, **args)
    assert disabled.sleep_ms == 5000 and disabled.fade_ms is None


def test_no_unconditional_visual_timers_and_close_cleans_sources():
    control = (Path(__file__).parents[1] / "src/cast_control.py").read_text()
    tree = ast.parse(control)
    methods = {method.name for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "MainWindow" for method in node.body
               if isinstance(method, ast.FunctionDef)}
    assert {"_sync_ui_timers", "_stop_ui_timers", "_bind_surface_resize"} <= methods
    assert "GLib.timeout_add(100, self._meter_tick)" not in control
    assert "GLib.timeout_add(500, self._tick)" not in control
    lifecycle = (Path(__file__).parents[1] / "src/cast_lifecycle.py").read_text()
    assert "self._stop_ui_timers()" in lifecycle
