"""Inline player settings card, separate from the main GUI layout.

This optional inline view and the searchable Preferences window delegate to
the existing MainWindow handlers for persistence and Cast safety.
"""
from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

import loudness
import settings
from cast_widgets import save_config
import music_autogain


class SettingsCardController:
    """Composition replacement for SettingsCardMixin (#691); widgets stay attributes of the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _build_settings_card(self) -> Gtk.Box:
        w = self.w
        card, body = w._card(
            "Playback settings", "Optimise picture, sound and subtitles for your TV."
        )
        card.add_css_class("settings-card")
        body.set_spacing(11)
        # Every common control sits right here; the searchable Preferences
        # window reaches the same handlers plus the rarely used options.
        preferences_button = Gtk.Button(label="All preferences…")
        preferences_button.set_halign(Gtk.Align.START)
        preferences_button.set_tooltip_text("Search all playback, sound, subtitle and appearance settings (Ctrl+,)")
        preferences_button.connect("clicked", lambda _button: w.action_preferences())
        body.append(preferences_button)
        w._syncing = True

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
        w.quality_dropdown = dropdown_row(
            "Video quality",
            ["High", "Balanced", "Data saver"],
            w.cfg["quality"],
            "Transcoding quality — applies on the next (re)start",
        )
        w.quality_dropdown.set_selected({"high": 0, "balanced": 1, "saver": 2}.get(w.cfg["quality"], 1))
        w.quality_dropdown.connect("notify::selected", w._on_quality)

        group("AUDIO")
        w.audio_dropdown = dropdown_row(
            "Sound profile",
            ["Original audio", "Dialogue auto-fix", "Night mode"],
            w.cfg["audio"],
            "Audio processing — applies on the next (re)start",
        )
        w.audio_dropdown.set_selected({"original": 0, "dialogue": 1, "night": 2}.get(w.cfg["audio"], 1))
        w.audio_dropdown.connect("notify::selected", w._on_audio)

        w.loudness_dropdown = dropdown_row(
            "Loudness normalisation",
            ["Off", "Programme (-16 LUFS)", "Album (-18 LUFS)"],
            w.cfg.get("audio_loudness", "off"),
            "EBU R128 loudness with true-peak limiting — applies on the next (re)start",
        )
        w.loudness_dropdown.set_selected({"off": 0, "programme": 1, "album": 2}.get(w.cfg.get("audio_loudness", "off"), 0))
        w.loudness_dropdown.connect("notify::selected", self._on_loudness)

        w.music_autogain_switch = music_autogain.add_settings_switch(
            body, Gtk, bool(w.cfg.get("music_autogain", False)),
            self._on_music_autogain,
        )

        w.audio_track_dropdown = dropdown_row(
            "Film audio track",
            ["Auto (file default)"],
            -1,
            "Choose the MKV audio language, commentary or channel mix; changing the active cast restarts at the current position",
        )
        w.audio_track_dropdown.set_sensitive(False)
        w.audio_track_dropdown.connect("notify::selected", w._on_audio_track)

        w.rotation_dropdown = dropdown_row(
            "Video rotation",
            ["None", "90°", "180°", "270°"],
            w.cfg["rotation"],
            "Rotate the transcoded video clockwise — applies on the next (re)start",
        )
        w.rotation_dropdown.set_selected({0: 0, 90: 1, 180: 2, 270: 3}.get(w.cfg["rotation"], 0))
        w.rotation_dropdown.connect("notify::selected", w._on_rotation)

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
            value=settings.AudioSettings.from_config(w.cfg).gain,
            lower=0, upper=24, step_increment=1, page_increment=3,
        )
        w.gain_spin = Gtk.SpinButton(adjustment=gain_adjustment, digits=0, climb_rate=1.0)
        w.gain_spin.set_valign(Gtk.Align.CENTER)
        w.gain_spin.set_tooltip_text("Type a boost in dB (0–24) and press Enter, or use the arrows")
        w.gain_spin.connect("value-changed", w._on_gain)
        gain_unit = Gtk.Label(label="dB", xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        gain_unit.add_css_class("dim-label")
        gain_row.append(gain_text)
        gain_row.append(w.gain_spin)
        gain_row.append(gain_unit)
        body.append(gain_row)

        group("SUBTITLES")
        w.subs_dropdown = dropdown_row(
            "Subtitles",
            ["Off", "Auto (sidecar or MKV)", "Pick .srt / subtitles…", "Embedded (MKV track)"],
            w.cfg["subs"],
            "External subtitles served to the TV",
        )
        w.subs_dropdown.set_selected({"off": 0, "auto": 1, "pick": 2, "embedded": 3}.get(w.cfg["subs"], 1))
        w.subs_dropdown.connect("notify::selected", w._on_subs_mode)
        w.subs_detail = Gtk.Label(label="", xalign=0.0, wrap=True)
        w.subs_detail.add_css_class("dim-label")
        w.subs_detail.add_css_class("caption")
        body.append(w.subs_detail)
        w.embedded_dropdown = Gtk.DropDown.new_from_strings(["Preferred embedded track"])
        w.embedded_dropdown.set_tooltip_text("Select a text subtitle track inside the current MKV")
        w.embedded_dropdown.set_visible(False)
        w.embedded_dropdown.connect("notify::selected", w._on_embedded_track)
        body.append(w.embedded_dropdown)

        burn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        burn_row.add_css_class("setting-row")
        burn_label = Gtk.Label(label="Burn subtitles into video", xalign=0.0, hexpand=True)
        burn_label.add_css_class("label-strong")
        burn_label.set_tooltip_text("Slower CPU encode — only if the TV cannot show CC tracks")
        w.burn_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        w.burn_switch.set_active(bool(w.cfg["burn_subs"]))
        w.burn_switch.update_property([Gtk.AccessibleProperty.LABEL], ["Burn subtitles into video"])
        w.burn_switch.connect("notify::active", w._on_burn)
        burn_row.append(burn_label)
        burn_row.append(w.burn_switch)
        body.append(burn_row)

        group("PLAYBACK")
        w.direct_switch = w._switch_row(
            body,
            "Direct play when possible",
            "Instant seeking for H.264/AAC files",
            bool(w.cfg["direct"]),
            w._on_direct,
        )
        w.keep_switch = w._switch_row(
            body,
            "Keep streaming after closing",
            "The TV keeps playing if the app exits",
            bool(w.cfg["keep_streaming"]),
            w._on_keep,
        )
        w._syncing = False
        return card


    def _on_loudness(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        value = {0: "off", 1: "programme", 2: "album"}.get(dropdown.get_selected(), "off")
        if value != w.cfg.get("audio_loudness", "off"):
            w.cfg["audio_loudness"] = value
            save_config(w.cfg)
            w.toast(f"Loudness: {loudness.label(value)} (restart to apply)")
        w._refresh_direct_note()


    def _on_music_autogain(self, switch, _param) -> None:
        w = self.w
        if w._syncing:
            return
        active = bool(switch.get_active())
        if active != bool(w.cfg.get("music_autogain", False)):
            w.cfg["music_autogain"] = active
            save_config(w.cfg)
            w.toast("Music autogain enabled (applies on the next cast or restart)"
                       if active else "Music autogain disabled")
            w._publish_portal_status()


    def _sleep_fade_tick(self) -> bool:
        """Fade Cast volume before the sleep timer fires; restore it after (#270)."""
        w = self.w
        w._sleep_fader.tick(
            now=time.time(), deadline=w.cfg.get("sleep_timer_deadline", 0.0),
            fade_seconds=w.cfg.get("sleep_fade_seconds", 0), device=w._device(),
            active=(w.session is not None or w._url_cast_url is not None)
            and w._dlna_renderer() is None)
        return True
