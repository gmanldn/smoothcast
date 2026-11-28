"""Audio/subtitle track, subtitle-file and portal-port handlers for Preferences.

Split from ``preferences_ui`` (#588 follow-up) so that module stays small enough
to read narrowly; the methods are unchanged and run on the PreferencesWindow.
"""
from __future__ import annotations

import pathlib

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk

import subtitle_search
import settings_catalog
from cast_widgets import save_config


class TrackPreferencesMixin:
    def _page(self, title: str, icon: str):
        page = Adw.PreferencesPage(title=title, icon_name=icon)
        self.add(page)
        return page

    @staticmethod
    def _group(page, page_name: str, title: str):
        description = settings_catalog.group_description(page_name, title)
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

    def _build_subtitle_search(self, captions) -> None:
        self.subtitle_search_row = Adw.ExpanderRow(
            title="Search other folders",
            subtitle="When Auto finds no sidecar next to the film, look in these "
                     "folders. Nothing is downloaded.",
        )
        add = Gtk.Button(label="Add folder…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda _button: self._choose_subtitle_search_folder())
        self.subtitle_search_row.add_suffix(add)
        self._subtitle_search_rows = []
        captions.add(self.subtitle_search_row)
        self._refresh_subtitle_search_rows()

    def _refresh_subtitle_search_rows(self) -> None:
        row = getattr(self, "subtitle_search_row", None)
        if row is None:
            return
        for child in getattr(self, "_subtitle_search_rows", []):
            row.remove(child)
        rows = []
        folders = subtitle_search.clean_folders(
            self.owner.cfg.get("subtitle_search_folders"))
        for folder in folders:
            child = Adw.ActionRow(
                title=pathlib.Path(folder).name or folder, subtitle=folder)
            remove = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
            remove.add_css_class("destructive-action")
            remove.connect(
                "clicked",
                lambda _button, value=folder: self._remove_subtitle_search_folder(value),
            )
            child.add_suffix(remove)
            child.set_activatable_widget(remove)
            row.add_row(child)
            rows.append(child)
        if not folders:
            empty = Adw.ActionRow(
                title="No extra folders",
                subtitle="Auto only looks next to each film.",
            )
            row.add_row(empty)
            rows.append(empty)
        self._subtitle_search_rows = rows

    def _choose_subtitle_search_folder(self) -> None:
        dialog = Gtk.FileDialog(title="Choose a subtitle search folder")
        dialog.select_folder(self, None, self._subtitle_search_folder_chosen)

    def _subtitle_search_folder_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.select_folder_finish(result)
        except (GLib.Error, ValueError):
            return
        path = chosen.get_path() if chosen is not None else None
        if not path:
            return
        folders = subtitle_search.clean_folders(
            [*(self.owner.cfg.get("subtitle_search_folders") or []), path])
        self.owner.cfg["subtitle_search_folders"] = folders
        save_config(self.owner.cfg)
        self._refresh_subtitle_search_rows()
        self.owner.toast(f"Subtitle search folder: {pathlib.Path(path).name}")

    def _remove_subtitle_search_folder(self, folder: str) -> None:
        folders = [value for value in subtitle_search.clean_folders(
            self.owner.cfg.get("subtitle_search_folders")) if value != folder]
        self.owner.cfg["subtitle_search_folders"] = folders
        save_config(self.owner.cfg)
        self._refresh_subtitle_search_rows()
