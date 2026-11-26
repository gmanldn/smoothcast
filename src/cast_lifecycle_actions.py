#!/usr/bin/env python3
"""Lifecycle menu actions (open/add/stop, shortcuts, speed, about, diagnostics).

Extracted from ``cast_lifecycle.py`` unchanged so that module stays within its
INV-011 read budget; the methods run on the same ``LifecycleMixin`` instance.
"""
from __future__ import annotations

import shortcut_map
import version
from cast_widgets import APP_NAME, ICON_NAME, Async
from gi.repository import Adw, Gtk


class LifecycleActionsMixin:
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
        spin.update_property([Gtk.AccessibleProperty.LABEL], ["Playback speed"])
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
    def perform_action(self, name: str) -> None:
        if name == "open":
            self.action_open()
        elif name == "add":
            self.action_add_files()
        elif name == "stop":
            self.action_stop()
        elif name == "shortcuts":
            self.action_shortcuts()
