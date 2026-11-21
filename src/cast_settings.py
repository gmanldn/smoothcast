"""Inline player settings card, separate from the main GUI layout.

This optional inline view and the searchable Preferences window delegate to
the existing MainWindow handlers for persistence and Cast safety.
"""
from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

import loudness
from cast_widgets import DEFAULTS, save_config


class SettingsCardMixin:
    def _build_settings_card(self) -> Gtk.Box:
        card, body = self._card(
            "Playback settings", "Optimise picture, sound and subtitles for your TV."
        )
        card.add_css_class("settings-card")
        body.set_spacing(11)
        # The player stays media-first. Existing controls remain available
        # without a duplicated handler or broken cross-module widget reference.
        preferences_button = Gtk.Button(label="Open Preferences…")
        preferences_button.set_halign(Gtk.Align.START)
        preferences_button.set_tooltip_text("Search all playback, sound, subtitle and appearance settings (Ctrl+,)")
        preferences_button.connect("clicked", lambda _button: self.action_preferences())
        body.append(preferences_button)
        inline = Gtk.Expander(label="Show inline playback controls")
        inline.set_expanded(False)
        inline.set_tooltip_text("The familiar quality, sound and caption controls")
        inline_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        inline.set_child(inline_body)
        body.append(inline)
        body = inline_body
        self._syncing = True

        def group(title: str) -> None:
            label = Gtk.Label(label=title, xalign=0.0)
            label.add_css_class("setting-group")
            body.append(label)

        def dropdown_row(label, options, current, tooltip=""):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("setting-row")
            tag = Gtk.Label(label=label, xalign=0.0, hexpand=True)
            tag.add_css_class("label-strong")
            dropdown = Gtk.DropDown.new_from_strings(options)
            dropdown.set_valign(Gtk.Align.CENTER)
            if tooltip:
                dropdown.set_tooltip_text(tooltip)
            row.append(tag)
            row.append(dropdown)
            body.append(row)
            return dropdown

        group("VIDEO")
        self.quality_dropdown = dropdown_row(
            "Video quality",
            ["High", "Balanced", "Data saver"],
            self.cfg["quality"],
            "Transcoding quality — applies on the next (re)start",
        )
        self.quality_dropdown.set_selected({"high": 0, "balanced": 1, "saver": 2}.get(self.cfg["quality"], 1))
        self.quality_dropdown.connect("notify::selected", self._on_quality)

        group("AUDIO")
        self.audio_dropdown = dropdown_row(
            "Sound profile",
            ["Original audio", "Dialogue auto-fix", "Night mode"],
            self.cfg["audio"],
            "Audio processing — applies on the next (re)start",
        )
        self.audio_dropdown.set_selected({"original": 0, "dialogue": 1, "night": 2}.get(self.cfg["audio"], 1))
        self.audio_dropdown.connect("notify::selected", self._on_audio)

        self.loudness_dropdown = dropdown_row(
            "Loudness normalisation",
            ["Off", "Programme (-16 LUFS)", "Album (-18 LUFS)"],
            self.cfg.get("audio_loudness", "off"),
            "EBU R128 loudness with true-peak limiting — applies on the next (re)start",
        )
        self.loudness_dropdown.set_selected({"off": 0, "programme": 1, "album": 2}.get(self.cfg.get("audio_loudness", "off"), 0))
        self.loudness_dropdown.connect("notify::selected", self._on_loudness)

        self.audio_track_dropdown = dropdown_row(
            "Film audio track",
            ["Auto (file default)"],
            -1,
            "Choose the MKV audio language, commentary or channel mix; changing the active cast restarts at the current position",
        )
        self.audio_track_dropdown.set_sensitive(False)
        self.audio_track_dropdown.connect("notify::selected", self._on_audio_track)

        self.rotation_dropdown = dropdown_row(
            "Video rotation",
            ["None", "90°", "180°", "270°"],
            self.cfg["rotation"],
            "Rotate the transcoded video clockwise — applies on the next (re)start",
        )
        self.rotation_dropdown.set_selected({0: 0, 90: 1, 180: 2, 270: 3}.get(self.cfg["rotation"], 0))
        self.rotation_dropdown.connect("notify::selected", self._on_rotation)

        gain_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gain_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        gain_text.set_hexpand(True)
        gain_title = Gtk.Label(label="Dialogue loudness boost", xalign=0.0)
        gain_title.add_css_class("label-strong")
        gain_title.set_tooltip_text("Extra loudness for quiet dialogue — type a value in dB (0–24). Applies on the next (re)start.")
        gain_sub = Gtk.Label(label="Levels loud bangs vs quiet speech; add dB here if you want it louder", xalign=0.0, wrap=True)
        gain_sub.add_css_class("dim-label")
        gain_sub.add_css_class("caption")
        gain_text.append(gain_title)
        gain_text.append(gain_sub)
        gain_adjustment = Gtk.Adjustment(
            value=float(self.cfg.get("audio_gain", DEFAULTS["audio_gain"])),
            lower=0, upper=24, step_increment=1, page_increment=3,
        )
        self.gain_spin = Gtk.SpinButton(adjustment=gain_adjustment, digits=0, climb_rate=1.0)
        self.gain_spin.set_valign(Gtk.Align.CENTER)
        self.gain_spin.set_tooltip_text("Type a boost in dB (0–24) and press Enter, or use the arrows")
        self.gain_spin.connect("value-changed", self._on_gain)
        gain_unit = Gtk.Label(label="dB", xalign=0.0)
        gain_unit.add_css_class("dim-label")
        gain_row.append(gain_text)
        gain_row.append(self.gain_spin)
        gain_row.append(gain_unit)
        body.append(gain_row)

        group("SUBTITLES")
        self.subs_dropdown = dropdown_row(
            "Subtitles",
            ["Off", "Auto (sidecar or MKV)", "Pick .srt / subtitles…", "Embedded (MKV track)"],
            self.cfg["subs"],
            "External subtitles served to the TV",
        )
        self.subs_dropdown.set_selected({"off": 0, "auto": 1, "pick": 2, "embedded": 3}.get(self.cfg["subs"], 1))
        self.subs_dropdown.connect("notify::selected", self._on_subs_mode)
        self.subs_detail = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.subs_detail.add_css_class("dim-label")
        self.subs_detail.add_css_class("caption")
        body.append(self.subs_detail)
        self.embedded_dropdown = Gtk.DropDown.new_from_strings(["Preferred embedded track"])
        self.embedded_dropdown.set_tooltip_text("Select a text subtitle track inside the current MKV")
        self.embedded_dropdown.set_visible(False)
        self.embedded_dropdown.connect("notify::selected", self._on_embedded_track)
        body.append(self.embedded_dropdown)

        burn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        burn_row.add_css_class("setting-row")
        burn_label = Gtk.Label(label="Burn subtitles into video", xalign=0.0, hexpand=True)
        burn_label.add_css_class("label-strong")
        burn_label.set_tooltip_text("Slower CPU encode — only if the TV cannot show CC tracks")
        self.burn_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.burn_switch.set_active(bool(self.cfg["burn_subs"]))
        self.burn_switch.connect("notify::active", self._on_burn)
        burn_row.append(burn_label)
        burn_row.append(self.burn_switch)
        body.append(burn_row)

        group("PLAYBACK")
        self.direct_switch = self._switch_row(
            body,
            "Direct play when possible",
            "Instant seeking for H.264/AAC files",
            bool(self.cfg["direct"]),
            self._on_direct,
        )
        self.keep_switch = self._switch_row(
            body,
            "Keep streaming after closing",
            "The TV keeps playing if the app exits",
            bool(self.cfg["keep_streaming"]),
            self._on_keep,
        )
        self._syncing = False
        return card


    def _on_loudness(self, dropdown, _param) -> None:
        if self._syncing:
            return
        value = {0: "off", 1: "programme", 2: "album"}.get(dropdown.get_selected(), "off")
        if value != self.cfg.get("audio_loudness", "off"):
            self.cfg["audio_loudness"] = value
            save_config(self.cfg)
            self.toast(f"Loudness: {loudness.label(value)} (restart to apply)")
        self._refresh_direct_note()


    def _sleep_fade_tick(self) -> bool:
        """Fade Cast volume before the sleep timer fires; restore it after (#270)."""
        self._sleep_fader.tick(
            now=time.time(), deadline=self.cfg.get("sleep_timer_deadline", 0.0),
            fade_seconds=self.cfg.get("sleep_fade_seconds", 0), device=self._device(),
            active=(self.session is not None or self._url_cast_url is not None)
            and self._dlna_renderer() is None)
        return True
