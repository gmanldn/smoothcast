#!/usr/bin/env python3
"""Window lifecycle, actions and screenshots."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk
import pathlib

import threading
import reliability_metrics
import shortcut_map

import diagnostics

import playback_state

import screenshot

import version

from cast_widgets import APP_NAME, ICON_NAME, save_config, flush_config, fmt_time, Async


class LifecycleMixin:
    def _cast_preflight_failed(self, message: str) -> None:
        """A rejected new cast must not tear down its still-owned predecessor."""
        reliability_metrics.fail_attempt(self, Async.run)
        self._dlna_cancel = None
        prior = self.session
        if (prior is not None and prior.active()
                and getattr(prior.state, "device", None) == self._device()):
            self.busy = False
            self.toast(f"Cast not started: {message}", error=True)
            self._console(f"Cast preparation failed: {message}")
            self._refresh_controls()
            return
        self._cast_failed(message)


    def _on_close(self, _window) -> bool:
        self._closing = True
        self._stop_ui_timers()
        reliability_metrics.finish_active(self, "interrupted", Async.run)
        getattr(self, "_cancel_music_import", lambda: None)()
        self._cancel_queue_prewarm()
        self._stop_portal()
        watch = getattr(self, "_cast_status_watch", None)
        if watch is not None:
            watch.close()
        if self._dlna_cancel is not None:
            self._dlna_cancel.set()
        if self._cast_starting:
            # Closing a GtkApplication while Async.run's daemon worker is
            # still running can terminate that worker before GLib.idle_add
            # delivers cleanup. Hide the window, but keep its application
            # main loop alive until the cast callback finishes. This never
            # opens or raises a GUI window during tests.
            if not self._closing_hold:
                app = self.get_application()
                if app is not None:
                    app.hold()
                    self._closing_hold = True
                self.set_visible(False)
            return True
        self._stop_monitor()
        self._unload_local_video()
        # Save the last *actual* normal allocation, not GTK's default size.
        # Fullscreen/maximised allocations are never persisted as preferences.
        self._remember_normal_geometry()
        width, height = self._last_normal_size
        if width > 0 and height > 0:
            self.cfg["window_width"] = width
            self.cfg["window_height"] = height
        save_config(self.cfg)
        flush_config()
        # DLNA's local HTTP server is process-owned; unlike Chromecast's HLS
        # keep-streaming path it cannot survive closing this application.
        if self.session is not None and (
                not self.cfg["keep_streaming"] or self.session.mode == "dlna"):
            session, self.session = self.session, None
            device = self._device()
            thread = threading.Thread(target=lambda: session.stop(device), daemon=False)
            thread.start()
        return False


    def _finish_delayed_close(self) -> None:
        """Close only after the cast worker reports success/failure to GTK."""
        if not self._closing_hold:
            return
        app = self.get_application()
        try:
            self.close()
        finally:
            self._closing_hold = False
            if app is not None:
                app.release()


    def _on_hover(self, hovering: bool, value: float) -> None:
        previewing = self.session is None and not self.external and self._preview_path is not None
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if previewing and not duration:
            duration = self.queue_durations.get(self._preview_path, 0.0)
        if hovering:
            self.elapsed_label.set_text(fmt_time(value))
            if duration:
                self.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - value))}")
            if previewing:
                self._timed_subtitle_preview(value)
            if previewing and self._local_stream() is None:
                self._queue_preview(value)
        else:
            if previewing:
                self._timed_subtitle_preview(None)
            position = self._preview_position if previewing else self.tracker.value()
            if position is not None:
                self.elapsed_label.set_text(fmt_time(position))
                if duration:
                    self.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - position))}")


    def _flush_stale_state(self) -> None:
        """Clear any leftover state from a previous run so the UI starts clean.

        Ensures that sessions, meters, preview, tracker, and all UI labels are
        reset to a fresh 'nothing playing' state. Changes made in the last run
        (or leftover state from a crash) never persist into this launch.
        """
        # Stop any lingering audio analysis from a previous instance.
        if self.monitor is not None:
            try:
                self.monitor.stop()
            except Exception:
                pass
            self.monitor = None

        # Clear session/media state.
        self.session = None
        self.media = None
        self.device_info = None
        self.now_playing = None
        self.selected_index = None
        self.external = False
        self.busy = False
        self._dlna_cancel = None
        self.poll_busy = False
        self.scan_busy = False
        self._scan_again = False
        self.queue = []
        self.queue_durations = {}
        self._preview_generation += 1
        self._preview_path = None
        self._preview_position = 0.0
        self._preview_pending = None
        self._unload_local_video()
        self.preview_picture.set_visible(False)

        # Reset tracker and position state.
        self.tracker.clear()
        self._finished_handled = False
        self._last_state = "IDLE"

        # Reset UI widgets to clean defaults.
        if self.np_title is not None:
            self.np_title.set_text("Ready to cast")
        if self.np_meta is not None:
            self.np_meta.set_text("Open a video and send it to your TV")
        if self.state_chip is not None:
            self.state_chip.set_text("Ready")
            self.state_chip.remove_css_class("playing")
            self.state_chip.remove_css_class("buffering")
            self.state_chip.remove_css_class("paused")
            self.state_chip.remove_css_class("offline")
            self.state_chip.remove_css_class("error")
            self.state_chip.add_css_class("idle")
        if self.preview is not None:
            self.preview.set_video("No video", "")
        if self.seekbar is not None:
            self.seekbar.set_state(0.0, 0.0, 0.0)
        if self.elapsed_label is not None:
            self.elapsed_label.set_text("0:00:00")
        if self.remaining_label is not None:
            self.remaining_label.set_text("--:--")

        # Reset level meters.
        if self.meter is not None:
            self.meter.reset()

        # Reset details card labels.
        if hasattr(self, "detail_labels"):
            for key, label in self.detail_labels.items():
                label.set_text("—")

        # Clear levels hint.
        if hasattr(self, "levels_hint") and self.levels_hint is not None:
            self.levels_hint.set_text("")

        # Clear any queued timer-based pending state.
        self._volume_job = None
        self._volume_target = None
        self._volume_user_ts = 0.0
        self._syncing = False
        self._subs_cache = ("", None)
        self._hover_time = None


    def action_open(self, *_args) -> None:
        self.open_video()


    def action_add_files(self, *_args) -> None:
        self.add_files()


    def action_stop(self, *_args) -> None:
        self.stop_stream()


    def action_shortcuts(self, *_args) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("Keyboard shortcuts")
        dialog.set_content_width(420)
        dialog.set_content_height(520)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        shortcuts = shortcut_map.desktop_labels() + [
            ("K", "Play or pause"),
            ("<Shift>Left", "Skip back 30 seconds"),
            ("<Shift>Right", "Skip forward 30 seconds"),
            ("J", "Skip back 10 seconds"),
            ("L", "Skip forward 10 seconds"),
            ("comma", "Step back one frame"),
            ("period", "Step forward one frame"),
            ("Home", "Back to start"),
            ("G", "Subtitles 100 ms earlier"),
            ("H", "Subtitles 100 ms later"),
            ("S", "Stop the stream"),
            ("<Control>o", "Open a video"),
            ("<Control>a", "Add videos to queue"),
            ("<Control>f", "Search queue"),
            ("<Control>w", "Stop the stream"),
            ("<Control>q", "Quit"),
            ("<Control>question", "This shortcuts window"),
        ]
        for accel, title in shortcuts:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            label = Gtk.Label(label=title, xalign=0.0, hexpand=True)
            shortcut_label = Gtk.ShortcutLabel(accelerator=accel)
            row.append(label)
            row.append(shortcut_label)
            box.append(row)
        for text, keys in (("Jump to 10% – 90%", "1 – 9"), ("Side panel tabs", "Alt+1 – 5")):
            row = Gtk.Box(spacing=12)
            chips = Gtk.Label(label=keys)
            chips.add_css_class("dim-label")
            row.append(Gtk.Label(label=text, xalign=0.0, hexpand=True))
            row.append(chips)
            box.append(row)
        note = Gtk.Label(
            label="While previewing locally these act on the preview; while "
                  "casting they act on the TV.",
            wrap=True, xalign=0.0,
        )
        note.add_css_class("dim-label")
        box.append(note)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(box)
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        dialog.present(self)


    def action_custom_speed(self, *_args) -> None:
        """Pick a precise playback rate; validated to a safe 0.25x-4x range."""
        dialog = Adw.Dialog()
        dialog.set_title("Custom playback speed")
        dialog.set_content_width(340)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.append(Gtk.Label(label="Playback speed (0.25x - 4x)", xalign=0.0))
        spin = Gtk.SpinButton.new_with_range(0.25, 4.0, 0.05)
        spin.set_digits(2)
        spin.set_value(min(4.0, max(0.25, float(self.cfg.get("playback_speed", 1.0)))))
        box.append(spin)
        apply = Gtk.Button(label="Apply")
        apply.add_css_class("suggested-action")

        def on_apply(_button):
            dialog.close()
            self._set_speed(spin.get_value())

        apply.connect("clicked", on_apply)
        box.append(apply)
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(self)


    def action_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=ICON_NAME,
            version=version.__version__,
            developer_name="gridout",
            comments="A modern companion for casting local videos to a Chromecast: live HLS transcoding or direct play, queue, captions, sound profiles and full remote control.",
        )
        about.present(self)


    def action_save_diagnostics(self) -> None:
        """Write a bounded, redacted support bundle off the GTK thread."""
        self.toast("Collecting diagnostics…")
        activity = list(self.console_lines)
        config = dict(self.cfg)
        receiver = diagnostics.receiver_report(self._dlna_renderer(), next(
            (d for d in self.devices if d.name == self.cfg["device"]), None))
        # Collecting tool versions and reading the log may touch the disk;
        # never block the GTK event loop.
        Async.run(
            lambda: diagnostics.export(activity=activity, config=config, receiver=receiver),
            done=lambda path: self.toast(f"Diagnostics saved: {path.name}"),
            failed=lambda message: self.toast(
                f"Diagnostics failed: {message}", error=True,
            ),
        )


    def perform_action(self, name: str) -> None:
        if name == "open":
            self.action_open()
        elif name == "add":
            self.action_add_files()
        elif name == "stop":
            self.action_stop()
        elif name == "shortcuts":
            self.action_shortcuts()


    def _screenshot(self) -> None:
        media = self.media
        if media is None:
            self.toast("No media loaded", error=True)
            return
        source = pathlib.Path(media.path)
        try:
            position = screenshot.owned_frame_time(
                source, session=self.session, external=self.external,
                tracker=self.tracker, local_video_path=self._local_video_path,
                local_stream=self._local_stream if self._local_video_path else None,
                preview_path=self._preview_path,
                preview_position=self._preview_position,
            )
        except screenshot.CaptureError as exc:
            self.toast(str(exc) or "Couldn't take the screenshot.", error=True)
            return
        output_dir = pathlib.Path(
            self.cfg.get("screenshot_dir") or pathlib.Path.home() / "Pictures"
        ).expanduser()
        self.toast("Capturing screenshot…")
        video_index = media.video_stream_index
        Async.run(
            lambda: screenshot.capture_frame(
                source, position, output_dir, video_stream_index=video_index,
            ),
            done=lambda out: self.toast(f"Screenshot saved: {out.name}"),
            failed=lambda message: self.toast(f"Screenshot failed: {message}", error=True),
        )


    def _toggle_loop_all(self) -> None:
        """Loop the whole queue (wrap last -> first); independent of repeat-one."""
        self.cfg["loop_all"] = not bool(self.cfg.get("loop_all", False))
        save_config(self.cfg)
        self.toast("Loop all on" if self.cfg["loop_all"] else "Loop all off")


    def _shuffle_queue(self) -> None:
        """Deterministically permute the queue so display and skip stay in sync."""
        if len(self.queue) < 2:
            self.toast("Nothing to shuffle")
            return
        seed = int(self.cfg.get("shuffle_seed", 1)) % 9999 + 1
        self.cfg["shuffle_seed"] = seed
        save_config(self.cfg)
        self.queue = playback_state.shuffle_order(self.queue, seed)
        self._rebuild_queue()
        self.toast("Queue shuffled")


    def _theme_tick(self) -> bool:
        """Re-evaluate the time-based theme so it switches at the day boundary."""
        self._apply_color_scheme()
        return True


    def _frame_step(self, direction: int) -> None:
        """Step one source frame (1 s fallback) using the media frame rate."""
        fps = self.media.fps if self.media and self.media.fps else 0.0
        self._skip(direction * playback_state.frame_step_delta(fps))
