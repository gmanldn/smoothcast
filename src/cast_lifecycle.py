#!/usr/bin/env python3
"""Window lifecycle, actions and screenshots."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk
import pathlib

import threading

import diagnostics

import screenshot

import version

from cast_widgets import APP_NAME, ICON_NAME, save_config, fmt_time, Async


class LifecycleMixin:
    def _on_close(self, _window) -> bool:
        self._closing = True
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
        # Gtk4 tracks the normal window size separately from fullscreen and
        # maximized allocations. Save that instead of the temporary screen size.
        width, height = self.get_default_size()
        if width > 0 and height > 0:
            self.cfg["window_width"] = width
            self.cfg["window_height"] = height
        save_config(self.cfg)
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
            if previewing and self._local_stream() is None:
                self._queue_preview(value)
        else:
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
        if self.master_meter is not None:
            self.master_meter.reset()

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
        shortcuts = [
            ("Space", "Play or pause"),
            ("K", "Play or pause"),
            ("Left", "Skip back 10 seconds"),
            ("Right", "Skip forward 10 seconds"),
            ("<Shift>Left", "Skip back 30 seconds"),
            ("<Shift>Right", "Skip forward 30 seconds"),
            ("J", "Skip back 10 seconds"),
            ("L", "Skip forward 10 seconds"),
            ("Up", "Volume up 5%"),
            ("Down", "Volume down 5%"),
            ("M", "Mute"),
            ("S", "Stop the stream"),
            ("P", "Previous in queue"),
            ("N", "Next in queue"),
            ("<Control>o", "Open a video"),
            ("<Control>a", "Add videos to queue"),
            ("<Control>f", "Search queue"),
        ]
        for accel, title in shortcuts:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            label = Gtk.Label(label=title, xalign=0.0, hexpand=True)
            shortcut_label = Gtk.ShortcutLabel(accelerator=accel)
            row.append(label)
            row.append(shortcut_label)
            box.append(row)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label="Jump to 10% – 90%", xalign=0.0, hexpand=True)
        chips = Gtk.Label(label="1 – 9")
        chips.add_css_class("dim-label")
        row.append(label)
        row.append(chips)
        box.append(row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(box)
        toolbar.set_content(scroller)
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
        # Collecting tool versions and reading the log may touch the disk;
        # never block the GTK event loop.
        Async.run(
            lambda: diagnostics.export(activity=activity, config=config),
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
        output_dir = pathlib.Path(
            self.cfg.get("screenshot_dir") or pathlib.Path.home() / "Pictures"
        ).expanduser()
        position = self.tracker.value() or 0.0
        self.toast("Capturing screenshot…")
        # FFmpeg, filesystem access and a corrupt input file may block for
        # seconds. Keep all of it off the GTK event loop.
        Async.run(
            lambda: screenshot.capture_frame(source, position, output_dir),
            done=lambda out: self.toast(f"Screenshot saved: {out.name}"),
            failed=lambda message: self.toast(
                f"Screenshot failed: {message}", error=True,
            ),
        )
