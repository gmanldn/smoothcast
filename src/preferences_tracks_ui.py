"""Audio/subtitle track, subtitle-file and portal-port handlers for Preferences.

Split from ``preferences_ui`` (#588 follow-up) so that module stays small enough
to read narrowly; the methods are unchanged and run on the PreferencesWindow.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, Gtk

from cast_widgets import save_config


class TrackPreferencesMixin:
    def _page(self, title: str, icon: str):
        page = Adw.PreferencesPage(title=title, icon_name=icon)
        self.add(page)
        return page

    @staticmethod
    def _group(page, title: str, description: str):
        group = Adw.PreferencesGroup(title=title, description=description)
        page.add(group)
        return group

    def _change_portal_port(self, spin) -> None:
        if self._syncing:
            return
        value = int(spin.get_value())
        if not 49152 <= value <= 65535:
            return
        self.owner.cfg["portal_port"] = value
        save_config(self.owner.cfg)

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
