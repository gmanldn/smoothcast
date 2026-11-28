"""Idle-aware UI timers and resize reflow for the main window (#443)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib

import time

import castctl
import idle_timers
import playback_state
import portal_status
import sleep_fade
import stream_watchdog
import streamer
from cast_widgets import Async, save_config


class UiTimerController:
    """Composition replacement for UiTimerMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _start_window_timers(self) -> None:
        w = self.w
        w._timers_enabled = True
        if getattr(w, "_core_status", None) is None:
            w._core_status = portal_status.PublishedStatus()
        # The first FFmpeg version query can take seconds; pay it before the first cast.
        Async.run(streamer.require_compatible_ffmpeg, failed=lambda _message: None)
        w._refresh_portal()
        GLib.timeout_add_seconds(15, w._refresh_portal)
        GLib.timeout_add_seconds(15, w._refresh_network_activity)
        GLib.timeout_add_seconds(1, w._mesh_heartbeat_tick)
        GLib.timeout_add_seconds(2, w._publish_core_status)
        w._sync_ui_timers()
        GLib.timeout_add(900, lambda: (w._poll_device(), False)[1])
        GLib.timeout_add(400, w._initial_scan)
        GLib.timeout_add(600, w._adopt_session)
        GLib.timeout_add_seconds(600, w._theme_tick)

    def _publish_core_status(self) -> bool:
        """Publish a bounded cast summary for the always-on sc-core coordinator.

        Reads only GTK-owned state on the GTK thread and publishes a detached
        copy, so the coordinator thread never touches a widget (never raises).
        """
        w = self.w
        if w._closing:
            return False
        snapshot = getattr(w, "_core_status", None)
        if snapshot is None:
            return True
        try:
            session = w.session
            snapshot.publish({
                "active": bool(session is not None or w.external
                               or getattr(w, "_url_cast_url", None)),
                "state": str(w.device_state or ""),
                "mode": str(getattr(session, "mode", "") or ""),
                "target": str(w._device() or ""),
            })
        except Exception:  # noqa: BLE001 - a timer tick must never raise into GLib
            pass
        return True

    def _mesh_heartbeat_tick(self) -> bool:
        """Refresh the Info-tab heartbeat at ~1 Hz only while it is visible."""
        w = self.w
        if w._closing:
            return False
        try:
            stack = getattr(w, "panel_stack", None)
            if (w.get_mapped() and stack is not None
                    and stack.get_visible_child_name() == "info"):
                w._refresh_mesh_heartbeat()
        except Exception:  # noqa: BLE001 - a timer tick must never raise into GLib
            pass
        return True

    def _bind_surface_resize(self, *_args) -> None:
        """Listen to real GdkSurface allocations, not a periodic size poll."""
        w = self.w
        surface = w.get_surface()
        if surface is not None:
            surface.connect("notify::width", w._queue_reflow)
            surface.connect("notify::height", w._queue_reflow)
            w._queue_reflow()

    def _queue_reflow(self, *_args) -> None:
        w = self.w
        if not w._closing and w._reflow_source is None:
            w._reflow_source = GLib.idle_add(w._flush_reflow)

    def _flush_reflow(self) -> bool:
        w = self.w
        w._reflow_source = None
        if not w._closing:
            w._refresh_responsive_layout()
        return False

    def _on_mapping_change(self, *_args) -> None:
        w = self.w
        if not w._timers_enabled or w._closing:
            return
        if w.get_mapped():
            w._queue_reflow()
        w._sync_ui_timers()
        w._sync_portal_activity_timer()

    def _ui_playing(self) -> bool:
        w = self.w
        stream = w._local_stream()
        if stream is not None and stream.get_playing():
            return True
        return (
            bool(w.session is not None or w.external or w._url_cast_url)
            and (w.device_state in {"PLAYING", "BUFFERING"} or w._cast_starting)
        )

    def _set_ui_timer(self, name: str, interval: int | None, callback) -> None:
        w = self.w
        previous = w._timer_ids.get(name)
        if w._timer_periods.get(name) == interval and (
            interval is None or previous is not None
        ):
            return
        if previous is not None:
            GLib.source_remove(previous)
            w._timer_ids.pop(name, None)
        w._timer_periods[name] = interval
        if interval is not None:
            w._timer_ids[name] = GLib.timeout_add(interval, callback)

    def _sync_ui_timers(self) -> None:
        w = self.w
        if not getattr(w, "_timers_enabled", False) or w._closing:
            return
        sleep_armed = idle_timers.active_deadline(w.cfg.get("sleep_timer_deadline"))
        schedule = idle_timers.timer_plan(
            mapped=bool(w.get_mapped()), playing=w._ui_playing(),
            monitoring=w.monitor is not None, foreground=bool(w.is_active()),
            has_sleep=sleep_armed,
            fade_enabled=bool(sleep_fade.valid_seconds(w.cfg.get("sleep_fade_seconds"))),
            fade_active=w._sleep_fader.phase is not None,
            transcoding=bool(w.session and getattr(w.session, "mode", None) == "transcode"
                             and getattr(w.session, "state", None)),
        )
        wake_seek = schedule.seek_ms is not None and "seek" not in w._timer_ids
        w._set_ui_timer("seek", schedule.seek_ms, w._tick)
        w._set_ui_timer("meter", schedule.meter_ms, w._meter_tick)
        w._set_ui_timer("poll", schedule.poll_ms, w._poll_device)
        app = getattr(w, "app", None)
        if getattr(app, "_mpris", None) is not None:
            w._set_ui_timer("mpris", schedule.mpris_ms, app._mpris_tick)
        w._set_ui_timer("sleep", schedule.sleep_ms, w._scheduled_sleep_tick)
        w._set_ui_timer("fade", schedule.fade_ms, w._scheduled_fade_tick)
        w._set_ui_timer("watchdog", schedule.watchdog_ms, w._hidden_watchdog_tick)
        if wake_seek:
            w._seek_idle_source = GLib.idle_add(w._resume_seek_tick)
        elif schedule.seek_ms is None:
            w._cancel_seek_resume()

    def _resume_seek_tick(self) -> bool:
        w = self.w
        w._seek_idle_source = None
        w._tick()
        return False

    def _cancel_seek_resume(self) -> None:
        w = self.w
        if w._seek_idle_source is not None:
            GLib.source_remove(w._seek_idle_source)
            w._seek_idle_source = None

    def _hidden_watchdog_tick(self) -> bool:
        """Preserve HLS stall recovery while seekbar/meter updates are hidden."""
        w = self.w
        session = w.session
        if (session is not None and getattr(session, "mode", None) == "transcode"
                and getattr(session, "state", None) is not None):
            stream_watchdog.recover_window(w, session.progress(), w.tracker.value())
        return True

    def _scheduled_sleep_tick(self) -> bool:
        w = self.w
        w._sleep_tick()
        if idle_timers.active_deadline(w.cfg.get("sleep_timer_deadline")):
            return True
        w._timer_ids.pop("sleep", None)
        w._timer_periods["sleep"] = None
        return False

    def _scheduled_fade_tick(self) -> bool:
        w = self.w
        w._sleep_fade_tick()
        armed = idle_timers.active_deadline(w.cfg.get("sleep_timer_deadline"))
        fade = bool(sleep_fade.valid_seconds(w.cfg.get("sleep_fade_seconds")))
        if (armed and fade) or w._sleep_fader.phase is not None:
            return True
        w._timer_ids.pop("fade", None)
        w._timer_periods["fade"] = None
        return False

    def _stop_ui_timers(self) -> None:
        w = self.w
        w._timers_enabled = False
        for source in w._timer_ids.values():
            GLib.source_remove(source)
        w._timer_ids.clear()
        w._timer_periods.clear()
        w._cancel_seek_resume()
        if w._reflow_source is not None:
            GLib.source_remove(w._reflow_source)
            w._reflow_source = None

    def _sleep_timer(self, minutes: int) -> None:
        w = self.w
        minutes = max(0, int(minutes))
        w.cfg["sleep_timer_minutes"] = minutes
        w.cfg["sleep_timer_deadline"] = playback_state.sleep_deadline(
            time.time(), minutes,
        )
        save_config(w.cfg)
        w.toast(
            f"Sleep timer armed: {minutes} min" if minutes
            else "Sleep timer cancelled"
        )
        w._sync_ui_timers()

    def _sleep_tick(self) -> bool:
        w = self.w
        deadline = w.cfg.get("sleep_timer_deadline", 0.0)
        if not playback_state.timer_expired(deadline, time.time()):
            return True
        if w.busy:
            return True  # Do not interrupt an in-flight cast command.
        w.cfg["sleep_timer_deadline"] = 0.0
        w.cfg["sleep_timer_minutes"] = 0
        save_config(w.cfg)
        if w.session is not None:
            w.toast("Sleep timer expired — stopping cast")
            w.stop_stream()
        elif w._url_cast_url is not None:
            w._sleep_stop_url_cast()
        else:
            w.toast("Sleep timer expired")
        return True

    def _sleep_stop_url_cast(self) -> None:
        """Stop our own URL cast at the deadline, never a replacement.

        A URL cast has no local Session. Re-check the receiver off the GTK
        thread at command time and stop only if it still reports the exact URL
        we sent; if another app replaced it, leave that content playing.
        """
        w = self.w
        device = w._device()
        saved_url = w._url_cast_url or ""
        w.busy = True
        w._refresh_controls()

        def work():
            try:
                observed = castctl.info(device)
            except (OSError, ValueError, TypeError):
                observed = None
            if not playback_state.url_cast_matches(observed, saved_url):
                return False
            ok, _ = castctl.stop(device)
            return ok

        def done(stopped):
            w.busy = False
            w._url_cast_url = None
            w._url_cast_seen = False
            if stopped:
                w.external = False
                w.tracker.clear()
                w.now_playing = None
                w._finished_handled = False
                w.toast("Sleep timer expired — stopped the URL cast")
            else:
                w.toast("Sleep timer expired; left the current TV content playing")
            w._refresh_controls()
            w._poll_device()

        Async.run(work, done=done, failed=w._cast_failed, domain="transport")
