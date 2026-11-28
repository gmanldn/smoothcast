"""Preferences > Library page: choose, label and share media folders (#407)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

import library_folders
from cast_widgets import save_config

KIND_LABELS = ("Auto", "Films & TV", "Music", "Photos & home video")


class LibraryFoldersPage:
    """Builds the Library page inside an ``Adw.PreferencesWindow``."""

    def __init__(self, window) -> None:
        self.window = window
        self.rows: list = []
        page = window._page("Library", "folder-symbolic")
        self.group = window._group(
            page, "Library", "Library folders")
        add = Gtk.Button(label="Add folder…", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", self._choose_folder)
        self.group.set_header_suffix(add)
        self.empty = Adw.ActionRow(
            title="No library folders yet",
            subtitle="Add the folders that hold your films, shows and music.")
        self.refresh()

    # -- state ------------------------------------------------------------
    @property
    def folders(self) -> list:
        return library_folders.load(self.window.owner.cfg)

    def _commit(self, folders: list) -> None:
        owner = self.window.owner
        owner.cfg["library_folders"] = library_folders.to_config(folders)
        save_config(owner.cfg)
        notify = getattr(owner, "on_library_folders_changed", None)
        if callable(notify):
            notify(folders)
        self.refresh()

    # -- UI ---------------------------------------------------------------
    def refresh(self) -> None:
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        folders = self.folders
        for folder in folders:
            row = self._row(folder)
            self.group.add(row)
            self.rows.append(row)
        if not folders:
            self.group.add(self.empty)
            self.rows.append(self.empty)

    def _row(self, folder) -> Adw.ExpanderRow:
        row = Adw.ExpanderRow(title=folder.label, subtitle=folder.path)
        share = Gtk.Switch(active=folder.shared, valign=Gtk.Align.CENTER)
        share.set_tooltip_text("Share with the house")
        share.connect("notify::active", lambda sw, _p: self._commit(
            library_folders.update(self.folders, folder.id, shared=sw.get_active())))
        row.add_suffix(share)

        name = Adw.EntryRow(title="Name", text=folder.label)
        name.connect("apply", lambda entry: self._commit(
            library_folders.update(self.folders, folder.id, label=entry.get_text())))
        name.set_show_apply_button(True)
        row.add_row(name)

        kind = Adw.ComboRow(title="Contains")
        kind.set_model(Gtk.StringList.new(list(KIND_LABELS)))
        kind.set_selected(library_folders.KINDS.index(folder.kind))
        kind.connect("notify::selected", lambda combo, _p: self._commit(
            library_folders.update(self.folders, folder.id,
                                   kind=library_folders.KINDS[combo.get_selected()])))
        row.add_row(kind)

        remove = Adw.ActionRow(title="Stop indexing this folder",
                               subtitle="Its entries disappear from house search. Files are not deleted.")
        button = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.connect("clicked", lambda _b: self._confirm_remove(folder))
        remove.add_suffix(button)
        row.add_row(remove)
        return row

    def _confirm_remove(self, folder) -> None:
        dialog = Adw.MessageDialog.new(
            self.window, f"Stop indexing “{folder.label}”?",
            "Its entries will disappear from house search. Files are not deleted.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._commit(
            library_folders.remove(self.folders, folder.id)) if response == "remove" else None)
        dialog.present()

    def _choose_folder(self, _button) -> None:
        dialog = Gtk.FileDialog(title="Choose a library folder")
        dialog.select_folder(self.window, None, self._folder_chosen)

    def _folder_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.select_folder_finish(result)
        except Exception:  # Cancelled or portal failure: nothing to add.  # noqa: BLE001 - cancelled dialog or portal failure: nothing to add
            return
        path = chosen.get_path() if chosen is not None else None
        if not path:
            return
        folders, error = library_folders.add(self.folders, path)
        if error:
            self.window.add_toast(Adw.Toast(title=error))
            return
        self._commit(folders)
