"""Idle-aware UI timers and resize reflow for the main window (#443)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib

import idle_timers
import sleep_fade
import stream_watchdog


class UiTimerMixin:
    def _start_window_timers(self) -> None:
        self._timers_enabled = True
        self._refresh_portal()
        GLib.timeout_add_seconds(15, self._refresh_portal)
        GLib.timeout_add_seconds(15, self._refresh_network_activity)
        self._sync_ui_timers()
        GLib.timeout_add(900, lambda: (self._poll_device(), False)[1])
        GLib.timeout_add(400, self._initial_scan)
        GLib.timeout_add(600, self._adopt_session)
        GLib.timeout_add_seconds(600, self._theme_tick)

    def _bind_surface_resize(self, *_args) -> None:
        """Listen to real GdkSurface allocations, not a periodic size poll."""
        surface = self.get_surface()
        if surface is not None:
            surface.connect("notify::width", self._queue_reflow)
            surface.connect("notify::height", self._queue_reflow)
            self._queue_reflow()

    def _queue_reflow(self, *_args) -> None:
        if not self._closing and self._reflow_source is None:
            self._reflow_source = GLib.idle_add(self._flush_reflow)

    def _flush_reflow(self) -> bool:
        self._reflow_source = None
        if not self._closing:
            self._refresh_responsive_layout()
        return False

    def _on_mapping_change(self, *_args) -> None:
        if not self._timers_enabled or self._closing:
            return
        if self.get_mapped():
            self._queue_reflow()
        self._sync_ui_timers()
        self._sync_portal_activity_timer()

    def _ui_playing(self) -> bool:
        stream = self._local_stream()
        if stream is not None and stream.get_playing():
            return True
        return (
            bool(self.session is not None or self.external or self._url_cast_url)
            and (self.device_state in {"PLAYING", "BUFFERING"} or self._cast_starting)
        )

    def _set_ui_timer(self, name: str, interval: int | None, callback) -> None:
        previous = self._timer_ids.get(name)
        if self._timer_periods.get(name) == interval and (
            interval is None or previous is not None
        ):
            return
        if previous is not None:
            GLib.source_remove(previous)
            self._timer_ids.pop(name, None)
        self._timer_periods[name] = interval
        if interval is not None:
            self._timer_ids[name] = GLib.timeout_add(interval, callback)

    def _sync_ui_timers(self) -> None:
        if not getattr(self, "_timers_enabled", False) or self._closing:
            return
        sleep_armed = idle_timers.active_deadline(self.cfg.get("sleep_timer_deadline"))
        schedule = idle_timers.timer_plan(
            mapped=bool(self.get_mapped()), playing=self._ui_playing(),
            monitoring=self.monitor is not None, foreground=bool(self.is_active()),
            has_sleep=sleep_armed,
            fade_enabled=bool(sleep_fade.valid_seconds(self.cfg.get("sleep_fade_seconds"))),
            fade_active=self._sleep_fader.phase is not None,
            transcoding=bool(self.session and getattr(self.session, "mode", None) == "transcode"
                             and getattr(self.session, "state", None)),
        )
        wake_seek = schedule.seek_ms is not None and "seek" not in self._timer_ids
        self._set_ui_timer("seek", schedule.seek_ms, self._tick)
        self._set_ui_timer("meter", schedule.meter_ms, self._meter_tick)
        self._set_ui_timer("poll", schedule.poll_ms, self._poll_device)
        app = getattr(self, "app", None)
        if getattr(app, "_mpris", None) is not None:
            self._set_ui_timer("mpris", schedule.mpris_ms, app._mpris_tick)
        self._set_ui_timer("sleep", schedule.sleep_ms, self._scheduled_sleep_tick)
        self._set_ui_timer("fade", schedule.fade_ms, self._scheduled_fade_tick)
        self._set_ui_timer("watchdog", schedule.watchdog_ms, self._hidden_watchdog_tick)
        if wake_seek:
            self._seek_idle_source = GLib.idle_add(self._resume_seek_tick)
        elif schedule.seek_ms is None:
            self._cancel_seek_resume()

    def _resume_seek_tick(self) -> bool:
        self._seek_idle_source = None
        self._tick()
        return False

    def _cancel_seek_resume(self) -> None:
        if self._seek_idle_source is not None:
            GLib.source_remove(self._seek_idle_source)
            self._seek_idle_source = None

    def _hidden_watchdog_tick(self) -> bool:
        """Preserve HLS stall recovery while seekbar/meter updates are hidden."""
        session = self.session
        if (session is not None and getattr(session, "mode", None) == "transcode"
                and getattr(session, "state", None) is not None):
            stream_watchdog.recover_window(self, session.progress(), self.tracker.value())
        return True

    def _scheduled_sleep_tick(self) -> bool:
        self._sleep_tick()
        if idle_timers.active_deadline(self.cfg.get("sleep_timer_deadline")):
            return True
        self._timer_ids.pop("sleep", None)
        self._timer_periods["sleep"] = None
        return False

    def _scheduled_fade_tick(self) -> bool:
        self._sleep_fade_tick()
        armed = idle_timers.active_deadline(self.cfg.get("sleep_timer_deadline"))
        fade = bool(sleep_fade.valid_seconds(self.cfg.get("sleep_fade_seconds")))
        if (armed and fade) or self._sleep_fader.phase is not None:
            return True
        self._timer_ids.pop("fade", None)
        self._timer_periods["fade"] = None
        return False

    def _stop_ui_timers(self) -> None:
        self._timers_enabled = False
        for source in self._timer_ids.values():
            GLib.source_remove(source)
        self._timer_ids.clear()
        self._timer_periods.clear()
        self._cancel_seek_resume()
        if self._reflow_source is not None:
            GLib.source_remove(self._reflow_source)
            self._reflow_source = None
