"""Searchable libadwaita preferences sharing the in-player controls."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

import library_folders_ui
import preference_choices
import picture_adjustments
from preferences_picture_ui import PicturePreferencesMixin
from cast_widgets import save_config


class PreferencesWindow(PicturePreferencesMixin, Adw.PreferencesWindow):
    def __init__(self, owner) -> None:
        super().__init__(transient_for=owner, modal=True)
        self.owner = owner
        self._syncing = False
        self._combos = {}
        self._switches = {}
        self._picture_spins = {}
        self._audio_labels = None
        self._embedded_labels = None
        self.set_title("SmoothCast Preferences")
        self.set_default_size(660, 520)
        self.set_search_enabled(True)
        self._build()
        self.library_page = library_folders_ui.LibraryFoldersPage(self)
        self.sync_from_owner()

    def _page(self, title: str, icon: str):
        page = Adw.PreferencesPage(title=title, icon_name=icon)
        self.add(page)
        return page

    @staticmethod
    def _group(page, title: str, description: str):
        group = Adw.PreferencesGroup(title=title, description=description)
        page.add(group)
        return group

    def _choice(self, group, key: str, title: str, help_text: str):
        row = Adw.ComboRow(title=title, subtitle=help_text)
        row.set_model(Gtk.StringList.new(preference_choices.labels(key)))
        self._combos[key] = row
        group.add(row)
        row.connect("notify::selected", lambda widget, _pspec: self._change_choice(key, widget))
        return row

    def _switch(self, group, key: str, title: str, help_text: str):
        row = Adw.SwitchRow(title=title, subtitle=help_text)
        self._switches[key] = row
        group.add(row)
        row.connect("notify::active", lambda widget, _pspec: self._change_switch(key, widget))
        return row

    def _build(self) -> None:
        playback = self._page("Playback", "media-playback-start-symbolic")
        output = self._group(
            playback, "Picture and delivery",
            "Changes to encoding take effect on the next cast or transcode restart.",
        )
        self._choice(output, "quality", "Video quality",
                     "High uses more processing; Data saver reduces bandwidth and resolution.")
        self._switch(output, "quality_auto", "Automatically choose video quality",
                     "Benchmark this CPU after the window opens, then choose a safe "
                     "software-encoding tier. Turn off to use the quality selected above.")
        self._choice(output, "rotation", "Video rotation",
                     "Clockwise rotation requires video transcoding.")
        self._choice(output, "aspect_override", "Aspect ratio",
                     "Stretch can distort the picture. Changes appear in the scrub preview and apply to the next cast.")
        self._switch(output, "direct", "Direct play when supported",
                     "Send a compatible file unchanged; sound filters and rotation may require conversion.")
        self._switch(output, "keep_streaming", "Keep casting after closing",
                     "Chromecast may continue playing; DLNA's local server always stops on exit.")
        self._switch(output, "auto_crop", "Crop black bars automatically",
                     "Detects letterboxing before a transcode and crops it; adds a few seconds to a cast start.")
        self._switch(output, "auto_deinterlace", "Deinterlace automatically",
                     "Only when the film is clearly interlaced; progressive video is never touched.")
        self._build_picture_preferences(playback, output)

        queue = self._group(
            playback, "Queue behaviour",
            "These options control what happens when the current film finishes.",
        )
        self._switch(queue, "autonext", "Play next film automatically",
                     "Advance to the next item without another click.")
        self._switch(queue, "loop", "Repeat current film",
                     "Repeat this film instead of advancing the queue.")
        self._switch(queue, "loop_all", "Repeat the whole queue",
                     "After the final item, return to the first.")
        self._switch(queue, "auto_shutdown", "Close app after the final film",
                     "Close SmoothCast when playback finishes; receiver behaviour follows the keep-casting setting.")

        self._switch(queue, "portal_screens", "Let room browsers play the queue",
                     "Paired phones and TVs can act as screens or speakers.")
        self._switch(queue, "house_pin_enabled", "Require a house PIN to join",
                     "Only needed if people you don't trust use your Wi-Fi. Applies the next time the room restarts.")
        room_port_row = Adw.ActionRow(
            title="Room remote port",
            subtitle="High-range port used by phone links and QR codes. Change takes effect on the next launch.",
        )
        self.portal_port_spin = Gtk.SpinButton.new_with_range(49152, 65535, 1)
        self.portal_port_spin.set_numeric(True)
        self.portal_port_spin.update_property([Gtk.AccessibleProperty.LABEL], ["Room remote port"])
        room_port_row.add_suffix(self.portal_port_spin)
        room_port_row.set_activatable_widget(self.portal_port_spin)
        self.portal_port_spin.connect("value-changed", self._change_portal_port)
        queue.add(room_port_row)

        alerts = self._group(
            playback, "Playback alerts",
            "Alerts stay inside SmoothCast and never add a counter to the OS dock.",
        )
        art = self._group(playback, "Artwork", "Shown in the preview above the scrubber.")
        self._switch(art, "show_cover_art", "Show cover art",
                     "Use a track's embedded artwork; turn off to keep the plain slate.")
        self._switch(alerts, "notifications", "Show in-app playback alerts",
                     "Keep finished, error and receiver-offline notices in the activity console "
                     "and show a short in-app toast while the window is unfocused.")

        sound = self._page("Sound & subtitles", "audio-speakers-symbolic")
        audio = self._group(
            sound, "Audio",
            "Profiles and gain are applied at the next cast or encoder restart.",
        )
        self._choice(audio, "audio", "Sound profile",
                     "Original preserves the mix; Dialogue boosts speech; Night tames loud passages.")
        self._switch(audio, "music_autogain", "Music autogain", "Match tracks to -16 LUFS.")
        self.audio_track = Adw.ComboRow(
            title="Film audio track",
            subtitle="Choose language or commentary for the selected film. Changing an active cast restarts it.",
        )
        audio.add(self.audio_track)
        self.audio_track.connect("notify::selected", self._change_audio_track)

        boost = Adw.ActionRow(
            title="Dialogue loudness boost",
            subtitle="Additional level in dB (0–24); effective when dialogue processing is enabled.",
        )
        self.gain = Gtk.SpinButton.new_with_range(0, 24, 1)
        self.gain.set_valign(Gtk.Align.CENTER)
        self.gain.set_tooltip_text("Dialogue boost, 0 to 24 decibels")
        boost.add_suffix(self.gain)
        boost.set_activatable_widget(self.gain)
        self.gain.connect("value-changed", self._change_gain)
        audio.add(boost)

        captions = self._group(
            sound, "Captions",
            "Text tracks can be sent to a Cast receiver or burned into the picture.",
        )
        self._choice(captions, "subs", "Subtitle source",
                     "Off, automatic sidecar/MKV, external file, or embedded MKV text.")
        self.subtitle_file = Adw.ActionRow(
            title="External subtitle file",
            subtitle="Select an .srt, .vtt, .ttml, .ass or .ssa file without changing the film.",
        )
        pick = Gtk.Button(label="Choose…")
        pick.set_valign(Gtk.Align.CENTER)
        pick.connect("clicked", lambda _button: self._choose_subtitle_file())
        self.subtitle_file.add_suffix(pick)
        self.subtitle_file.set_activatable_widget(pick)
        captions.add(self.subtitle_file)
        self.embedded_track = Adw.ComboRow(
            title="Embedded subtitle track",
            subtitle="Only text subtitles in the currently selected MKV can be rendered.",
        )
        captions.add(self.embedded_track)
        self.embedded_track.connect("notify::selected", self._change_embedded_track)
        self._switch(captions, "burn_subs", "Burn subtitles into the video",
                     "For receivers that cannot display separate captions; needs encoding.")
        self._choice(
            captions, "subtitle_style", "Subtitle appearance",
            "For plain-text subtitles only; applies on the next cast or encoder restart. "
            "ASS/SSA keep their authored styling.",
        )

        general = self._page("Appearance", "preferences-desktop-theme-symbolic")
        visual = self._group(
            general, "Theme",
            "Choose the appearance that makes the player most comfortable to read.",
        )
        self._choice(visual, "color_scheme", "Colour scheme",
                     "A manual choice turns off automatic day/night switching.")
        self._switch(visual, "auto_theme", "Switch theme by time of day",
                     "Use a light theme during the day and a dark theme at night.")
        self._choice(visual, "accent", "Accent colour",
                     "Highlights buttons, sliders and switches. Every option keeps text readable; Default restores the original blue.")
        self._choice(visual, "density", "Interface density",
                     "Scales spacing and control sizes. Long text wraps in narrow windows and under large fonts instead of being clipped.")

        updates = self._group(
            general, "Updates",
            "Nothing is downloaded or installed automatically. These options "
            "apply on the next app launch, not during playback.",
        )
        self._choice(updates, "update_channel", "Update channel",
                     "Develop (default) receives frequent tested builds; Main follows releases. "
                     "Only read-only checks work so far; installing safely in the background is pending.")
        self._switch(updates, "check_release_updates", "Check for releases on startup",
                     "Off by default. Uses the Internet only when enabled, after "
                     "the window appears; a check never changes the running code.")
        self._switch(updates, "release_check_verify", "Require a trusted signature",
                     "On by default. Updates without a signature trusted by "
                     "your Git keyring are not offered as safe to install.")

    def sync_from_owner(self) -> None:
        """Read live values whenever shown or after an action; never emit edits."""
        cfg = self.owner.cfg
        self._syncing = True
        try:
            for key, row in self._combos.items():
                row.set_selected(preference_choices.selected_index(key, cfg.get(key)))
            for key, row in self._switches.items():
                row.set_active(bool(cfg.get(key, False)))
            for key, spin in self._picture_spins.items():
                spin.set_value(picture_adjustments.validated(
                    key, cfg.get(key, picture_adjustments.DEFAULTS[key])))
            self.gain.set_value(float(cfg.get("audio_gain", 6.0)))
            self.portal_port_spin.set_value(max(49152, int(cfg.get("portal_port") or 49152)))
            media = self.owner.media
            audio_tracks = media.audio_streams if media is not None else []
            audio_labels = ["Auto (file default)"] + [track.label for track in audio_tracks]
            if audio_labels != self._audio_labels:
                self.audio_track.set_model(Gtk.StringList.new(audio_labels))
                self._audio_labels = audio_labels
            self.audio_track.set_sensitive(bool(audio_tracks))
            self.audio_track.set_selected(self.owner.audio_track_dropdown.get_selected())
            embedded_tracks = (
                [track for track in media.subtitle_tracks if track.is_supported]
                if media is not None else []
            )
            embedded_labels = ["Preferred embedded track"] + [track.label for track in embedded_tracks]
            if embedded_labels != self._embedded_labels:
                self.embedded_track.set_model(Gtk.StringList.new(embedded_labels))
                self._embedded_labels = embedded_labels
            self.embedded_track.set_sensitive(bool(embedded_tracks) and cfg.get("subs") == "embedded")
            self.embedded_track.set_selected(self.owner.embedded_dropdown.get_selected())
            self.subtitle_file.set_subtitle(self.owner._subs_status_text())
        finally:
            self._syncing = False

    def _change_choice(self, key: str, row) -> None:
        if self._syncing:
            return
        value = preference_choices.selected_value(key, row.get_selected())
        if key == "subs" and value == "pick":
            self._choose_subtitle_file()
            return
        if key == "color_scheme":
            self.owner.app.scheme_action.activate(GLib.Variant("s", value))
        elif key == "accent":
            self.owner.cfg["accent"] = str(value)
            save_config(self.owner.cfg)
            self.owner.app.apply_accent(value)
        elif key == "density":
            self.owner.cfg["density"] = str(value)
            save_config(self.owner.cfg)
            self.owner.app.apply_density(value)
            self.owner._refresh_responsive_layout()
        elif key == "update_channel":
            self.owner.cfg["update_channel"] = str(value)
            save_config(self.owner.cfg)
        elif key in {"subtitle_style", "aspect_override"}:
            owner = self.owner
            owner.cfg[key] = str(value)
            save_config(owner.cfg)
            if key == "aspect_override":
                owner._preview_generation += 1
                owner._refresh_thumbnail_strip(0.0, visible=False)
                owner._queue_preview(owner._preview_position)
        else:
            widgets = {
                "quality": "quality_dropdown",
                "audio": "audio_dropdown",
                "rotation": "rotation_dropdown",
                "subs": "subs_dropdown",
            }
            getattr(self.owner, widgets[key]).set_selected(row.get_selected())
        self.sync_from_owner()

    def _change_switch(self, key: str, row) -> None:
        if self._syncing:
            return
        active = row.get_active()
        owner = self.owner
        widgets = {
            "direct": "direct_switch",
            "keep_streaming": "keep_switch",
            "burn_subs": "burn_switch",
            "autonext": "autonext_switch",
            "music_autogain": "music_autogain_switch",
        }
        toggles = {
            "loop": "_toggle_loop",
            "loop_all": "_toggle_loop_all",
            "auto_shutdown": "_toggle_auto_shutdown",
            "auto_theme": "_toggle_auto_theme",
        }
        if key in widgets:
            getattr(owner, widgets[key]).set_active(active)
        elif key in ("auto_crop", "auto_deinterlace", "notifications", "portal_screens",
                     "house_pin_enabled", "show_cover_art", "check_release_updates",
                     "release_check_verify", "quality_auto"):
            owner.cfg[key] = active  # read from config.json at the next transcode (#54)
            save_config(owner.cfg)
        elif bool(owner.cfg.get(key, False)) != active:
            getattr(owner, toggles[key])()
        self.sync_from_owner()

    def _change_portal_port(self, spin) -> None:
        if self._syncing:
            return
        value = int(spin.get_value())
        if not 49152 <= value <= 65535:
            return
        self.owner.cfg["portal_port"] = value
        save_config(self.owner.cfg)

    def _change_gain(self, spin) -> None:
        if not self._syncing:
            self.owner.gain_spin.set_value(spin.get_value())

    def _change_audio_track(self, row, _pspec) -> None:
        if not self._syncing:
            self.owner.audio_track_dropdown.set_selected(row.get_selected())
            self.sync_from_owner()

    def _change_embedded_track(self, row, _pspec) -> None:
        if not self._syncing:
            self.owner.embedded_dropdown.set_selected(row.get_selected())
            self.sync_from_owner()

    def _choose_subtitle_file(self) -> None:
        dialog = Gtk.FileDialog(title="Choose a subtitle file")
        subtitle_filter = Gtk.FileFilter()
        subtitle_filter.set_name("Supported subtitles")
        for extension in ("*.srt", "*.vtt", "*.ttml", "*.ass", "*.ssa"):
            subtitle_filter.add_pattern(extension)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(subtitle_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._subtitle_selected)

    def _subtitle_selected(self, dialog, result) -> None:
        # Reuse the existing file validation, cancel path and persistence code.
        self.owner._subs_file_chosen(dialog, result)
        was_syncing = self.owner._syncing
        self.owner._syncing = True
        try:
            self.owner.subs_dropdown.set_selected(
                preference_choices.selected_index("subs", self.owner.cfg["subs"])
            )
        finally:
            self.owner._syncing = was_syncing
        self.sync_from_owner()
