#!/usr/bin/env python3
"""Window lifecycle, actions and screenshots."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pathlib

import threading
import diagnostics
import reliability_metrics


import playback_state

import screenshot


from cast_lifecycle_actions import LifecycleActionsController
from cast_widgets import save_config, flush_config, fmt_time, Async


class LifecycleController(LifecycleActionsController):
    """Composition replacement for LifecycleMixin (#691); all state stays on the window."""

    def _cast_preflight_failed(self, message: str) -> None:
        """A rejected new cast must not tear down its still-owned predecessor."""
        w = self.w
        w._cast_feedback = {"receiver": w._device(), "state": "failed", "message": message}
        reliability_metrics.fail_attempt(w, Async.run)
        w._dlna_cancel = None
        prior = w.session
        if (prior is not None and prior.active()
                and getattr(prior.state, "device", None) == w._device()):
            w.busy = False
            w.toast(f"Cast not started: {message}", error=True)
            w._console(f"Cast preparation failed: {message}")
            w._refresh_controls()
            return
        w._cast_failed(message)


    def _stop_sc_core(self) -> None:
        """Stop the always-on house coordinator before the mesh is torn down."""
        w = self.w
        import sc_core
        sc_core.stop(w)

    def _on_close(self, _window) -> bool:
        w = self.w
        w._closing = True
        plan = w._shutdown_plan()            # ordered steps, per-step deadlines, 1 s budget (#465)
        plan.run("ui_timers", w._stop_ui_timers)
        plan.run("metrics", lambda: reliability_metrics.finish_active(w, "interrupted", Async.run))
        plan.run("background_work", lambda: (
            getattr(w, "_cancel_music_import", lambda: None)(), w._cancel_queue_prewarm()))
        plan.run("join_slate", getattr(w, "_join_slate_clear_now", bool), deadline=0.4, threaded=True)
        plan.run("sc_core", w._stop_sc_core, deadline=0.4, threaded=True)
        plan.run("portal", w._stop_portal)
        plan.run("house_services", w._stop_house_services, deadline=0.4, threaded=True)

        def receiver_watch() -> None:
            watch = getattr(w, "_cast_status_watch", None)
            if watch is not None:
                watch.close()
            if w._dlna_cancel is not None:
                w._dlna_cancel.set()
        plan.run("receiver_watch", receiver_watch)
        if w._cast_starting:
            # Closing a GtkApplication while Async.run's daemon worker is
            # still running can terminate that worker before GLib.idle_add
            # delivers cleanup. Hide the window, but keep its application
            # main loop alive until the cast callback finishes. This never
            # opens or raises a GUI window during tests.
            if not w._closing_hold:
                app = w.get_application()
                if app is not None:
                    app.hold()
                    w._closing_hold = True
                w.set_visible(False)
            return True
        plan.run("media", lambda: (w._stop_monitor(), w._unload_local_video()))

        def save_settings() -> None:
            # Save the last *actual* normal allocation, not GTK's default size.
            # Fullscreen/maximised allocations are never persisted as preferences.
            w._remember_normal_geometry()
            width, height = w._last_normal_size
            if width > 0 and height > 0:
                w.cfg["window_width"] = width
                w.cfg["window_height"] = height
            save_config(w.cfg)
            flush_config()
        plan.run("settings", save_settings)
        # DLNA's local HTTP server is process-owned; unlike Chromecast's HLS
        # keep-streaming path it cannot survive closing this application.
        if w.session is not None and (
                not w.cfg["keep_streaming"] or w.session.mode == "dlna"):
            session, w.session = w.session, None
            device = w._device()
            thread = threading.Thread(target=lambda: session.stop(device), daemon=False)
            thread.start()
        w._finish_shutdown()
        return False


    def _finish_delayed_close(self) -> None:
        """Close only after the cast worker reports success/failure to GTK."""
        w = self.w
        if not w._closing_hold:
            return
        app = w.get_application()
        try:
            w.close()
        finally:
            w._closing_hold = False
            if app is not None:
                app.release()


    def _on_hover(self, hovering: bool, value: float) -> None:
        w = self.w
        previewing = w.session is None and not w.external and w._preview_path is not None
        duration = w.tracker.duration or (w.media.duration if w.media else 0.0)
        if previewing and not duration:
            duration = w.queue_durations.get(w._preview_path, 0.0)
        if hovering:
            w._refresh_thumbnail_strip(value, visible=previewing)
            w.elapsed_label.set_text(fmt_time(value))
            if duration:
                w.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - value))}")
            if previewing:
                w._timed_subtitle_preview(value)
            if previewing and w._local_stream() is None:
                if w.seekbar.scrubbing:
                    target = min(value, max(0.0, duration - 1.0)) if duration else value
                    # Instant: the nearest decoded frame; then a keyframe-fast
                    # decode at the playhead. The exact frame follows on release.
                    w._show_nearest_preview(target)
                    w._queue_preview(target, fast=True)
                else:
                    w._queue_preview(value, sparse=True)
        else:
            if previewing:
                w._timed_subtitle_preview(None)
            position = w._preview_position if previewing else w.tracker.value()
            if position is not None:
                w.elapsed_label.set_text(fmt_time(position))
                if duration:
                    w.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - position))}")


    def _flush_stale_state(self) -> None:
        """Clear any leftover state from a previous run so the UI starts clean.

        Ensures that sessions, meters, preview, tracker, and all UI labels are
        reset to a fresh 'nothing playing' state. Changes made in the last run
        (or leftover state from a crash) never persist into this launch.
        """
        w = self.w
        # Stop any lingering audio analysis from a previous instance.
        if w.monitor is not None:
            try:
                w.monitor.stop()
            except Exception:  # noqa: BLE001 - best-effort monitor stop
                pass
            w.monitor = None

        # Clear session/media state.
        w.session = None
        w.media = None
        w.device_info = None
        w.now_playing = None
        w.selected_index = None
        w.external = False
        w.busy = False
        w._dlna_cancel = None
        w.poll_busy = False
        w.scan_busy = False
        w._scan_again = False
        w.queue = []
        w.queue_durations = {}
        w._preview_generation += 1
        w._preview_path = None
        w._preview_position = 0.0
        w._preview_pending = None
        w._refresh_thumbnail_strip(0.0, visible=False)
        w._unload_local_video()
        w.preview_picture.set_visible(False)

        # Reset tracker and position state.
        w.tracker.clear()
        w._finished_handled = False
        w._last_state = "IDLE"

        # Reset UI widgets to clean defaults.
        if w.np_title is not None:
            w.np_title.set_text("Ready to cast")
        if w.np_meta is not None:
            w.np_meta.set_text("Open a video and send it to your TV")
        if w.state_chip is not None:
            w.state_chip.set_text("Ready")
            w.state_chip.remove_css_class("playing")
            w.state_chip.remove_css_class("buffering")
            w.state_chip.remove_css_class("paused")
            w.state_chip.remove_css_class("offline")
            w.state_chip.remove_css_class("error")
            w.state_chip.add_css_class("idle")
        if w.preview is not None:
            w.preview.set_video("No video", "")
        if w.seekbar is not None:
            w.seekbar.set_state(0.0, 0.0, 0.0)
        if w.elapsed_label is not None:
            w.elapsed_label.set_text("0:00:00")
        if w.remaining_label is not None:
            w.remaining_label.set_text("--:--")

        # Reset level meters.
        if w.meter is not None:
            w.meter.reset()

        # Reset details card labels.
        if hasattr(w, "detail_labels"):
            for key, label in w.detail_labels.items():
                label.set_text("—")

        # Clear levels hint.
        if hasattr(w, "levels_hint") and w.levels_hint is not None:
            w.levels_hint.set_text("")

        # Clear any queued timer-based pending state.
        w._volume_job = None
        w._volume_target = None
        w._volume_user_ts = 0.0
        w._syncing = False
        w._subs_cache = ("", None)
        w._hover_time = None


    def _screenshot(self) -> None:
        w = self.w
        media = w.media
        if media is None:
            w.toast("No media loaded", error=True)
            return
        source = pathlib.Path(media.path)
        try:
            position = screenshot.owned_frame_time(
                source, session=w.session, external=w.external,
                tracker=w.tracker, local_video_path=w._local_video_path,
                local_stream=w._local_stream if w._local_video_path else None,
                preview_path=w._preview_path,
                preview_position=w._preview_position,
            )
        except screenshot.FramePositionError as exc:
            w.toast(exc.message, error=True)
            return
        output_dir = pathlib.Path(
            w.cfg.get("screenshot_dir") or pathlib.Path.home() / "Pictures"
        ).expanduser()
        w.toast("Capturing screenshot…")
        video_index = media.video_stream_index
        Async.run(
            lambda: screenshot.capture_frame(
                source, position, output_dir, video_stream_index=video_index,
            ),
            done=lambda out: w.toast(f"Screenshot saved: {out.name}"),
            failed=lambda _message: w.toast(
                "Could not save the screenshot. Check the file and screenshot folder, then try again.",
                error=True,
            ),
        )


    def _toggle_loop_all(self) -> None:
        """Loop the whole queue (wrap last -> first); independent of repeat-one."""
        w = self.w
        w.cfg["loop_all"] = not bool(w.cfg.get("loop_all", False))
        save_config(w.cfg)
        w.toast("Loop all on" if w.cfg["loop_all"] else "Loop all off")


    def _shuffle_queue(self) -> None:
        """Deterministically permute the queue so display and skip stay in sync."""
        w = self.w
        if len(w.queue) < 2:
            w.toast("Nothing to shuffle")
            return
        seed = int(w.cfg.get("shuffle_seed", 1)) % 9999 + 1
        w.cfg["shuffle_seed"] = seed
        save_config(w.cfg)
        w.queue = playback_state.shuffle_order(w.queue, seed)
        w._rebuild_queue()
        w.toast("Queue shuffled")


    def _theme_tick(self) -> bool:
        """Re-evaluate the time-based theme so it switches at the day boundary."""
        w = self.w
        w._apply_color_scheme()
        return True


    def _frame_step(self, direction: int) -> None:
        """Step one source frame (1 s fallback) using the media frame rate."""
        w = self.w
        fps = w.media.fps if w.media and w.media.fps else 0.0
        w._skip(direction * playback_state.frame_step_delta(fps))
    def action_save_diagnostics(self) -> None:
        """Write a bounded, redacted support bundle off the GTK thread."""
        w = self.w
        w.toast("Collecting diagnostics…")
        activity = list(w.console_lines)
        config = dict(w.cfg)
        receiver = diagnostics.receiver_report(w._dlna_renderer(), next(
            (d for d in w.devices if d.name == w.cfg["device"]), None))
        # Collecting tool versions and reading the log may touch the disk;
        # never block the GTK event loop.
        Async.run(
            lambda: diagnostics.export(activity=activity, config=config, receiver=receiver),
            done=lambda path: w.toast(f"Diagnostics saved: {path.name}"),
            failed=lambda message: w.toast(
                f"Diagnostics failed: {message}", error=True,
            ),
        )

    @classmethod
    def install(cls, window) -> "LifecycleController":
        """Bind every lifecycle/action method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in LIFECYCLE_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


LIFECYCLE_METHODS = ('action_open', 'action_add_files', 'action_stop', 'action_shortcuts', 'action_custom_speed', 'action_about', 'perform_action', '_cast_preflight_failed', '_stop_sc_core', '_on_close', '_finish_delayed_close', '_on_hover', '_flush_stale_state', '_screenshot', '_toggle_loop_all', '_shuffle_queue', '_theme_tick', '_frame_step', 'action_save_diagnostics')
