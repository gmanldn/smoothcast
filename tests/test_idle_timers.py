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
    assert hidden.watchdog_ms is None
    hidden_transcode = timer_plan(
        mapped=False, playing=True, monitoring=True, transcoding=True, **args)
    assert hidden_transcode.watchdog_ms == 1000
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


def test_real_window_timer_callbacks_under_fake_glib_clock():
    """Execute the actual GUI timer methods, with no GTK, LAN or threads."""
    from types import SimpleNamespace
    import textwrap
    import idle_timers
    import sleep_fade
    from gui_source import main_window_methods

    class Clock:
        def __init__(self):
            self.ms = 0
            self.next_id = 0
            self.jobs = {}

        def timeout_add(self, interval, callback):
            self.next_id += 1
            self.jobs[self.next_id] = (interval, self.ms + interval, callback)
            return self.next_id

        def source_remove(self, source):
            self.jobs.pop(source, None)
            return True

        def idle_add(self, callback):
            callback()
            return 0

        def run(self, milliseconds):
            end = self.ms + milliseconds
            count = 0
            while True:
                upcoming = [
                    (next_time, token) for token, (_delay, next_time, _fn)
                    in self.jobs.items() if next_time <= end
                ]
                if not upcoming:
                    break
                next_time, token = min(upcoming)
                self.ms = next_time
                delay, _next, callback = self.jobs[token]
                keep = callback()
                count += 1
                if token in self.jobs:
                    if keep:
                        self.jobs[token] = (delay, self.ms + delay, callback)
                    else:
                        self.jobs.pop(token)
            self.ms = end
            return count

    names = ("_set_ui_timer", "_sync_ui_timers", "_ui_playing",
             "_scheduled_sleep_tick", "_scheduled_fade_tick", "_stop_ui_timers")
    sources = main_window_methods()
    code = "class Window:\n" + "\n".join(
        textwrap.indent(textwrap.dedent(sources[name]), "    ") + "\n"
        for name in names
    )
    clock = Clock()
    namespace = {"GLib": clock, "idle_timers": idle_timers, "sleep_fade": sleep_fade}
    exec(compile(code, "<headless-timers>", "exec"), namespace)  # noqa: S102
    window = namespace["Window"]()
    window._timers_enabled = True
    window._closing = False
    window._timer_ids = {}
    window._timer_periods = {}
    window._reflow_source = None
    window.cfg = {"sleep_timer_deadline": 0, "sleep_fade_seconds": 30}
    window._sleep_fader = SimpleNamespace(phase=None)
    window.monitor = None
    window.session = None
    window.external = False
    window._url_cast_url = None
    window._cast_starting = False
    window.device_state = "IDLE"
    window._local_stream = lambda: None
    mapped = [False]
    focused = [False]
    window.get_mapped = lambda: mapped[0]
    window.is_active = lambda: focused[0]
    counts = {"seek": 0, "meter": 0, "poll": 0}

    def count(name):
        def callback():
            counts[name] += 1
            return True
        return callback

    window._tick = count("seek")
    window._meter_tick = count("meter")
    window._poll_device = count("poll")
    window._sleep_tick = lambda: True
    window._sleep_fade_tick = lambda: True
    window._sync_ui_timers()
    assert clock.run(60_000) == 2
    assert counts == {"seek": 0, "meter": 0, "poll": 2}

    mapped[0] = True
    focused[0] = True
    window.session = object()
    window.device_state = "PLAYING"
    window.monitor = object()
    window._sync_ui_timers()
    clock.run(2_000)
    assert counts["seek"] >= 4 and counts["meter"] >= 20
    old = counts.copy()

    mapped[0] = False
    window._sync_ui_timers()
    clock.run(2_000)
    assert counts["seek"] == old["seek"] and counts["meter"] == old["meter"]
    window._stop_ui_timers()
    assert clock.jobs == {}
