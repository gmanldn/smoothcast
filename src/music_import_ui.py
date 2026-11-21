"""GTK controls for explicit audio/folder queue imports and drag/drop."""
from __future__ import annotations

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

import music_import
import streamer

from cast_widgets import Async


class MusicImportMixin:
    def _build_music_actions(self) -> Gtk.MenuButton:
        menu = Gtk.MenuButton(label="Add Music")
        popover = Gtk.Popover()
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        files = Gtk.Button(label="Choose audio files")
        folder = Gtk.Button(label="Add music folder")
        files.connect("clicked", lambda _b: (popover.popdown(), self.add_music()))
        folder.connect("clicked", lambda _b: (popover.popdown(), self.add_music_folder()))
        actions.append(files)
        actions.append(folder)
        popover.set_child(actions)
        menu.set_popover(popover)
        return menu

    def _build_music_import_status(self) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_visible(False)
        self._music_scan_label = Gtk.Label(label="", xalign=0.0, hexpand=True)
        self._music_scan_label.add_css_class("caption")
        self._music_scan_bar = Gtk.ProgressBar()
        self._music_scan_bar.set_hexpand(True)
        self._music_scan_bar.set_pulse_step(0.08)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self._cancel_music_import())
        row.append(self._music_scan_label)
        row.append(self._music_scan_bar)
        row.append(cancel)
        self._music_scan_status = row
        return row

    def _install_queue_drop_target(self, target: Gtk.Widget) -> None:
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._drop_queue_media)
        target.add_controller(drop)

    def add_music(self) -> None:
        dialog = Gtk.FileDialog(title="Add music to the queue")
        store = Gio.ListStore.new(Gtk.FileFilter)
        audio_filter = Gtk.FileFilter()
        audio_filter.set_name("Audio files")
        for suffix in sorted(streamer.AUDIO_EXTS):
            audio_filter.add_pattern(f"*{suffix}")
        store.append(audio_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        store.append(all_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(audio_filter)
        dialog.open_multiple(self, None, self._music_files_chosen)

    def add_music_folder(self) -> None:
        dialog = Gtk.FileDialog(title="Add a music folder")
        dialog.select_folder(self, None, self._music_folder_chosen)

    def _music_files_chosen(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        self._start_music_import([
            path for index in range(files.get_n_items())
            if (path := files.get_item(index).get_path())
        ], audio_only=True, natural_sort=False)

    def _music_folder_chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = folder.get_path()
        if path:
            self._start_music_import([path], audio_only=True)

    def _drop_queue_media(self, _target, file_list, _x, _y) -> bool:
        sources = [file.get_path() for file in file_list.get_files() if file.get_path()]
        if not sources:
            self.toast("Drop local media files or folders onto the queue", error=True)
            return False
        self._start_music_import(sources, audio_only=False)
        return True

    def _start_music_import(
        self, sources: list[str], *, audio_only: bool, natural_sort: bool = True,
    ) -> None:
        if not sources:
            return
        self._cancel_music_import()
        self._music_scan_generation = getattr(self, "_music_scan_generation", 0) + 1
        generation = self._music_scan_generation
        cancel = threading.Event()
        self._music_scan_cancel = cancel
        self._music_scan_status.set_visible(True)
        self._music_scan_label.set_text("Preparing music import…")
        self._music_scan_bar.set_fraction(0.0)
        extensions = streamer.AUDIO_EXTS if audio_only else streamer.MEDIA_EXTS

        def progress(count: int) -> None:
            GLib.idle_add(self._show_music_import_progress, generation, count)

        def work():
            return music_import.discover(
                sources, extensions=extensions, cancel=cancel, progress=progress,
                natural_sort=natural_sort,
            )

        Async.run(
            work,
            done=lambda result: self._music_import_done(generation, result),
            failed=lambda message: self._music_import_failed(generation, message),
            domain="media",
            valid=lambda: not self._closing and generation == self._music_scan_generation,
        )

    def _show_music_import_progress(self, generation: int, count: int) -> bool:
        if generation == getattr(self, "_music_scan_generation", -1) and not self._closing:
            self._music_scan_label.set_text(f"Scanning folders… {count:,} entries")
            self._music_scan_bar.pulse()
        return False

    def _finish_music_import(self, generation: int) -> bool:
        if generation == getattr(self, "_music_scan_generation", -1):
            self._music_scan_cancel = None
            self._music_scan_status.set_visible(False)
        return generation == getattr(self, "_music_scan_generation", -1)

    def _music_import_done(self, generation: int, result: music_import.Discovery) -> None:
        if not self._finish_music_import(generation):
            return
        if result.paths:
            self._enqueue(list(result.paths))
        if result.cancelled:
            self.toast(f"Import cancelled after {result.visited:,} entries")
        elif result.truncated:
            self.toast(f"Import capped at {len(result.paths):,} items; choose a smaller folder")
        elif result.skipped:
            self.toast(f"Imported {len(result.paths):,}; skipped {result.skipped:,} unsupported or unreadable items")
        elif not result.paths:
            self.toast("No supported media files found", error=True)

    def _music_import_failed(self, generation: int, message: str) -> None:
        if self._finish_music_import(generation):
            self.toast(f"Music import failed: {message}", error=True)

    def _cancel_music_import(self) -> None:
        cancel = getattr(self, "_music_scan_cancel", None)
        if cancel is not None:
            cancel.set()
            if hasattr(self, "_music_scan_label"):
                self._music_scan_label.set_text("Stopping folder scan…")
