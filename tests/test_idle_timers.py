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
    periods = [plan.poll_ms, plan.mpris_ms, plan.room_ms, 15_000, 15_000, 600_000]
    callback_count = sum(60_000 // ms for ms in periods)
    assert callback_count <= 60


def test_seek_and_meter_run_at_full_rate_only_when_mapped_and_playing():
    args = dict(foreground=True, has_sleep=False, fade_enabled=False, fade_active=False)
    visible = timer_plan(mapped=True, playing=True, monitoring=True, **args)
    assert (visible.seek_ms, visible.meter_ms, visible.poll_ms, visible.mpris_ms) == (500, 100, 4000, 1000)
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
    src = Path(__file__).parents[1] / "src"
    control = (src / "cast_control.py").read_text()
    timers = (src / "cast_ui_timers.py").read_text()
    methods = {method.name for node in ast.parse(timers).body if isinstance(node, ast.ClassDef)
               and node.name == "UiTimerController" for method in node.body
               if isinstance(method, ast.FunctionDef)}
    assert {"_sync_ui_timers", "_stop_ui_timers", "_bind_surface_resize"} <= methods
    assert "UiTimerController" in control
    assert "GLib.timeout_add_seconds(1, self._mpris_tick)" not in control
    for text in (control, timers):
        assert "GLib.timeout_add(100, self._meter_tick)" not in text
        assert "GLib.timeout_add(500, self._tick)" not in text
    lifecycle = (Path(__file__).parents[1] / "src/cast_lifecycle.py").read_text()
    assert 'plan.run("ui_timers", self._stop_ui_timers)' in lifecycle


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
            return self.timeout_add(0, callback)

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
             "_scheduled_sleep_tick", "_scheduled_fade_tick", "_stop_ui_timers",
             "_hidden_watchdog_tick", "_resume_seek_tick", "_cancel_seek_resume")
    sources = main_window_methods()
    code = "class Window:\n" + "\n".join(
        textwrap.indent(textwrap.dedent(sources[name]), "    ") + "\n"
        for name in names
    )
    clock = Clock()
    namespace = {"GLib": clock, "idle_timers": idle_timers, "sleep_fade": sleep_fade,
                 "stream_watchdog": __import__("stream_watchdog")}
    exec(compile(code, "<headless-timers>", "exec"), namespace)  # noqa: S102
    window = namespace["Window"]()
    window.w = window
    import cast_portal_room
    window._sync_portal_activity_timer = cast_portal_room.PortalRoomController(
        window, glib=clock)._sync_portal_activity_timer
    window._timers_enabled = True
    window._closing = False
    window._timer_ids = {}
    window._timer_periods = {}
    window._reflow_source = None
    window._seek_idle_source = None
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
    counts = {"seek": 0, "meter": 0, "poll": 0, "mpris": 0, "room": 0}

    def count(name):
        def callback():
            counts[name] += 1
            return True
        return callback

    window._tick = count("seek")
    window._meter_tick = count("meter")
    window._poll_device = count("poll")
    window.app = SimpleNamespace(_mpris=object(), _mpris_tick=count("mpris"))
    window._portal = object()
    window._refresh_portal_activity = count("room")
    window._sleep_tick = lambda: True
    window._sleep_fade_tick = lambda: True
    window._sync_ui_timers()
    window._sync_portal_activity_timer()
    # Account for the app's periodic room-discovery, network and theme sources.
    for interval in (15_000, 15_000, 600_000):
        clock.timeout_add(interval, lambda: True)
    assert clock.run(60_000) == 16
    assert counts == {"seek": 0, "meter": 0, "poll": 2, "mpris": 2, "room": 4}

    mapped[0] = True
    focused[0] = True
    window.session = object()
    window.device_state = "PLAYING"
    window.monitor = object()
    window._sync_ui_timers()
    clock.run(2_000)
    assert counts["seek"] == 5 and counts["meter"] == 20
    assert counts["mpris"] == 4
    old = counts.copy()

    mapped[0] = False
    window._sync_ui_timers()
    clock.run(2_000)
    assert counts["seek"] == old["seek"] and counts["meter"] == old["meter"]
    # Mapping queues an immediate seek update. An unmap before idle dispatch cancels it.
    mapped[0] = True
    window._sync_ui_timers()
    assert window._seek_idle_source in clock.jobs
    mapped[0] = False
    window._sync_ui_timers()
    clock.run(0)
    assert counts["seek"] == old["seek"]

    mapped[0] = True
    window._sync_ui_timers()
    pending_seek = window._seek_idle_source
    assert pending_seek in clock.jobs
    window._stop_ui_timers()
    assert window._timer_ids == {}
    assert pending_seek not in clock.jobs
    assert window._seek_idle_source is None
